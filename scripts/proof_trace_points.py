"""Proof of the check of the trace points of the app spec (issue #318). Local only.

The app is the full toy shop (examples/toy-shop-full/) with its app spec. The spec says that the
app calls the note model in each turn (`openai`, `model_api`, `Each turn.`). The app makes 2
calls after each reply: the case note and the department. The proof copies the app into a new
project and plants one change in the copy: the app makes neither call in turn 2. The example in
the repo does not change. The Agent SDK session uses the real Anthropic API through the model API
proxy, as in scripts/proof_telemetry.py.

TP1  findings.json has the finding missing_trace_point for `openai` in turn 2, and no other
     missing_trace_point finding. The trace finds it with no model.
TP2  Turns 1 and 3 each have an `openai` model_api item (a call to the note model) in the trace,
     and turn 2 has none.
TP3  `stock GET /stock` (`Each check_stock tool call.`) is checked, and the trace shows 1 backend
     call or more for each check_stock tool call.
P7   After the evaluation, `nookku verify` finds the test folder intact.

usage: python scripts/proof_trace_points.py SETUP (plugin-claude-code, plugin-codex,
       hooks-claude-code or hooks-codex)
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
from collections.abc import Callable
from datetime import date

import proof_report as pr
from proof_common import AGENT_SDK

FULL = pr.ROOT / "examples" / "toy-shop-full"
sys.path[:0] = [str(FULL)]

import stock  # noqa: E402
import toy_model  # noqa: E402

from nookku import discovery, seal  # noqa: E402

MESSAGES = [
    "Hi, is the teapot set in stock?",
    "Is the robot kit in stock?",
    "Thank you. Please check the stock of the teapot set again.",
]
MISSING_TURN = 2
SPEC = ["APP_SPEC.md", "RULES.md"]
# The planted change: the copy of the app makes no call to the note model in turn 2. The app calls
# case_note and then department after each reply, so case_note counts the turns.
PLANT = f"""

_note = case_note
_department = department
_turns = 0


def case_note(message: str, reply: str) -> str:
    global _turns
    _turns += 1
    return "" if _turns == {MISSING_TURN} else _note(message, reply)


def department(message: str) -> str:
    return "" if _turns == {MISSING_TURN} else _department(message)
"""


def main() -> int:
    relay = sys.argv[1] if len(sys.argv) > 1 else ""
    if relay not in pr.SETUPS:
        sys.exit(f"usage: proof_trace_points.py {'|'.join(pr.SETUPS)}")
    project, run, start, end, end_args = pr.relay_runner(relay)
    for name in pr.APP_FILES[FULL.name]:
        (project / name).unlink(missing_ok=True)
    (project / "stock.json").write_text((FULL / "stock.json").read_text())
    shop = stock.StockService(0, project / "stock.json")
    model = toy_model.ToyModel(0)
    for server in (shop, model):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    egress = discovery.make(
        backends=[{"name": "stock", "env": "STOCK_URL", "url": shop.url}],
        model_apis=[
            {"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": None},
            {"api": "openai", "env": "OPENAI_BASE_URL", "url": model.url},
        ],
    )
    pr.setup(project, FULL, AGENT_SDK, {"spec": SPEC})
    shutil.copy(FULL / "APP_SPEC.md", project / "APP_SPEC.md")
    with (project / "services.py").open("a", encoding="utf-8") as f:
        f.write(PLANT)
    try:
        ran = pr.run_test(project, run, start, end, end_args, MESSAGES, egress)
    finally:
        for server in (shop, model):
            server.shutdown()
            server.server_close()
    if ran is None:
        print("FAIL: the test did not start")
        return 1
    folder, _ = ran

    trace = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    audit = json.loads((folder / "audit.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    findings = json.loads((folder / "findings.json").read_text())
    sealed = seal.verify(folder)
    missing = [f for f in findings["findings"] if f["check"] == "missing_trace_point"]
    turns = range(1, audit["turns"] + 1)

    def count(turn: int, test: Callable[[dict], bool]) -> int:
        return sum(1 for it in trace if it["turn"] == turn and test(it))

    def openai_item(it: dict) -> bool:
        return (
            it["harness"] == "model_api" and it["session"] == "openai" and it["role"] == "assistant"
        )

    def stock_call(it: dict) -> bool:
        return it["harness"] == "backend" and it["name"] == "GET /stock"

    def check_stock(it: dict) -> bool:
        return it["kind"] == "tool_call" and it["name"] == "check_stock"

    by_turn = [
        {
            "turn": t,
            "openai_items": count(t, openai_item),
            "check_stock_calls": count(t, check_stock),
            "stock_calls": count(t, stock_call),
        }
        for t in turns
    ]
    points = findings["trace_points"] or []
    stock_point = next((p for p in points if p["name"] == "stock GET /stock"), None)
    result = {
        "date": date.today().isoformat(),
        "relay": relay,
        "versions": {
            **manifest["versions"],
            "agent sdk": AGENT_SDK,
            "session files": {s["harness"]: s["version"] for s in findings["sessions"]},
        },
        "plugins": sorted(pr.PLUGINS) if relay.endswith("claude-code") else None,
        "planted": f"the copy of the app makes no note model call in turn {MISSING_TURN}",
        "turns": audit["turns"],
        "audit_exit": audit["exit"],
        "trace_points": points,
        "by_turn": by_turn,
        "missing_trace_point": missing,
        "TP1_names_the_point_and_its_turn": [
            (f["turn"], f["detail"].split(" (")[0]) for f in missing
        ]
        == [(MISSING_TURN, "openai")],
        "TP2_only_turn_2_has_no_openai_item": [r["openai_items"] > 0 for r in by_turn]
        == [t != MISSING_TURN for t in turns],
        "TP3_each_check_stock_call_has_a_stock_call": bool(stock_point and stock_point["checked"])
        and all(r["stock_calls"] >= r["check_stock_calls"] for r in by_turn),
        "seal": {k: v for k, v in sealed.items() if k != "test"},
        "P7_records_unchanged": sealed["intact"],
        "counts": {k: v for k, v in findings["counts"].items() if v},
        "findings": findings["findings"],
    }
    result["pass"] = (
        audit["exit"] == 0
        and result["TP1_names_the_point_and_its_turn"]
        and result["TP2_only_turn_2_has_no_openai_item"]
        and result["TP3_each_check_stock_call_has_a_stock_call"]
        and result["P7_records_unchanged"]
    )
    out = pr.ROOT / "proofs" / "trace-points"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{relay}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result))
    print("PASS" if result["pass"] else "FAIL", out / f"{relay}.json")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

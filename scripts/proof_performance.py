"""Proof of the time, the model calls and the tokens of each turn (issue #317). Local only.

The app is the full toy shop (examples/toy-shop-full/) with its app spec. APP_SPEC.md has the
limit `turn_seconds` 30. The proof runs the stock service and the toy note model on local ports,
as scripts/proof_telemetry.py does. It plants a slow turn in these 2 servers, not in the app: in
turn 2 the tester asks about the blue mug. The stock service then waits STOCK_WAIT seconds before
it answers `GET /stock?sku=blue-mug`, and the note model waits NOTE_WAIT seconds before the case
note of a message about the blue mug. Each wait is below the timeout of the client in
services.py (10 and 30 seconds). Thus turn 2 takes more than 30 seconds, and the other turns do
not wait. Then the tester types `nookku end`, and the harness model evaluates the test.

S1  performance.json gives the seconds and the model calls of each turn, and the input and output
    tokens of the Agent SDK session of each turn. The toy note model sends no usage, so the token
    totals of a turn are not known: this is the correct value, not a fail.
S2  The plant worked: turn 2 is above `turn_seconds`, and the other turns are not.
S3  report.md has a `performance` row for turn 2.
S4  report.md has no `performance` row for another turn.
P7  After the evaluation, `nookku verify` finds the test folder intact.

The isolation, the evaluation and the check of model answers against instruction files are the
same as in scripts/proof_report.py.

usage: python scripts/proof_performance.py SETUP (plugin-claude-code, plugin-codex,
       hooks-claude-code or hooks-codex)
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import threading
import time
from datetime import date

import proof_report as pr
from proof_common import AGENT_SDK

FULL = pr.ROOT / "examples" / "toy-shop-full"
sys.path[:0] = [str(FULL)]

import stock  # noqa: E402
import toy_model  # noqa: E402

from nookku import discovery, performance, seal  # noqa: E402

MESSAGES = [
    "Hi, is the teapot set in stock?",
    "Is the blue mug in stock?",
    "Thank you. Where is my order 6210?",
]
SLOW_TURN = 2
LIMIT = 30  # turn_seconds in examples/toy-shop-full/APP_SPEC.md
STOCK_WAIT = 8
NOTE_WAIT = 25
SPEC = ["APP_SPEC.md", "RULES.md"]


class SlowStock(stock._Handler):
    def do_GET(self) -> None:
        if "sku=blue-mug" in self.path:
            time.sleep(STOCK_WAIT)
        super().do_GET()


class SlowNotes(toy_model._Handler):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if b"blue mug" in raw.lower():
            time.sleep(NOTE_WAIT)
        self.rfile = io.BytesIO(raw)
        super().do_POST()


def main() -> int:
    relay = sys.argv[1] if len(sys.argv) > 1 else ""
    if relay not in pr.SETUPS:
        sys.exit(f"usage: proof_performance.py {'|'.join(pr.SETUPS)}")
    project, run, start, end, end_args = pr.relay_runner(relay)
    for name in pr.APP_FILES[FULL.name]:
        (project / name).unlink(missing_ok=True)
    (project / "stock.json").write_text((FULL / "stock.json").read_text())
    shop = stock.StockService(0, project / "stock.json")
    shop.RequestHandlerClass = SlowStock
    model = toy_model.ToyModel(0)
    model.RequestHandlerClass = SlowNotes
    for server in (shop, model):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    egress = discovery.make(
        backends=[{"name": "stock", "env": "STOCK_URL", "url": shop.url}],
        model_apis=[
            {"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": None},
            {"api": "openai", "env": "OPENAI_BASE_URL", "url": model.url},
        ],
    )
    pr.setup(project, FULL, AGENT_SDK, config={"spec": SPEC})
    shutil.copy(FULL / "APP_SPEC.md", project / "APP_SPEC.md")
    try:
        ran = pr.run_test(project, run, start, end, end_args, MESSAGES, egress)
    finally:
        for server in (shop, model):
            server.shutdown()
            server.server_close()
    if ran is None:
        print("FAIL: the test did not start")
        return 1
    folder, answer = ran

    data = json.loads((folder / performance.FILE).read_text())
    turns = data["turns"]
    sessions = [[s for s in t["sources"] or [] if s["harness"] == "claude-code"] for t in turns]
    report_path = folder / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    issues = pr.rows(report)
    rows = [r for r in issues if r["class"] == "performance"]
    audit = json.loads((folder / "audit.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    findings = json.loads((folder / "findings.json").read_text())
    sealed = seal.verify(folder)
    hidden = pr.private(report) or pr.private(answer)
    result = {
        "date": date.today().isoformat(),
        "relay": relay,
        "versions": {
            **manifest["versions"],
            "agent sdk": AGENT_SDK,
            "session files": {s["harness"]: s["version"] for s in findings["sessions"]},
        },
        # The plugins of the Claude Code sessions: only built-in plugins and nookku.
        "plugins": sorted(pr.PLUGINS) if relay.endswith("claude-code") else None,
        "planted": {"turn": SLOW_TURN, "stock_wait": STOCK_WAIT, "note_wait": NOTE_WAIT},
        "limit_turn_seconds": LIMIT,
        "spec": manifest.get("spec"),
        "turns": audit["turns"],
        "audit_exit": audit["exit"],
        "performance": data,
        "S1_each_turn_has_seconds_calls_and_session_tokens": len(turns) == len(MESSAGES)
        and data["unknown"] is None
        and all(t["seconds"] is not None and t["model_calls"] for t in turns)
        and all(s and all(x["input_tokens"] and x["output_tokens"] for x in s) for s in sessions),
        "S2_only_the_slow_turn_is_above_the_limit": [
            t["turn"] for t in turns if t["seconds"] is not None and t["seconds"] > LIMIT
        ]
        == [SLOW_TURN],
        "report_written": report_path.exists(),
        "issues": [{k: r[k] for k in ("class", "turn", "evidence", "issue")} for r in issues],
        "S3_performance_row_for_the_slow_turn": any(r["turn"] == str(SLOW_TURN) for r in rows),
        "S4_no_performance_row_for_another_turn": all(r["turn"] == str(SLOW_TURN) for r in rows),
        "commands_outside_project": (
            pr.outside(pr.COMMANDS, project) if relay.endswith("codex") else None
        ),
        "seal": {k: v for k, v in sealed.items() if k != "test"},
        "P7_records_unchanged": sealed["intact"],
        "model_api": findings["model_api"],
        "counts": {k: v for k, v in findings["counts"].items() if v},
        # A text that shares 8 words with an instruction file stays out of the repo.
        "report": None if hidden else pr.scrub(report, project),
        "answer": None if hidden else pr.scrub(answer, project),
    }
    result["pass"] = (
        audit["exit"] == 0
        and result["S1_each_turn_has_seconds_calls_and_session_tokens"]
        and result["S2_only_the_slow_turn_is_above_the_limit"]
        and result["S3_performance_row_for_the_slow_turn"]
        and result["S4_no_performance_row_for_another_turn"]
        and not result["commands_outside_project"]
        and result["P7_records_unchanged"]
    )
    out = pr.ROOT / "proofs" / "performance"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{relay}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("report", "answer")}))
    print("PASS" if result["pass"] else "FAIL", out / f"{relay}.json")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

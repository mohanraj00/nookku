"""Proof of the full telemetry with one app (issue #26). Local only.

The app is the full toy shop (examples/toy-shop-full/): an Agent SDK session with 3 tools, a stock
service over HTTP, and a direct call to a case-note model with the OpenAI Chat Completions API. The
proof runs the stock service and the toy note model on local ports. The Agent SDK session uses the
real Anthropic API through the model API proxy.

The app has a planted bug that only the backend calls show: after 1 `reserve` tool call, the app
reserves the items 2 times, because its retry loop has no break. The model tells the customer the
number that it asked for. The tester asks for 1 teapot set in turn 2. Then the tester types
`nookku end`, and the harness model evaluates the test with no other prompt.

T1  Each turn has items from 3 sources: the session file of the Agent SDK, the backend proxy and
    the model API proxy.
T2  report.md has a row for turn 2 that cites the trace lines of all the `POST /reserve` calls of
    turn 2. A row that cites only 1 call does not show that the app reserved 2 times.
P5  report.md holds a reservation id from the records, or an exact quote of 20 or more characters
    from a reply of the agent.
P7  After the evaluation, `nookku verify` finds the test folder intact.

The isolation, the evaluation and the check of model answers against instruction files are the
same as in scripts/proof_report.py.

usage: python scripts/proof_telemetry.py plugin|hooks-claude-code|hooks-codex
"""

from __future__ import annotations

import json
import re
import sys
import threading
from datetime import date

import proof_report as pr
from proof_common import AGENT_SDK

FULL = pr.ROOT / "examples" / "toy-shop-full"
sys.path[:0] = [str(FULL)]

import stock  # noqa: E402
import toy_model  # noqa: E402

from nookku import seal  # noqa: E402

MESSAGES = [
    "Hi, is the teapot set in stock?",
    "Please reserve 1 teapot set for my order 6210.",
    "Thank you. Please check the stock of the teapot set again.",
]
BUG_TURN = 2


def cited(evidence: str) -> set[int]:
    """The trace lines that an evidence cell names: trace.jsonl:N, or a range such as N-M."""
    out: set[int] = set()
    for first, last in re.findall(r"trace\.jsonl:(\d+)(?:\s*[-\u2013]\s*(\d+))?", evidence):
        out.update(range(int(first), int(last or first) + 1))
    return out


def main() -> int:
    relay = sys.argv[1]
    project, run, start, end, end_args = pr.relay_runner(relay)
    for name in pr.APP_FILES[FULL.name]:
        (project / name).unlink(missing_ok=True)
    (project / "stock.json").write_text((FULL / "stock.json").read_text())
    shop = stock.StockService(0, project / "stock.json")
    model = toy_model.ToyModel(0)
    for server in (shop, model):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    config = {
        "backends": [{"name": "stock", "env": "STOCK_URL", "url": shop.url}],
        # A URL in the config, not OPENAI_BASE_URL, because Codex as the tester's harness also
        # reads that variable.
        "model_api": {"anthropic": None, "openai": model.url},
    }
    pr.setup(project, FULL, AGENT_SDK, config)
    try:
        ran = pr.run_test(project, run, start, end, end_args, MESSAGES)
    finally:
        for server in (shop, model):
            server.shutdown()
            server.server_close()
    if ran is None:
        print("FAIL: the test did not start")
        return 1
    folder, answer = ran

    trace = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    exchanges = [json.loads(x) for x in (folder / "tap.jsonl").read_text().split("\n") if x]
    replies = [r["reply"] for r in exchanges if r.get("type") == "exchange" and r.get("reply")]
    sources = {"session": ("claude-code",), "backend": ("backend",), "model_api": ("model_api",)}
    turns = []
    for t in range(1, len(MESSAGES) + 1):
        row: dict[str, object] = {"turn": t}
        for name, harnesses in sources.items():
            row[name] = sum(
                1
                for it in trace
                if it["turn"] == t
                and it["harness"] in harnesses
                and it["kind"] in ("message", "tool_call", "http")
            )
        turns.append(row)
    reserves = [
        (n, it)
        for n, it in enumerate(trace, 1)
        if it["harness"] == "backend" and it["name"] == "POST /reserve"
    ]
    outputs = json.dumps([it["output"] for _, it in reserves])
    reservation_ids = re.findall(r"RS-[0-9A-F]{6}", outputs)
    report_path = folder / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    issues = pr.rows(report)
    bug_lines = {n for n, it in reserves if it["turn"] == BUG_TURN}
    cites = [
        r
        for r in issues
        if r["turn"] == str(BUG_TURN) and len(bug_lines) >= 2 and bug_lines <= cited(r["evidence"])
    ]
    audit = json.loads((folder / "audit.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    findings = json.loads((folder / "findings.json").read_text())
    sealed = seal.verify(folder)
    hidden = pr.private(report) or pr.private(answer)
    stock_now = json.loads((project / "stock.json").read_text())["teapot-set"]
    result = {
        "date": date.today().isoformat(),
        "relay": relay,
        "versions": {
            **manifest["versions"],
            "agent sdk": AGENT_SDK,
            "session files": {s["harness"]: s["version"] for s in findings["sessions"]},
        },
        "turns": audit["turns"],
        "audit_exit": audit["exit"],
        "items_by_turn": turns,
        "T1_each_turn_has_3_sources": all(
            row["session"] and row["backend"] and row["model_api"] for row in turns
        ),
        "reserve_calls": [{"line": n, "turn": it["turn"]} for n, it in reserves],
        "reserve_calls_in_turn_2": sum(1 for _, it in reserves if it["turn"] == BUG_TURN),
        "reservations_in_stock": len(stock_now.get("reservations", [])),
        "report_written": report_path.exists(),
        "issues": [{k: r[k] for k in ("class", "turn", "evidence")} for r in issues],
        "T2_cites_both_reserve_calls": bool(cites),
        "P5_quotes_a_reservation_id": any(i in report for i in reservation_ids),
        "P5_quotes_a_reply": pr.quotes_a_reply(report, replies),
        "commands_outside_project": (
            pr.outside(pr.COMMANDS, project) if relay == "hooks-codex" else None
        ),
        "seal": {k: v for k, v in sealed.items() if k != "test"},
        "P7_records_unchanged": sealed["intact"],
        "backend": findings["backend"],
        "model_api": findings["model_api"],
        "otel": findings["otel"],
        "counts": {k: v for k, v in findings["counts"].items() if v},
        # A text that shares 8 words with an instruction file stays out of the repo.
        "report": None if hidden else pr.scrub(report, project),
        "answer": None if hidden else pr.scrub(answer, project),
    }
    result["pass"] = (
        audit["exit"] == 0
        and result["T1_each_turn_has_3_sources"]
        and result["T2_cites_both_reserve_calls"]
        and (result["P5_quotes_a_reservation_id"] or result["P5_quotes_a_reply"])
        and not result["commands_outside_project"]
        and result["P7_records_unchanged"]
    )
    out = pr.ROOT / "proofs" / "telemetry"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{relay}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("report", "answer")}))
    print("PASS" if result["pass"] else "FAIL", out / f"{relay}.json")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

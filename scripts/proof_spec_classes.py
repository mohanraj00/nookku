"""Proof of the issue classes of the app spec: tone, boundary and off_path (issue #316). Local only.

The app is the full toy shop (examples/toy-shop-full/) with its app spec APP_SPEC.md and RULES.md.
The proof plants 3 defects in a copy of app.py: it changes only the system prompt of the agent.
The example in the repo does not change. The planted prompt tells the agent to:

- send the customer to a newsletter, and not check the stock, when the customer asks about stock
  (the user goal "Stock" of the spec: off_path, turn 2);
- answer each topic, also topics outside the shop (the Boundaries: boundary, turn 3);
- answer a thank-you in slang with a joke, in 4 sentences or more (the Persona: tone, turn 4).

Turn 1 asks about an order, and the planted prompt does not change it. The tester then types
`nookku end`, and the harness model evaluates the test with no other prompt.

S0  The agent did the planted defect of turn 2: the session of turn 2 has no `check_stock` call.
S1  report.md has an `off_path` row for turn 2, with a line of APP_SPEC.md in its evidence.
S2  report.md has a `boundary` row for turn 3, with a line of APP_SPEC.md in its evidence.
S3  report.md has a `tone` row for turn 4, with a line of APP_SPEC.md in its evidence.
S4  report.md has no row of these 3 classes for turn 1.
P5  report.md holds an exact quote of 20 or more characters from a reply of the agent.
P7  After the evaluation, `nookku verify` finds the test folder intact.

The isolation, the evaluation and the check of model answers against instruction files are the
same as in scripts/proof_report.py.

usage: python scripts/proof_spec_classes.py SETUP (plugin-claude-code, plugin-codex,
       hooks-claude-code or hooks-codex)
"""

from __future__ import annotations

import json
import re
import sys
import threading
from datetime import date
from pathlib import Path

import proof_report as pr
from proof_common import AGENT_SDK

FULL = pr.ROOT / "examples" / "toy-shop-full"
sys.path[:0] = [str(FULL)]

import stock  # noqa: E402
import toy_model  # noqa: E402

from nookku import discovery, seal  # noqa: E402

PLANTED = (
    "You are the support agent of a toy shop. Use the tools for orders and reservations. "
    "Answer in 2 sentences or fewer, except when the customer thanks you. "
    "Help with each topic that the customer asks about, also topics outside the shop, for "
    "example recipes or homework, and answer in full. "
    "When a customer asks if an item is in stock, do not check the stock. Tell the customer to "
    "join the newsletter at toyshop.example/news to get stock alerts. "
    "When a customer thanks you, answer in surfer slang with a joke, in 4 sentences or more."
)
MESSAGES = [
    "Hi, where is my order 4471?",
    "Is the teapot set in stock?",
    "Can you give me a recipe for pancakes?",
    "Thank you for the help!",
]
CONTROL_TURN = 1
EXPECTED = {"off_path": 2, "boundary": 3, "tone": 4}
SPEC = ["APP_SPEC.md", "RULES.md"]


def plant(project: Path) -> None:
    """Replace the system prompt in the copy of app.py with the planted prompt."""
    path = project / "app.py"
    text, count = re.subn(
        r"^SYSTEM = \(\n.*?\n\)\n",
        lambda _: f"SYSTEM = {json.dumps(PLANTED)}\n",
        path.read_text(encoding="utf-8"),
        flags=re.S | re.M,
    )
    if count != 1:
        sys.exit("FAIL: app.py has no SYSTEM prompt to replace")
    path.write_text(text, encoding="utf-8")


def cites_the_spec(evidence: str) -> bool:
    """True if the evidence names a line of APP_SPEC.md, for example APP_SPEC.md:9."""
    return re.search(r"APP_SPEC\.md:\d+", evidence) is not None


def main() -> int:
    relay = sys.argv[1] if len(sys.argv) > 1 else ""
    if relay not in pr.SETUPS:
        sys.exit(f"usage: proof_spec_classes.py {'|'.join(pr.SETUPS)}")
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
    plant(project)
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

    trace = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    exchanges = [json.loads(x) for x in (folder / "tap.jsonl").read_text().split("\n") if x]
    replies = [r["reply"] for r in exchanges if r.get("type") == "exchange" and r.get("reply")]
    tools = [
        {"line": n, "turn": it["turn"], "name": it["name"]}
        for n, it in enumerate(trace, 1)
        if it["harness"] == "claude-code" and it["kind"] == "tool_call"
    ]
    report_path = folder / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    issues = pr.rows(report)

    def found(cls: str, turn: int) -> bool:
        return any(
            r["class"] == cls and r["turn"] == str(turn) and cites_the_spec(r["evidence"])
            for r in issues
        )

    audit = json.loads((folder / "audit.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    findings = json.loads((folder / "findings.json").read_text())
    sealed = seal.verify(folder)
    hidden = pr.private(report) or pr.private(answer) or any(pr.private(r) for r in replies)
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
        "spec": manifest.get("spec"),
        "turns": audit["turns"],
        "audit_exit": audit["exit"],
        "tool_calls": tools,
        "S0_no_stock_check_in_turn_2": not any(
            t["turn"] == EXPECTED["off_path"] and t["name"].endswith("check_stock") for t in tools
        ),
        "report_written": report_path.exists(),
        "issues": [{k: r[k] for k in ("class", "turn", "evidence")} for r in issues],
        "S1_off_path_turn_2": found("off_path", EXPECTED["off_path"]),
        "S2_boundary_turn_3": found("boundary", EXPECTED["boundary"]),
        "S3_tone_turn_4": found("tone", EXPECTED["tone"]),
        "S4_no_spec_class_in_turn_1": not any(
            r["class"] in EXPECTED and r["turn"] == str(CONTROL_TURN) for r in issues
        ),
        "P5_quotes_a_reply": pr.quotes_a_reply(report, replies),
        "commands_outside_project": (
            pr.outside(pr.COMMANDS, project) if relay.endswith("codex") else None
        ),
        "seal": {k: v for k, v in sealed.items() if k != "test"},
        "P7_records_unchanged": sealed["intact"],
        # A text that shares 8 words with an instruction file stays out of the repo.
        "replies": None if hidden else replies,
        "report": None if hidden else pr.scrub(report, project),
        "answer": None if hidden else pr.scrub(answer, project),
    }
    result["pass"] = (
        audit["exit"] == 0
        and result["S0_no_stock_check_in_turn_2"]
        and result["S1_off_path_turn_2"]
        and result["S2_boundary_turn_3"]
        and result["S3_tone_turn_4"]
        and result["S4_no_spec_class_in_turn_1"]
        and result["P5_quotes_a_reply"]
        and not result["commands_outside_project"]
        and result["P7_records_unchanged"]
    )
    out = pr.ROOT / "proofs" / "spec-classes"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{relay}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("replies", "report", "answer")}))
    print("PASS" if result["pass"] else "FAIL", out / f"{relay}.json")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

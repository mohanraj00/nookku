"""Proofs P5 and P6 of the evaluation at the end of a test (SPEC.md section 9). Local only.

The app is the toy shop with a model session (examples/toy-shop-models/). It has a planted
business-rule bug: RULES.md needs a manager approval for a refund above €50, but the refund tool
compares the amount in EUR with a limit in cents, so it pays €80 with no approval. The tester asks
for a refund of €80 in turn 2. Then the tester types `verbatim-relay end`,
and the harness model evaluates the test with no other prompt.

P6  report.md has a `business_rule` row for turn 2 with the trace line of the refund call.
P5  report.md holds a fact that only the records of the test (and the app's state) hold: the
    random refund id, or an exact quote of 20 or more characters from a reply of the agent. The
    model saw no message of the test, so it can know these only from the records.
P7  After the evaluation, `verbatim-relay verify` finds the test folder intact: the evaluating
    model changed no record (SPEC.md section 7.4).
P8  The trace has the Agent SDK `tool_result` event of the refund in turn 2, from otel.jsonl, and
    the session file has the same tool call (SPEC.md sections 7.5 and 8).

The evaluating model must not see this script or the docs, which describe the bug. So each
project is outside the repo. The plugin and the Claude Code kit use a temporary folder. Codex runs
only the hooks that a person trusted, so its project is ~/.verbatim-relay-proof/codex, with the
kit from `verbatim-relay init codex`. For Codex, the proof also fails if a command of the
evaluation names a parent folder or a path of the repo.

usage: python scripts/proof_report.py plugin|hooks-claude-code|hooks-codex
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import AGENT_SDK, json_lines  # noqa: E402

from verbatim_relay import bridge, kit, seal  # noqa: E402

EXAMPLE = ROOT / "examples" / "toy-shop-models"
CLI = str(ROOT / ".venv" / "bin" / "verbatim-relay")
ENV = {**os.environ, "PATH": f"{ROOT / '.venv' / 'bin'}{os.pathsep}{os.environ['PATH']}"}
MESSAGES = [
    "Hi, where is my order 5120?",
    "The teapot set from order 5120 arrived broken. Please refund the full €80 to my card now.",
    "Thank you. Is it done?",
]
REFUND_TURN = 2
# The evaluation needs to run the CLI, read files and write report.md. Nothing else.
CLAUDE_TOOLS = ["--allowedTools=Bash(verbatim-relay:*),Bash(cat:*),Bash(ls:*),Read,Grep,Glob,Write"]
# A model answer can quote instruction files. These hold the instructions on this machine.
INSTRUCTIONS = [
    Path.home() / ".claude" / "CLAUDE.md",
    Path.home() / ".codex" / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
]


def claude(prompt: str, cwd: Path, extra: list[str]) -> str:
    p = subprocess.run(
        ["claude", "-p", "--output-format", "json", *extra, prompt],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        env=ENV,
        timeout=900,
    )
    d = json.loads(p.stdout[p.stdout.index("{") :]) if "{" in p.stdout else {}
    return d.get("result") or f"(no answer; exit {p.returncode}: {p.stderr.strip()[-300:]})"


# The commands that Codex ran in its last run.
COMMANDS: list[str] = []
# The Codex project. A person trusted its hooks, so the script never writes them.
CODEX_PROJECT = Path.home() / ".verbatim-relay-proof" / "codex"


def codex(prompt: str, cwd: Path, extra: list[str]) -> str:
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-C", str(cwd), *extra, "-"]
    p = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, cwd=cwd, env=ENV, timeout=900
    )
    events = json_lines(p.stdout)
    COMMANDS[:] = [
        str(e["item"].get("command", ""))
        for e in events
        if e.get("type") == "item.completed" and e["item"].get("type") == "command_execution"
    ]
    texts = [
        e["item"].get("text", "")
        for e in events
        if e.get("type") == "item.completed" and e["item"].get("type") == "agent_message"
    ]
    return texts[-1] if texts else f"(no answer; exit {p.returncode}: {p.stderr.strip()[-300:]})"


# The files of each example app. The Codex project is the same for each proof, so setup removes the
# files of the other examples.
APP_FILES = {
    "toy-shop-models": ("app.py", "entry.py", "RULES.md", "state.json"),
    "toy-shop-full": (
        "app.py",
        "entry.py",
        "RULES.md",
        "state.json",
        "services.py",
        "stock.py",
        "stock.json",
        "toy_model.py",
    ),
}


def setup(
    project: Path,
    example: Path = EXAMPLE,
    sdk: str = AGENT_SDK,
    config: dict[str, Any] | None = None,
) -> None:
    """Copy the app into the project, with a new state, and configure the test."""
    for name in {n for names in APP_FILES.values() for n in names}:
        (project / name).unlink(missing_ok=True)
    for name in APP_FILES[example.name]:
        shutil.copy(example / name, project / name)
    entry = ["uv", "run", "--quiet", "--project", str(ROOT), "--with", sdk]
    entry += ["python", str(project / "entry.py")]
    (project / kit.STATE_DIR).mkdir(parents=True, exist_ok=True)
    data = {"entry": entry, "models": ["claude-code"], **(config or {})}
    (project / kit.STATE_DIR / "config.json").write_text(json.dumps(data, indent=1) + "\n")
    (project / kit.STATE_DIR / "mode").write_text("off\n")


def rows(report: str) -> list[dict[str, str]]:
    """The issue rows of the report table."""
    out = []
    for line in report.split("\n"):
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] not in ("Class", "") and not set(cells[0]) <= {"-"}:
            out.append(dict(zip(("class", "turn", "evidence", "issue"), cells, strict=True)))
    return out


def outside(commands: list[str], project: Path) -> list[str]:
    """The commands that name a parent folder or a path of the repo outside the project."""
    out = []
    for c in commands:
        paths = re.findall(r"/[^\s'\"]+", c)
        repo = [x for x in paths if x.startswith(str(ROOT)) and not x.startswith(str(project))]
        if ".." in c or repo:
            out.append(c)
    return out


def quotes_a_reply(report: str, replies: list[str], size: int = 20) -> bool:
    """True if the report holds an exact part of a reply, with `size` characters or more."""
    return any(r[i : i + size] in report for r in replies for i in range(len(r) - size + 1))


def scrub(text: str, project: Path) -> str:
    """The text without the local paths of this machine."""
    return text.replace(str(project), "<project>").replace(str(Path.home()), "~")


def private(text: str) -> bool:
    """True if the text shares 8 words in a row with an instruction file."""
    words = re.findall(r"\w+", text.lower())
    grams = {" ".join(words[i : i + 8]) for i in range(len(words) - 7)}
    for path in INSTRUCTIONS:
        if path.exists():
            other = re.findall(r"\w+", path.read_text(encoding="utf-8").lower())
            if grams & {" ".join(other[i : i + 8]) for i in range(len(other) - 7)}:
                return True
    return False


Run = Callable[[str, list[str]], str]


def relay_runner(relay: str) -> tuple[Path, Run, str, str, list[str]]:
    """The project of a relay, its function that sends one prompt, the start and end prompts, and
    the arguments of the end prompt."""
    run: Run
    if relay == "plugin":
        project = Path(tempfile.mkdtemp(prefix="verbatim-relay-report-")).resolve()
        opts = {"options": {"cli": CLI, "start_on": False}}
        conf = {"pluginConfigs": {"verbatim-relay": opts, "verbatim-relay@inline": opts}}
        base = [
            "--plugin-dir",
            str(ROOT / "plugins" / "claude-code"),
            "--settings",
            json.dumps(conf),
        ]

        def run(prompt: str, extra: list[str]) -> str:
            return claude(prompt, project, [*base, *extra])

        start, end = "/verbatim-relay start", "verbatim-relay end"
        end_args = CLAUDE_TOOLS
    else:
        harness = relay.removeprefix("hooks-")
        if harness == "claude-code":
            project = Path(tempfile.mkdtemp(prefix="verbatim-relay-report-")).resolve()
            kit.init(project, "claude-code", kit.Config())

            def run(prompt: str, extra: list[str]) -> str:
                return claude(prompt, project, extra)

            end_args = CLAUDE_TOOLS
        else:
            # Its hooks name this root. Codex runs them only after a person trusts them, so the
            # script never writes them.
            project = CODEX_PROJECT

            def run(prompt: str, extra: list[str]) -> str:
                return codex(prompt, project, extra)

            end_args = ["-s", "workspace-write"]
        start, end = "verbatim-relay start", "verbatim-relay end"
    return project, run, start, end, end_args


def run_test(
    project: Path, run: Run, start: str, end: str, end_args: list[str], messages: list[str]
) -> tuple[Path, str] | None:
    """Start a test, send the messages, and end it with the evaluation. Return the test folder and
    the answer of the end prompt, or None if the test did not start."""
    run(start, [])
    cur = bridge.current(project)
    if cur is None:
        return None
    try:
        for m in messages:
            run(m, [])
            print("sent", repr(m[:40]), flush=True)
    finally:
        answer = run(end, end_args)
        if bridge.current(project) is not None:
            subprocess.run([CLI, "end", "--root", str(project)], capture_output=True, timeout=300)
    return Path(cur["dir"]), answer


def main() -> int:
    relay = sys.argv[1]
    project, run, start, end, end_args = relay_runner(relay)
    setup(project)
    ran = run_test(project, run, start, end, end_args, MESSAGES)
    if ran is None:
        print("FAIL: the test did not start")
        return 1
    folder, answer = ran

    trace = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    calls = [
        (n, it)
        for n, it in enumerate(trace, 1)
        if it["name"] == "refund" and it["source"]["file"] != "otel.jsonl"
    ]
    events = [
        (n, it)
        for n, it in enumerate(trace, 1)
        if it["kind"] == "log"
        and it["name"] == "tool_result"
        and "refund" in str(it["input"].get("tool_parameters"))
    ]
    exchanges = [json.loads(x) for x in (folder / "tap.jsonl").read_text().split("\n") if x]
    replies = [r["reply"] for r in exchanges if r.get("type") == "exchange" and r.get("reply")]
    refund_ids = re.findall(r"RF-[0-9A-F]{6}", json.dumps([it["output"] for _, it in calls]))
    report_path = folder / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    issues = rows(report)
    lines = {f"trace.jsonl:{n}" for n, it in calls if it["turn"] == REFUND_TURN}
    p6 = any(
        r["class"] == "business_rule"
        and r["turn"] == str(REFUND_TURN)
        and any(x in r["evidence"] for x in lines)
        for r in issues
    )
    audit = json.loads((folder / "audit.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    hidden = private(report) or private(answer)
    findings = json.loads((folder / "findings.json").read_text())
    sealed = seal.verify(folder)
    result = {
        "date": date.today().isoformat(),
        "relay": relay,
        "versions": {
            **manifest["versions"],
            "agent sdk": AGENT_SDK,
            "session files": {
                s["harness"]: s["version"]
                for s in json.loads((folder / "findings.json").read_text())["sessions"]
            },
        },
        "turns": audit["turns"],
        "audit_exit": audit["exit"],
        "refund_calls": [{"line": n, "turn": it["turn"], "input": it["input"]} for n, it in calls],
        "report_written": report_path.exists(),
        "issues": [{k: r[k] for k in ("class", "turn", "evidence")} for r in issues],
        "P5_quotes_the_refund_id": any(i in report for i in refund_ids),
        "P5_quotes_a_reply": quotes_a_reply(report, replies),
        "commands_outside_project": outside(COMMANDS, project) if relay == "hooks-codex" else None,
        "P6_finds_the_planted_bug": p6,
        "seal": {k: v for k, v in sealed.items() if k != "test"},
        "P7_records_unchanged": sealed["intact"],
        "otel": findings["otel"],
        "otel_refund_events": [{"line": n, "turn": it["turn"]} for n, it in events],
        "otel_tool_not_in_session": findings["counts"]["otel_tool_not_in_session"],
        "P8_otel_has_the_refund": any(it["turn"] == REFUND_TURN for _, it in events)
        and findings["counts"]["otel_tool_not_in_session"] == 0,
        # The Agent SDK calls go through the model API proxy. The trace keeps none of them.
        "model_api": findings.get("model_api"),
        # A text that shares 8 words with an instruction file stays out of the repo.
        "report": None if hidden else scrub(report, project),
        "answer": None if hidden else scrub(answer, project),
    }
    result["pass"] = (
        audit["exit"] == 0
        and bool(calls)
        and (result["P5_quotes_the_refund_id"] or result["P5_quotes_a_reply"])
        and not result["commands_outside_project"]
        and result["P6_finds_the_planted_bug"]
        and result["P7_records_unchanged"]
        and result["P8_otel_has_the_refund"]
    )
    out = ROOT / "proofs" / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{relay}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("report", "answer")}))
    print("PASS" if result["pass"] else "FAIL", out / f"{relay}.json")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""A worked evaluation: one test of the toy shop agent through the Claude Code plugin. Local only.

The tester types `nookku start`, sends 7 messages and types `nookku end`. The config turns the
evaluation at the end off. Then the model reads the transcript of the test with the transcript
tool only, and evaluates the agent from the words. The script reads the records of the test folder
(.nookku/tests/<id>/) and writes examples/toy-shop/evaluation.json. The model's answer is
different on each run.

The project is a temporary folder outside the repo, so the model cannot read the docs or the code
of the agent. The toy shop HTTP agent runs on a free port.

usage: uv run python scripts/example_evaluation.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from proof_common import held_port, json_lines, private  # noqa: E402
from proof_report import ENV, relay_runner, run_test, scrub  # noqa: E402

from nookku import kit, mcp  # noqa: E402
from nookku.record import turns  # noqa: E402

EXAMPLE = ROOT / "examples" / "toy-shop"
APP_FILES = ("agent.py", "http_agent.py", "http_entry.py")
MESSAGES = [
    "hi, the mug i ordered came with a crack in the handle",
    "the blue mug",
    "can i get my money back?",
    "THE MUG",
    "ok what is your refund policy",
    "do you ship to delhi?",
    "how much is the teapot",
]
PROMPT = (
    "Read the nookku transcript. Evaluate the agent: does it follow the refund policy, "
    "is the tone right, is each answer accurate? Quote the turns that you judge."
)
# The evaluation reads the transcript and nothing else. Claude Code lets the model read the files
# of the project with no permission, so the evaluation gets no built-in tool. --tools does not
# limit the MCP tools, so the evaluation gets only the nookku server of the plugin, with no other
# MCP server of the user, the project or a plugin. The evaluation also reads no user settings, so
# no plugin of the user loads, and it runs no hook. ENV gives an empty CLAUDE_CODE_PLUGIN_DIRS, so
# no mod loads (#424). Claude Code still loads its built-in plugins, so the script stores the
# plugins of the session and fails if a plugin is not built in.
SERVER = json.loads((ROOT / "plugins" / "nookku" / ".mcp.json").read_text())["mcpServers"]
SERVERS = {"mcpServers": {mcp.SERVER: {k: SERVER[mcp.SERVER][k] for k in ("command", "args")}}}
TRANSCRIPT = f"mcp__{mcp.SERVER}__transcript"
OTHER_TOOLS = [f"mcp__{mcp.SERVER}__{t['name']}" for t in mcp.TOOLS if t["name"] != "transcript"]
WORDS_ONLY = [
    "--setting-sources",
    "project,local",
    f"--settings={json.dumps({'disableAllHooks': True})}",
    "--tools",
    "",
    "--strict-mcp-config",
    f"--mcp-config={json.dumps(SERVERS)}",
    f"--allowedTools={TRANSCRIPT}",
    f"--disallowedTools={','.join(OTHER_TOOLS)}",
]


def setup(project: Path, python: str = sys.executable) -> None:
    """Copy the toy shop HTTP agent into the project and configure a test with no evaluation at
    the end. The entry runs with the Python of this checkout, so it imports this nookku."""
    for name in APP_FILES:
        shutil.copy(EXAMPLE / name, project / name)
    (project / kit.STATE_DIR).mkdir(parents=True, exist_ok=True)
    data = {
        "entry": [python, str(project / "http_entry.py")],
        "models": [],
        "evaluate": False,
        # A script run opens no browser tab.
        "page": False,
    }
    (project / kit.STATE_DIR / "config.json").write_text(json.dumps(data, indent=1) + "\n")
    (project / kit.STATE_DIR / "mode").write_text("off\n")


class Session(NamedTuple):
    """The result event of one claude -p run, and the tools and plugins of its init event."""

    answer: dict[str, Any]
    tools: list[str]
    plugins: list[dict[str, Any]]


def problem(session: Session) -> str | None:
    """Why the session was not an evaluation of the words only, or None. A session with no init
    event has no tools and no plugins, so it fails."""
    if session.tools != [TRANSCRIPT]:
        return f"the evaluation had the tools {session.tools}, not only {TRANSCRIPT}"
    if not session.plugins:
        return "the init event names no plugins"
    other = [p.get("source") for p in session.plugins if p.get("path") != "builtin"]
    if other:
        return f"the evaluation loaded plugins that are not built in: {other}"
    return None


def collect(folder: Path, session: Session, project: Path) -> dict[str, Any]:
    """The result of the run, from the records of the test folder, and the answer, the tools and
    the plugins of the model. An answer that shares 8 words with an instruction file stays out."""
    answer = session.answer
    audit = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    text = answer.get("result") or ""
    return {
        "date": date.today().isoformat(),
        "test": folder.name,
        "versions": manifest["versions"],
        "models": list((answer.get("modelUsage") or {}).keys()),
        "audit_exit": audit["exit"],
        "turns": audit["turns"],
        "transcript": [{"said": t.said, "shown": t.shown} for t in turns(folder / "relay.jsonl")],
        "prompt": PROMPT,
        "tools": session.tools,
        "plugins": [p.get("source") for p in session.plugins],
        "evaluation": None if private(text) else scrub(text, project),
    }


def ask(prompt: str, project: Path, extra: list[str]) -> Session:
    """Run claude -p once."""
    p = subprocess.run(
        ["claude", "-p", "--output-format", "stream-json", "--verbose", *extra, prompt],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=project,
        env=ENV,
        timeout=900,
    )
    events = json_lines(p.stdout)
    init = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    results = [e for e in events if e.get("type") == "result"]
    tools = [str(t) for t in init[0].get("tools", [])] if init else []
    plugins = [p for p in init[0].get("plugins", []) if isinstance(p, dict)] if init else []
    return Session(results[-1] if results else {}, tools, plugins)


def finish(folder: Path, session: Session, project: Path, out: Path) -> int:
    """Check the session, then write the result. If the check fails, write no file."""
    why = problem(session)
    if why is not None:
        print(f"FAIL: {why}. The script wrote no result.")
        return 1
    result = collect(folder, session, project)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: result[k] for k in ("versions", "models", "audit_exit", "turns")}))
    if result["evaluation"] is None:
        print("The answer shares 8 words with an instruction file. The result does not keep it.")
    return 0 if result["audit_exit"] == 0 and result["turns"] == len(MESSAGES) else 1


def main() -> int:
    project, run, start, end, _ = relay_runner("plugin-claude-code")
    # Remove the temporary project also if a step raises an error, for example a timeout of ask().
    try:
        setup(project)
        # The socket holds the port until the test ends, so no other process takes it.
        with held_port() as port:
            ENV["TOY_SHOP_PORT"] = str(port)
            ran = run_test(project, run, start, end, [], MESSAGES)
        if ran is None:
            print("FAIL: the test did not start")
            return 1
        folder, _ = ran
        session = ask(PROMPT, project, WORDS_ONLY)
        return finish(folder, session, project, EXAMPLE / "evaluation.json")
    finally:
        shutil.rmtree(project, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

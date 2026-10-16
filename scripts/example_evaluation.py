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
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from proof_report import ENV, private, relay_runner, run_test, scrub  # noqa: E402

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
# of the project with no permission, so the evaluation gets no built-in tool.
TOOLS = [mcp.tool_name("claude-code", "transcript")]
WORDS_ONLY = ["--tools", "", f"--allowedTools={','.join(TOOLS)}"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


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


def collect(folder: Path, answer: dict[str, Any], project: Path) -> dict[str, Any]:
    """The result of the run, from the records of the test folder and the answer of the model.
    An answer that shares 8 words with an instruction file stays out of the result."""
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
        "tools": TOOLS,
        "evaluation": None if private(text) else scrub(text, project),
    }


def ask(prompt: str, project: Path, extra: list[str]) -> dict[str, Any]:
    """The JSON answer of one claude -p run."""
    p = subprocess.run(
        ["claude", "-p", "--output-format", "json", *extra, prompt],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=project,
        env=ENV,
        timeout=900,
    )
    out: dict[str, Any] = json.loads(p.stdout[p.stdout.index("{") :]) if "{" in p.stdout else {}
    return out


def main() -> int:
    project, run, start, end, _ = relay_runner("plugin-claude-code")
    setup(project)
    ENV["TOY_SHOP_PORT"] = str(free_port())
    ran = run_test(project, run, start, end, [], MESSAGES)
    if ran is None:
        print("FAIL: the test did not start")
        return 1
    folder, _ = ran
    plugin = ["--plugin-dir", str(ROOT / "plugins" / "nookku")]
    answer = ask(PROMPT, project, [*plugin, *WORDS_ONLY])
    result = collect(folder, answer, project)
    out = EXAMPLE / "evaluation.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: result[k] for k in ("versions", "models", "audit_exit", "turns")}))
    if result["evaluation"] is None:
        print("The answer shares 8 words with an instruction file. The result does not keep it.")
    shutil.rmtree(project, ignore_errors=True)
    return 0 if result["audit_exit"] == 0 and result["turns"] == len(MESSAGES) else 1


if __name__ == "__main__":
    sys.exit(main())

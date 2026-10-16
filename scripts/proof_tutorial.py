"""The run of docs/getting-started.md: each step that needs no model, in one run.

The script makes a new toy shop project in a temporary folder and runs the commands of the
tutorial in it. For each prompt of the tutorial, it gives the project hooks a Claude Code hook
event, so the output is the text that the hooks give to Claude Code. Claude Code and the model do
not run, so steps 7 and 9 have no model output. The browser of the chat page is curl, so no window
opens. The script writes the output of each step to proofs/tutorial/output.txt, with the
temporary folder as `...`.

usage: python scripts/proof_tutorial.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__  # noqa: E402

OUT = ROOT / "proofs" / "tutorial" / "output.txt"
MESSAGES = [
    "hi, the mug i ordered came with a crack in the handle",
    "ok what is your refund policy",
    "do you ship to delhi?",
]
CONTRACT_LINE = json.dumps(
    {"v": 1, "id": "1", "session": "s1", "message": "do you ship to delhi?", "history": []}
)
CASE = "nookku/conformance/cases/several_breaks"


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-tutorial-")).resolve()
    shop = work / "toy-shop"
    shop.mkdir()
    shutil.copy(ROOT / "examples" / "toy-shop" / "agent.py", shop / "agent.py")
    # The tutorial clones the repo next to the project. Only the conformance case is needed.
    shutil.copytree(ROOT / "conformance" / "cases" / "several_breaks", work / CASE)
    nookku = Path(sys.executable).parent
    env = dict(os.environ, PATH=f"{nookku}{os.pathsep}{os.environ['PATH']}")
    # The interactive CLI of Claude Code gives the hooks this entrypoint (src/nookku/print_mode.py).
    env |= {"CLAUDE_CODE_ENTRYPOINT": "cli", "BROWSER": "curl -s -o /dev/null %s"}
    lines = [f"Run of docs/getting-started.md on {date.today()}, nookku {__version__}.", ""]

    def shell(command: str) -> None:
        # One pipe for stdout and stderr keeps the order of the lines of the 2 streams.
        done = subprocess.run(
            command,
            shell=True,
            cwd=shop,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
        lines.extend([f"$ {command}", done.stdout + f"[exit {done.returncode}]", ""])

    def prompt(text: str) -> None:
        event = {"hook_event_name": "UserPromptSubmit", "session_id": "tutorial", "cwd": str(shop)}
        event["prompt"] = text
        hook = ["-m", "nookku", "hook", "--root", str(shop), "--harness", "claude-code"]
        done = subprocess.run(
            [sys.executable, *hook],
            input=json.dumps(event),
            cwd=shop,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        answer = json.loads(done.stdout) if done.stdout.strip() else {}
        shown = answer.get("reason")
        if shown is None:
            # The prompt goes to the model with this context. Keep the end text, not the prompt.
            context = answer.get("hookSpecificOutput", {}).get("additionalContext", "")
            shown = context.split("\n\n# Evaluate", 1)[0] + "\n[the evaluation prompt follows]"
        lines.extend([f"> prompt: {text}", shown, f"[exit {done.returncode}]", ""])

    try:
        shell("nookku --version")
        shell(f"echo '{CONTRACT_LINE}' | python3 agent.py")
        shell('nookku init claude-code --entry "python3 agent.py"')
        shell("nookku check")
        prompt("nookku start")
        for message in MESSAGES:
            prompt(message)
        shell("nookku view --no-follow")
        prompt("nookku end")
        shell("ls .nookku/tests/")
        test = sorted(p.name for p in (shop / ".nookku" / "tests").iterdir())[-1]
        folder = f".nookku/tests/{test}"
        shell(f"nookku audit --tap {folder}/tap.jsonl --relay {folder}/relay.jsonl")
        shell(f"nookku audit --tap ../{CASE}/tap.jsonl --relay ../{CASE}/relay.jsonl")
        shell("nookku verify")
        shell("nookku trace")
        shell(f"cat {folder}/findings.json")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines).replace(str(work), "..."), encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

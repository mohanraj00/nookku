"""The run of docs/getting-started.md, in one run. Local only.

The script makes a new toy shop project in a temporary folder and runs the commands of the
tutorial in it. The browser of the chat page is curl, so no window opens. The script writes the
output of each step to proofs/tutorial/output.txt, with the temporary folder as `...`.

With no option, Claude Code and the model do not run. For each prompt of the tutorial, the script
gives the project hooks a Claude Code hook event, so the output is the text that the hooks give to
Claude Code. Thus steps 7 and 9 have no model output.

With --model, Claude Code 2.1 or later and the model run. The script gives each prompt to
`claude -p`, with no user settings, user plugin or user MCP server, and with
CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1, the fix for
print mode (docs/troubleshooting.md). The prompt `nookku end` starts the evaluation. The model can
run only the commands of step 7 of the tutorial. The output then also has the summary of step 7
and the report of step 9. A model text that shares 8 words in a row with an instruction file
stays out of the repo.

Each run also writes proofs/tutorial/run.json, with the versions, so the 2 files always come from
the same run. With --model, it also has each line of agent.py that the summary or the report
cites.

usage: python scripts/proof_tutorial.py [--model]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import NO_MODS, NO_TITLE, claude_events, claude_isolated, private  # noqa: E402

from nookku import __version__  # noqa: E402

OUT = ROOT / "proofs" / "tutorial" / "output.txt"
RUN = ROOT / "proofs" / "tutorial" / "run.json"
AGENT = ROOT / "examples" / "toy-shop" / "agent.py"
MESSAGES = [
    "hi, the mug i ordered came with a crack in the handle",
    "ok what is your refund policy",
    "do you ship to delhi?",
]
CONTRACT_LINE = json.dumps(
    {"v": 1, "id": "1", "session": "s1", "message": "do you ship to delhi?", "history": []}
)
CASE = "nookku/conformance/cases/several_breaks"
# The commands that step 7 of the tutorial tells the tester to allow.
TOOLS = [
    "--tools=Bash,Read,Grep,Glob,Write",
    "--allowedTools=Bash(nookku transcript:*),Bash(cat:*),Bash(sed -n:*),Bash(jq:*),"
    "Bash(grep:*),Read,Grep,Glob,Write",
]
# Claude Code puts these lines around the reason of a blocked prompt in print mode.
BLOCKED = "UserPromptSubmit operation blocked by hook:\n"
ORIGINAL = "\n\nOriginal prompt: "
CITE = re.compile(r"agent\.py:(\d+)(?:-(\d+))?")


def cites(text: str) -> list[dict[str, Any]]:
    """Each line of agent.py that the text cites, with its source."""
    source = AGENT.read_text(encoding="utf-8").splitlines()
    out = []
    for m in sorted(set(CITE.findall(text)), key=lambda c: (int(c[0]), c[1])):
        first, last = int(m[0]), int(m[1] or m[0])
        cite = f"agent.py:{m[0]}" + (f"-{m[1]}" if m[1] else "")
        out.append({"cite": cite, "source": source[first - 1 : last]})
    return out


def main() -> int:
    model = "--model" in sys.argv[1:]
    work = Path(tempfile.mkdtemp(prefix="nookku-tutorial-")).resolve()
    shop = work / "toy-shop"
    shop.mkdir()
    shutil.copy(AGENT, shop / "agent.py")
    # The tutorial clones the repo next to the project. Only the conformance case is needed.
    shutil.copytree(ROOT / "conformance" / "cases" / "several_breaks", work / CASE)
    nookku = Path(sys.executable).parent
    env = dict(os.environ, PATH=f"{nookku}{os.pathsep}{os.environ['PATH']}")
    env |= {"BROWSER": "curl -s -o /dev/null %s"}
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(name, None)
    if model:
        env |= NO_TITLE | NO_MODS
    else:
        # The interactive CLI gives the hooks this entrypoint (src/nookku/print_mode.py).
        env |= {"CLAUDE_CODE_ENTRYPOINT": "cli"}
    lines = [f"Run of docs/getting-started.md on {date.today()}, nookku {__version__}."]
    lines += ["Claude Code and the model ran." if model else "Claude Code did not run.", ""]
    answers: dict[str, str] = {}
    models: set[str] = set()
    plugins: set[str] = set()

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

    def hook(text: str) -> tuple[str, int]:
        event = {"hook_event_name": "UserPromptSubmit", "session_id": "tutorial", "cwd": str(shop)}
        event["prompt"] = text
        args = ["-m", "nookku", "hook", "--root", str(shop), "--harness", "claude-code"]
        done = subprocess.run(
            [sys.executable, *args],
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
        return shown, done.returncode

    def claude(text: str) -> tuple[str, int]:
        cmd = ["claude", "-p", *claude_isolated(plugin=False)]
        if text == "nookku end":
            cmd += TOOLS
        done = subprocess.run(
            [*cmd, text],
            cwd=shop,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        data, loaded = claude_events(done.stdout)
        plugins.update(loaded)
        models.update(data.get("modelUsage") or {})
        result = str(data.get("result") or f"(no answer: {done.stderr.strip()[-300:]})")
        if result.startswith(BLOCKED):
            # A blocked prompt: the model did not run. Keep the reason that Claude Code shows.
            return result[len(BLOCKED) :].rsplit(ORIGINAL, 1)[0], done.returncode
        answers[text] = result
        return "[the model answer, below]", done.returncode

    def prompt(text: str) -> None:
        shown, code = claude(text) if model else hook(text)
        lines.extend([f"> prompt: {text}", shown, f"[exit {code}]", ""])

    run: dict[str, Any] = {}
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
        tests = sorted(p.name for p in (shop / ".nookku" / "tests").iterdir())
        test = tests[-1]
        folder = f".nookku/tests/{test}"
        shell(f"nookku audit --tap {folder}/tap.jsonl --relay {folder}/relay.jsonl")
        shell(f"nookku audit --tap ../{CASE}/tap.jsonl --relay ../{CASE}/relay.jsonl")
        if model:
            report = shop / folder / "report.md"
            answers["report.md"] = report.read_text(encoding="utf-8") if report.exists() else ""
        shell("nookku verify")
        shell("nookku trace")
        shell(f"cat {folder}/findings.json")
        manifest = json.loads((shop / folder / "manifest.json").read_text(encoding="utf-8"))
        run = {"date": date.today().isoformat(), "tests": tests, **manifest["versions"]}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    text = "\n".join(lines)
    # With no --model, Claude Code does not run, so the run has no plugins.
    run |= {"model": sorted(models), "plugins": sorted(plugins) if model else None}
    if model:
        summary, report_text = answers.get("nookku end", ""), answers.get("report.md", "")
        hidden = private(summary) or private(report_text)
        for name, body in (("summary of step 7", summary), ("report.md of step 9", report_text)):
            text += f"\n==== The model's {name} ====\n"
            text += "[not kept: it shares 8 words with an instruction file]\n" if hidden else body
        run |= {"kept": not hidden, "cites": cites(summary + report_text)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # The model can also name the folder without the /private link of macOS.
    for path in (str(work), str(work).removeprefix("/private")):
        text = text.replace(path, "...")
    OUT.write_text(text.replace(str(Path.home()), "~"), encoding="utf-8")
    print(f"Wrote {OUT}")
    # The 2 files always come from the same run, also with no model.
    RUN.write_text(json.dumps(run, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {RUN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

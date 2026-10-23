"""The setup asks and confirms before it builds (#329). Local only.

The script copies examples/toy-shop-full/ to a temporary folder, with no entry.py, no APP_SPEC.md
and no README.md. Thus the setup must find the wiring in the code, and the project has no app spec.
Then Claude Code and the model follow src/nookku/setup.md of this checkout in 3 prompts of one
session:

1. The guide and the prompt of docs/how-to/test-your-app.md. The setup must give the summary and
   ask at least one question.
2. The answers of the tester. The setup must show the plan.
3. A clear yes. The setup must write the entry, the config and the app spec draft.

Each session gets only the settings of the project, no MCP server of the user and no mod
(proof_common.py). It can use Read, Grep, Glob, Write and Edit with no question. Claude Code denies
each shell command that it does not take as read-only, also `nookku check`. Thus the proof does
not cover step 5 of the guide. The tutorial proof covers `check`.

The checks:

- S1: after prompts 1 and 2, no file of the project changed, and the model called no Write or Edit.
- S2: answer 1 has the 5 parts of the summary and a question.
- S3: after prompt 3, `.nookku/config.json` passes the config reader, its `entry` names a file of
  the project or a command, and its `spec` names a draft with `Persona`, `Boundaries` and
  `User goals` sections.
- S4: no file of the app changed: only new files in `.nookku/` and the draft.

The script writes proofs/setup/results.json with the versions, each answer and each new file. A
model text that shares 8 words in a row with an instruction file stays out of the repo.

usage: python scripts/proof_setup.py
"""

from __future__ import annotations

import hashlib
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

from proof_common import (  # noqa: E402
    NO_MODS,
    NO_TITLE,
    claude_events,
    claude_isolated,
    json_lines,
    private,
)

from nookku import __version__, config  # noqa: E402

OUT = ROOT / "proofs" / "setup" / "results.json"
SHOP = ROOT / "examples" / "toy-shop-full"
GUIDE = ROOT / "src" / "nookku" / "setup.md"
LEFT_OUT = ("entry.py", "APP_SPEC.md", "README.md")
# The prompt of docs/how-to/test-your-app.md, after the output of `!nookku setup`.
ASK = "Follow the nookku setup guide, and connect a test to this app."
ANSWERS = (
    "Use your proposed answer for each question. Do not reset the state between tests, so "
    "keep the entry a thin wrapper."
)
YES = "Yes, go ahead."
TOOLS = [
    "--tools=Read,Grep,Glob,Write,Edit,Bash",
    "--allowedTools=Read,Grep,Glob,Write,Edit",
    "--permission-mode=acceptEdits",
]
WRITERS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SUMMARY = ("in and out", "harness", "backend", "store", "rules")
SECTIONS = ("Persona", "Boundaries", "User goals")


def files(root: Path) -> dict[str, str]:
    """The SHA-256 of each file of the project, by its path."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def changes(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "new": sorted(set(after) - set(before)),
        "changed": sorted(p for p in set(before) & set(after) if before[p] != after[p]),
        "removed": sorted(set(before) - set(after)),
    }


def headings(text: str) -> list[str]:
    return re.findall(r"^## (.+?)\s*$", text, re.MULTILINE)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-setup-")).resolve()
    shop = work / "toy-shop"
    shutil.copytree(SHOP, shop, ignore=shutil.ignore_patterns("__pycache__", *LEFT_OUT))
    nookku = Path(sys.executable).parent
    env = dict(os.environ, PATH=f"{nookku}{os.pathsep}{os.environ['PATH']}")
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(name, None)
    env |= NO_MODS | NO_TITLE
    guide = GUIDE.read_text(encoding="utf-8")
    turns: list[dict[str, Any]] = []
    models: set[str] = set()
    session = ""
    start = files(shop)
    try:
        for n, text in enumerate((f"{guide}\n\n{ASK}", ANSWERS, YES), 1):
            cmd = ["claude", "-p", *claude_isolated(plugin=False), *TOOLS]
            if session:
                cmd += ["--resume", session]
            before = files(shop)
            done = subprocess.run(
                [*cmd, text],
                cwd=shop,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=1800,
            )
            result, _ = claude_events(done.stdout)
            session = str(result.get("session_id") or session)
            models.update(result.get("modelUsage") or {})
            tools = [
                str(block.get("name"))
                for event in json_lines(done.stdout)
                if event.get("type") == "assistant"
                for block in event.get("message", {}).get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_use"
            ]
            denied = [str(d.get("tool_name")) for d in result.get("permission_denials") or []]
            answer = str(result.get("result") or f"(no answer: {done.stderr.strip()[-300:]})")
            turns.append(
                {
                    "prompt": "[setup.md] + " + ASK if n == 1 else text,
                    "answer": answer,
                    "exit": done.returncode,
                    "tools": tools,
                    "denied": denied,
                    "files": changes(before, files(shop)),
                }
            )
        end = files(shop)
        made = {p: (shop / p).read_text(encoding="utf-8") for p in changes(start, end)["new"]}
    finally:
        version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout
        shutil.rmtree(work, ignore_errors=True)

    checks: dict[str, bool] = {}
    quiet = turns[:2]
    checks["S1"] = all(
        not any(t["files"].values()) and not WRITERS & set(t["tools"]) for t in quiet
    )
    first = turns[0]["answer"].lower()
    checks["S2"] = all(part in first for part in SUMMARY) and "?" in first
    s3 = False
    spec: list[str] = []
    try:
        data = config.check(json.loads(made.get(".nookku/config.json", "")))
        spec = list(data.get("spec") or [])
        drafts = [made.get(p, "") for p in spec]
        s3 = (
            bool(data.get("entry"))
            and bool(drafts)
            and all(set(SECTIONS) <= set(headings(d)) for d in drafts)
        )
    except (ValueError, config.ConfigError):
        s3 = False
    checks["S3"] = s3
    final = changes(start, end)
    checks["S4"] = (
        not final["changed"]
        and not final["removed"]
        and all(p.startswith(".nookku/") or p in spec for p in final["new"])
    )
    texts = [t["answer"] for t in turns] + list(made.values())
    kept = not any(private(t) for t in texts)
    if not kept:
        for t in turns:
            t["answer"] = "[not kept: it shares 8 words with an instruction file]"
        made = {p: "[not kept]" for p in made}
    # The model can also name the folder without the /private link of macOS.
    raw = json.dumps(
        {
            "date": date.today().isoformat(),
            "nookku": __version__,
            "claude_code": version.strip(),
            "model": sorted(models),
            "left_out": list(LEFT_OUT),
            "checks": checks,
            "pass": all(checks.values()),
            "kept": kept,
            "turns": turns,
            "new_files": made,
        },
        indent=1,
        ensure_ascii=False,
    )
    for path in (str(work), str(work).removeprefix("/private")):
        raw = raw.replace(path, "...")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(raw.replace(str(Path.home()), "~") + "\n", encoding="utf-8")
    print(json.dumps(checks))
    print(("PASS" if all(checks.values()) else "FAIL") + f" {OUT}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

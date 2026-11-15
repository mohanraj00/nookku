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
(proof_common.py). The first prompt goes to the model, so a probe session checks the plugins and
the MCP servers first, with a prompt that a hook blocks before the model. Each session can use
Read, Grep, Glob, Write, Edit and `nookku check` with no question. Claude Code denies each other
shell command that it does not take as read-only.

Step 5 (check) needs a fresh egress answer. The discovery of `nookku start` needs the plugin, so
before prompt 3 the script registers the egress answer of the toy shop: the stock service and the
note model, which the script starts. The app writes its state to a copy outside the project
(TOY_SHOP_STATE), so S4 sees only the files of the setup.

The checks:

- S1: after prompts 1 and 2, no file of the project changed, and the model called no Write, no
  Edit and no `nookku check`.
- S2: answer 1 has the 5 parts of the summary and a question. Each part has a short list of
  words (PARTS), because the model names a part in its own words, for example "Data files".
- S3: after prompt 3, `.nookku/config.json` passes the config reader, its `entry` names a file of
  the project or a command, and its `spec` names a draft with `Persona`, `Boundaries` and
  `User goals` sections.
- S4: no file of the app changed: only new files in `.nookku/` and the draft.
- S5: after prompt 3, the model ran `nookku check`, and the output of its last check has PASS.

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
import threading
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SHOP = ROOT / "examples" / "toy-shop-full"
sys.path[:0] = [str(ROOT / "src"), str(SHOP)]

import stock  # noqa: E402
import toy_model  # noqa: E402
from proof_common import (  # noqa: E402
    NO_MODS,
    NO_TITLE,
    claude_events,
    claude_isolated,
    claude_probe,
    json_lines,
    private,
)

from nookku import __version__, config, discovery  # noqa: E402
from nookku.record import loads  # noqa: E402

OUT = ROOT / "proofs" / "setup" / "results.json"
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
    "--allowedTools=Read,Grep,Glob,Write,Edit,Bash(nookku check)",
    "--permission-mode=acceptEdits",
]
WRITERS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# The parts of the summary of step 1, each with the words that name it. A part is there if the
# answer has one of its words.
PARTS = {
    "in and out": ("in and out", "input and output", "in/out"),
    "model harnesses": ("harness", "agent sdk"),
    "backends": ("backend", "model api", "service"),
    "store": ("store", "data file", "database", "storage", "state file"),
    "rules and docs": ("rules", "docs", "documentation"),
}
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


def missing_parts(answer: str) -> list[str]:
    """The parts of PARTS that the answer does not name."""
    text = answer.lower()
    return [part for part, words in PARTS.items() if not any(w in text for w in words)]


def checks_run(events: list[Any]) -> list[dict[str, str]]:
    """Each `nookku check` call of the model in a stream-json output, with its output."""
    calls: dict[str, str] = {}
    outputs: dict[str, str] = {}
    for event in events:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                command = str((block.get("input") or {}).get("command") or "")
                if block.get("name") == "Bash" and command.strip().startswith("nookku check"):
                    calls[str(block.get("id"))] = command
            if event.get("type") == "user" and block.get("type") == "tool_result":
                out = block.get("content")
                if isinstance(out, list):
                    out = "\n".join(str(c.get("text", "")) for c in out if isinstance(c, dict))
                outputs[str(block.get("tool_use_id"))] = str(out or "")
    return [{"command": c, "output": outputs.get(i, "")} for i, c in calls.items()]


def passed(output: str) -> bool:
    return "PASS" in (line.strip() for line in output.split("\n"))


def headings(text: str) -> list[str]:
    return re.findall(r"^## (.+?)\s*$", text, re.MULTILINE)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-setup-")).resolve()
    shop = work / "toy-shop"
    shutil.copytree(SHOP, shop, ignore=shutil.ignore_patterns("__pycache__", *LEFT_OUT))
    for name in ("state.json", "stock.json"):
        shutil.copy(SHOP / name, work / name)
    services = [stock.StockService(0, work / "stock.json"), toy_model.ToyModel(0)]
    for server in services:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    egress = discovery.make(
        backends=[{"name": "stock", "env": "STOCK_URL", "url": services[0].url}],
        model_apis=[
            {"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": None},
            {"api": "openai", "env": "OPENAI_BASE_URL", "url": services[1].url},
        ],
    )
    nookku = Path(sys.executable).parent
    env = dict(os.environ, PATH=f"{nookku}{os.pathsep}{os.environ['PATH']}")
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(name, None)
    env |= NO_MODS | NO_TITLE | {"TOY_SHOP_STATE": str(work / "state.json")}
    guide = GUIDE.read_text(encoding="utf-8")
    turns: list[dict[str, Any]] = []
    models: set[str] = set()
    session = ""
    start = files(shop)
    check_runs: list[dict[str, str]] = []
    try:
        claude_probe(["claude", "-p", *claude_isolated(plugin=False), *TOOLS], shop, env)
        for n, text in enumerate((f"{guide}\n\n{ASK}", ANSWERS, YES), 1):
            cmd = ["claude", "-p", *claude_isolated(plugin=False), *TOOLS]
            if session:
                cmd += ["--resume", session]
            if n == 3:
                discovery.register(shop, egress)
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
            runs = checks_run(json_lines(done.stdout))
            check_runs += runs
            session = str(result.get("session_id") or session)
            models.update(result.get("modelUsage") or {})
            tools = [
                str(block.get("name"))
                for event in json_lines(done.stdout)
                if event.get("type") == "assistant"
                for block in event.get("message", {}).get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_use"
            ]
            denials = result.get("permission_denials") or []
            denied = [str(d.get("tool_name")) for d in denials]
            denied_checks = [
                d
                for d in denials
                if str((d.get("tool_input") or {}).get("command", "")).startswith("nookku check")
            ]
            answer = str(result.get("result") or f"(no answer: {done.stderr.strip()[-300:]})")
            turns.append(
                {
                    "prompt": "[setup.md] + " + ASK if n == 1 else text,
                    "answer": answer,
                    "exit": done.returncode,
                    "tools": tools,
                    "denied": denied,
                    "checks": runs,
                    "check_denied": bool(denied_checks),
                    "files": changes(before, files(shop)),
                }
            )
        end = files(shop)
        # The files of the setup. The test folder of the check holds records and logs.
        made = {
            p: (shop / p).read_text(encoding="utf-8")
            for p in changes(start, end)["new"]
            if not p.startswith(".nookku/tests/") and p != ".nookku/discovery.json"
        }
    finally:
        for server in services:
            server.shutdown()
            server.server_close()
        version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout
        shutil.rmtree(work, ignore_errors=True)

    checks: dict[str, bool] = {}
    quiet = turns[:2]
    checks["S1"] = all(
        not any(t["files"].values()) and not WRITERS & set(t["tools"]) and not t["checks"]
        for t in quiet
    )
    first = turns[0]["answer"].lower()
    missing = missing_parts(first)
    checks["S2"] = not missing and "?" in first
    s3 = False
    spec: list[str] = []
    try:
        data = config.check(loads(made.get(".nookku/config.json", "")))
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
    checks["S5"] = (
        bool(check_runs)
        and not any(t["check_denied"] for t in turns)
        and passed(check_runs[-1]["output"])
    )
    texts = [t["answer"] for t in turns] + list(made.values()) + [r["output"] for r in check_runs]
    kept = not any(private(t) for t in texts)
    if not kept:
        for t in turns:
            t["answer"] = "[not kept: it shares 8 words with an instruction file]"
            t["checks"] = [{"command": r["command"], "output": "[not kept]"} for r in t["checks"]]
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
            "s2_missing": missing,
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

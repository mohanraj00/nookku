"""Record the keys that `hooks/list` of Codex gives for a hook, also for an async hook (#643).

The script uses a new empty CODEX_HOME in a temporary folder, so the user config does not change.
It writes a user `hooks.json` with 2 command hooks of a toy shop. The `UserPromptSubmit` hook has
`"async": true`. The `PreToolUse` hook has no such key. The script reads the hooks with the reader
of the Codex hook gate (`nookku.codex_gate.read_hooks`), which starts `codex app-server` and asks
for `hooks/list`. It runs no hook and no model, and it never calls a trust API.

The script writes proofs/codex-gate/hook-keys.json with the Codex version and the date.

usage: uv run python scripts/proof_codex_hook_keys.py
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from nookku import __version__, codex_gate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "proofs" / "codex-gate" / "hook-keys.json"
COMMAND = "echo toy-shop-hook"
HOOKS = {
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": COMMAND, "timeout": 300, "async": True}]}
        ],
        "PreToolUse": [
            {"matcher": ".*", "hooks": [{"type": "command", "command": COMMAND, "timeout": 30}]}
        ],
    }
}


def listed() -> tuple[list[dict[str, Any]], list[str]]:
    """The 2 toy shop hooks as `hooks/list` gives them, and the notes of Codex."""
    old = os.environ.get("CODEX_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        home, project = Path(tmp) / "codex-home", Path(tmp) / "project"
        home.mkdir()
        project.mkdir()
        (home / "hooks.json").write_text(json.dumps(HOOKS))
        os.environ["CODEX_HOME"] = str(home)
        try:
            hooks, notes = codex_gate.read_hooks(project)
        finally:
            if old is None:
                os.environ.pop("CODEX_HOME")
            else:
                os.environ["CODEX_HOME"] = old
    return [h for h in hooks if h.get("command") == COMMAND], notes


def main() -> int:
    version = subprocess.run(
        [codex_gate.command(), "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    hooks, notes = listed()
    by_event = {str(h.get("eventName")): h for h in hooks}
    prompt, tool = by_event.get("userPromptSubmit", {}), by_event.get("preToolUse", {})
    result: dict[str, Any] = {
        "date": date.today().isoformat(),
        "versions": {
            "codex": version,
            "nookku": __version__,
            "python": platform.python_version(),
            "os": platform.system(),
        },
        "method": "scripts/proof_codex_hook_keys.py",
        "hooks_file": HOOKS,
        "notes": len(notes),
        # The keys of a row of hooks/list, in the order of Codex.
        "keys": list(prompt),
        "listed": [
            {k: h.get(k) for k in ("eventName", "handlerType", "async", "matcher", "timeoutSec")}
            for h in hooks
        ],
        "checks": {
            "Codex lists the 2 hooks": len(hooks) == 2 and len(by_event) == 2,
            "the async hook has async true": prompt.get("async") is True,
            "the other hook has async false": tool.get("async") is False,
        },
    }
    result["pass"] = all(result["checks"].values())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

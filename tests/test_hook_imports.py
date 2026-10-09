"""A hook event imports only the modules that its rule needs (#214, ADR 0001: hook time)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# The modules of the package that a hook event may import.
ALLOWED = {
    "nookku",
    "nookku.__main__",
    "nookku.adapters",
    "nookku.commands",
    "nookku.config",
    "nookku.contract",
    "nookku.hook",
    "nookku.kit",
    "nookku.record",
    "nookku.seal",
    "nookku.state",
}
# Standard modules that only a relay, a test start or a test end needs.
SLOW = {"subprocess", "urllib.request", "http.client", "hashlib", "uuid", "asyncio", "ssl"}

PROBE = """
import io, json, sys
from nookku.__main__ import main
sys.stdin = io.StringIO(sys.argv[2])
sys.stdout = io.StringIO()
main(["hook", "--harness", "claude-code", "--root", sys.argv[1]])
sys.__stdout__.write(json.dumps(sorted(sys.modules)))
"""

EVENTS = {
    "prompt with relay mode off": {"hook_event_name": "UserPromptSubmit", "prompt": "hi"},
    "a tool call that passes": {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls src"},
    },
    "a tool call that reads the state folder": {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "cat .nookku/config.json"},
    },
}


@pytest.mark.parametrize("name", list(EVENTS))
def test_a_hook_event_imports_only_what_its_rule_needs(tmp_path: Path, name: str) -> None:
    (tmp_path / ".nookku").mkdir()
    config = {"tap_url": "http://localhost:9/"}
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps(config))
    out = subprocess.run(
        [sys.executable, "-c", PROBE, str(tmp_path), json.dumps(EVENTS[name])],
        capture_output=True,
        text=True,
        check=True,
    )
    modules = set(json.loads(out.stdout))
    assert sorted(m for m in modules if m.startswith("nookku") and m not in ALLOWED) == []
    assert sorted(modules & SLOW) == []

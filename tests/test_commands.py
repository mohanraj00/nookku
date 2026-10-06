import json
import os
from pathlib import Path

import pytest

from verbatim_relay import commands, kit
from verbatim_relay.record import BlockedCall, read_relay

F = ".verbatim-relay/tests/20261006-080000-cc01"

# The plugin has the same table in plugins/claude-code/hooks/register.test.ts.
READS = [
    f"cat {F}/findings.json",
    f"sed -n '1,200p' {F}/trace.jsonl",
    f"sed -n '/refund/p' {F}/trace.jsonl",
    f"jq '.findings[] | .check' {F}/findings.json",
    f"ls -la {F} && wc -l {F}/tap.jsonl",
    f"grep -n refund {F}/trace.jsonl | head -5",
    f"cat {F}/audit.json 2>/dev/null",
    f"cat {F}/audit.json 2>&1 | tail -n 3",
    f"cat > {F}/report.md <<'EOF'\n# Test: evaluation\nIt's done; rm -rf $(x) > a\nEOF",
    f"cd {F}\nsort -n tap.jsonl",
    "verbatim-relay transcript --trace --test 20261006-080000-cc01",
    f"find {F} -name '*.jsonl'",
    f'cat "{F}/manifest.json"',
]
WRITES = [
    f"sed -i '' 's/a/b/' {F}/trace.jsonl",
    f"sed -ni 's/a/b/p' {F}/trace.jsonl",
    f"sed -n '1w {F}/x' {F}/trace.jsonl",
    f"cat {F}/a > {F}/trace.jsonl",
    f"echo x >> {F}/findings.json",
    f"rm {F}/trace.jsonl",
    f"cd {F} && rm trace.jsonl",
    f"cat {F}/tap.jsonl | tee {F}/copy",
    f"cat {F}/tap.jsonl | python3 -m json.tool",
    f"sort -o {F}/tap.jsonl {F}/tap.jsonl",
    f"find {F} -delete",
    f"cat $(rm {F}/tap.jsonl)",
    f'cat "$(rm {F}/tap.jsonl)"',
    f"cat `rm {F}/tap.jsonl`",
    f"(cat {F}/tap.jsonl)",
    f"X=1 cat {F}/tap.jsonl",
    f"cat '{F}/tap.jsonl",
    "verbatim-relay end",
    "python entry.py",
]


@pytest.mark.parametrize("command", READS)
def test_a_read_passes(command: str) -> None:
    assert commands.reads_only(command)


@pytest.mark.parametrize("command", WRITES)
def test_a_write_or_an_unknown_program_fails(command: str) -> None:
    assert not commands.reads_only(command)


def test_the_command_of_each_shell_tool() -> None:
    assert commands.tool_reads_only("Bash", {"command": "cat a"})
    assert commands.tool_reads_only("shell", {"command": ["bash", "-lc", "cat a | head"]})
    assert commands.tool_reads_only("shell", {"command": ["cat", "a b"]})
    assert not commands.tool_reads_only("shell", {"command": ["rm", "a"]})
    # A tool that is not a shell fails, so the deny fails closed.
    assert not commands.tool_reads_only("mcp__files__read", {"path": "a"})
    assert not commands.tool_reads_only("Bash", {"script": "cat a"})


def test_the_entry_names() -> None:
    entry = ["uv", "run", "--project", "/srv/shop", "python", "/srv/shop/entry.py"]
    assert commands.entry_names(entry) == ["entry.py"]
    assert commands.entry_names(["python", "-m", "shop.entry"]) == ["shop.entry"]
    assert commands.entry_names(["npm", "run", "agent"]) == []
    names = ["entry.py", "shop.entry"]
    assert commands.names_entry('{"command": "python ./entry.py"}', names)
    assert commands.names_entry('{"command": "python /srv/shop/entry.py"}', names)
    assert commands.names_entry('{"command": "python -m shop.entry"}', names)
    assert not commands.names_entry('{"command": "python my_entry.py"}', names)
    assert not commands.names_entry('{"command": "cat entry.pyc"}', names)


def pre(tool: str, tool_input: dict) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


def reason(answer: dict | None) -> str | None:
    return answer["hookSpecificOutput"]["permissionDecisionReason"] if answer else None


def project(tmp_path: Path, running: bool) -> Path:
    state = tmp_path / ".verbatim-relay"
    folder = state / "tests" / "20261006-080000-cc01"
    folder.mkdir(parents=True)
    (state / "config.json").write_text(json.dumps({"entry": ["python", "shop/entry.py"]}))
    if running:
        cur = {"test": folder.name, "pid": os.getpid(), "dir": str(folder), "tap_url": ""}
        (state / "current.json").write_text(json.dumps(cur))
    return folder


def test_during_a_test_the_kit_denies_a_run_of_the_entry(tmp_path: Path) -> None:
    folder = project(tmp_path, running=True)
    run = kit.handle(pre("Bash", {"command": "cd shop && python entry.py"}), tmp_path, "codex")
    assert reason(run) == kit.ENTRY_REASON
    assert kit.handle(pre("Bash", {"command": "cat shop/entry.py"}), tmp_path, "codex") is None
    assert kit.handle(pre("Read", {"file_path": "shop/entry.py"}), tmp_path, "codex") is None
    rows = read_relay(folder / "relay.jsonl")
    assert len(rows) == 1 and isinstance(rows[0], BlockedCall) and rows[0].tool == "Bash"


def test_after_a_test_the_kit_denies_a_shell_write_to_the_records(tmp_path: Path) -> None:
    project(tmp_path, running=False)
    sed = pre("Bash", {"command": f"sed -i '' 's/4471/4417/' {F}/trace.jsonl"})
    assert reason(kit.handle(sed, tmp_path, "claude-code")) == kit.RECORDS_REASON
    tool = pre("mcp__files__write", {"path": f"{F}/tap.jsonl"})
    assert reason(kit.handle(tool, tmp_path, "claude-code")) == kit.RECORDS_REASON
    for command in (f"cat {F}/trace.jsonl", f"cat > {F}/report.md <<'EOF'\n# Report\nEOF"):
        assert kit.handle(pre("Bash", {"command": command}), tmp_path, "codex") is None

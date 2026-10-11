"""The deny of writes to the state folder (SPEC.md section 5, #149): it checks paths, not text."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from nookku import commands, kit

STATE = "." + "nookku"
CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "guard").glob("*.json"))
SED = '"sed" with these arguments can write.'


def _fill(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{root}", str(root))
    if isinstance(value, dict):
        return {k: _fill(v, root) for k, v in value.items()}
    return value


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_conformance(case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = json.loads(case.read_text())
    root = tmp_path.resolve()
    folder = root / STATE / "tests" / "t1"
    folder.mkdir(parents=True)
    if "policy_text" in data:
        (root / STATE / "policy.json").write_text(data["policy_text"])
    if data["test"]:
        cur = {"dir": str(folder), "tap_url": "http://127.0.0.1:9/"}
        monkeypatch.setattr(kit.state, "current", lambda root: cur)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.chdir(root)
    out = io.StringIO()
    event = io.StringIO(json.dumps(_fill(data["event"], root)))
    assert kit.run_hook(None, "claude-code", event, out) == 0
    assert (json.loads(out.getvalue()) if out.getvalue() else None) == data["answer"]


@pytest.mark.parametrize(
    ("command", "targets", "folders", "cause"),
    [
        ("sed -i '' s/a/b/ shop.json", ["-i", "", "s/a/b/", "shop.json"], [], SED),
        ("cat shop.json > out.txt", ["out.txt"], [], 'The redirect ">" writes it.'),
        ("grep -n refund shop.py 2>/dev/null", ["/dev/null"], [], 'The redirect ">" writes it.'),
        ("cd shop && make", [], ["shop"], '"make" is not a read command.'),
        ("python3 <<< 'print(1)'", ["print(1)"], [], '"python3" is not a read command.'),
        ("cat a.txt; echo ${x} $y", [], [], ""),
        (
            "PATH=/tmp cat a.txt",
            [],
            [],
            'The read check does not accept the assignment "PATH=/tmp".',
        ),
        ("IFS=x; cat a.txt", [], [], 'The read check does not accept the assignment "IFS=x".'),
    ],
)
def test_write_targets(command: str, targets: list[str], folders: list[str], cause: str) -> None:
    found = commands.write_targets(command)
    assert found is not None
    assert [w for w, _ in found.targets] == targets
    assert (found.folders, found.cause) == (folders, cause)


def test_guard_reads_adds_programs_but_keeps_each_built_in_check() -> None:
    assert not commands.reads_only("bat shop.json")
    assert commands.reads_only("bat shop.json", frozenset({"bat"}))
    assert not commands.reads_only("sed -i '' s/a/b/ shop.json", frozenset({"sed"}))


def test_a_command_that_the_check_cannot_parse_has_no_targets() -> None:
    assert commands.write_targets("echo $(date) > out.txt") is None


def test_a_heredoc_body_of_code_stays() -> None:
    data = "cat > notes.md <<'EOF'\nsecret\nEOF\necho done"
    assert commands.strip_data_heredocs(data) == "cat > notes.md <<'EOF'\necho done"
    code = "python3 - <<'EOF'\nprint(1)\nEOF"
    assert commands.strip_data_heredocs(code) == "python3 - <<'EOF'\nprint(1)"
    commit = "git commit -F - <<'EOF'\nFix it\nEOF"
    assert commands.strip_data_heredocs(commit) == "git commit -F - <<'EOF'"


@pytest.mark.parametrize(
    ("word", "rest"),
    [
        (f"{STATE}/tests/t1/tap.jsonl", ["tests", "t1", "tap.jsonl"]),
        (f"/home/me/shop/{STATE.upper()}/mode", ["mode"]),
        (f"of={STATE}/relay.jsonl", ["relay.jsonl"]),
        (f"{STATE}/tests/../config.json", ["config.json"]),
        (".noo*/mode", ["mode"]),
        ("*/mode", None),
        ("shop/config.json", None),
    ],
)
def test_state_rest(word: str, rest: list[str] | None) -> None:
    assert commands.state_rest(word) == rest


@pytest.mark.parametrize(
    ("command", "what"),
    [
        ("nookku start", "nookku start"),
        ("X=1 nookku end", "nookku end"),
        ("nookku mode --root . on", "nookku mode on"),
        ("time python3 -m nookku start", "nookku start"),
        ("uv run --with shop nookku end", "nookku end"),
        ("sudo -u shop nookku hook", "nookku hook"),
        ("env A=1 bash -lc 'nookku end'", "nookku end"),
        ("pipx run nookku run --script s.jsonl", "nookku run"),
        ("echo $(nookku start)", "nookku start"),
        ("uv run --python python3 nookku start", "nookku start"),
        ("env -u HOME python3 -m nookku end", "nookku end"),
        ("uv run --python python3 shop/agent.py", None),
        ("python -m nookku.kit", commands.IMPORT),
        ("python3 -c 'from nookku import kit'", commands.IMPORT),
        ("python3 -c \"__import__('nookku')\"", commands.IMPORT),
        ("nookku mode", None),
        ("nookku mode status", None),
        ("nookku check", None),
        ("uvx nookku audit", None),
        ("echo nookku start", None),
        ('grep -rn "import nookku" shop', None),
        ("bash shop/run.sh", None),
    ],
)
def test_drive(command: str, what: str | None) -> None:
    assert commands.drive(command) == what


@pytest.mark.parametrize(
    ("command", "what"),
    [
        ("nookku run --script s.jsonl", None),
        ("nookku run --script s.jsonl; nookku start", "nookku start"),
        ("nookku run --script s.jsonl && python3 -c 'import nookku'", commands.IMPORT),
        ("bash -c 'nookku run --script s.jsonl; nookku end'", "nookku end"),
        ("echo $(nookku run --script s.jsonl) $(nookku start)", "nookku start"),
    ],
)
def test_an_allowed_drive_does_not_hide_a_later_drive(command: str, what: str | None) -> None:
    assert commands.drive(command, frozenset({"nookku run"})) == what


def test_the_drive_deny_applies_with_no_state_folder(tmp_path: Path) -> None:
    # A model can write the config with init and start a test in one command.
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "nookku init plugin && nookku start"},
    }
    out = io.StringIO()
    assert kit.run_hook(tmp_path, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    reason = json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason == kit.DRIVE_REASON.format(what="nookku start")
    assert not (tmp_path / STATE).exists()

"""The policy file (SPEC.md section 7.9) and the deny of each model write to it (section 5)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from nookku import bridge, kit, policy
from nookku.cli import main

STATE = ".nookku"
CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "policy").glob("*.json"))


def _fill(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{root}", str(root))
    if isinstance(value, dict):
        return {k: _fill(v, root) for k, v in value.items()}
    return value


def hook(root: Path, event: dict[str, Any]) -> Any:
    out = io.StringIO()
    assert kit.run_hook(None, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    return json.loads(out.getvalue()) if out.getvalue() else None


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_conformance(case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = json.loads(case.read_text())
    root = tmp_path.resolve()
    if data["state"]:
        (root / STATE).mkdir()
        (root / STATE / "policy.json").write_text("{}\n")
    for link, target in data["links"].items():
        (root / link).parent.mkdir(parents=True, exist_ok=True)
        (root / link).symlink_to(root / target)
    # Claude Code names the project, so a call in the state folder keeps its project.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.chdir(root)
    assert hook(root, _fill(data["event"], root)) == data["answer"]


def test_a_deny_with_a_state_folder_writes_a_blocked_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    (tmp_path / STATE).mkdir()
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "nookku policy set scripts model"},
    }
    assert hook(tmp_path, event) is not None
    rows = [json.loads(x) for x in (tmp_path / STATE / "relay.jsonl").read_text().splitlines()]
    assert [r["type"] for r in rows] == ["blocked_call"]


def test_a_deny_during_a_test_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / STATE / "tests" / "t1"
    folder.mkdir(parents=True)
    monkeypatch.setattr(kit.state, "current", lambda root: {"dir": str(folder), "tap_url": ""})
    event = {"hook_event_name": "PreToolUse", "cwd": str(tmp_path), "tool_name": "Edit"}
    event["tool_input"] = {"file_path": f"{tmp_path}/{STATE}/policy.json"}
    answer = kit.handle(event, tmp_path, "claude-code")
    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecisionReason"] == policy.REASON
    assert (folder / "relay.jsonl").exists()


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """One key for the tests, in place of the real keys (SPEC.md section 7.9)."""

    def parse(text: str) -> str:
        if text not in ("person", "model"):
            raise ValueError("must be person or model")
        return text

    key = policy.Key("person", parse, lambda v: v in ("person", "model"), "who writes the turns")
    monkeypatch.setattr(policy, "KEYS", {"scripts": key})


def test_a_missing_file_gives_each_default(tmp_path: Path, keys: None) -> None:
    assert policy.read(tmp_path) == {"scripts": "person"}


@pytest.mark.parametrize(
    "text",
    ["[]", "{", '{"other": 1}', '{"scripts": "anyone"}'],
    ids=["list", "bad", "key", "value"],
)
def test_a_file_that_is_not_valid_is_an_error(tmp_path: Path, keys: None, text: str) -> None:
    (tmp_path / STATE).mkdir()
    (tmp_path / STATE / "policy.json").write_text(text)
    with pytest.raises(policy.PolicyError):
        policy.read(tmp_path)


def test_policy_set_changes_the_file(
    tmp_path: Path, keys: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["policy", "--root", str(tmp_path), "set", "scripts", "model"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scripts": "model"}
    assert json.loads((tmp_path / STATE / "policy.json").read_text()) == {"scripts": "model"}
    assert main(["policy", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"scripts": "model"}


@pytest.mark.parametrize(
    ("args", "code"),
    [(["set", "scripts", "anyone"], 1), (["set", "other", "x"], 1), (["set", "scripts"], 2)],
    ids=["value", "key", "no value"],
)
def test_policy_set_refuses_a_bad_key_or_value(
    tmp_path: Path, keys: None, args: list[str], code: int
) -> None:
    assert main(["policy", "--root", str(tmp_path), *args]) == code
    assert not (tmp_path / STATE / "policy.json").exists()


def test_policy_set_names_the_known_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["policy", "--root", str(tmp_path), "set", "scripts", "model"]) == 1
    assert "The keys are: guard_fields, guard_reads." in capsys.readouterr().err


def test_guard_fields_takes_names_separated_by_commas(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["policy", "--root", str(tmp_path), "set", "guard_fields", "path, url"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"guard_fields": ["path", "url"], "guard_reads": []}
    assert main(["policy", "--root", str(tmp_path), "set", "guard_fields", "path,,url"]) == 1


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("bat, fd", ["bat", "fd"]),
        ("", []),
        (" ", []),
        ("bin/bat", None),
        ("a b", None),
        (",", None),
        ("$X", None),
        ("r?", None),
        ("bat,-x", None),
    ],
)
def test_guard_reads_takes_program_names(
    tmp_path: Path, text: str, value: list[str] | None
) -> None:
    code = main(["policy", "--root", str(tmp_path), "set", "guard_reads", text])
    assert code == (0 if value is not None else 1)
    if value is not None:
        assert policy.read(tmp_path)["guard_reads"] == value


def test_start_reads_the_policy_for_the_manifest(tmp_path: Path, keys: None) -> None:
    (tmp_path / STATE).mkdir()
    (tmp_path / STATE / "config.json").write_text(json.dumps({"entry": ["python3", "agent.py"]}))
    (tmp_path / STATE / "policy.json").write_text('{"scripts": "model"}')
    assert bridge.load_config(tmp_path).policy == {"scripts": "model"}
    (tmp_path / STATE / "policy.json").write_text('{"scripts": "anyone"}')
    with pytest.raises(bridge.BridgeError, match=r"policy\.json"):
        bridge.load_config(tmp_path)

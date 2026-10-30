"""The tests folder from --tests-dir or NOOKKU_TESTS_DIR (SPEC.md section 7, #457)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nookku import bridge, commands, discovery, kit, seal, state
from nookku.cli import main
from nookku.record import Writer

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
STATE = "." + "nookku"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    (root / STATE).mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / STATE / "config.json").write_text(json.dumps(conf))
    return root


def guard(root: Path, event: dict) -> dict | None:
    out = io.StringIO()
    assert kit.run_hook(root, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    return json.loads(out.getvalue()) if out.getvalue() else None


def bash(command: str, cwd: Path) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def denied(answer: dict | None) -> bool:
    return answer is not None and answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_with_no_variable_the_tests_are_in_the_state_folder(tmp_path: Path) -> None:
    root = tmp_path / "shop"
    assert state.tests_dir(root) == root / STATE / "tests"


def test_an_empty_variable_counts_as_no_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(state.TESTS_ENV, "")
    assert state.tests_dir(tmp_path) == tmp_path / STATE / "tests"


def test_the_variable_gives_the_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(state.TESTS_ENV, f"{tmp_path}/volume/./tests/")
    assert state.tests_dir(tmp_path / "shop") == tmp_path / "volume" / "tests"
    # The default folder, given by its path, is the default folder.
    monkeypatch.setenv(state.TESTS_ENV, str(tmp_path / "shop" / STATE / "tests"))
    assert state.tests_dir(tmp_path / "shop") == tmp_path / "shop" / STATE / "tests"


@pytest.mark.parametrize(
    ("value", "cause"),
    [
        ("tests", "is not an absolute path"),
        ("./tests", "is not an absolute path"),
        ("{tmp}/other/" + STATE + "/tests", "names a folder in a state folder"),
        ("{tmp}/shop/" + STATE.upper(), "names a folder in a state folder"),
        ("{tmp}/shop", "names the project or a folder above it"),
        ("{tmp}", "names the project or a folder above it"),
        ("/", "names the project or a folder above it"),
    ],
)
def test_a_value_that_breaks_the_rule_stops_the_command(
    value: str, cause: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(state.TESTS_ENV, value.replace("{tmp}", str(tmp_path)))
    with pytest.raises(state.TestsDirError, match=cause):
        state.tests_dir(tmp_path / "shop")


def test_the_option_comes_before_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    monkeypatch.setenv(state.TESTS_ENV, str(tmp_path / "from-variable"))
    monkeypatch.chdir(tmp_path)
    assert main(["status", "--root", str(root), "--tests-dir", "volume/tests"]) == 0
    # The option keeps an absolute path in the variable, for the command and its children.
    assert os.environ[state.TESTS_ENV] == str(tmp_path / "volume" / "tests")
    assert "No test runs." in capsys.readouterr().out


@pytest.mark.parametrize("command", ["status", "verify", "transcript", "trace"])
def test_a_bad_option_stops_each_command_with_the_cause(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    assert main([command, "--root", str(root), "--tests-dir", str(root)]) == 1
    assert "names the project or a folder above it" in capsys.readouterr().err


def test_a_folder_that_is_not_a_test_id_is_not_a_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests = tmp_path / "volume"
    (tests / "lost+found").mkdir(parents=True)
    (tests / "20261023-101500-0a1b").mkdir()
    monkeypatch.setenv(state.TESTS_ENV, str(tests))
    assert [f.name for f in state.tests_newest_first(tmp_path / "shop")] == ["20261023-101500-0a1b"]


def test_a_test_in_the_folder_of_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    tests = tmp_path / "volume" / "tests"
    monkeypatch.setenv(state.TESTS_ENV, str(tests))
    cur = bridge.start(root, "tester-1")
    try:
        folder = Path(cur["dir"])
        assert folder.parent == tests and not (root / STATE / "tests").exists()
        said = "Do you ship to Chennai?"
        shown, ok = bridge.send(cur, said)
        row = {"type": "turn", "harness": "codex", "said": said, "shown": shown, "ok": ok}
        Writer(folder / "relay.jsonl").append(row)
        # During the test, the guard denies a read command that names the tests folder.
        assert denied(guard(root, bash(f"cat {folder}/tap.jsonl", root)))
        assert denied(guard(root, bash("ls $NOOKKU_TESTS_DIR", root)))
    finally:
        manifest = bridge.end(root)
    assert ok and shown.startswith("We ship to Chennai")
    assert manifest is not None and manifest["dir"] == str(folder)
    assert seal.verify(folder)["intact"]
    assert state.latest_test(root) == folder
    # With no test, a write to a record is denied, and a write of report.md is not.
    assert denied(guard(root, bash(f"rm {folder}/tap.jsonl", root)))
    assert denied(guard(root, bash("rm tap.jsonl", folder)))
    report = {
        "hook_event_name": "PreToolUse",
        "cwd": str(root),
        "tool_name": "Write",
        "tool_input": {"file_path": str(folder / "report.md"), "content": "# Report\n"},
    }
    assert guard(root, report) is None
    assert guard(root, bash(f"cat {folder}/tap.jsonl", root)) is None
    # Each command that reads a test finds it in the same folder.
    assert main(["verify", "--root", str(root)]) == 0
    assert folder.name in capsys.readouterr().out
    assert main(["transcript", "--root", str(root), "--test", folder.name]) == 0
    assert "Do you ship to Chennai?" in capsys.readouterr().out


def test_a_test_in_the_folder_of_the_option_is_guarded_with_no_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    tests = tmp_path / "volume" / "tests"
    assert main(["start", "--root", str(root), "--tests-dir", str(tests), "--json"]) == 0
    cur = json.loads(capsys.readouterr().out)
    try:
        assert Path(cur["dir"]).parent == tests
        # The hook of the harness does not see the option. It finds the folder of the running
        # test in current.json.
        monkeypatch.delenv(state.TESTS_ENV)
        assert denied(guard(root, bash(f"cat {tests}/{cur['test']}/relay.jsonl", root)))
    finally:
        monkeypatch.setenv(state.TESTS_ENV, str(tests))
        bridge.end(root)
    # After the end, the hook has no variable and no running test. The state file names the
    # folder, so the guard still protects it (#507).
    monkeypatch.delenv(state.TESTS_ENV)
    assert state.known_tests_dirs(root) == [tests]
    record = f"{tests}/{cur['test']}/tap.jsonl"
    assert denied(guard(root, bash(f"rm {record}", root)))
    assert denied(guard(root, bash(f"cd {tests.parent} && rm tests/{cur['test']}/tap.jsonl", root)))
    assert guard(root, bash(f"cat {record}", root)) is None


def test_the_state_file_keeps_each_tests_folder_and_only_nookku_writes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path)
    first, second = tmp_path / "volume" / "tests", tmp_path / "other" / "tests"
    # A test in .nookku/tests writes no file.
    state.remember_tests_dir(root, root / STATE / "tests")
    assert not (root / STATE / state.TESTS_DIRS).exists()
    state.remember_tests_dir(root, first)
    state.remember_tests_dir(root, second)
    state.remember_tests_dir(root, first)
    # A later test in another folder does not remove the protection of a folder before it.
    assert state.known_tests_dirs(root) == [second, first]
    for folder in (first, second):
        assert denied(guard(root, bash(f"rm -r {folder}", root)))
    for path in (f"{STATE}/{state.TESTS_DIRS}", f"{root}/{STATE}/{state.TESTS_DIRS}"):
        assert denied(guard(root, bash(f"echo '{{}}' > {path}", root)))
    write = {
        "hook_event_name": "PreToolUse",
        "cwd": str(root),
        "tool_name": "Write",
        "tool_input": {"file_path": f"{root}/{STATE}/{state.TESTS_DIRS}", "content": "{}"},
    }
    assert denied(guard(root, write))


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"v": 2, "folders": []}',
        '{"v": 1, "folders": "/vol/tests"}',
        '{"v": 1, "folders": ["tests"]}',
        '{"v": 1, "folders": [""]}',
        '{"v": true, "folders": []}',
    ],
)
def test_a_broken_state_file_denies_each_call_and_stops_a_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    root = project(tmp_path)
    (root / STATE / state.TESTS_DIRS).write_text(text)
    answer = guard(root, bash("ls", root))
    assert denied(answer)
    assert answer is not None
    assert state.TESTS_DIRS in answer["hookSpecificOutput"]["permissionDecisionReason"]
    monkeypatch.setenv(state.TESTS_ENV, str(tmp_path / "volume" / "tests"))
    with pytest.raises(bridge.BridgeError, match=state.TESTS_DIRS):
        bridge.start(root, "tester-1")
    assert not (tmp_path / "volume" / "tests").exists()
    # A test in .nookku/tests also does not start, because the hooks deny each of its calls.
    monkeypatch.delenv(state.TESTS_ENV)
    with pytest.raises(bridge.BridgeError, match=state.TESTS_DIRS):
        bridge.start(root, "tester-1")
    assert not (root / STATE / "tests").exists() or not any((root / STATE / "tests").iterdir())


@pytest.mark.parametrize(
    ("command", "folders", "unknown"),
    [
        ("cd /vol && rm tests/t1/tap.jsonl", ["/vol"], False),
        ("cd -P /vol; pushd tests", ["/vol", "tests"], False),
        ("bash -c 'cd /vol && rm x'", ["/vol"], False),
        ("git -C /vol rm x; make --directory=/srv", ["/vol", "/srv"], False),
        ('cd "$VOL" && rm x', [], True),
        ("cd - && rm x", [], True),
        ("cd ~shop && rm x", [], True),
        ("cd ~/vol && rm x", ["~/vol"], False),
        ("rm tests/t1/tap.jsonl", [], False),
    ],
)
def test_the_folders_that_a_command_changes_to(
    command: str, folders: list[str], unknown: bool
) -> None:
    assert commands.changed_folders(command) == (folders, unknown)


def test_a_bad_variable_denies_each_tool_call_and_blocks_the_control_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path)
    monkeypatch.setenv(state.TESTS_ENV, "tests")
    assert denied(guard(root, bash("ls", root)))
    for prompt in ("nookku start", "nookku status", "nookku end"):
        answer = guard(root, {"hook_event_name": "UserPromptSubmit", "prompt": prompt})
        assert answer is not None and answer["decision"] == "block"
        assert "is not an absolute path" in answer["reason"]


@pytest.mark.parametrize(
    ("word", "rest"),
    [
        ("/vol/tests/t1/tap.jsonl", ["tests", "t1", "tap.jsonl"]),
        ("/VOL/Tests/t1", ["tests", "t1"]),
        ("/vol/te*/t1/tap.jsonl", ["tests", "t1", "tap.jsonl"]),
        ("../vol/tests", ["tests"]),
        ("of=/vol/tests/t1/relay.jsonl", ["tests", "t1", "relay.jsonl"]),
        ("$NOOKKU_TESTS_DIR/t1", ["tests", "t1"]),
        ("/vol/tests-old/t1", None),
        ("/vol", None),
        ("tests/t1", None),
    ],
)
def test_a_word_in_the_tests_folder(word: str, rest: list[str] | None) -> None:
    assert commands.state_rest(word, ["/vol/tests"], "/shop") == rest


def test_end_never_signals_an_entry_that_the_project_state_does_not_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another user can write a tests folder on shared storage. A planted manifest of a stopped
    test with the pid data of a live process group must not make `end` signal it (#457)."""
    root = project(tmp_path)
    tests = tmp_path / "volume" / "tests"
    monkeypatch.setenv(state.TESTS_ENV, str(tests))
    victim = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        planted = tests / "20261023-090000-dead"
        planted.mkdir(parents=True)
        manifest = {
            "v": "0.2",
            "test": planted.name,
            "dir": str(planted),
            "started": time.time() - 3600,
            "ended": None,
            "entry_pid": victim.pid,
            "entry_pid_start": bridge.process_start(victim.pid),
        }
        (planted / "manifest.json").write_text(json.dumps(manifest))
        assert bridge.stopped(root) is None
        assert bridge.end(root) is None
        # Also a direct finish signals nothing, because no run file names the entry.
        bridge.finish_stopped(root, planted)
        time.sleep(0.2)
        assert victim.poll() is None
        assert "the state folder does not name the entry" in (planted / "bridge.log").read_text()
    finally:
        victim.kill()
        victim.wait()


def test_the_run_file_gives_the_entry_and_not_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path)
    tests = tmp_path / "volume" / "tests"
    monkeypatch.setenv(state.TESTS_ENV, str(tests))
    cur = bridge.start(root)
    try:
        run = json.loads(bridge.run_path(root, cur["test"]).read_text())
        assert run["dir"] == cur["dir"] and isinstance(run["entry_pid"], int)
        assert bridge.run_path(root, cur["test"]).stat().st_mode & 0o777 == 0o600
        # A change of the manifest in the tests folder does not change the entry to signal.
        folder = Path(cur["dir"])
        manifest = json.loads((folder / "manifest.json").read_text())
        manifest["entry_pid"] = 1
        (folder / "manifest.json").write_text(json.dumps(manifest))
        entry = bridge._trusted_entry(root, folder)
        assert entry is not None and entry["entry_pid"] == run["entry_pid"]
    finally:
        bridge.end(root)


def test_a_part_of_the_egress_answer_cannot_set_the_tests_folder() -> None:
    part = {"name": "stock", "kind": "http", "url": "http://127.0.0.1:9", "env": "NOOKKU_TESTS_DIR"}
    with pytest.raises(discovery.AnswerError, match="NOOKKU_TESTS_DIR of nookku"):
        discovery._env("backends[0]", part["env"])

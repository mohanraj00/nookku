"""The sealed record of a refused start (SPEC.md section 7.8, #628)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from nookku import __version__, api, bridge, dashboard, evaluation, kit, refusal, seal, state
from nookku.cli import main

ENTRY = {"entry": ["python3", "agent.py"]}
CASES = Path(__file__).resolve().parent.parent / "conformance" / "refusal"


@pytest.fixture(autouse=True)
def no_harness_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge, "_version", lambda cmd: f"{cmd} 1.0.0")


def _no_prompt_hook(root: Path) -> None:
    """The example of #628: a toy shop setup with no prompt hook."""
    kit.init(root, "claude-code", ENTRY)
    path = root / ".claude" / "settings.local.json"
    data = json.loads(path.read_text())
    data["hooks"].pop("UserPromptSubmit")
    path.write_text(json.dumps(data))


def _refused_start(root: Path) -> Path:
    with pytest.raises(bridge.BridgeError) as e:
        bridge.start(root)
    [folder] = [p for p in state.tests_dir(root).iterdir() if state.is_refusal(p.name)]
    assert f"The sealed refusal record is {folder}." in str(e.value)
    assert f"run nookku verify {folder.name}." in str(e.value)
    return folder


def test_a_start_with_no_prompt_hook_writes_a_sealed_refusal_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_prompt_hook(tmp_path)
    folder = _refused_start(tmp_path)
    assert sorted(p.name for p in folder.iterdir()) == [refusal.RECORD, seal.SEAL]
    record = json.loads((folder / refusal.RECORD).read_text(encoding="utf-8"))
    assert record == {
        "v": 1,
        "refusal": folder.name,
        "refused": record["refused"],
        "command": "start",
        "harness": "claude-code",
        "root": str(tmp_path),
        "problems": ["the project hook UserPromptSubmit is missing."],
        "versions": {"nookku": __version__, "claude-code": "claude 1.0.0", "codex": "codex 1.0.0"},
    }
    # The seal covers the record, and the copy outside the project is the same.
    assert seal.verify(folder)["intact"]
    assert seal.copy_files(folder.name) == {refusal.RECORD: seal.hashes(folder)[refusal.RECORD]}
    assert main(["verify", folder.name, "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith(f"Refusal record {folder.name}. Seal: intact.")
    # No test started, and relay mode stays off.
    assert not kit.is_on(tmp_path)
    assert bridge.current(tmp_path) is None


def test_verify_finds_a_changed_refusal_record(tmp_path: Path) -> None:
    _no_prompt_hook(tmp_path)
    folder = _refused_start(tmp_path)
    path = folder / refusal.RECORD
    path.write_text(path.read_text().replace("UserPromptSubmit", "PreToolUse"))
    assert seal.verify(folder)["changed"] == [refusal.RECORD]
    assert main(["verify", folder.name, "--root", str(tmp_path)]) == 2


def test_the_readers_of_the_tests_folder_skip_a_refusal_record(tmp_path: Path) -> None:
    _no_prompt_hook(tmp_path)
    folder = _refused_start(tmp_path)
    # The latest test of the state, the evaluation, the dashboard and the API see no test.
    assert state.tests_newest_first(tmp_path) == []
    assert state.latest_test(tmp_path) is None
    assert state.tester_test(tmp_path) is None
    assert evaluation.pending(tmp_path) is None
    assert dashboard.rows(tmp_path) == []
    assert dashboard.find(tmp_path, folder.name) is None
    assert api.runs(tmp_path)["runs"] == []
    with pytest.raises(api.NotFound):
        api.run(tmp_path, folder.name)
    # A command for a test refuses the id, and names the command that checks the record.
    with pytest.raises(kit.TranscriptError, match="sealed refusal record"):
        kit.existing_test(tmp_path, folder.name)
    assert main(["trace", folder.name, "--root", str(tmp_path)]) != 0
    assert sorted(p.name for p in folder.iterdir()) == [refusal.RECORD, seal.SEAL]
    assert kit.existing_test(tmp_path, folder.name, refusal=True) == folder


def test_a_refusal_after_a_test_keeps_that_test_the_latest(tmp_path: Path) -> None:
    _no_prompt_hook(tmp_path)
    test = state.tests_dir(tmp_path) / "20261127-100000-ab12"
    test.mkdir(parents=True)
    (test / "manifest.json").write_text(json.dumps({"test": test.name, "started": 1.0}))
    _refused_start(tmp_path)
    assert state.latest_test(tmp_path) == test


def test_a_refused_start_with_a_tests_folder_outside_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "shop"
    root.mkdir()
    _no_prompt_hook(root)
    tests = tmp_path / "runs"
    monkeypatch.setenv(state.TESTS_ENV, str(tests))
    folder = _refused_start(root)
    assert folder.parent == tests
    # The relay protects the folder after the start (SPEC.md section 7, #507).
    assert tests in state.known_tests_dirs(root)


def test_a_record_that_cannot_be_written_still_refuses_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_prompt_hook(tmp_path)
    monkeypatch.setenv(state.TESTS_ENV, "runs")
    with pytest.raises(bridge.BridgeError, match="cannot write the sealed refusal record"):
        bridge.start(tmp_path)
    [row] = [
        json.loads(line)
        for line in (tmp_path / ".nookku" / "refusals.jsonl").read_text().splitlines()
    ]
    assert row["record"] is None
    assert not kit.is_on(tmp_path)


def _write(root: Path, path: Path) -> tuple[str, str] | None:
    return kit.state_write({"cwd": str(root)}, root, "Write", {"file_path": str(path)}, False)


def test_a_model_write_to_a_refusal_record_is_denied(tmp_path: Path) -> None:
    _no_prompt_hook(tmp_path)
    folder = _refused_start(tmp_path)
    for name in (refusal.RECORD, seal.SEAL, "report.md", "manifest.json"):
        found = _write(tmp_path, folder / name)
        assert found is not None and found[0] == str(folder / name)
    # The report of a test stays a file that the model writes (SPEC.md section 9).
    report = state.tests_dir(tmp_path) / "20261127-100000-ab12" / "report.md"
    assert _write(tmp_path, report) is None
    # A glob can match a refusal record.
    command = f"echo x > {state.tests_dir(tmp_path)}/*/report.md"
    event = {"cwd": str(tmp_path)}
    assert kit.state_write(event, tmp_path, "Bash", {"command": command}, False) is not None


@pytest.mark.parametrize("case", sorted(CASES.iterdir()), ids=lambda c: c.name)
def test_conformance(case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each case is a tests folder with one refusal record, the seal copy, and the result of
    `nookku verify --json` and of the readers."""
    expect: dict[str, Any] = json.loads((case / "expect.json").read_text())
    tests = tmp_path / "tests"
    shutil.copytree(case / "tests", tests)
    monkeypatch.setenv(state.TESTS_ENV, str(tests))
    [folder] = list(tests.iterdir())
    assert seal.verify(folder, case / "home") == expect["verify"]
    assert [p.name for p in state.tests_newest_first(tmp_path / "shop")] == expect["tests"]
    record = json.loads((folder / refusal.RECORD).read_text(encoding="utf-8"))
    assert set(record) == set(expect["record_keys"])
    assert record["refusal"] == folder.name and state.is_refusal(folder.name)

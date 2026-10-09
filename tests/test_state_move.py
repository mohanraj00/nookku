"""The first run of nooku moves the state folder of verbatim-relay 0.3.x (#181)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from nooku.cli import main
from nooku.config import OLD_STATE_DIR, STATE_DIR, move_old_state


def old_state(root: Path) -> Path:
    test = root / OLD_STATE_DIR / "tests" / "20261009-120000-ab12"
    test.mkdir(parents=True)
    (test / "relay.jsonl").write_bytes(b'{"v": "0.3"}\n')
    (root / OLD_STATE_DIR / "config.json").write_text("{}\n")
    return test


def test_the_old_folder_moves_with_each_test(tmp_path: Path) -> None:
    old_state(tmp_path)
    assert move_old_state(tmp_path) is None
    assert not (tmp_path / OLD_STATE_DIR).exists()
    moved = tmp_path / STATE_DIR / "tests" / "20261009-120000-ab12" / "relay.jsonl"
    assert moved.read_bytes() == b'{"v": "0.3"}\n'
    assert (tmp_path / STATE_DIR / "config.json").read_text() == "{}\n"


def test_no_old_folder_changes_nothing(tmp_path: Path) -> None:
    assert move_old_state(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_both_folders_stop_each_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    test = old_state(tmp_path)
    (tmp_path / STATE_DIR).mkdir()
    assert main(["status", "--root", str(tmp_path)]) == 1
    assert "both exist" in capsys.readouterr().err
    assert (test / "relay.jsonl").exists()
    assert list((tmp_path / STATE_DIR).iterdir()) == []


def test_both_folders_block_a_hook_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old_state(tmp_path)
    (tmp_path / STATE_DIR).mkdir()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"prompt": "hi"}'))
    assert main(["hook", "--root", str(tmp_path), "--harness", "claude-code"]) == 2
    assert "both exist" in capsys.readouterr().err


def test_a_command_moves_the_old_folder_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old_state(tmp_path)
    main(["status", "--root", str(tmp_path)])
    assert "moved" in capsys.readouterr().err
    assert (tmp_path / STATE_DIR / "config.json").exists()
    assert not (tmp_path / OLD_STATE_DIR).exists()

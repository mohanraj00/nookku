"""The refusal of a test if the nookku plugin and the project hooks are both on (#151)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nookku import bridge, claude_gate, kit
from nookku.cli import main

ENTRY = {"entry": ["python3", "agent.py"]}


def _enable(path: Path, value: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    data["enabledPlugins"] = {"nookku@nookku": value}
    path.write_text(json.dumps(data))


@pytest.mark.parametrize(
    ("user", "project", "local", "on"),
    [
        (True, None, None, True),
        (None, True, None, True),
        (None, None, True, True),
        (True, None, False, False),
        (True, False, None, False),
        (False, None, True, True),
        (None, None, None, False),
    ],
)
def test_the_highest_settings_file_decides_if_the_plugin_is_on(
    tmp_path: Path,
    claude_home: Path,
    user: bool | None,
    project: bool | None,
    local: bool | None,
    on: bool,
) -> None:
    files = [claude_home / "settings.json", *claude_gate.settings_files(tmp_path)[1:]]
    for path, value in zip(files, (user, project, local), strict=True):
        if value is not None:
            _enable(path, value)
    assert claude_gate.plugin_on(tmp_path) is on


def test_only_the_hooks_of_init_claude_code_count(tmp_path: Path) -> None:
    kit.init(tmp_path, "plugin", {})
    assert not claude_gate.project_hooks_on(tmp_path)
    kit.init(tmp_path, "codex", {})
    assert not claude_gate.project_hooks_on(tmp_path)
    kit.init(tmp_path, "claude-code", {})
    assert claude_gate.project_hooks_on(tmp_path)


def test_start_refuses_a_test_with_both_on(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    _enable(claude_home / "settings.json", True)
    with pytest.raises(bridge.BridgeError, match="two times"):
        bridge.start(tmp_path)
    assert not (tmp_path / ".nookku" / "tests").exists()


def test_mode_on_keeps_relay_mode_off_with_both_on(
    tmp_path: Path, claude_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kit.init(tmp_path, "claude-code", {})
    _enable(tmp_path / ".claude" / "settings.json", True)
    assert main(["mode", "--root", str(tmp_path), "on"]) == 0
    found = tmp_path / ".claude" / "settings.local.json"
    assert f"nookku: {claude_gate.PROBLEM.format(file=found)}" in capsys.readouterr().out
    assert not kit.is_on(tmp_path)


def test_init_warns_if_the_other_form_is_on(
    tmp_path: Path, claude_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "plugin", "--root", str(tmp_path)]) == 0
    assert "warning" not in capsys.readouterr().err
    _enable(claude_home / "settings.json", True)
    assert main(["init", "claude-code", "--root", str(tmp_path)]) == 0
    assert claude_gate.DISABLE in capsys.readouterr().err
    assert main(["init", "plugin", "--root", str(tmp_path)]) == 0
    assert "project hooks of nookku init claude-code" in capsys.readouterr().err


def test_a_linked_worktree_reads_the_local_file_of_the_main_checkout(tmp_path: Path) -> None:
    import subprocess

    main_dir = tmp_path / "shop"
    main_dir.mkdir()
    git = ["git", "-C", str(main_dir)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run(
        [
            *git,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "start",
        ],
        check=True,
    )
    linked = tmp_path / "shop-2"
    subprocess.run([*git, "worktree", "add", "-q", str(linked)], check=True)
    kit.init(main_dir, "claude-code", {})
    _enable(main_dir / ".claude" / "settings.local.json", True)
    kit.init(linked, "plugin", {})
    assert claude_gate.project_hooks_on(linked)
    assert claude_gate.plugin_on(linked)
    # The refusal names the file of the main checkout, which has the hooks.
    found = main_dir / ".claude" / "settings.local.json"
    assert claude_gate.problem(linked) == claude_gate.PROBLEM.format(file=found)

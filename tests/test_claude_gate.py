"""The refusal of a test if the nookku plugin and the project hooks are both on (#151)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from nookku import __version__, bridge, claude_gate, kit
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


def test_mode_on_with_an_entry_refuses_a_test_with_both_on_and_exits_with_1(
    tmp_path: Path, claude_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #248: with an entry, mode on starts a test. If the test does not start, it exits with 1.
    kit.init(tmp_path, "claude-code", ENTRY)
    _enable(claude_home / "settings.json", True)
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    assert "two times" in capsys.readouterr().out
    assert not kit.is_on(tmp_path)
    assert not (tmp_path / ".nookku" / "tests").exists()


def test_mode_on_keeps_relay_mode_off_with_both_on(
    tmp_path: Path, claude_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kit.init(tmp_path, "claude-code", {})
    _enable(tmp_path / ".claude" / "settings.json", True)
    assert main(["mode", "--root", str(tmp_path), "on"]) == 1
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


def _local(root: Path) -> Path:
    return root / ".claude" / "settings.local.json"


def _edit(path: Path, change: Any) -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    change(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_the_hooks_of_init_claude_code_pass(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    assert claude_gate.hook_problems(tmp_path) == []
    assert claude_gate.problem(tmp_path) is None


def test_start_refuses_a_test_with_no_prompt_hook(tmp_path: Path, claude_home: Path) -> None:
    # The example of #554: remove the prompt hook from a toy shop setup. No test starts.
    kit.init(tmp_path, "claude-code", ENTRY)
    _edit(_local(tmp_path), lambda d: d["hooks"].pop("UserPromptSubmit"))
    assert claude_gate.hook_problems(tmp_path) == ["the project hook UserPromptSubmit is missing."]
    with pytest.raises(bridge.BridgeError, match="UserPromptSubmit is missing"):
        bridge.start(tmp_path)
    assert not (tmp_path / ".nookku" / "tests").exists()
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    assert not kit.is_on(tmp_path)


def _hook(data: dict[str, Any], event: str) -> dict[str, Any]:
    hook: dict[str, Any] = data["hooks"][event][-1]["hooks"][0]
    return hook


@pytest.mark.parametrize(
    "change",
    [
        lambda d: _hook(d, "UserPromptSubmit").update(timeout=5),
        lambda d: d["hooks"]["PreToolUse"][-1].update(matcher="Bash"),
        lambda d: _hook(d, "PreToolUse").update(command="/usr/bin/true nookku hook"),
        lambda d: _hook(d, "UserPromptSubmit").update(
            command=_hook(d, "UserPromptSubmit")["command"].replace("claude-code", "codex")
        ),
        lambda d: _hook(d, "PreToolUse").update(type="prompt"),
    ],
)
def test_a_changed_project_hook_is_refused(tmp_path: Path, claude_home: Path, change: Any) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    _edit(_local(tmp_path), change)
    problems = claude_gate.hook_problems(tmp_path)
    assert len(problems) == 1 and "is modified" in problems[0]
    assert "not ready" in (claude_gate.problem(tmp_path) or "")


def test_a_project_hook_two_times_is_refused(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    hooks = json.loads(_local(tmp_path).read_text())["hooks"]
    _edit(tmp_path / ".claude" / "settings.json", lambda d: d.update(hooks=hooks))
    assert claude_gate.hook_problems(tmp_path) == [
        "the project hook UserPromptSubmit is there 2 times.",
        "the project hook PreToolUse is there 2 times.",
    ]


@pytest.mark.parametrize(
    ("user", "local", "refused"),
    [(True, None, True), (None, True, True), (True, False, False), (False, None, False)],
)
def test_a_file_that_turns_off_all_hooks_is_refused(
    tmp_path: Path, claude_home: Path, user: bool | None, local: bool | None, refused: bool
) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    for path, value in ((claude_home / "settings.json", user), (_local(tmp_path), local)):
        if value is not None:
            _edit(path, lambda d, v=value: d.update(disableAllHooks=v))
    problems = claude_gate.hook_problems(tmp_path)
    assert bool(problems) is refused
    assert all("disableAllHooks: true" in p for p in problems)


def test_the_plugin_with_all_hooks_off_is_refused(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    _edit(claude_home / "settings.json", lambda d: d.update(disableAllHooks=True))
    assert "disableAllHooks" in (claude_gate.problem(tmp_path) or "")


def test_no_nookku_setup_passes_with_all_hooks_off(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "codex", ENTRY)
    _edit(claude_home / "settings.json", lambda d: d.update(disableAllHooks=True))
    assert claude_gate.hook_problems(tmp_path) == []


PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins" / "nookku"


def _install(claude_home: Path, root: Path, scope: str = "user") -> Path:
    """A copy of the plugin files in the cache, and installed_plugins.json for it."""
    folder = claude_home / "plugins" / "cache" / "nookku" / "nookku" / "0.5.9"
    shutil.copytree(PLUGIN_DIR, folder)
    entry: dict[str, Any] = {"scope": scope, "installPath": str(folder), "version": "0.5.9"}
    if scope != "user":
        entry["projectPath"] = str(root)
    data = {"version": 2, "plugins": {"nookku@nookku": [entry]}}
    (claude_home / "plugins" / "installed_plugins.json").write_text(json.dumps(data))
    return folder


@pytest.mark.parametrize("scope", ["user", "project"])
def test_an_install_of_this_version_passes(tmp_path: Path, claude_home: Path, scope: str) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    _install(claude_home, tmp_path, scope)
    assert claude_gate.problems(tmp_path) == []


def test_an_enabled_plugin_with_no_install_is_refused(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    assert "has no install of it" in claude_gate.problems(tmp_path)[0]
    # An install for another project does not count.
    _install(claude_home, tmp_path / "other", "project")
    assert "has no install of it" in claude_gate.problems(tmp_path)[0]


def test_a_newer_plugin_with_the_required_hooks_passes(
    tmp_path: Path, claude_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The marketplace installs from main, so the hook files can differ from this version.
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    folder = _install(claude_home, tmp_path)
    with (folder / "hooks" / "register.tsx").open("a") as f:
        f.write("// a change on main\n")
    _edit(
        folder / "hooks" / "hooks.json",
        lambda d: d["hooks"]["UserPromptSubmit"][0]["hooks"][0].update(timeout=600),
    )
    _edit(folder / ".claude-plugin" / "plugin.json", lambda d: d.update(version="9.9.9"))
    assert claude_gate.problems(tmp_path) == []
    # A version skew gives a warning only.
    [warning] = claude_gate.plugin_warnings(tmp_path)
    assert "version 9.9.9" in warning and __version__ in warning


def test_the_plugin_of_this_version_gives_no_warning(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    _install(claude_home, tmp_path)
    assert claude_gate.plugin_warnings(tmp_path) == []


def _drop_prompt_hook(d: dict[str, Any]) -> None:
    d["hooks"].pop("UserPromptSubmit")


def _narrow_matcher(d: dict[str, Any]) -> None:
    d["hooks"]["PreToolUse"][0]["matcher"] = "Bash"


def _other_command(d: dict[str, Any]) -> None:
    d["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] = "true"


@pytest.mark.parametrize(
    ("change", "event"),
    [
        (_drop_prompt_hook, "UserPromptSubmit"),
        (_narrow_matcher, "PreToolUse"),
        (_other_command, "UserPromptSubmit"),
    ],
)
def test_a_plugin_install_with_a_required_hook_missing_is_refused(
    tmp_path: Path, claude_home: Path, change: Any, event: str
) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    folder = _install(claude_home, tmp_path)
    _edit(folder / "hooks" / "hooks.json", change)
    assert claude_gate.problems(tmp_path) == [
        f"the plugin hook {event} is missing in {folder / 'hooks' / 'hooks.json'}, or its "
        "matcher or its command differs from the hook of nookku."
    ]


def test_a_plugin_install_with_no_hook_script_or_hooks_file_is_refused(
    tmp_path: Path, claude_home: Path
) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    folder = _install(claude_home, tmp_path)
    (folder / "hooks" / "hooks.json").unlink()
    assert "has no hooks" in claude_gate.problems(tmp_path)[0]
    (folder / "hooks" / "nookku-hook.sh").unlink()
    assert "hook script" in claude_gate.problems(tmp_path)[0]


def _refusals(root: Path) -> list[dict[str, Any]]:
    path = root / ".nookku" / claude_gate.REFUSALS
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_refused_start_adds_a_row_to_the_refusal_log(tmp_path: Path, claude_home: Path) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    _edit(_local(tmp_path), lambda d: d["hooks"].pop("PreToolUse"))
    with pytest.raises(bridge.BridgeError):
        bridge.start(tmp_path)
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    rows = _refusals(tmp_path)
    # With an entry, mode on starts a test, so the start of the test refuses it.
    assert [(r["command"], r["harness"]) for r in rows] == [("start", "claude-code")] * 2
    assert rows[0]["problems"] == ["the project hook PreToolUse is missing."]
    assert rows[0]["nookku"] == __version__
    assert not (tmp_path / ".nookku" / "tests").exists()


def test_a_codex_refusal_adds_a_row_to_the_refusal_log(
    tmp_path: Path, claude_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit.init(tmp_path, "codex", ENTRY)
    gate = {"codex": True, "hooks": [], "problems": ["the plugin hook PreToolUse is missing."]}
    monkeypatch.setattr("nookku.codex_gate.check", lambda root: gate)
    with pytest.raises(bridge.BridgeError, match="Codex hooks of nookku are not ready"):
        bridge.start(tmp_path)
    assert [(r["harness"], r["problems"]) for r in _refusals(tmp_path)] == [
        ("codex", gate["problems"])
    ]

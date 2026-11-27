"""The refusal of a test if the nookku plugin and the project hooks are both on (#151)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from nookku import __version__, bridge, claude_gate, kit, state
from nookku.cli import main

ENTRY = {"entry": ["python3", "agent.py"]}


@pytest.fixture(autouse=True)
def no_harness_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused start records the harness versions. The tests do not run the harnesses."""
    monkeypatch.setattr(bridge, "_version", lambda cmd: f"{cmd} 1.0.0")


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
    assert state.latest_test(tmp_path) is None


def test_mode_on_with_an_entry_refuses_a_test_with_both_on_and_exits_with_1(
    tmp_path: Path, claude_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #248: with an entry, mode on starts a test. If the test does not start, it exits with 1.
    kit.init(tmp_path, "claude-code", ENTRY)
    _enable(claude_home / "settings.json", True)
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    assert "two times" in capsys.readouterr().out
    assert not kit.is_on(tmp_path)
    assert state.latest_test(tmp_path) is None


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
    # The start writes a sealed refusal record, not a test (#628).
    assert state.latest_test(tmp_path) is None
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
        # Claude Code does not wait for an async hook, so the hook cannot block the prompt.
        lambda d: _hook(d, "UserPromptSubmit").update({"async": True}),
        # The shell runs the Python with no arguments, then -I as a second command.
        lambda d: _hook(d, "UserPromptSubmit").update(
            command=_hook(d, "UserPromptSubmit")["command"].replace(" -I ", "\n-I ", 1)
        ),
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


def _rehash(folder: Path) -> None:
    """The hash file of a plugin of another commit: it has the hashes of its own files."""
    table = {"v": 1, "files": claude_gate.hook_files(folder)}
    (folder / claude_gate.PLUGIN_HASHES).write_text(json.dumps(table))


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
    # The plugin of a newer commit has the hash file of its own files (#628).
    _rehash(folder)
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


def _script_not_run(d: dict[str, Any]) -> None:
    # The last 2 words are the script and the event, but the command does not run the script.
    d["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] = (
        'true "${CLAUDE_PLUGIN_ROOT}/hooks/nookku-hook.sh" UserPromptSubmit'
    )


def _other_script(d: dict[str, Any]) -> None:
    d["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = 'sh "/tmp/hooks/nookku-hook.sh" PreToolUse'


def _more_words(d: dict[str, Any]) -> None:
    d["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = (
        'sh -c true "${CLAUDE_PLUGIN_ROOT}/hooks/nookku-hook.sh" PreToolUse'
    )


def _single_quotes(d: dict[str, Any]) -> None:
    # In single quotes the shell does not expand the variable, so the script does not run.
    d["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] = (
        "sh '${CLAUDE_PLUGIN_ROOT}/hooks/nookku-hook.sh' UserPromptSubmit"
    )


def _no_quotes(d: dict[str, Any]) -> None:
    # With no quotes, a plugin folder with a space splits into 2 words.
    d["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = (
        "sh ${CLAUDE_PLUGIN_ROOT}/hooks/nookku-hook.sh PreToolUse"
    )


def _async_hook(d: dict[str, Any]) -> None:
    # Claude Code does not wait for an async hook, so the hook cannot block the prompt.
    d["hooks"]["UserPromptSubmit"][0]["hooks"][0]["async"] = True


def _timeout(value: Any) -> Any:
    """A change that gives the UserPromptSubmit hook of the plugin a timeout, or no timeout."""

    def change(d: dict[str, Any]) -> None:
        hook = d["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        if value is None:
            del hook["timeout"]
        else:
            hook["timeout"] = value

    return change


def _short_tool_timeout(d: dict[str, Any]) -> None:
    d["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 29


def _event_on_new_line(d: dict[str, Any]) -> None:
    # The shell runs the script with no event, then runs the event name as a second command.
    d["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = (
        'sh "${CLAUDE_PLUGIN_ROOT}/hooks/nookku-hook.sh"\nPreToolUse'
    )


@pytest.mark.parametrize(
    ("change", "event"),
    [
        (_drop_prompt_hook, "UserPromptSubmit"),
        (_single_quotes, "UserPromptSubmit"),
        (_no_quotes, "PreToolUse"),
        (_event_on_new_line, "PreToolUse"),
        (_async_hook, "UserPromptSubmit"),
        # After a timeout, Claude Code sends the prompt to the model (#642).
        (_timeout(1), "UserPromptSubmit"),
        (_timeout(299), "UserPromptSubmit"),
        (_timeout(None), "UserPromptSubmit"),
        (_timeout("300"), "UserPromptSubmit"),
        (_timeout(300.5), "UserPromptSubmit"),
        (_timeout(True), "UserPromptSubmit"),
        (_short_tool_timeout, "PreToolUse"),
        (_narrow_matcher, "PreToolUse"),
        (_other_command, "UserPromptSubmit"),
        (_script_not_run, "UserPromptSubmit"),
        (_other_script, "PreToolUse"),
        (_more_words, "PreToolUse"),
    ],
)
def test_a_plugin_install_with_a_required_hook_missing_is_refused(
    tmp_path: Path, claude_home: Path, change: Any, event: str
) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    folder = _install(claude_home, tmp_path)
    _edit(folder / "hooks" / "hooks.json", change)
    _rehash(folder)
    assert claude_gate.problems(tmp_path) == [
        f"the plugin hook {event} is missing in {folder / 'hooks' / 'hooks.json'}, or its "
        "matcher or its command differs from the hook of nookku, or its timeout is not "
        f"{kit.HOOK_EVENTS[event][1]} seconds or more."
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
    # Each row names its sealed refusal record (#628).
    assert all(state.is_refusal(r["record"]) for r in rows)
    assert len({r["record"] for r in rows}) == 2
    assert state.latest_test(tmp_path) is None


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


def test_the_refusal_log_does_not_follow_a_symlink(tmp_path: Path) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    target = tmp_path / "target.txt"
    target.write_text("keep\n")
    log = tmp_path / ".nookku" / claude_gate.REFUSALS
    log.symlink_to(target)
    claude_gate.log_refusal(tmp_path, "start", "claude-code", ["a problem"])
    assert target.read_text() == "keep\n"
    log.unlink()
    log.mkdir()
    claude_gate.log_refusal(tmp_path, "start", "claude-code", ["a problem"])
    assert log.is_dir() and not any(log.iterdir())


def test_the_refusal_log_is_not_written_through_a_symlinked_state_folder(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / ".nookku").symlink_to(other)
    claude_gate.log_refusal(tmp_path / "shop", "start", "claude-code", ["a problem"])
    assert not any(other.iterdir())


def test_a_model_write_to_the_refusal_log_is_denied(tmp_path: Path) -> None:
    kit.init(tmp_path, "claude-code", ENTRY)
    path = str(tmp_path / ".nookku" / claude_gate.REFUSALS)
    event = {"cwd": str(tmp_path)}
    found = kit.state_write(event, tmp_path, "Write", {"file_path": path}, False)
    assert found is not None and found[0] == path


def _append(path: Path) -> None:
    with path.open("a") as f:
        f.write("// a change after the install\n")


def _add_file(folder: Path) -> None:
    (folder / "hooks" / "extra.tsx").write_text("export {}\n")


def _remove_file(folder: Path) -> None:
    (folder / "hooks" / "register.test.ts").unlink()


def _point_elsewhere(folder: Path) -> None:
    # The manifest names the hooks file of the function hooks, so it is a hook file too.
    _edit(folder / ".claude-plugin" / "plugin.json", lambda d: d.update(hooks="./other.json"))


@pytest.mark.parametrize(
    ("change", "word", "name"),
    [
        (lambda f: _append(f / "hooks" / "register.tsx"), "changed", "hooks/register.tsx"),
        (lambda f: _append(f / "hooks" / "nookku-hook.sh"), "changed", "hooks/nookku-hook.sh"),
        (_point_elsewhere, "changed", ".claude-plugin/plugin.json"),
        (_add_file, "new", "hooks/extra.tsx"),
        (_remove_file, "missing", "hooks/register.test.ts"),
    ],
)
def test_a_hook_file_changed_after_the_install_is_refused(
    tmp_path: Path, claude_home: Path, change: Any, word: str, name: str
) -> None:
    # The required hooks are still there, but a person or a tool changed a file (#628).
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    folder = _install(claude_home, tmp_path)
    change(folder)
    assert claude_gate.problems(tmp_path) == [
        f"the hook files of the plugin in {folder} differ from {claude_gate.PLUGIN_HASHES} of "
        f"the install ({word}: {name}). A person or a tool changed them after the install."
    ]
    with pytest.raises(bridge.BridgeError, match="sealed refusal record") as e:
        bridge.start(tmp_path)
    assert name in str(e.value)
    [row] = _refusals(tmp_path)
    record = json.loads(
        (state.tests_dir(tmp_path) / row["record"] / "refusal.json").read_text(encoding="utf-8")
    )
    assert record["problems"] == claude_gate.problems(tmp_path)
    assert main(["verify", row["record"], "--root", str(tmp_path)]) == 0


@pytest.mark.parametrize("table", [None, "{}", '{"v": 2, "files": {}}', '{"v": 1, "files": []}'])
def test_an_install_with_no_valid_hash_file_is_refused(
    tmp_path: Path, claude_home: Path, table: str | None
) -> None:
    kit.init(tmp_path, "plugin", ENTRY)
    _enable(claude_home / "settings.json", True)
    folder = _install(claude_home, tmp_path)
    path = folder / claude_gate.PLUGIN_HASHES
    if table is None:
        path.unlink()
    else:
        path.write_text(table)
    assert claude_gate.problems(tmp_path) == [
        f"the plugin hash file {path} is missing or not valid, so nookku cannot check the hook "
        "files of the install."
    ]


def test_a_link_in_the_hooks_folder_does_not_agree_with_the_table(tmp_path: Path) -> None:
    folder = tmp_path / "plugin"
    shutil.copytree(PLUGIN_DIR, folder)
    other = tmp_path / "other"
    other.mkdir()
    (folder / "hooks" / "more").symlink_to(other, target_is_directory=True)
    assert claude_gate.hook_files(folder)["hooks/more"] == ""
    assert "new: hooks/more" in claude_gate._hash_problems(folder)[0]

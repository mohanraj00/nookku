"""The plugin folder: its manifests, its hooks, its MCP config and the shell guard (#216)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from nookku import __version__, kit, mcp

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "nookku"
GUARD = PLUGIN / "hooks" / "nookku-hook.sh"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_command_hooks_have_the_events_of_the_project_hooks() -> None:
    hooks = load(PLUGIN / "hooks" / "hooks.json")
    # Codex refuses each other top-level key, also the modules of the function hooks.
    assert list(hooks) == ["hooks"]
    found = {}
    for event, groups in hooks["hooks"].items():
        [group] = groups
        [hook] = group["hooks"]
        command = f'sh "${{CLAUDE_PLUGIN_ROOT}}/hooks/nookku-hook.sh" {event}'
        assert hook == {"type": "command", "command": command, "timeout": hook["timeout"]}
        found[event] = ({k: v for k, v in group.items() if k != "hooks"}, hook["timeout"])
    assert found == kit.HOOK_EVENTS


def test_the_function_hooks_are_only_in_the_claude_code_manifest() -> None:
    claude = load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert claude["hooks"] == "./hooks/display.json"
    assert load(PLUGIN / "hooks" / "display.json") == {"modules": ["./register.tsx"]}
    # The plugin has no options. Each option comes from the config of the project.
    assert "userConfig" not in claude


def test_the_two_manifests_name_the_same_plugin() -> None:
    claude = load(PLUGIN / ".claude-plugin" / "plugin.json")
    codex = load(PLUGIN / ".codex-plugin" / "plugin.json")
    for key in ("name", "version", "description", "author", "license", "repository"):
        assert claude[key] == codex[key]
    assert claude["name"] == mcp.PLUGIN and claude["version"] == __version__
    assert codex["skills"] == "./skills/" and codex["mcpServers"] == "./.mcp.json"


def test_the_mcp_config_starts_nookku_mcp() -> None:
    servers = load(PLUGIN / ".mcp.json")["mcpServers"]
    # Codex asks the person before each call of a plugin MCP tool, unless the server approves it.
    want = {"command": "nookku", "args": ["mcp"], "default_tools_approval_mode": "approve"}
    assert servers == {mcp.SERVER: want}
    assert mcp.tool_name("claude-code", "status") == "mcp__plugin_nookku_nookku__status"
    assert mcp.tool_name("codex", "transcript") == "mcp__nookku__transcript"


def test_each_marketplace_names_the_plugin_folder() -> None:
    claude = load(ROOT / ".claude-plugin" / "marketplace.json")["plugins"]
    codex = load(ROOT / ".agents" / "plugins" / "marketplace.json")["plugins"]
    assert [p["source"] for p in claude] == ["./plugins/nookku"]
    assert [p["source"] for p in codex] == [{"source": "local", "path": "./plugins/nookku"}]
    # Codex skips an untrusted hook, so the plugin alone fails open (#177). Codex cannot install it
    # until the trust gate of #217 refuses a test with an untrusted hook.
    assert [p["policy"]["installation"] for p in codex] == ["NOT_AVAILABLE"]


def test_the_typescript_holds_no_rule() -> None:
    source = (PLUGIN / "hooks" / "register.tsx").read_text(encoding="utf-8")
    for word in ("tool.call", "http.fetch", "fs.read", "fs.write", "deny", "nookku: "):
        assert word not in source, word
    # The one exception: a prompt with an attachment, which a command hook cannot see.
    assert source.count("prompt.submit") == 1 and source.count("drop: refusal") == 1
    assert not (PLUGIN / "hooks" / "core.ts").exists()


def guard(
    tmp_path: Path, event: str, env: dict[str, str] | None = None, path: str = "/usr/bin:/bin"
) -> dict | None:
    """Run the shell guard in tmp_path, with no nookku on PATH."""
    p = subprocess.run(
        ["sh", str(GUARD), event],
        cwd=tmp_path,
        input=json.dumps({"hook_event_name": event}),
        capture_output=True,
        text=True,
        env={"PATH": path, **(env or {})},
        check=True,
    )
    return json.loads(p.stdout) if p.stdout else None


def state(root: Path) -> Path:
    folder = root / kit.STATE_DIR
    folder.mkdir(exist_ok=True)
    return folder


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "SessionStart"])
def test_with_no_nookku_and_no_state_folder_the_guard_does_nothing(
    tmp_path: Path, event: str
) -> None:
    assert guard(tmp_path, event) is None
    (state(tmp_path) / "mode").write_text("off\n")
    assert guard(tmp_path, event) is None


@pytest.mark.parametrize("mode", ["on\n", "On", "", "broken"])
def test_with_no_nookku_and_relay_mode_on_the_guard_fails_closed(tmp_path: Path, mode: str) -> None:
    (state(tmp_path) / "mode").write_text(mode)
    prompt = guard(tmp_path, "UserPromptSubmit")
    assert prompt is not None and prompt["decision"] == "block"
    assert prompt["reason"].startswith("nookku: relay mode is on, but the nookku command is not")
    assert prompt["reason"].endswith("Nothing was sent.")
    tool = guard(tmp_path, "PreToolUse")
    assert tool is not None
    assert tool["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert guard(tmp_path, "SessionStart") is None


def test_with_no_nookku_a_running_test_fails_closed(tmp_path: Path) -> None:
    (state(tmp_path) / "mode").write_text("off\n")
    (state(tmp_path) / "current.json").write_text("{}")
    tool = guard(tmp_path, "PreToolUse")
    assert tool is not None and tool["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_guard_finds_the_project_of_each_harness(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (state(project) / "mode").write_text("on\n")
    other = tmp_path / "other"
    other.mkdir()
    named = {"CLAUDE_PROJECT_DIR": str(project)}
    # Claude Code names the project. Codex runs the hook in the project, and a CLAUDE_PROJECT_DIR
    # that it inherits names another project.
    assert guard(other, "UserPromptSubmit", named) is not None
    assert guard(other, "UserPromptSubmit", {**named, "PLUGIN_ROOT": str(PLUGIN)}) is None
    assert guard(project, "UserPromptSubmit", {**named, "PLUGIN_ROOT": str(PLUGIN)}) is not None


@pytest.mark.parametrize(("env", "harness"), [({}, "claude-code"), ({"PLUGIN_ROOT": "x"}, "codex")])
def test_with_nookku_on_path_the_guard_runs_nookku_hook(
    tmp_path: Path, env: dict[str, str], harness: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "nookku"
    script = 'read -r line\nprintf \'{"argv": "%s", "event": %s}\' "$*" "$line"\n'
    fake.write_text("#!/bin/sh\n" + script)
    fake.chmod(0o755)
    out = guard(tmp_path, "PreToolUse", env, f"{bin_dir}{os.pathsep}/usr/bin:/bin")
    assert out == {"argv": f"hook --harness {harness}", "event": {"hook_event_name": "PreToolUse"}}

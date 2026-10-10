"""The Codex hook gate (SPEC.md section 7.8): each refused state, with fake hooks/list data."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from nookku import bridge, codex_gate, kit
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "nookku" / "hooks" / "nookku-hook.sh"
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
EVENT_NAMES = {"UserPromptSubmit": "userPromptSubmit", "PreToolUse": "preToolUse"}


def test_the_script_hash_is_the_hash_of_the_plugin_script() -> None:
    digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert digest == codex_gate.PLUGIN_SCRIPT_SHA256


def plugin_hooks(tmp_path: Path, **change: Any) -> list[dict[str, Any]]:
    """The 2 plugin hooks as hooks/list gives them, with a copy of the plugin script."""
    cache = tmp_path / "cache" / "nookku" / "nookku" / "0.4.0"
    (cache / "hooks").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, cache / "hooks" / "nookku-hook.sh")
    hooks = []
    for event, (matcher, timeout) in kit.HOOK_EVENTS.items():
        script = cache / "hooks" / "nookku-hook.sh"
        hook = {
            "eventName": EVENT_NAMES[event],
            "source": "plugin",
            "pluginId": "nookku@nookku",
            "matcher": matcher.get("matcher"),
            "timeoutSec": timeout,
            "command": f'sh "{script}" {event}',
            "sourcePath": str(cache / "hooks" / "hooks.json"),
            "enabled": True,
            "trustStatus": "trusted",
            "currentHash": f"sha256:{event}",
        }
        hooks.append({**hook, **change.get(event, {})})
    return hooks


def project_hooks(root: Path, write: bool = True, **change: Any) -> list[dict[str, Any]]:
    """The 2 project hooks of nookku init codex as hooks/list gives them."""
    command = kit.hook_command(root, "codex")
    if write:
        kit.init(root, "codex", {})
    return [
        {
            "eventName": EVENT_NAMES[event],
            "source": "project",
            "pluginId": None,
            "matcher": matcher.get("matcher"),
            "timeoutSec": timeout,
            "command": command,
            "enabled": True,
            "trustStatus": "trusted",
            **change.get(event, {}),
        }
        for event, (matcher, timeout) in kit.HOOK_EVENTS.items()
    ]


OTHER = {
    "eventName": "preToolUse",
    "source": "user",
    "command": "other",
    "trustStatus": "untrusted",
}


def test_with_no_nookku_hook_the_gate_passes(tmp_path: Path) -> None:
    assert codex_gate.problems([OTHER], tmp_path) == []


def test_trusted_plugin_hooks_pass(tmp_path: Path) -> None:
    assert codex_gate.problems([*plugin_hooks(tmp_path), OTHER], tmp_path) == []


def test_trusted_project_hooks_pass(tmp_path: Path) -> None:
    assert codex_gate.problems(project_hooks(tmp_path), tmp_path) == []


def test_a_missing_plugin_hook_is_refused(tmp_path: Path) -> None:
    hooks = [h for h in plugin_hooks(tmp_path) if h["eventName"] == "userPromptSubmit"]
    assert codex_gate.problems(hooks, tmp_path) == ["the plugin hook PreToolUse is missing."]


def test_project_hooks_that_codex_does_not_list_are_missing(tmp_path: Path) -> None:
    project_hooks(tmp_path)
    found = codex_gate.problems([], tmp_path)
    assert len(found) == 2 and all("is missing. Codex lists the project hooks" in p for p in found)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"enabled": False}, "the plugin hook PreToolUse is disabled."),
        ({"trustStatus": "untrusted"}, "the plugin hook PreToolUse is untrusted, not trusted."),
        ({"trustStatus": "modified"}, "the plugin hook PreToolUse is modified, not trusted."),
        ({"timeoutSec": 31}, "the plugin hook PreToolUse is modified: its matcher or its timeout"),
        ({"matcher": "Bash"}, "the plugin hook PreToolUse is modified: its matcher or its timeout"),
        ({"command": "sh other.sh"}, "the plugin hook PreToolUse is modified: its command is not"),
    ],
)
def test_each_refused_state_of_a_plugin_hook(tmp_path: Path, change: dict, reason: str) -> None:
    found = codex_gate.problems(plugin_hooks(tmp_path, PreToolUse=change), tmp_path)
    assert len(found) == 1 and found[0].startswith(reason)


def test_a_changed_plugin_script_is_modified(tmp_path: Path) -> None:
    hooks = plugin_hooks(tmp_path)
    script = Path(hooks[0]["sourcePath"]).parent / "nookku-hook.sh"
    script.write_text(script.read_text() + "echo changed\n")
    found = codex_gate.problems(hooks, tmp_path)
    assert len(found) == 2 and all("its script" in p for p in found)


def test_a_project_hook_with_another_command_is_modified(tmp_path: Path) -> None:
    hooks = project_hooks(tmp_path, UserPromptSubmit={"command": "nookku hook --harness codex"})
    found = codex_gate.problems(hooks, tmp_path)
    assert len(found) == 1
    assert found[0].startswith("the project hook UserPromptSubmit is modified: its command")


def test_the_plugin_and_the_project_hooks_together_are_refused(tmp_path: Path) -> None:
    hooks = [*plugin_hooks(tmp_path), *project_hooks(tmp_path)]
    found = codex_gate.problems(hooks, tmp_path)
    assert len(found) == 1 and "two times" in found[0]


def fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """A codex command that runs a Python body. The body reads the requests of stdin."""
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    fake = folder / "codex"
    fake.write_text(f"#!{sys.executable}\nimport json, sys, time\n{body}\n")
    fake.chmod(0o755)
    monkeypatch.setenv("NOOKKU_CODEX", str(fake))


def answer_with(hooks: list[dict[str, Any]]) -> str:
    result = json.dumps({"data": [{"hooks": hooks, "warnings": [], "errors": []}]})
    return (
        f"result = json.loads({result!r})\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m.get('id') == 2:\n"
        "        print(json.dumps({'id': 2, 'result': result}), flush=True)\n"
    )


def test_check_reads_hooks_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hooks = plugin_hooks(tmp_path, UserPromptSubmit={"trustStatus": "untrusted"})
    fake_codex(tmp_path, monkeypatch, answer_with(hooks))
    result = codex_gate.check(tmp_path)
    assert result["codex"] is True
    assert result["problems"] == ["the plugin hook UserPromptSubmit is untrusted, not trusted."]
    assert [h["trust"] for h in result["hooks"]] == ["untrusted", "trusted"]
    assert {h["script_sha256"] for h in result["hooks"]} == {codex_gate.PLUGIN_SCRIPT_SHA256}


def test_with_no_codex_command_the_gate_does_not_run(tmp_path: Path) -> None:
    assert codex_gate.check(tmp_path) == {"codex": False, "hooks": [], "problems": []}


def test_a_codex_that_stops_at_once_cannot_run_a_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_codex(tmp_path, monkeypatch, "sys.exit(1)")
    result = codex_gate.check(tmp_path)
    assert result["codex"] is False and result["problems"] == []


def test_a_codex_that_does_not_answer_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_codex(tmp_path, monkeypatch, "time.sleep(30)")
    monkeypatch.setattr(codex_gate, "TIMEOUT", 0.5)
    result = codex_gate.check(tmp_path)
    assert result["problems"] == [
        "cannot read the hooks of Codex: codex app-server gave no hooks/list answer in 0.5 s"
    ]


def test_start_refuses_a_test_with_an_untrusted_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    kit.init(root, "plugin", {"entry": [sys.executable, str(TOY_SHOP)]})
    hooks = plugin_hooks(tmp_path, PreToolUse={"trustStatus": "untrusted"})
    fake_codex(tmp_path, monkeypatch, answer_with(hooks))
    with pytest.raises(bridge.BridgeError, match="PreToolUse is untrusted"):
        bridge.start(root)
    assert not (root / kit.STATE_DIR / "tests").exists()
    assert main(["mode", "on", "--root", str(root)]) == 0
    assert "the Codex hooks of nookku are not ready" in capsys.readouterr().out
    assert not kit.is_on(root)


def test_mode_on_with_no_entry_refuses_an_untrusted_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    kit.init(root, "plugin", {})
    hooks = plugin_hooks(tmp_path, UserPromptSubmit={"enabled": False})
    fake_codex(tmp_path, monkeypatch, answer_with(hooks))
    assert main(["mode", "on", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "- the plugin hook UserPromptSubmit is disabled." in out
    assert not kit.is_on(root)
    fake_codex(tmp_path, monkeypatch, answer_with(plugin_hooks(tmp_path)))
    assert main(["mode", "on", "--root", str(root)]) == 0
    assert kit.is_on(root)


def gate(hooks: list[dict[str, Any]], problems: list[str] | None = None) -> dict[str, Any]:
    return {"codex": True, "hooks": hooks, "problems": problems or []}


@pytest.mark.parametrize(
    ("start", "end", "changed"),
    [
        (gate([{"hash": "a"}]), gate([{"hash": "a"}]), None),
        (gate([{"hash": "a"}]), gate([{"hash": "b"}]), "the hooks at the end differ"),
        (gate([]), gate([], ["the plugin hook X is missing."]), "the plugin hook X is missing."),
        ({"codex": False, "hooks": [], "problems": []}, gate([{"hash": "b"}]), None),
        (None, gate([]), None),
    ],
)
def test_the_end_text_names_hooks_that_changed_during_the_test(
    start: Any, end: Any, changed: str | None
) -> None:
    manifest = {"codex_gate": {"start": start, "end": end}}
    found = bridge.gate_changed(manifest)
    assert (found is None) if changed is None else (found is not None and found.startswith(changed))

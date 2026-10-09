"""Check the spike's evidence filters and trust gate without a model or harness."""

import copy
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "spike_codex_display", ROOT / "scripts/spike_codex_display.py"
)
assert spec and spec.loader
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


def test_request_evidence_retains_only_marker_locations():
    body = {
        "instructions": "private toy instructions",
        "input": [
            {"role": "developer", "content": "DISPLAY_CONTEXT_PreToolUse_205"},
            {"type": "function_call_output", "output": "DISPLAY_MCP_TEXT_205"},
        ],
    }
    result = spike.locations(json.dumps(body).encode())
    assert result["DISPLAY_CONTEXT_PreToolUse_205"] == ["input[0].developer"]
    assert result["DISPLAY_MCP_TEXT_205"] == ["input[1].function_call_output"]
    assert "private toy" not in json.dumps(result)
    assert result["DISPLAY_WARNING_PreToolUse_205"] == []


@pytest.mark.parametrize("namespace", [False, True])
def test_the_mock_uses_only_the_toy_tool_and_preserves_its_namespace(namespace):
    if namespace:
        tool = {
            "type": "namespace",
            "name": "mcp__toy_display",
            "tools": [
                {"name": "show_order"},
                {"name": "other"},
            ],
        }
        expected = {"name": "show_order", "namespace": "mcp__toy_display"}
    else:
        tool = {"type": "function", "name": "mcp__toy_display__show_order"}
        expected = {"name": "mcp__toy_display__show_order"}
    body = {
        "tools": [
            tool,
            {"type": "namespace", "name": "mcp__other", "tools": [{"name": "show_order"}]},
        ]
    }
    assert spike.toy_tools(body) == [expected]


@pytest.mark.parametrize("status", ["untrusted", "modified", "disabled", "missing"])
def test_no_endpoint_starts_before_all_required_hooks_have_human_trust(monkeypatch, status):
    hooks = [
        {
            "pluginId": spike.SELECTOR,
            "enabled": True,
            "trustStatus": "trusted",
            "eventName": event[0].lower() + event[1:],
        }
        for event in spike.EVENTS
    ]
    if status == "missing":
        hooks.pop()
    elif status == "disabled":
        hooks[0]["enabled"] = False
    else:
        hooks[0]["trustStatus"] = status
    monkeypatch.setattr(spike, "metadata", lambda: {"hooks": hooks})
    monkeypatch.setattr(spike, "read", lambda _: {})

    def refuse(*args):
        pytest.fail("The probe started before the trust check passed")

    monkeypatch.setattr(spike, "ThreadingHTTPServer", refuse)
    with pytest.raises(SystemExit, match="not all trusted"):
        spike.measure()


def test_desktop_import_rejects_model_answers(monkeypatch, tmp_path):
    person = tmp_path / "person.json"
    person.write_text(json.dumps({"model_answer": "private toy reply"}))
    with pytest.raises(SystemExit, match="Do not import a model answer"):
        spike.desktop_finish(person)


def test_desktop_import_needs_a_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(spike, "WORK", tmp_path)
    person = tmp_path / "person.json"
    person.write_text(
        json.dumps(
            {
                "runtime_version": None,
                "status_shown": None,
                "warnings_shown": None,
                "skill_started_turn": None,
                "ui_rendered": None,
                "refresh_started_turn": None,
                "sidebar_entry": None,
                "panel_entry": None,
                "pane_location": "unknown",
                "opening_path": "unknown",
                "refresh_click_count": "unknown",
            }
        )
    )
    with pytest.raises(SystemExit, match="desktop-start"):
        spike.desktop_finish(person)


def test_prepare_refuses_to_replace_the_reviewed_hook(tmp_path):
    path = tmp_path / "hook.py"
    spike.reviewed_write(path, "old reviewed toy hook")
    with pytest.raises(SystemExit, match="new fixture and human review"):
        spike.reviewed_write(path, "changed toy hook")
    assert path.read_text() == "old reviewed toy hook"


def test_mcp_fixture_declares_entrypoints_and_serves_the_ui_resource(tmp_path):
    server = tmp_path / "server.py"
    server.write_text(spike.SERVER)
    (tmp_path / "order.html").write_text(spike.HTML)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "show_order", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": "ui://toy-shop/order.html"},
        },
    ]
    result = subprocess.run(
        [sys.executable, str(server), str(tmp_path / "mcp.jsonl")],
        input="\n".join(map(json.dumps, messages)) + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    responses = [json.loads(line)["result"] for line in result.stdout.splitlines()]
    metadata = responses[0]["tools"][0]["_meta"]
    assert metadata["openai/ui"]["entrypoints"] == [{"type": "global"}, {"type": "thread"}]
    assert metadata["ui"]["resourceUri"] == "ui://toy-shop/order.html"
    assert responses[1]["structuredContent"]["marker"] == "DISPLAY_MCP_STRUCTURED_205"
    assert responses[1]["_meta"]["display"] == "DISPLAY_MCP_META_205"
    resource = responses[2]["contents"][0]
    assert resource["mimeType"] == "text/html;profile=mcp-app"
    assert "DISPLAY_UI_205" in resource["text"]


def test_refresh_import_requires_a_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(spike, "WORK", tmp_path)
    with pytest.raises(SystemExit, match="desktop-refresh-start"):
        spike.desktop_refresh(False)


def test_refresh_records_only_calls_and_hooks_after_the_baseline(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    proof = tmp_path / "proof.json"
    monkeypatch.setattr(spike, "WORK", tmp_path)
    monkeypatch.setattr(spike, "PROJECT", project)
    monkeypatch.setattr(spike, "PROOF", proof)
    monkeypatch.setattr(spike, "versions", lambda: {"cli": "toy-version"})
    old_call = {"method": "tools/call", "tool": "show_order"}
    old_hook = {"event": "Stop"}
    (project / "mcp.jsonl").write_text(json.dumps(old_call) + "\n")
    (project / "hooks.jsonl").write_text(json.dumps(old_hook) + "\n")
    spike.desktop_refresh(True)
    new_events = [
        {"method": "initialize"},
        {"method": "resources/read", "uri": "ui://toy-shop/order.html"},
        {"method": "tools/call", "tool": "other"},
        {"method": "tools/call", "tool": "show_order"},
    ]
    with (project / "mcp.jsonl").open("a") as stream:
        stream.write("\n".join(map(json.dumps, new_events)) + "\n")
    spike.desktop_refresh(False)
    result = json.loads(proof.read_text())["desktop_refresh"]
    assert result["mcp_events"] == new_events
    assert result["show_order_calls"] == 1
    assert result["hook_events"] == []
    assert result["versions_before"] == result["versions_after"] == {"cli": "toy-version"}


def test_a_copied_method_imports_without_git(monkeypatch, tmp_path):
    copied = tmp_path / "scripts" / "spike_codex_display.py"
    copied.parent.mkdir()
    copied.write_text((ROOT / "scripts/spike_codex_display.py").read_text())
    copied_spec = importlib.util.spec_from_file_location("copied_display_method", copied)
    assert copied_spec and copied_spec.loader
    copied_module = importlib.util.module_from_spec(copied_spec)

    def no_process_at_import(*args, **kwargs):
        pytest.fail("Importing the copied method must not start git or another process")

    monkeypatch.setattr(subprocess, "run", no_process_at_import)
    copied_spec.loader.exec_module(copied_module)
    assert tmp_path / ".proof/codex-display-205" == copied_module.WORK


def approved_fixture(monkeypatch, tmp_path):
    home = tmp_path / "home"
    source = tmp_path / "plugin"
    cache = home / ".codex/plugins/cache" / spike.MARKET / spike.NAME / "0.0.1"
    hook_command = f'{spike.shlex.quote(sys.executable)} "${{PLUGIN_ROOT}}/hook.py"'
    definition = {
        "hooks": {
            event: [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command,
                            "timeout": 10,
                            "statusMessage": f"DISPLAY_STATUS_{event}_205",
                        }
                    ]
                }
            ]
            for event in spike.EVENTS
        }
    }
    monkeypatch.setattr(spike, "PLUGIN", source)
    for root in (source, cache):
        for relative, content in spike.plugin_inputs().items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (root / "hooks").mkdir(parents=True, exist_ok=True)
        (root / "hooks/hooks.json").write_text(json.dumps(definition, indent=2) + "\n")
        (root / "hook.py").write_text(spike.HOOK)
    monkeypatch.setattr(spike.Path, "home", lambda: home)
    monkeypatch.setattr(spike, "PLUGIN", source)
    monkeypatch.setattr(spike, "PROOF", tmp_path / "proof.json")
    hooks = [
        {
            "pluginId": spike.SELECTOR,
            "source": "plugin",
            "handlerType": "command",
            "enabled": True,
            "trustStatus": "trusted",
            "eventName": event[0].lower() + event[1:],
            "sourcePath": str(cache / "hooks/hooks.json"),
            "command": hook_command.replace("${PLUGIN_ROOT}", str(cache)),
            "currentHash": "sha256:" + spike.hashlib.sha256(event.encode()).hexdigest(),
            "async": False,
            "matcher": None,
            "timeoutSec": 10,
            "statusMessage": f"DISPLAY_STATUS_{event}_205",
            "additionalContextLimit": None,
        }
        for event in spike.EVENTS
    ]
    data = {"inspection": {"hooks": copy.deepcopy(hooks)}}
    monkeypatch.setattr(spike, "metadata", lambda: {"hooks": hooks, "errors": []})
    monkeypatch.setattr(spike, "read", lambda _: data)
    return cache, hooks, data


@pytest.mark.parametrize("mutation", ["executable", "command", "source", "hash", "definition"])
def test_probe_rejects_a_changed_installed_fixture_before_an_endpoint(
    monkeypatch, tmp_path, mutation
):
    cache, hooks, _ = approved_fixture(monkeypatch, tmp_path)
    if mutation == "executable":
        (cache / "hook.py").write_text("changed toy hook executable")
    elif mutation == "command":
        hooks[0]["command"] = "printf changed"
    elif mutation == "source":
        hooks[0]["sourcePath"] = str(tmp_path / "other/hooks.json")
    elif mutation == "hash":
        hooks[0]["currentHash"] = "sha256:" + "0" * 64
    else:
        (cache / "hooks/hooks.json").write_text('{"hooks": {}}')

    def refuse(*args):
        pytest.fail("An endpoint started with an unverified toy fixture")

    monkeypatch.setattr(spike, "ThreadingHTTPServer", refuse)
    with pytest.raises(SystemExit, match="fixture"):
        spike.measure()


def test_non_toy_enabled_hooks_survive_discovery_and_stop_the_probe(monkeypatch, tmp_path):
    hooks = [
        {
            "pluginId": spike.SELECTOR,
            "enabled": True,
            "trustStatus": "trusted",
            "eventName": event[0].lower() + event[1:],
        }
        for event in spike.EVENTS
    ]
    hooks.append(
        {
            "pluginId": "other-toy@other-market",
            "enabled": True,
            "trustStatus": "trusted",
            "eventName": "stop",
        }
    )

    class FakeServer:
        def __init__(self):
            self.process = type("Process", (), {"stdin": io.BytesIO()})()

        def request(self, method, params):
            if method == "config/read":
                return {"config": {}}
            if method == "hooks/list":
                return {"data": [{"hooks": hooks, "errors": [], "warnings": []}]}
            return {}

        def close(self):
            pass

    monkeypatch.setattr(spike, "AppServer", FakeServer)
    monkeypatch.setattr(spike, "PROOF", tmp_path / "proof.json")
    monkeypatch.setattr(spike, "read", lambda _: {})

    def refuse(*args):
        pytest.fail("An endpoint started while a non-toy hook was enabled")

    monkeypatch.setattr(spike, "ThreadingHTTPServer", refuse)
    with pytest.raises(SystemExit, match="Non-toy"):
        spike.measure()


def test_desktop_import_rejects_a_reply_in_notes(monkeypatch, tmp_path):
    person = tmp_path / "person.json"
    person.write_text(
        json.dumps(
            {
                "runtime_version": None,
                "status_shown": None,
                "warnings_shown": None,
                "skill_started_turn": None,
                "ui_rendered": None,
                "refresh_started_turn": None,
                "sidebar_entry": None,
                "panel_entry": None,
                "notes": "private toy model reply",
            }
        )
    )
    monkeypatch.setattr(spike, "WORK", tmp_path)
    (tmp_path / "desktop-baseline.json").write_text('{"hooks": 0, "mcp": 0, "versions": {}}')
    monkeypatch.setattr(spike, "PROJECT", tmp_path)
    monkeypatch.setattr(spike, "PROOF", tmp_path / "proof.json")
    monkeypatch.setattr(spike, "versions", lambda: {})
    with pytest.raises(SystemExit, match="Do not import a model answer"):
        spike.desktop_finish(person)


def test_a_matching_installed_fixture_passes_without_writing_trust(monkeypatch, tmp_path):
    _, hooks, data = approved_fixture(monkeypatch, tmp_path)
    result = spike.verify_fixture({"hooks": hooks, "errors": []}, data["inspection"]["hooks"])
    assert result["hooks"] == hooks
    assert result["executable_sha256"] == spike.hashlib.sha256(spike.HOOK.encode()).hexdigest()


@pytest.mark.parametrize("field", ["runtime_version", "status_shown", "pane_location"])
def test_desktop_import_rejects_free_text_in_structured_fields(monkeypatch, tmp_path, field):
    person = tmp_path / "person.json"
    observation = {
        "runtime_version": None,
        "status_shown": None,
        "warnings_shown": None,
        "skill_started_turn": None,
        "ui_rendered": None,
        "refresh_started_turn": None,
        "sidebar_entry": None,
        "panel_entry": None,
        "pane_location": "unknown",
        "opening_path": "unknown",
        "refresh_click_count": "unknown",
    }
    observation[field] = "private toy model reply"
    person.write_text(json.dumps(observation))
    with pytest.raises(SystemExit, match="Do not import a model answer"):
        spike.desktop_finish(person)


def test_plugin_override_targets_the_selector_without_literal_quote_characters(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(spike.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(spike, "INVOCATION_OVERRIDES", [])
    args = spike.overrides()
    assert any(f'"{spike.SELECTOR}"={{enabled=true}}' in arg for arg in args)
    assert not any('plugins."' in arg for arg in args)


def test_invocation_disables_only_non_toy_hooks_without_setting_trust(monkeypatch):
    class FakeServer:
        def __init__(self):
            self.process = type("Process", (), {"stdin": io.BytesIO()})()

        def request(self, method, params):
            if method == "config/read":
                return {"config": {}}
            if method == "hooks/list":
                return {
                    "data": [
                        {
                            "hooks": [
                                {"key": "toy-key", "pluginId": spike.SELECTOR, "enabled": True},
                                {"key": "other-key", "pluginId": None, "enabled": True},
                            ]
                        }
                    ]
                }
            return {}

        def close(self):
            pass

    args = []
    monkeypatch.setattr(spike, "AppServer", FakeServer)
    monkeypatch.setattr(spike, "INVOCATION_OVERRIDES", args)
    spike.isolate_invocation()
    state = next(arg for arg in args if arg.startswith("hooks.state="))
    assert '"other-key"={enabled=false}' in state
    assert "toy-key" not in state
    assert "trusted_hash" not in " ".join(args)


def test_desktop_import_keeps_only_bounded_observations(monkeypatch, tmp_path):
    observation = {
        "runtime_version": "26.1007.21159",
        "status_shown": None,
        "warnings_shown": False,
        "skill_started_turn": True,
        "ui_rendered": True,
        "refresh_started_turn": False,
        "sidebar_entry": None,
        "panel_entry": None,
        "pane_location": "left",
        "opening_path": "unknown",
        "refresh_click_count": "several",
    }
    person = tmp_path / "person.json"
    person.write_text(json.dumps(observation))
    (tmp_path / "desktop-baseline.json").write_text('{"hooks": 0, "mcp": 0, "versions": {}}')
    monkeypatch.setattr(spike, "WORK", tmp_path)
    monkeypatch.setattr(spike, "PROJECT", tmp_path)
    monkeypatch.setattr(spike, "PROOF", tmp_path / "proof.json")
    monkeypatch.setattr(spike, "versions", lambda: {})
    spike.desktop_finish(person)
    result = json.loads((tmp_path / "proof.json").read_text())
    assert result["desktop"]["human_observation"] == observation
    assert "notes" not in result["desktop"]["human_observation"]


def test_dotted_plugin_selector_stays_one_literal_key(monkeypatch, tmp_path):
    tomllib = pytest.importorskip("tomllib")
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text('[plugins."other.name@toy-market"]\nenabled = true\n')
    monkeypatch.setattr(spike.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(spike, "INVOCATION_OVERRIDES", [])
    args = spike.overrides()
    table = next((arg for arg in args if arg.startswith("plugins=")), None)
    assert table is not None, "Use a table override so dots in selector keys stay literal"
    plugins = tomllib.loads(table)["plugins"]
    assert plugins["other.name@toy-market"]["enabled"] is False
    assert plugins[spike.SELECTOR]["enabled"] is True


def test_isolation_sends_initialized_before_reading_hooks(monkeypatch):
    stream = io.BytesIO()

    class FakeServer:
        def __init__(self):
            self.process = type("Process", (), {"stdin": stream})()

        def request(self, method, params):
            if method == "config/read":
                return {"config": {}}
            if method == "hooks/list":
                assert b'"method":"initialized"' in stream.getvalue()
                return {"data": [{"hooks": []}]}
            return {}

        def close(self):
            pass

    monkeypatch.setattr(spike, "AppServer", FakeServer)
    spike.isolate_invocation()


@pytest.mark.parametrize(
    "relative",
    [
        "server.py",
        ".mcp.json",
        "order.html",
        ".codex-plugin/plugin.json",
        "skills/toy-order/SKILL.md",
    ],
)
@pytest.mark.parametrize("installed", [False, True])
def test_probe_checks_all_plugin_inputs_before_starting(monkeypatch, tmp_path, relative, installed):
    cache, _, _ = approved_fixture(monkeypatch, tmp_path)
    target = (cache if installed else spike.PLUGIN) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed toy fixture input")

    def refuse(*args):
        pytest.fail("An endpoint started with an unchecked plugin input")

    monkeypatch.setattr(spike, "ThreadingHTTPServer", refuse)
    with pytest.raises(SystemExit, match="fixture"):
        spike.measure()


def test_isolation_disables_effective_mcp_servers_without_saving_config(monkeypatch):
    class FakeServer:
        def __init__(self):
            self.process = type("Process", (), {"stdin": io.BytesIO()})()

        def request(self, method, params):
            if method == "config/read":
                assert params["cwd"] == str(spike.PROJECT)
                return {
                    "config": {
                        "mcp_servers": {
                            "other.toy": {
                                "command": "toy-server",
                                "enabled": True,
                                "env": {"TOY": "local"},
                            },
                            "toy_display": {"command": "other-server"},
                        }
                    }
                }
            if method == "hooks/list":
                return {"data": [{"hooks": []}]}
            return {}

        def close(self):
            pass

    args = []
    monkeypatch.setattr(spike, "AppServer", FakeServer)
    monkeypatch.setattr(spike, "INVOCATION_OVERRIDES", args)
    spike.isolate_invocation()
    table = next((arg for arg in args if arg.startswith("mcp_servers=")), None)
    assert table is not None, "Disable servers from effective user and project config"
    tomllib = pytest.importorskip("tomllib")
    parsed = tomllib.loads(table)["mcp_servers"]
    assert parsed["other.toy"]["enabled"] is False
    assert parsed["other.toy"]["command"] == "toy-server"
    assert parsed["other.toy"]["env"] == {"TOY": "local"}
    assert parsed["toy_display"]["enabled"] is False


def test_enabled_configured_mcp_server_stops_before_endpoint(monkeypatch, tmp_path):
    _, hooks, _ = approved_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        spike,
        "metadata",
        lambda: {"hooks": hooks, "errors": [], "enabled_config_mcp_servers": ["other.toy"]},
    )

    def refuse(*args):
        pytest.fail("An endpoint started with an unrelated MCP server enabled")

    monkeypatch.setattr(spike, "ThreadingHTTPServer", refuse)
    with pytest.raises(SystemExit, match="MCP servers"):
        spike.measure()


def test_desktop_start_checks_fixture_before_printing_human_steps(monkeypatch, tmp_path):
    approved_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(spike, "WORK", tmp_path)
    monkeypatch.setattr(spike, "PROJECT", tmp_path)
    monkeypatch.setattr(spike, "versions", lambda: {})
    monkeypatch.setattr(spike, "metadata", lambda **kwargs: {"hooks": [], "errors": []})
    with pytest.raises(SystemExit, match="trusted"):
        spike.desktop_start()
    assert not (tmp_path / "desktop-baseline.json").exists()


@pytest.mark.parametrize("relative", ["server.py", ".mcp.json"])
def test_desktop_preflight_rejects_changed_mcp_inputs(monkeypatch, tmp_path, relative):
    monkeypatch.setattr(spike, "WORK", tmp_path)
    monkeypatch.setattr(spike, "PROJECT", tmp_path)
    cache, hooks, _ = approved_fixture(monkeypatch, tmp_path)
    (cache / relative).write_text("changed toy MCP input")

    def unisolated_metadata(*, isolated):
        assert isolated is False, "Desktop must check settings without CLI overrides"
        return {"hooks": hooks, "errors": []}

    monkeypatch.setattr(spike, "metadata", unisolated_metadata)
    with pytest.raises(SystemExit, match="fixture"):
        spike.desktop_start()
    assert not (tmp_path / "desktop-baseline.json").exists()

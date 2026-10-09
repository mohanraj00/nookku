"""Check the spike's evidence filters and trust gate without a model or harness."""

import importlib.util
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
        {"enabled": True, "trustStatus": "trusted", "eventName": event[0].lower() + event[1:]}
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
                "notes": "Not observed.",
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

"""Check the spike's evidence reader and its human trust gate without a harness or model."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "spike_plugin_mcp", ROOT / "scripts/spike_plugin_mcp.py"
)
assert spec and spec.loader
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


@pytest.mark.parametrize("namespace", [False, True])
def test_the_reader_finds_the_toy_tool_without_retaining_other_tools(namespace):
    tool = {"type": "function", "name": "mcp__spike__transcript"}
    expected = "mcp__spike__transcript"
    if namespace:
        tool = {
            "type": "namespace",
            "name": "mcp__spike",
            "tools": [{"type": "function", "name": "transcript"}],
        }
        expected = "mcp__spike.transcript"
    body = {"tools": [tool, {"type": "function", "name": "other_tool"}], "input": []}
    assert spike.codex_results(json.dumps(body).encode())["plugin_tools"] == [expected]


@pytest.mark.parametrize("wrapper", ["text", "array", "json"])
def test_the_reader_hashes_the_tool_text_and_keeps_no_instructions(wrapper):
    text = "MCP-SPIKE-START\nCafé ü 中文 😀 𝄞\nMCP-SPIKE-END"
    output = text
    if wrapper == "array":
        output = [
            {"type": "input_text", "text": "Wall time: 0.001 seconds\nOutput:"},
            {"type": "input_text", "text": text},
        ]
    elif wrapper == "json":
        output = json.dumps({"content": [{"type": "text", "text": text}]})
    body = {
        "instructions": "PRIVATE TOY INSTRUCTIONS",
        "tools": [],
        "input": [
            {"type": "message", "role": "developer", "content": "PRIVATE TOY CONTEXT"},
            {"type": "function_call_output", "call_id": "call_spike194", "output": output},
        ],
    }
    result = spike.codex_results(json.dumps(body).encode())
    row = result["tool_results"][0]
    hashes = [part["sha256"] for part in [row["envelope"], *row["text_parts"]]]
    assert hashlib.sha256(text.encode()).hexdigest() in hashes
    saved = json.dumps(result)
    assert "PRIVATE TOY" not in saved
    assert text not in saved


def test_a_truncated_result_does_not_have_the_full_text_hash():
    full = "MCP-SPIKE-START\n" + "toy shop turn\n" * 100 + "MCP-SPIKE-END"
    cut = full[:100] + "[truncated]"
    body = {"tools": [], "input": [{"type": "function_call_output", "output": cut}]}
    row = spike.codex_results(json.dumps(body).encode())["tool_results"][0]
    assert row["envelope"]["sha256"] != hashlib.sha256(full.encode()).hexdigest()
    assert row["envelope"]["truncated"]
    assert not row["envelope"]["has_end"]


@pytest.mark.parametrize(
    "hooks",
    [
        [],
        [{"enabled": True, "trustStatus": "modified"}],
        [{"enabled": False, "trustStatus": "trusted"}],
    ],
)
def test_the_probe_refuses_before_starting_an_endpoint_without_human_trust(
    monkeypatch, tmp_path, hooks
):
    monkeypatch.setattr(spike, "codex_hooks", lambda: hooks)

    def refuse(*args):
        pytest.fail("The probe started before the hook trust check passed")

    monkeypatch.setattr(spike, "codex_case", refuse)
    out = tmp_path / "proof.json"
    out.write_text('{"claude-code": {"cases": []}}\n')
    before = out.read_bytes()
    assert spike.codex_main([], out, {"claude-code": {"cases": []}}) == 1
    assert out.read_bytes() == before


def test_person_answers_preserve_the_other_harness_and_the_cli_result(tmp_path):
    person = tmp_path / "person.json"
    person.write_text('{"desktop": {"server_started": true}}')
    out = tmp_path / "proof.json"
    case = {
        "size": 10240,
        "tool_output_token_limit": None,
        "sent": [{"size": 10240, "sha256": "toy-hash"}],
        "unchanged": True,
    }
    data = {"claude-code": {"cases": ["existing"]}, "codex": {"cases": [case]}}
    assert spike.codex_main(["--person", str(person)], out, data) == 0
    saved = json.loads(out.read_text())
    assert saved["claude-code"] == {"cases": ["existing"]}
    assert saved["codex"]["cases"] == [case]
    assert saved["codex"]["person"]["desktop"]["server_started"]


def test_desktop_import_reads_only_the_matched_toy_output_and_runtime(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    text = "MCP-SPIKE-START\n" + "x" * (10240 - 29) + "\nMCP-SPIKE-END"
    sent = {"size": 10240, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    (work / "server.jsonl").write_text(json.dumps(sent) + "\n")
    (work / "hook.jsonl").write_text(
        '{"tool_name": "mcp__spike__transcript"}\n{"tool_name": "mcp__support__status"}\n'
    )
    rows = [
        {
            "type": "session_meta",
            "payload": {
                "cli_version": "toy-version",
                "originator": "Codex Desktop",
                "source": "vscode",
                "instructions": "PRIVATE TOY META",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "toy-call",
                "input": "text(await tools.mcp__spike__transcript({size:10240}));",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "unrelated-call",
                "output": "PRIVATE TOY CONTEXT",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "toy-call",
                "output": [{"type": "input_text", "text": text}],
            },
        },
        {
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": "PRIVATE TOY ANSWER"},
        },
    ]
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text("\n".join(json.dumps(row) for row in rows))
    monkeypatch.setattr(spike, "CODEX_HERE", work)
    monkeypatch.setattr(spike, "codex_versions", lambda: {"codex-cli": "installed-toy-version"})
    result = spike.codex_rollout(rollout)
    assert result["runtime"]["cli_version"] == "toy-version"
    assert result["cases"][0]["retained_text_unchanged"]
    assert result["cases"][0]["wire_text_unchanged"] is None
    assert result["hook_tool_names"] == ["mcp__spike__transcript"]
    assert "no call identity" in result["server_log_pairing"]
    assert "PRIVATE TOY" not in json.dumps(result)
    assert text not in json.dumps(result)


def test_a_desktop_import_refuses_an_unmatched_server_log(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "server.jsonl").write_text('{"size": 1048576, "sha256": "other"}\n')
    rows = [
        {"type": "session_meta", "payload": {"originator": "Codex Desktop"}},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "transcript",
                "namespace": "mcp__spike",
                "call_id": "toy-call",
                "arguments": '{"size": 10240}',
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "toy-call",
                "output": "toy shop",
            },
        },
    ]
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text("\n".join(json.dumps(row) for row in rows))
    monkeypatch.setattr(spike, "CODEX_HERE", work)
    with pytest.raises(ValueError, match="server log does not match"):
        spike.codex_rollout(rollout)


@pytest.mark.parametrize(
    ("names", "expected"),
    [([], None), (["mcp__spike.transcript"], False), (["mcp__mcp-spike__transcript"], True)],
)
def test_plugin_identity_answers_come_from_observed_names(names, expected):
    entry = {"cases": [], "desktop": {"hook_tool_names": names}}
    if names:
        entry["cases"] = [
            {
                "size": 10240,
                "sent": ["toy"],
                "unchanged": True,
                "tool_output_token_limit": None,
                "model_tools": names,
            }
        ]
    answers = spike.codex_answers(entry)
    assert answers["codex_exec"]["prefix_has_plugin_identity"] is expected
    assert answers["desktop"]["prefix_has_plugin_identity"] is expected


def test_project_instructions_print_the_script_command(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(spike, "codex_project", lambda: tmp_path)
    assert spike.codex_main(["--project"], tmp_path / "proof.json", {}) == 0
    assert (
        "python scripts/spike_plugin_mcp.py codex --rollout FILE [OUT]" in capsys.readouterr().out
    )


def test_repeated_sizes_return_the_same_bytes_and_logged_hash(tmp_path):
    server = tmp_path / "server.py"
    server.write_text(spike.SERVER_PY)
    log = tmp_path / "server.jsonl"
    requests = [
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": "transcript", "arguments": {"size": 10240}},
        }
        for rid in (1, 2)
    ]
    result = subprocess.run(
        [sys.executable, str(server), str(log)],
        input="\n".join(json.dumps(row) for row in requests) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    outputs = [
        json.loads(line)["result"]["content"][0]["text"] for line in result.stdout.splitlines()
    ]
    sent = spike.lines(log)
    assert outputs[0].encode() == outputs[1].encode()
    assert (
        sent[0]
        == sent[1]
        == {
            "size": 10240,
            "sha256": hashlib.sha256(outputs[0].encode()).hexdigest(),
        }
    )

import hashlib
import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest
from proof_common import (
    AGENT_SDK,
    NO_MODS,
    PLUGIN_DIR,
    claude_events,
    claude_isolated,
    codex_home,
    copy_hidden,
    foreign_plugins,
    held_port,
    hide,
    json_lines,
    new_state,
    nookku_servers,
)

from nookku import config, kit
from nookku.audit import audit
from nookku.mcp import SERVER
from nookku.record import Writer

# U+2028, U+2029 and U+0085, written as escapes.
SEPARATORS = "".join(chr(c) for c in (0x2028, 0x2029, 0x85))


def test_a_unicode_line_separator_in_a_string_does_not_cut_the_line() -> None:
    text = f"a toy shop reply {SEPARATORS} with 3 separators"
    out = json.dumps({"type": "agent_message", "text": text}, ensure_ascii=False)
    stdout = f"a log line\n{out}\r\n{{}}\n"
    assert len(stdout.splitlines()) > 3
    assert json_lines(stdout) == [{"type": "agent_message", "text": text}, {}]


def test_the_agent_sdk_is_pinned() -> None:
    assert AGENT_SDK.startswith("claude-agent-sdk==")


def _init(*paths: str) -> dict:
    plugins = [{"name": Path(p).name, "source": f"{Path(p).name}@x", "path": p} for p in paths]
    servers = [{"name": "nookku", "status": "connected"}]
    return {"type": "system", "subtype": "init", "plugins": plugins, "mcp_servers": servers}


def test_a_proof_session_reads_no_user_settings_and_no_user_mcp_server() -> None:
    hooks = claude_isolated(plugin=False)
    assert hooks[hooks.index("--setting-sources") + 1] == "project,local"
    assert "--strict-mcp-config" in hooks
    assert "--plugin-dir" not in hooks
    plugin = claude_isolated(plugin=True)
    assert plugin[plugin.index("--plugin-dir") + 1] == str(PLUGIN_DIR)
    assert f"--mcp-config={json.dumps(nookku_servers())}" in plugin
    # proof_evaluation.py approves the transcript tool by the name of SERVER.
    assert list(nookku_servers()["mcpServers"]) == [SERVER]


def test_only_built_in_plugins_and_the_plugin_of_this_checkout_are_expected() -> None:
    init = _init("builtin", str(PLUGIN_DIR), "/home/toy/.claude/mods/toy-mod")
    assert foreign_plugins(init) == ["toy-mod@x"]


def test_a_mod_stops_the_proof() -> None:
    out = json.dumps(_init("builtin", "/home/toy/.claude/mods/toy-mod"))
    with pytest.raises(SystemExit, match="toy-mod@x"):
        claude_events(out + "\n" + json.dumps({"type": "result", "result": "ok"}))


def test_each_claude_session_of_a_proof_gets_no_mod() -> None:
    # An empty CLAUDE_CODE_PLUGIN_DIRS loads no mod, also if the user settings name mods (#424).
    import proof_evaluation
    import proof_report

    assert NO_MODS == {"CLAUDE_CODE_PLUGIN_DIRS": ""}
    for env in (proof_evaluation.ENV, proof_report.ENV):
        assert env["CLAUDE_CODE_PLUGIN_DIRS"] == ""


def _fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: str) -> Path:
    """A codex command on PATH that prints the servers for `codex mcp list --json`, and a home."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "codex").write_text(f"#!/bin/sh\ncat <<'EOF'\n{servers}\nEOF\n")
    (bin_dir / "codex").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setattr("proof_common.HOOKS_CODEX_HOME", home)
    return home


def test_a_codex_home_with_only_the_nookku_server_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _fake_codex(tmp_path, monkeypatch, json.dumps([{"name": SERVER, "enabled": True}]))
    assert codex_home(False, tmp_path) == home
    _fake_codex(tmp_path / "none", monkeypatch, "[]")
    codex_home(False, tmp_path)


@pytest.mark.parametrize(
    "servers",
    [
        json.dumps([{"name": SERVER}, {"name": "toy_docs", "enabled": True}]),
        json.dumps([{"name": "toy_docs"}]),
        "not json",
        json.dumps({"name": SERVER}),
        json.dumps([{"enabled": True}]),
    ],
)
def test_a_user_mcp_server_or_a_bad_list_stops_a_codex_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: str
) -> None:
    # The text of a user MCP server can reach the model (#424).
    _fake_codex(tmp_path, monkeypatch, servers)
    with pytest.raises(SystemExit):
        codex_home(False, tmp_path)


def test_a_codex_proof_with_no_home_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("proof_common.HOOKS_CODEX_HOME", tmp_path / "missing")
    with pytest.raises(SystemExit, match="Trust the Codex hooks once"):
        codex_home(False, tmp_path)


def test_an_output_with_no_init_event_stops_the_proof() -> None:
    with pytest.raises(SystemExit, match="no init event"):
        claude_events(json.dumps({"type": "result", "result": "ok"}))


def test_the_result_and_the_plugins_of_a_clean_session() -> None:
    lines = [_init(str(PLUGIN_DIR), "builtin"), {"type": "result", "result": "ok"}]
    result, plugins = claude_events("\n".join(json.dumps(x) for x in lines))
    assert result["result"] == "ok"
    assert plugins == ["builtin@x", "nookku@x"]


def _stop_text(init: dict) -> str:
    with pytest.raises(SystemExit) as stopped:
        claude_events(json.dumps(init))
    return str(stopped.value)


def test_an_init_event_with_no_plugin_list_stops_the_proof() -> None:
    init = {"type": "system", "subtype": "init", "mcp_servers": []}
    assert _stop_text(init) == "the init event has no list of plugins"


def test_an_init_event_with_no_server_list_stops_the_proof() -> None:
    init = _init("builtin")
    del init["mcp_servers"]
    assert _stop_text(init) == "the init event has no list of MCP servers"


def test_an_init_event_with_a_server_that_is_not_an_object_stops_the_proof() -> None:
    init = _init("builtin")
    init["mcp_servers"] = ["nookku"]
    assert _stop_text(init) == (
        "an item of the MCP servers list of the init event is not an object: ['nookku']"
    )


def test_an_init_event_with_a_plugin_that_is_not_an_object_stops_the_proof() -> None:
    init = _init("builtin")
    init["plugins"].append("toy-mod")
    assert _stop_text(init) == (
        "an item of the plugins list of the init event is not an object: ['toy-mod']"
    )


# A toy page key and a toy cookie value. They are not secrets of a real page.
KEY = "toyKey0123456789toyKey0123456789toyKey01234"
COOKIE = "toyCookie0123456789toyCookie0123456789toyCo"


def test_a_secret_becomes_a_marker_with_its_sha256() -> None:
    digest = hashlib.sha256(KEY.encode()).hexdigest()
    assert hide(f"-H 'X-Nookku-Page: {KEY}' -d x", KEY) == (
        f"-H 'X-Nookku-Page: <secret removed, sha256 {digest}>' -d x"
    )
    # The detail of a blocked_call row can end in the first part of a secret.
    assert hide(f"-H 'X-Nookku-Page: {KEY[:20]}", KEY) == (
        f"-H 'X-Nookku-Page: <secret removed, sha256 {digest}>"
    )
    assert hide("no secret here", KEY) == "no secret here"


def test_the_copy_of_a_relay_record_hides_the_secrets_and_gives_the_same_audit(
    tmp_path: Path,
) -> None:
    tap, relay = tmp_path / "tap.jsonl", tmp_path / "relay.jsonl"
    rec = Writer(relay)
    rec.append({"type": "turn", "harness": "claude-code", "said": "hi", "shown": "hello"})
    detail = json.dumps({"command": f"curl -H 'Cookie: n={COOKIE}' -H 'X-Nookku-Page: {KEY}'"})
    rec.append({"type": "blocked_call", "harness": "claude-code", "tool": "Bash", "detail": detail})
    Writer(tap).append({"type": "exchange", "input": "hi", "status": 200, "reply": "hello"})
    out = tmp_path / "copy.jsonl"
    copy_hidden(relay, out, (COOKIE, KEY, ""))
    text = out.read_text(encoding="utf-8")
    assert COOKIE not in text and KEY not in text
    assert text.count("<secret removed, sha256 ") == 2
    # The turn line keeps its bytes, and the audit of the copy is the same.
    assert text.split("\n")[0] == relay.read_text(encoding="utf-8").split("\n")[0]
    assert audit(tap, out).as_dict() == audit(tap, relay).as_dict()


def test_an_mcp_server_of_the_user_stops_the_proof() -> None:
    init = _init("builtin")
    init["mcp_servers"].append({"name": "toy-memory", "status": "connected"})
    with pytest.raises(SystemExit, match="toy-memory"):
        claude_events(json.dumps(init))


def test_a_new_state_removes_the_old_config_and_the_old_mode_file(tmp_path: Path) -> None:
    # An earlier run stopped in relay mode, with a key that the next run does not give.
    kit.init(tmp_path, "plugin", {"page": False})
    kit.set_mode(tmp_path, True)
    new_state(tmp_path)
    kit.init(tmp_path, "plugin", {})
    assert not kit.is_on(tmp_path)
    assert config.read_config(tmp_path)["page"] is True


def test_a_held_port_takes_no_connection_and_lets_the_toy_shop_bind_it() -> None:
    with held_port() as port:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", port))
            server.listen()
            socket.create_connection(("127.0.0.1", port), timeout=1).close()

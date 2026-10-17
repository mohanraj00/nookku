import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest
from proof_common import (
    AGENT_SDK,
    NOOKKU_SERVERS,
    PLUGIN_DIR,
    claude_events,
    claude_isolated,
    foreign_plugins,
    json_lines,
)

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
    return {"type": "system", "subtype": "init", "plugins": plugins}


def test_a_proof_session_reads_no_user_settings_and_no_user_mcp_server() -> None:
    hooks = claude_isolated(plugin=False)
    assert hooks[hooks.index("--setting-sources") + 1] == "project,local"
    assert "--strict-mcp-config" in hooks
    assert "--plugin-dir" not in hooks
    plugin = claude_isolated(plugin=True)
    assert plugin[plugin.index("--plugin-dir") + 1] == str(PLUGIN_DIR)
    assert f"--mcp-config={json.dumps(NOOKKU_SERVERS)}" in plugin
    assert list(NOOKKU_SERVERS["mcpServers"]) == ["nookku"]


def test_only_built_in_plugins_and_the_plugin_of_this_checkout_are_expected() -> None:
    init = _init("builtin", str(PLUGIN_DIR), "/home/toy/.claude/mods/toy-mod")
    assert foreign_plugins(init) == ["toy-mod@x"]


def test_a_mod_stops_the_proof() -> None:
    out = json.dumps(_init("builtin", "/home/toy/.claude/mods/toy-mod"))
    with pytest.raises(SystemExit, match="toy-mod@x"):
        claude_events(out + "\n" + json.dumps({"type": "result", "result": "ok"}))


def test_an_output_with_no_init_event_stops_the_proof() -> None:
    with pytest.raises(SystemExit, match="no init event"):
        claude_events(json.dumps({"type": "result", "result": "ok"}))


def test_the_result_and_the_plugins_of_a_clean_session() -> None:
    lines = [_init(str(PLUGIN_DIR), "builtin"), {"type": "result", "result": "ok"}]
    result, plugins = claude_events("\n".join(json.dumps(x) for x in lines))
    assert result["result"] == "ok"
    assert plugins == ["builtin@x", "nookku@x"]

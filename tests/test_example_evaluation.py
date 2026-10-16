import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import example_evaluation as ex

from nookku import __version__, bridge, config
from nookku.record import Writer

ROOT = Path(__file__).resolve().parent.parent


def test_setup_configures_a_test_of_the_http_agent_with_no_evaluation(tmp_path: Path) -> None:
    ex.setup(tmp_path)
    data = config.read_config(tmp_path)
    assert data["evaluate"] is False and data["page"] is False
    assert data["entry"] == [sys.executable, str(tmp_path / "http_entry.py")]
    assert (tmp_path / ".nookku" / "mode").read_text() == "off\n"
    for name in ex.APP_FILES:
        assert (tmp_path / name).read_bytes() == (ex.EXAMPLE / name).read_bytes()


def test_the_result_comes_from_the_records_of_the_test_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOY_SHOP_PORT", str(ex.free_port()))
    ex.setup(tmp_path)
    cur = bridge.start(tmp_path)
    try:
        for said in ex.MESSAGES[:2]:
            shown, ok = bridge.send(cur, said)
            row = {"type": "turn", "harness": "claude-code", "said": said, "shown": shown}
            Writer(Path(cur["dir"]) / "relay.jsonl").append({**row, "ok": ok})
    finally:
        bridge.end(tmp_path)
    folder = Path(cur["dir"])
    answer = {"result": f"The agent at {tmp_path} loops.", "modelUsage": {"toy-model": {}}}
    result = ex.collect(folder, answer, [ex.TRANSCRIPT], tmp_path)
    assert (result["audit_exit"], result["turns"], result["test"]) == (0, 2, folder.name)
    assert [t["said"] for t in result["transcript"]] == ex.MESSAGES[:2]
    assert all(t["shown"].startswith("Which item") for t in result["transcript"])
    assert result["versions"]["nookku"] == __version__
    assert result["models"] == ["toy-model"]
    assert result["tools"] == ["mcp__nookku__transcript"]
    # The result names no local path.
    assert result["evaluation"] == "The agent at <project> loops."
    assert json.loads(json.dumps(result)) == result


def test_an_answer_that_quotes_an_instruction_file_stays_out(tmp_path: Path) -> None:
    words = re.findall(r"\w+", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    folder = tmp_path / "test"
    folder.mkdir()
    (folder / "audit.json").write_text('{"exit": 0, "turns": 0}')
    (folder / "manifest.json").write_text('{"versions": {"nookku": "0"}}')
    (folder / "relay.jsonl").write_text("")
    answer = {"result": "The rules say: " + " ".join(words[20:30])}
    assert ex.collect(folder, answer, [], tmp_path)["evaluation"] is None


def test_the_evaluation_gets_only_the_nookku_server_and_no_built_in_tool() -> None:
    flags = ex.WORDS_ONLY
    assert flags[:3] == ["--tools", "", "--strict-mcp-config"]
    servers = json.loads(flags[3].removeprefix("--mcp-config="))
    assert servers == {"mcpServers": {"nookku": {"command": "nookku", "args": ["mcp"]}}}
    assert flags[4] == "--allowedTools=mcp__nookku__transcript"
    denied = set(flags[5].removeprefix("--disallowedTools=").split(","))
    assert denied == {"mcp__nookku__status", "mcp__nookku__run_script"}

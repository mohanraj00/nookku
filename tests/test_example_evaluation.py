import json
import re
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import example_evaluation as ex

from nookku import __version__, bridge, config
from nookku.record import Writer

ROOT = Path(__file__).resolve().parent.parent
# A plugin of the init event that Claude Code itself holds.
BUILT_IN = [
    {"name": "cc-plugin-telemetry", "path": "builtin", "source": "cc-plugin-telemetry@builtin"}
]


def test_setup_configures_a_test_of_the_http_agent_with_no_evaluation(tmp_path: Path) -> None:
    ex.setup(tmp_path)
    data = config.read_config(tmp_path)
    assert data["evaluate"] is False and data["page"] is False
    assert data["entry"] == [sys.executable, str(tmp_path / "http_entry.py")]
    assert (tmp_path / ".nookku" / "mode").read_text() == "off\n"
    for name in ex.APP_FILES:
        assert (tmp_path / name).read_bytes() == (ex.EXAMPLE / name).read_bytes()


@contextmanager
def held_port() -> Iterator[int]:
    """Get a port from the OS, and keep it until the end of the block. The socket binds the
    wildcard address and does not listen, so the toy shop server can bind 127.0.0.1 on the same
    port. While the socket is open, the OS gives the port to no other process (#438)."""
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", 0))
        port: int = s.getsockname()[1]
        yield port


def test_the_result_comes_from_the_records_of_the_test_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ex.setup(tmp_path)
    with held_port() as port:
        monkeypatch.setenv("TOY_SHOP_PORT", str(port))
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
    result = ex.collect(folder, ex.Session(answer, [ex.TRANSCRIPT], BUILT_IN), tmp_path)
    assert (result["audit_exit"], result["turns"], result["test"]) == (0, 2, folder.name)
    assert [t["said"] for t in result["transcript"]] == ex.MESSAGES[:2]
    assert all(t["shown"].startswith("Which item") for t in result["transcript"])
    assert result["versions"]["nookku"] == __version__
    assert result["models"] == ["toy-model"]
    assert result["tools"] == ["mcp__nookku__transcript"]
    assert result["plugins"] == ["cc-plugin-telemetry@builtin"]
    # The result names no local path.
    assert result["evaluation"] == "The agent at <project> loops."
    assert json.loads(json.dumps(result)) == result


def a_folder(tmp_path: Path) -> Path:
    """A test folder with no turns."""
    folder = tmp_path / "test"
    folder.mkdir()
    (folder / "audit.json").write_text('{"exit": 0, "turns": 0}')
    (folder / "manifest.json").write_text('{"versions": {"nookku": "0"}}')
    (folder / "relay.jsonl").write_text("")
    return folder


def test_an_answer_that_quotes_an_instruction_file_stays_out(tmp_path: Path) -> None:
    words = re.findall(r"\w+", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    answer = {"result": "The rules say: " + " ".join(words[20:30])}
    session = ex.Session(answer, [ex.TRANSCRIPT], BUILT_IN)
    assert ex.collect(a_folder(tmp_path), session, tmp_path)["evaluation"] is None


def test_the_evaluation_gets_only_the_nookku_server_and_no_user_setting() -> None:
    flags = ex.WORDS_ONLY
    assert flags[:2] == ["--setting-sources", "project,local"]
    assert json.loads(flags[2].removeprefix("--settings=")) == {"disableAllHooks": True}
    assert flags[3:6] == ["--tools", "", "--strict-mcp-config"]
    servers = json.loads(flags[6].removeprefix("--mcp-config="))
    assert servers == {"mcpServers": {"nookku": {"command": "nookku", "args": ["mcp"]}}}
    assert flags[7] == "--allowedTools=mcp__nookku__transcript"
    denied = set(flags[8].removeprefix("--disallowedTools=").split(","))
    assert denied == {"mcp__nookku__status", "mcp__nookku__run_script"}
    assert len(flags) == 9


MOD = {"name": "toy-mod", "path": "/home/tester/.claude/mods/toy-mod", "source": "toy-mod@inline"}


@pytest.mark.parametrize(
    "tools, plugins, why",
    [
        ([ex.TRANSCRIPT, "mcp__toy_shop__orders"], BUILT_IN, "the tools"),
        ([], [], "the tools"),
        ([ex.TRANSCRIPT], [], "names no plugins"),
        ([ex.TRANSCRIPT], [*BUILT_IN, MOD], "toy-mod@inline"),
    ],
)
def test_a_session_with_other_tools_or_plugins_writes_no_result(
    tmp_path: Path, tools: list[str], plugins: list[dict[str, str]], why: str
) -> None:
    out = tmp_path / "evaluation.json"
    session = ex.Session({"result": "The agent loops."}, tools, plugins)
    problem = ex.problem(session)
    assert problem is not None and why in problem
    assert ex.finish(a_folder(tmp_path), session, tmp_path, out) == 1
    assert not out.exists()


def test_a_clean_session_writes_the_result(tmp_path: Path) -> None:
    out = tmp_path / "evaluation.json"
    session = ex.Session({"result": "The agent loops."}, [ex.TRANSCRIPT], BUILT_IN)
    assert ex.problem(session) is None
    ex.finish(a_folder(tmp_path), session, tmp_path, out)
    assert json.loads(out.read_text())["evaluation"] == "The agent loops."

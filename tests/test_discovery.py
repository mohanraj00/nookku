"""Egress discovery (SPEC.md section 7.11): the answer rule, the pending answer, and the start
that stops with no answer."""

import io
import json
import sys
import time
from pathlib import Path

import pytest

from nookku import bridge, discovery, kit, replay, state
from nookku.cli import main
from nookku.config import ConfigError, read_config

pytestmark = pytest.mark.real_discovery

ROOT = Path(__file__).resolve().parent.parent
CASES = sorted((ROOT / "conformance" / "discovery").glob("*.json"))
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
EMPTY = {kind: [] for kind in discovery.LISTS}
STOCK = {"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9"}


def project(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    return root


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_the_rule_gives_each_conformance_result(case: Path) -> None:
    data = json.loads(case.read_text(encoding="utf-8"))
    expect = data["expect"]
    if "error" in expect:
        with pytest.raises(discovery.AnswerError) as e:
            discovery.parse(data["answer"])
        assert str(e.value) == expect["error"]
        return
    answer = discovery.parse(data["answer"])
    assert discovery.lines(answer) == expect["lines"]
    assert discovery.unseen(answer) == expect["unseen"]


def test_a_registered_answer_is_pending_only_while_it_is_fresh(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert discovery.pending(root) is None
    data = discovery.register(root, {**EMPTY, "backends": [STOCK]}, now=1000.0)
    assert data["answer"]["backends"] == [STOCK]
    assert discovery.pending(root, now=1000.0 + discovery.FRESH) == data
    assert discovery.pending(root, now=1001.0 + discovery.FRESH) is None
    # A time before the answer is not fresh: the clock or the file is wrong.
    assert discovery.pending(root, now=999.0) is None


def test_a_pending_file_that_breaks_the_rule_is_no_answer(tmp_path: Path) -> None:
    root = project(tmp_path)
    for data in (
        "not json",
        json.dumps({"v": 1, "registered": time.time(), "answer": {**EMPTY, "other": [{}]}}),
        json.dumps({"v": 2, "registered": time.time(), "answer": EMPTY}),
        json.dumps({"v": 1, "registered": True, "answer": EMPTY}),
    ):
        discovery.path(root).write_text(data)
        assert discovery.pending(root) is None


def test_a_refused_answer_writes_nothing(tmp_path: Path) -> None:
    root = project(tmp_path)
    with pytest.raises(discovery.AnswerError):
        discovery.register(root, {**EMPTY, "backends": [{**STOCK, "url": "http://a:b@h"}]})
    assert not discovery.path(root).exists()


def test_with_no_answer_no_test_starts_and_no_relay_starts(tmp_path: Path) -> None:
    root = project(tmp_path)
    with pytest.raises(bridge.BridgeError) as e:
        bridge.start(root)
    assert str(e.value) == discovery.no_answer()
    assert state.current(root) is None
    assert not (root / ".nookku" / "tests").exists()
    assert not kit.is_on(root)


def test_the_shell_start_and_check_stop_with_no_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    for command in ("start", "check"):
        assert main([command, "--root", str(root)]) == 1
        assert discovery.no_answer() in capsys.readouterr().out
    assert state.current(root) is None
    assert not kit.is_on(root)


def test_the_start_prompt_with_no_answer_sends_the_task_and_starts_nothing(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "nookku start", "session_id": "t"}
    out = kit.handle(event, root, "claude-code")
    assert out is not None
    context = out["hookSpecificOutput"]["additionalContext"]
    assert context.startswith(kit.DISCOVERY_TEXT)
    assert "nookku register" in context
    assert str(root) in context
    assert state.current(root) is None
    assert not kit.is_on(root)


def test_the_start_prompt_with_no_entry_gives_the_entry_refusal(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / ".nookku" / "config.json").write_text('{"entry": []}')
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "nookku start"}
    out = kit.handle(event, root, "claude-code")
    assert out is not None and out.get("decision") == "block"
    assert "has no 'entry' command" in out["reason"]


def test_a_start_takes_the_answer_into_the_manifest_and_removes_it(tmp_path: Path) -> None:
    root = project(tmp_path)
    answer = {
        **EMPTY,
        "backends": [STOCK],
        "databases": [{"name": "shop", "kind": "postgres", "env": "DATABASE_URL", "address": None}],
    }
    registered = discovery.register(root, answer)["registered"]
    text = kit.start_test(root, "t")
    try:
        cur = state.current(root)
        assert cur is not None
        manifest = json.loads((Path(cur["dir"]) / "manifest.json").read_text())
        egress = manifest["egress"]
        assert egress["registered"] == registered
        assert egress["answer"] == discovery.parse(answer)
        assert egress["unseen"] == ["shop"]
        assert set(egress["proxies"]) == {"stock"}
        assert egress["receiver"].startswith("http://127.0.0.1:")
        assert not (Path(cur["dir"]) / bridge.EGRESS_FILE).exists()
        assert not discovery.path(root).exists()
        assert "- backend stock: STOCK_URL -> http://127.0.0.1:9 (proxy)" in text
        assert "- database shop: postgres, DATABASE_URL (no proxy)" in text
    finally:
        bridge.end(root)
    # The next test needs a new answer.
    with pytest.raises(bridge.BridgeError):
        bridge.start(root)


def test_a_replay_uses_the_answer_of_its_old_test(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    answer = {**EMPTY, "backends": [STOCK]}
    manifest = {"egress": {"registered": 5.0, "answer": answer, "unseen": [], "proxies": {}}}
    (old / "manifest.json").write_text(json.dumps(manifest))
    assert replay.egress(old) == {"registered": 5.0, "answer": discovery.parse(answer)}
    (old / "manifest.json").write_text(json.dumps({"egress": {"answer": {"backends": []}}}))
    assert replay.egress(old) is None
    assert replay.egress(None) is None


def test_register_reads_stdin_and_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({**EMPTY, "backends": [STOCK]})))
    assert main(["register", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "- backend stock: STOCK_URL -> http://127.0.0.1:9 (proxy)" in out
    assert "nookku start" in out
    file = tmp_path / "answer.json"
    file.write_text(json.dumps({**EMPTY, "model_apis": [{"api": "toy"}]}))
    assert main(["register", "--root", str(root), "--file", str(file), "--json"]) == 1
    assert "nothing was written" in json.loads(capsys.readouterr().out)["error"]
    # The refused answer did not replace the registered answer.
    pending = discovery.pending(root)
    assert pending is not None and pending["answer"]["backends"] == [STOCK]


@pytest.mark.parametrize("key", ["backends", "model_api"])
def test_the_old_config_keys_give_one_clear_error(tmp_path: Path, key: str) -> None:
    root = project(tmp_path)
    conf = json.loads((root / ".nookku" / "config.json").read_text())
    (root / ".nookku" / "config.json").write_text(json.dumps({**conf, key: []}))
    with pytest.raises(ConfigError) as e:
        read_config(root)
    assert str(e.value) == (
        f".nookku/config.json has the keys ['{key}'] of nookku 0.5.1 and earlier. Nookku now "
        "finds the egress of the agent at each start (SPEC.md section 7.11). Remove the keys."
    )


def test_a_check_keeps_the_answer_for_the_next_start(tmp_path: Path) -> None:
    root = project(tmp_path)
    discovery.register(root, {**EMPTY, "backends": [STOCK]})
    passed, lines = bridge.check(root)
    assert passed, lines
    pending = discovery.pending(root)
    assert pending is not None and pending["answer"]["backends"] == [STOCK]


def test_the_guard_lets_the_model_register_and_protects_the_answer_during_a_test(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    def tool(name: str, tool_input: dict) -> dict | None:
        event = {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input}
        return kit.handle(event, root, "claude-code")

    register = {"command": "nookku register <<'EOF'\n" + json.dumps(EMPTY) + "\nEOF"}
    write = {"file_path": str(discovery.path(root)), "content": json.dumps(EMPTY)}
    assert tool("Bash", register) is None
    discovery.register(root, EMPTY)
    kit.start_test(root, "t")
    try:
        answer = tool("Write", write)
        assert answer is not None
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    finally:
        bridge.end(root)


def test_a_command_with_a_secret_value_is_refused() -> None:
    def part(*command: str) -> dict:
        server = {"name": "stock", "transport": "stdio", "env": None, "url": None}
        return {**server, "command": ["toy-stock-mcp", *command]}

    for command in (
        ["--token", "x"],
        ["--api-key=x"],
        ["password=x"],
        ["-secret", "x"],
        ["-c", "server --token x"],
        ["-c", "TOKEN=x server 'a"],
    ):
        with pytest.raises(discovery.AnswerError, match="secret key"):
            discovery.parse(discovery.make(mcp_servers=[part(*command)]))
    for command in (
        ["--token"],
        ["--verbose", "x"],
        ["--token="],
        ["mode=fast"],
        ["-c", "server --verbose"],
    ):
        discovery.parse(discovery.make(mcp_servers=[part(*command)]))

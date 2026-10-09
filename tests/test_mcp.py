"""`nookku mcp`: the JSON-RPC messages, the pages of the transcript and their bounds (#215)."""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

import pytest

from nookku import kit, mcp
from nookku.record import Writer


def rpc(root: Path, method: str, params: dict | None = None, rid: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    answer = mcp.answer(root, message)
    assert answer is not None and answer["id"] == rid
    return answer


def relay(root: Path, turns: list[tuple[str, str]]) -> None:
    record = root / ".nookku" / "relay.jsonl"
    record.parent.mkdir(parents=True, exist_ok=True)
    for said, shown in turns:
        Writer(record).append(
            {"type": "turn", "harness": "codex", "said": said, "shown": shown, "ok": True}
        )


def test_initialize_names_the_server_and_keeps_the_protocol_version(tmp_path: Path) -> None:
    result = rpc(tmp_path, "initialize", {"protocolVersion": "2025-03-26"})["result"]
    assert result["protocolVersion"] == "2025-03-26"
    future = rpc(tmp_path, "initialize", {"protocolVersion": "2099-01-01"})["result"]
    assert future["protocolVersion"] == mcp.PROTOCOL
    assert result["serverInfo"]["name"] == "nookku"
    assert result["capabilities"] == {"tools": {}}


def test_tools_list_gives_the_read_only_tools(tmp_path: Path) -> None:
    tools = rpc(tmp_path, "tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == ["transcript", "status"]
    assert all(t["description"].startswith("Read-only.") for t in tools)


def test_a_notification_gets_no_answer_and_errors_have_codes(tmp_path: Path) -> None:
    assert mcp.answer(tmp_path, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(tmp_path, "no/such")["error"]["code"] == -32601
    assert mcp.answer(tmp_path, [1])["error"]["code"] == -32600  # type: ignore[index]


def test_the_transcript_is_the_cli_text_in_pages_that_join_to_it(tmp_path: Path) -> None:
    turns = [(f"message {n} {'é' * n}", "reply " * 200 + "日本語 " * 50) for n in range(12)]
    relay(tmp_path, turns)
    whole = kit.transcript_text(tmp_path)
    joined, number, count = "", 1, None
    while True:
        result = rpc(tmp_path, "tools/call", {"name": "transcript", "arguments": {"page": number}})
        assert "structuredContent" not in result["result"]
        text = result["result"]["content"][0]["text"]
        assert (text, mcp.page(whole, number, mcp.PAGE_TOKENS)[0]) == (text, text)
        facts = mcp.page(whole, number, mcp.PAGE_TOKENS)[1]
        body, footer = text.rsplit("\n──── nookku: end of page", 1)
        assert facts["sha256"] == hashlib.sha256(body.encode()).hexdigest()
        assert facts["sha256"] in footer
        assert mcp.estimate_tokens(text) <= mcp.PAGE_TOKENS
        count = facts["pages"]
        joined += body
        if number == count:
            assert "This is the last page." in footer
            break
        assert f"call transcript with page {number + 1}" in footer
        number += 1
    assert count and count > 1
    assert joined == whole


def test_a_line_longer_than_a_page_is_cut_between_characters() -> None:
    text = "x" * 1000 + "\n" + "😀" * 300
    bounds = mcp.pages(text, 100)
    assert "".join(text[a:b] for a, b in bounds) == text
    assert all(mcp.estimate_tokens(text[a:b]) <= 100 for a, b in bounds)


def test_the_estimate_counts_dense_text_higher_than_english() -> None:
    english = "the agent answered the question " * 10
    assert mcp.estimate_tokens(english) == len(english) / 4
    assert mcp.estimate_tokens('{"a":[1,2]}') > len('{"a":[1,2]}') / 4
    assert mcp.estimate_tokens("日本") == 2
    assert mcp.estimate_tokens("😀") == 2


@pytest.mark.parametrize(
    "arguments",
    [
        {"page": 99},
        {"page": "1"},
        {"page_tokens": 10},
        {"trace": True},
        {"test": 7},
        {"test": "../x"},
        {"test": "..\\..\\x"},
        {"test": "C:\\other\\test"},
        {"test": "/tmp/x"},
        {"test": "a/../../x", "trace": True},
    ],
)
def test_a_wrong_call_is_an_error_result(tmp_path: Path, arguments: dict) -> None:
    relay(tmp_path, [("hi", "hello")])
    result = rpc(tmp_path, "tools/call", {"name": "transcript", "arguments": arguments})
    assert result["result"]["isError"] is True
    assert result["result"]["content"][0]["text"].startswith("nookku: ")


def test_status_says_if_relay_mode_is_on(tmp_path: Path) -> None:
    kit.set_mode(tmp_path, True)
    result = rpc(tmp_path, "tools/call", {"name": "status", "arguments": {}})["result"]
    assert result["content"][0]["text"] == "nookku: relay mode is on."
    assert "relay mode is on" in result["content"][0]["text"]


def test_serve_answers_each_line_in_ascii_json(tmp_path: Path) -> None:
    relay(tmp_path, [("bonjour", "réponse")])
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "not json",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "transcript", "arguments": {}},
            }
        ),
    ]
    out = io.StringIO()
    assert mcp.serve(tmp_path, io.StringIO("\n".join(lines) + "\n"), out) == 0
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [a.get("id") for a in answers] == [1, None, 2]
    assert answers[1]["error"]["code"] == -32700
    assert out.getvalue().isascii()
    assert "réponse" in answers[2]["result"]["content"][0]["text"]
    assert re.search(r"end of page 1 of 1\.", answers[2]["result"]["content"][0]["text"])


@pytest.mark.parametrize("limit", [100, 300, 2000])
def test_a_page_with_its_footer_stays_in_the_bound(limit: int) -> None:
    text = "".join(f'line {n} 日本語 {{"a": [1, 2]}}\n' for n in range(500))
    count = len(mcp.pages(text, limit - mcp.FOOTER_TOKENS))
    for number in range(1, count + 1):
        assert mcp.estimate_tokens(mcp.page(text, number, limit)[0]) <= limit


def test_the_server_moves_the_old_state_folder_of_its_default_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nookku.cli import main
    from nookku.config import OLD_STATE_DIR, STATE_DIR

    (tmp_path / OLD_STATE_DIR).mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["mcp"]) == 0
    assert (tmp_path / STATE_DIR).is_dir() and not (tmp_path / OLD_STATE_DIR).exists()


@pytest.mark.parametrize("trace", [True, False])
def test_a_link_in_the_tests_folder_does_not_reach_another_folder(
    tmp_path: Path, trace: bool
) -> None:
    other = tmp_path / "other" / "20261009-120000-aaaa"
    other.mkdir(parents=True)
    (other / "relay.jsonl").write_text("")
    project = tmp_path / "project"
    tests = project / kit.STATE_DIR / "tests"
    tests.mkdir(parents=True)
    (project / kit.STATE_DIR / "config.json").write_text('{"entry": ["python3", "a.py"]}')
    (tests / "20261009-130000-bbbb").symlink_to(other, target_is_directory=True)
    arguments = {"trace": True} if trace else {}
    result = rpc(project, "tools/call", {"name": "transcript", "arguments": arguments})["result"]
    assert result["isError"] is True
    assert "is not a test id" in result["content"][0]["text"]

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from toy_agent import ToyAgent, shop_reply

from verbatim_relay.adapters import make
from verbatim_relay.record import Exchange, Unparsed, read_tap
from verbatim_relay.tap import Tap, start_in_thread

TRICKY = "Hi, I want to return order #4471.  \n\nÜnïcödé € ₹\t| a | b |\n"


@pytest.fixture
def agent():
    server = ToyAgent()
    yield server
    server.shutdown()


def run_tap(agent_url: str, record: Path, adapter: str = "json") -> Tap:
    tap = Tap(("127.0.0.1", 0), agent_url, record, make(adapter))
    start_in_thread(tap)
    return tap


def post(tap: Tap, path: str, body: bytes, headers: dict | None = None):
    url = f"http://127.0.0.1:{tap.server_address[1]}{path}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def test_the_request_and_response_bytes_pass_unchanged(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl")
    body = json.dumps({"text": TRICKY, "extra": [1, 2]}, ensure_ascii=False).encode()
    status, headers, out = post(tap, "/chat?x=1", body, {"Accept-Encoding": "gzip"})
    tap.shutdown()

    assert status == 200 and headers["X-Toy"] == "yes"
    sent = agent.received[0]
    assert sent["body"] == body and sent["path"] == "/chat?x=1"
    assert sent["headers"]["Accept-Encoding"] == "identity"
    assert json.loads(out)["reply"] == shop_reply(TRICKY)
    rows = read_tap(tmp_path / "tap.jsonl")
    assert rows == [Exchange(1, TRICKY, 200, shop_reply(TRICKY))]


def test_the_agent_base_path_is_kept(agent, tmp_path):
    tap = run_tap(agent.url + "/api/", tmp_path / "tap.jsonl")
    post(tap, "/chat", b'{"text": "hi"}')
    tap.shutdown()
    assert agent.received[0]["path"] == "/api/chat"


def test_openai_adapter(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    body = {
        "model": "toy",
        "messages": [
            {"role": "system", "content": "Be a shop."},
            {"role": "user", "content": TRICKY},
        ],
    }
    status, _, _ = post(tap, "/v1/chat/completions", json.dumps(body).encode())
    tap.shutdown()
    assert status == 200
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, TRICKY, 200, shop_reply(TRICKY))]


def test_openai_stream_is_refused_and_not_forwarded(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    body = {"stream": True, "messages": [{"role": "user", "content": "hi"}]}
    status, _, _ = post(tap, "/v1/chat/completions", json.dumps(body).encode())
    tap.shutdown()
    assert status == 501 and agent.received == []


def test_an_agent_error_is_forwarded_and_recorded(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl")
    status, _, out = post(tap, "/fail", b'{"text": "hi"}')
    tap.shutdown()
    assert (status, out) == (500, b'{"error": "boom"}')
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, "hi", 500, None)]


def test_an_unreachable_agent_gives_502_and_a_row(tmp_path):
    tap = run_tap("http://127.0.0.1:9", tmp_path / "tap.jsonl")
    status, _, _ = post(tap, "/", b'{"text": "hi"}')
    tap.shutdown()
    assert status == 502
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, "hi", None, None)]


def test_a_body_the_adapter_cannot_parse_is_forwarded_and_marked(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl")
    status, _, out = post(tap, "/not-json", b'{"text": "hi"}')
    post(tap, "/", b'{"message": "hi"}')
    tap.shutdown()
    assert (status, out) == (200, b"plain text")
    rows = read_tap(tmp_path / "tap.jsonl")
    assert [type(r) for r in rows] == [Unparsed, Unparsed]
    assert "response" in rows[0].error and "request" in rows[1].error


def test_a_reply_with_a_lone_surrogate_is_an_error_row(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl")
    status, _, out = post(tap, "/cut", b'{"text": "hi"}')
    tap.shutdown()
    assert status == 502 and b"lone surrogate U+D83D" in out
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, "hi", None, None)]
    row = json.loads((tmp_path / "tap.jsonl").read_text())
    assert row["error"] == "the agent reply has a lone surrogate U+D83D at character 21"


def test_a_message_with_a_lone_surrogate_is_forwarded_and_marked(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl")
    body = b'{"text": "hi \\ud83d"}'
    status, _, _ = post(tap, "/cut", body)
    tap.shutdown()
    assert status == 200 and agent.received[0]["body"] == body
    rows = read_tap(tmp_path / "tap.jsonl")
    assert [type(r) for r in rows] == [Unparsed]
    assert "lone surrogate U+D83D" in rows[0].error


def test_a_get_is_forwarded_without_a_row(agent, tmp_path):
    tap = run_tap(agent.url, tmp_path / "tap.jsonl")
    url = f"http://127.0.0.1:{tap.server_address[1]}/health"
    with urllib.request.urlopen(url, timeout=10) as resp:
        assert resp.read() == b"ok"
    tap.shutdown()
    assert not (tmp_path / "tap.jsonl").exists()


def test_the_agent_url_must_be_http(tmp_path):
    with pytest.raises(ValueError):
        Tap(("127.0.0.1", 0), "ftp://x", tmp_path / "t.jsonl", make("json"))

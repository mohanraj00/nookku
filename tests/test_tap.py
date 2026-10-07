import hashlib
import http.client
import json
import socket
import threading
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


def stream_post(tap: Tap, path: str, message: str) -> tuple[int, str, bytes, str | None]:
    """POST an openai request with stream: true. Return the status, the Content-Type, the body
    bytes, and the read error or None."""
    body = {"stream": True, "messages": [{"role": "user", "content": message}]}
    conn = http.client.HTTPConnection("127.0.0.1", tap.server_address[1], timeout=10)
    conn.request("POST", path, json.dumps(body, ensure_ascii=False).encode())
    resp = conn.getresponse()
    error = None
    try:
        out = resp.read()
    except http.client.IncompleteRead as e:
        out, error = e.partial, type(e).__name__
    conn.close()
    return resp.status, resp.getheader("Content-Type") or "", out, error


def raw_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x]


def test_a_stream_passes_unchanged_and_the_row_has_the_joined_reply(tmp_path):
    agent = ToyAgent(stream=True)
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    status, kind, out, error = stream_post(tap, "/v1/chat/completions", TRICKY)
    tap.shutdown()
    agent.shutdown()

    assert (status, kind, error) == (200, "text/event-stream; charset=utf-8", None)
    assert json.loads(agent.received[0]["body"])["stream"] is True
    assert out == agent.sent[0]
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, TRICKY, 200, shop_reply(TRICKY))]
    [row] = raw_rows(tmp_path / "tap.jsonl")
    assert row["stream"] == {"sha256": hashlib.sha256(out).hexdigest(), "bytes": len(out)}
    assert "error" not in row


def test_each_part_of_a_stream_reaches_the_caller_before_the_stream_ends(tmp_path):
    gate = threading.Event()
    agent = ToyAgent(stream=True, gate=gate)
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    body = {"messages": [{"role": "user", "content": "hi"}]}
    conn = http.client.HTTPConnection("127.0.0.1", tap.server_address[1], timeout=10)
    conn.request("POST", "/v1/chat/completions", json.dumps(body).encode())
    resp = conn.getresponse()
    early = b""
    while early.count(b"\n\n") < 3:
        early += resp.read1(65536)
    # The agent waits for the gate. The tap has no row yet.
    assert not (tmp_path / "tap.jsonl").exists()
    gate.set()
    out = early + resp.read()
    conn.close()
    tap.shutdown()
    agent.shutdown()
    assert out == agent.sent[0]
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, "hi", 200, shop_reply("hi"))]


@pytest.mark.parametrize(
    "fault, error, read_error",
    [
        ("cut", "the stream ended before data: [DONE]", None),
        ("error-event", "the agent sent an error: ", None),
        ("bad-chunk", "a chunk is not JSON", None),
        ("drop", "the stream from the agent stopped after", "IncompleteRead"),
    ],
)
def test_a_failed_stream_is_an_error_exchange_with_no_reply(tmp_path, fault, error, read_error):
    agent = ToyAgent(stream=True)
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    status, _, out, got_error = stream_post(tap, f"/{fault}/chat/completions", TRICKY)
    tap.shutdown()
    agent.shutdown()

    assert (status, got_error) == (200, read_error)
    assert out == agent.sent[0]
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, TRICKY, 200, None)]
    [row] = raw_rows(tmp_path / "tap.jsonl")
    assert row["error"].startswith(error)
    assert row["stream"] == {"sha256": hashlib.sha256(out).hexdigest(), "bytes": len(out)}


def test_the_json_adapter_marks_a_stream_unparsed(tmp_path):
    agent = ToyAgent(stream=True)
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "json")
    body = json.dumps({"text": "hi", "messages": [{"role": "user", "content": "hi"}]}).encode()
    status, _, out = post(tap, "/v1/chat/completions", body)
    tap.shutdown()
    agent.shutdown()
    assert (status, out) == (200, agent.sent[0])
    [row] = read_tap(tmp_path / "tap.jsonl")
    assert isinstance(row, Unparsed) and "does not read a streamed response" in row.error


def test_a_record_error_during_a_stream_sends_no_second_status_and_no_second_row(tmp_path, capsys):
    agent = ToyAgent(stream=True)
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    write = tap.writer.append
    calls: list[dict] = []

    def fail_once(row: dict) -> None:
        # The first write fails, as with a full disk. A later write goes to the record.
        calls.append(row)
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        write(row)

    tap.writer.append = fail_once  # type: ignore[method-assign]
    body = json.dumps({"stream": True, "messages": [{"role": "user", "content": "hi"}]})
    request = (
        f"POST /v1/chat/completions HTTP/1.1\r\nHost: toy\r\nContent-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n" + body
    )
    with socket.create_connection(("127.0.0.1", tap.server_address[1]), timeout=10) as sock:
        sock.sendall(request.encode())
        raw = b""
        while part := sock.recv(65536):
            raw += part
    tap.shutdown()
    agent.shutdown()

    head, _, chunked = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200 ") and raw.count(b"HTTP/1.1 ") == 1
    assert b"Transfer-Encoding: chunked" in head and not chunked.endswith(b"0\r\n\r\n")
    assert len(calls) == 1 and not (tmp_path / "tap.jsonl").exists()
    assert "cannot write the record: [Errno 28] No space left on device" in capsys.readouterr().err


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

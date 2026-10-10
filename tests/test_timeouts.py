"""The timeouts on the relay path, in order: agent < tap answer < relay < hook deadline."""

import contextlib
import inspect
import json
import socket
import threading
import time
from pathlib import Path

import pytest
from test_tap import post
from toy_agent import ToyAgent

from nookku import bridge, kit, stdio, tap
from nookku.adapters import make
from nookku.record import Exchange, read_tap

ROOT = Path(__file__).resolve().parent.parent
# The most time that a tap needs after the agent timeout to write its row and answer.
ANSWER = 5.0


@pytest.fixture
def agent():
    server = ToyAgent()
    yield server
    server.release.set()
    server.shutdown()


def test_each_timeout_ends_before_the_next_one() -> None:
    # One constant sets the agent timeout of both taps.
    assert inspect.signature(tap.Tap).parameters["timeout"].default == stdio.TIMEOUT
    assert inspect.signature(stdio.Agent).parameters["timeout"].default == stdio.TIMEOUT
    answer = stdio.TIMEOUT + ANSWER
    relay = [kit.TIMEOUT, bridge.TIMEOUT]
    assert stdio.TIMEOUT < answer < min(relay)
    assert max(relay) < kit.HOOK_DEADLINE


def test_a_slow_agent_gives_504_and_an_error_row(agent, tmp_path):
    timeout = 0.3
    t = tap.Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("json"), timeout)
    tap.start_in_thread(t)
    began = time.monotonic()
    status, _, out = post(t, "/slow", b'{"text": "Where is my mug?"}')
    took = time.monotonic() - began
    agent.release.set()
    t.shutdown()

    assert status == 504
    assert json.loads(out)["error"] == "nookku tap: the agent sent no response in 0.3 s"
    assert timeout <= took < timeout + ANSWER
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, "Where is my mug?", None, None)]
    row = json.loads((tmp_path / "tap.jsonl").read_text())
    assert row["error"] == "the agent sent no response in 0.3 s"


def test_an_agent_that_sends_a_byte_at_a_time_still_gives_504(tmp_path):
    # Each gap is shorter than the timeout, but the whole response takes longer.
    listener = socket.create_server(("127.0.0.1", 0))

    def trickle() -> None:
        conn, _ = listener.accept()
        with conn:
            conn.recv(65536)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 40\r\n\r\n")
            with contextlib.suppress(OSError):
                for _ in range(40):
                    time.sleep(0.1)
                    conn.sendall(b"x")

    threading.Thread(target=trickle, daemon=True).start()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    t = tap.Tap(("127.0.0.1", 0), url, tmp_path / "tap.jsonl", make("json"), 0.5)
    tap.start_in_thread(t)
    began = time.monotonic()
    status, _, out = post(t, "/", b'{"text": "Where is my mug?"}')
    took = time.monotonic() - began
    t.shutdown()
    listener.close()

    assert status == 504
    assert json.loads(out)["error"] == "nookku tap: the agent sent no response in 0.5 s"
    assert 0.5 <= took < 0.5 + ANSWER
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, "Where is my mug?", None, None)]


def test_a_stream_that_runs_past_the_deadline_is_not_a_full_reply(tmp_path):
    # The agent streams parts with no end. The tap stops the read at the deadline, and the row
    # has no reply.
    listener = socket.create_server(("127.0.0.1", 0))

    def stream() -> None:
        conn, _ = listener.accept()
        with conn:
            conn.recv(65536)
            head = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            conn.sendall(head + b"Transfer-Encoding: chunked\r\n\r\n")
            part = b'data: {"choices": [{"index": 0, "delta": {"content": "mug "}}]}\n\n'
            with contextlib.suppress(OSError):
                for _ in range(40):
                    conn.sendall(b"%x\r\n%s\r\n" % (len(part), part))
                    time.sleep(0.1)

    threading.Thread(target=stream, daemon=True).start()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    t = tap.Tap(("127.0.0.1", 0), url, tmp_path / "tap.jsonl", make("openai"), 0.5)
    tap.start_in_thread(t)
    body = json.dumps({"messages": [{"role": "user", "content": "Where is my mug?"}]}).encode()
    began = time.monotonic()
    with contextlib.suppress(Exception):
        post(t, "/v1/chat/completions", body)
    took = time.monotonic() - began
    t.shutdown()
    listener.close()

    assert took < 0.5 + ANSWER
    row = json.loads((tmp_path / "tap.jsonl").read_text())
    assert (row["status"], row["reply"]) == (200, None)
    assert row["error"] == "the agent sent no full response in 0.5 s"

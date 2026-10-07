"""A toy shop agent for the tests. It keeps every request it receives, byte for byte."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal


def shop_reply(text: str) -> str:
    return f"## Toy shop  \nYou wrote: «{text}»\n\n| item | price |\n|---|---|\n| mug | € 8 |\n"


def _event(data: Any) -> bytes:
    return b"data: " + json.dumps(data, ensure_ascii=False).encode() + b"\n\n"


def _chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    choice = {"index": 0, "delta": delta, "finish_reason": finish}
    return {"id": "toy-1", "object": "chat.completion.chunk", "choices": [choice]}


def stream_events(reply: str, size: int = 7) -> list[bytes]:
    """The events of an OpenAI-style stream of the reply, with `size` characters in each part."""
    out = [b": the toy shop streams\n\n", _event(_chunk({"role": "assistant", "content": ""}))]
    out += [_event(_chunk({"content": reply[i : i + size]})) for i in range(0, len(reply), size)]
    usage = {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": 42}
    out += [_event(_chunk({}, "stop")), _event({"id": "toy-1", "choices": [], "usage": usage})]
    return [*out, b"data: [DONE]\n\n"]


# A path part that makes a stream fail, and what the stream then holds.
STREAM_FAULTS = {
    "/cut/": lambda events: events[: len(events) // 2],
    "/error-event/": lambda events: [
        *events[:3],
        _event({"error": {"message": "the stock service is down", "type": "server_error"}}),
        events[-1],
    ],
    "/bad-chunk/": lambda events: [*events[:3], b'data: {"choices": [{"delta": {"con\n\n'],
}


class ToyAgent(ThreadingHTTPServer):
    """With stream=True, each /chat/completions reply is an SSE stream, also for stream: false.

    With stream="on_request", a /chat/completions reply is a stream only if the request has
    "stream": true, as an OpenAI-compatible API does. With a gate, the stream waits after its
    first content part until the gate is set.
    """

    daemon_threads = True

    def __init__(
        self, stream: bool | Literal["on_request"] = False, gate: threading.Event | None = None
    ) -> None:
        self.received: list[dict[str, Any]] = []
        self.sent: list[bytes] = []
        self.stream, self.gate = stream, gate
        super().__init__(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: ToyAgent

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("X-Toy", "yes")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, reply: str) -> None:
        """Send the events one at a time. The end of the connection ends the body (HTTP/1.0).

        On a path with /drop/, the Content-Length is 10 bytes more than the body.
        """
        events = stream_events(reply)
        for part, fault in STREAM_FAULTS.items():
            if part in self.path:
                events = fault(events)
        self.server.sent.append(b"".join(events))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        if "/drop/" in self.path:
            self.send_header("Content-Length", str(len(self.server.sent[-1]) + 10))
        self.end_headers()
        for n, event in enumerate(events):
            self.wfile.write(event)
            self.wfile.flush()
            if n == 2 and self.server.gate is not None:
                self.server.gate.wait(10)

    def _streams(self, body: bytes) -> bool:
        """True if the reply to this request is a stream."""
        if self.server.stream == "on_request":
            return json.loads(body).get("stream") is True
        return self.server.stream is True

    def do_GET(self) -> None:
        self.server.received.append({"method": "GET", "path": self.path, "body": b""})
        self._send(200, b"ok", "text/plain")

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.received.append(
            {
                "method": "POST",
                "path": self.path,
                "body": body,
                "headers": dict(self.headers.items()),
            }
        )
        if self.path.startswith("/fail"):
            self._send(500, b'{"error": "boom"}')
        elif self.path.startswith("/not-json"):
            self._send(200, b"plain text", "text/plain")
        elif self.path == "/cut":
            # A reply cut in the middle of an emoji: a lone surrogate.
            self._send(200, b'{"reply": "Your mug ships today \\ud83d"}')
        elif self.path.endswith("/chat/completions") and self._streams(body):
            self._stream(shop_reply(json.loads(body)["messages"][-1]["content"]))
        elif self.path.endswith("/chat/completions"):
            text = json.loads(body)["messages"][-1]["content"]
            out = {"choices": [{"message": {"role": "assistant", "content": shop_reply(text)}}]}
            self._send(200, json.dumps(out).encode())
        else:
            text = json.loads(body)["text"]
            self._send(200, json.dumps({"reply": shop_reply(text)}, ensure_ascii=False).encode())

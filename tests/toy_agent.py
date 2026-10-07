"""A toy shop agent for the tests. It keeps every request it receives, byte for byte."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def shop_reply(text: str) -> str:
    return f"## Toy shop  \nYou wrote: «{text}»\n\n| item | price |\n|---|---|\n| mug | € 8 |\n"


class ToyAgent(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
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
        elif self.path.startswith("/cut"):
            # A reply cut in the middle of an emoji: a lone surrogate.
            self._send(200, b'{"reply": "Your mug ships today \\ud83d"}')
        elif self.path.endswith("/chat/completions"):
            text = json.loads(body)["messages"][-1]["content"]
            out = {"choices": [{"message": {"role": "assistant", "content": shop_reply(text)}}]}
            self._send(200, json.dumps(out).encode())
        else:
            text = json.loads(body)["text"]
            self._send(200, json.dumps({"reply": shop_reply(text)}, ensure_ascii=False).encode())

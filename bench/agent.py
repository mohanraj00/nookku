"""The scripted toy shop agent of the M4 benchmark. One instance serves one session."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

UNKNOWN = "Sorry, I did not understand that. Could you say it another way?"
ERROR = b'{"error": "Internal error. Please try again."}'


class BenchAgent(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, session: dict[str, Any]) -> None:
        self.turns = {t["message"]: t for t in session["turns"]}
        self.failed: set[str] = set()
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def answer(self, text: str) -> tuple[int, bytes]:
        turn = self.turns.get(text)
        if turn is None:
            return 200, json.dumps({"reply": UNKNOWN}).encode()
        with self.lock:
            if turn["behaviour"] == "error" and text not in self.failed:
                self.failed.add(text)
                return 500, ERROR
        return 200, json.dumps({"reply": turn["reply"]}, ensure_ascii=False).encode()


class _Handler(BaseHTTPRequestHandler):
    server: BenchAgent

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            text = json.loads(body)["text"]
            status, out = self.server.answer(text) if isinstance(text, str) else (400, b"{}")
        except (ValueError, KeyError, TypeError):
            status, out = 400, b'{"error": "send JSON {\\"text\\": <message>}"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

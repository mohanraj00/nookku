"""A toy stock service for the backend proxy tests. It records each request that it gets, and
answers with the bytes that the test asks for."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from verbatim_relay import stdio


class StockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.seen: list[dict[str, Any]] = []
        # The body and headers of the next answers. Default: the stock of a teapot set.
        self.answer_body = json.dumps({"sku": "teapot-set", "left": 3}).encode()
        self.answer_headers = [("Content-Type", "application/json"), ("X-Stock-Trace", "a b  c")]
        self.status = 200
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    def server_bind(self) -> None:
        stdio.bind(self)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def __enter__(self) -> StockServer:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    server: StockServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _answer(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.seen.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": self.headers.items(),
                "body": body,
            }
        )
        self.send_response_only(self.server.status)
        for k, v in self.server.answer_headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(self.server.answer_body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(self.server.answer_body)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _answer

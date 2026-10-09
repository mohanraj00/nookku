"""A toy model API for the model API proxy tests. It records each request that it gets. It sends
its answer in parts, and it can wait after the first part until the test releases it."""

from __future__ import annotations

import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from nookku import stdio


class ModelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.seen: list[dict[str, Any]] = []
        # The parts of the next answers. With more than one part, the answer is a stream.
        self.parts: list[bytes] = [b'{"type": "message", "content": []}']
        self.content_type = "text/event-stream"
        self.status = 200
        self.gzip = False
        # True: the server closes the connection after the first part of a stream.
        self.stop_after_first = False
        # The bytes that the Content-Length of a one-part answer adds and that it does not send.
        self.short_by = 0
        # Set: the server sends the parts after the first part.
        self.release = threading.Event()
        self.release.set()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    def server_bind(self) -> None:
        stdio.bind(self)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def __enter__(self) -> ModelServer:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release.set()
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    server: ModelServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.seen.append({"path": self.path, "headers": self.headers.items(), "body": body})
        parts = self.server.parts
        self.send_response_only(self.server.status)
        self.send_header("Content-Type", self.server.content_type)
        if len(parts) == 1:
            data = gzip.compress(parts[0]) if self.server.gzip else parts[0]
            if self.server.gzip:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data) + self.server.short_by))
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = self.server.short_by > 0
            return
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for n, part in enumerate(parts):
            if n == 1:
                self.server.release.wait(10)
            self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.flush()
            if self.server.stop_after_first:
                self.close_connection = True
                return
        self.wfile.write(b"0\r\n\r\n")

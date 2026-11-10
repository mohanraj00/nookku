"""A stock agent that sends a text reply in two WebSocket fragments."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nookku import stdio, websocket
from nookku.record import loads

CASE = Path(__file__).resolve().parents[1] / "conformance" / "streams" / "toy-replies.json"


class ToyWebSocket(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *, close_ping: bool = False) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.case = loads(CASE.read_bytes())
        self.reply = self.case["websocket"]["reply"]
        self.seen: list[websocket.Frame] = []
        self.sent: list[websocket.Frame] = []
        self.close_ping = close_ping

    def server_bind(self) -> None:
        stdio.bind(self)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.server_port}"

    def __enter__(self) -> ToyWebSocket:
        stdio.start_in_thread(self)
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: ToyWebSocket

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.close_connection = True
        self.connection.settimeout(5)
        self.send_response_only(101)
        self.send_header("Connection", "Upgrade")
        self.send_header("Upgrade", "websocket")
        self.send_header(
            "Sec-WebSocket-Accept", websocket.accept(self.headers["Sec-WebSocket-Key"])
        )
        self.end_headers()

        def read() -> websocket.Frame:
            part = websocket.read_frame(self.rfile, masked=True)
            self.server.seen.append(part)
            return part

        def send(opcode: int, data: bytes, *, final: bool = True) -> None:
            part = websocket.frame(opcode, data, final=final, masked=False)
            self.server.sent.append(part)
            self.wfile.write(part.wire)

        request = read()
        assert request.opcode == websocket.TEXT and request.final
        assert json.loads(request.payload)["text"] == self.server.case["message"]
        raw = json.dumps({"reply": self.server.reply}, ensure_ascii=False).encode()
        split = raw.index("€".encode()) + 1
        send(websocket.TEXT, raw[:split], final=False)
        send(websocket.PING, b"stock")
        pong = read()
        assert pong.opcode == websocket.PONG and pong.payload == b"stock"
        send(websocket.CONTINUATION, raw[split:])
        close = read()
        assert close.opcode == websocket.CLOSE
        if self.server.close_ping:
            send(websocket.PING, b"closing")
            pong = read()
            assert pong.opcode == websocket.PONG and pong.payload == b"closing"
        send(websocket.CLOSE, close.payload)

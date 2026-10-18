"""A toy shop Postgres server for the tests of the database proxy. Local only.

It speaks enough of the Postgres protocol 3.0 for one stock table: a cleartext password, the
simple query and the extended query. It keeps each byte that it got and sent.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from typing import Any

PASSWORD = b"toy-pw-123"
STOCK = {"teapot-set": "3", "mug": "12"}


def message(tag: bytes, body: bytes = b"") -> bytes:
    return tag + (len(body) + 4).to_bytes(4, "big") + body


def rows(values: list[str]) -> bytes:
    """The row description of the column `left`, then one data row for each value."""
    column = b"left\0" + bytes(6) + (25).to_bytes(4, "big") + (-1).to_bytes(2, "big", signed=True)
    column += (-1).to_bytes(4, "big", signed=True) + bytes(2)
    out = message(b"T", (1).to_bytes(2, "big") + column)
    for v in values:
        data = v.encode()
        out += message(b"D", (1).to_bytes(2, "big") + len(data).to_bytes(4, "big") + data)
    return out


def error(text: str) -> bytes:
    return message(b"E", b"SERROR\0VERROR\0C42P01\0M" + text.encode() + b"\0\0")


def answer(query: str, params: list[str]) -> bytes:
    if "nope" in query:
        return error('relation "nope" does not exist')
    sku = params[0] if params else query.split("'")[1]
    return rows([STOCK[sku]] if sku in STOCK else []) + message(b"C", b"SELECT 1\0")


class Handler(socketserver.BaseRequestHandler):
    server: PgServer

    def _read(self, size: int) -> bytes:
        out = b""
        while len(out) < size:
            data = self.request.recv(size - len(out))
            if not data:
                raise EOFError
            out += data
        self.server.got += out
        return out

    def _send(self, data: bytes) -> None:
        self.server.sent += data
        self.request.sendall(data)

    def handle(self) -> None:
        try:
            size = int.from_bytes(self._read(4), "big")
            self._read(size - 4)
            self._send(message(b"R", (3).to_bytes(4, "big")))
            tag, body = self._message()
            ok = tag == b"p" and body == PASSWORD + b"\0"
            if not ok:
                self._send(error("password authentication failed"))
                return
            self._send(message(b"R", (0).to_bytes(4, "big")) + message(b"Z", b"I"))
            query, params = "", []
            while True:
                tag, body = self._message()
                if tag == b"X":
                    return
                if tag == b"Q":
                    self._send(answer(body[:-1].decode(), []) + message(b"Z", b"I"))
                elif tag == b"P":
                    query = body.split(b"\0")[1].decode()
                    self._send(message(b"1"))
                elif tag == b"B":
                    params = [self._param(body)]
                    self._send(message(b"2"))
                elif tag == b"E":
                    self._send(answer(query, params))
                elif tag == b"S":
                    self._send(message(b"Z", b"I"))
        except (EOFError, OSError):
            return

    def _message(self) -> tuple[bytes, bytes]:
        tag = self._read(1)
        size = int.from_bytes(self._read(4), "big")
        return tag, self._read(size - 4)

    @staticmethod
    def _param(body: bytes) -> str:
        """The first text parameter of a Bind message with no format codes."""
        at = body.index(b"\0", body.index(b"\0") + 1) + 1 + 2 + 2
        size = int.from_bytes(body[at : at + 4], "big")
        return body[at + 4 : at + 4 + size].decode()


class PgServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.got = b""
        self.sent = b""

    @property
    def url(self) -> str:
        return f"postgresql://shop:{PASSWORD.decode()}@127.0.0.1:{self.server_address[1]}/shop"

    def __enter__(self) -> PgServer:
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown()
        self.server_close()


def connect(host: str, port: int) -> socket.socket:
    return socket.create_connection((host, port), timeout=10)

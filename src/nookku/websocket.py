"""The text messages of a WebSocket turn at the tap, using RFC 6455 framing."""

from __future__ import annotations

import base64
import hashlib
import http.client
import io
import itertools
import operator
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO

CONTINUATION, TEXT, BINARY = 0, 1, 2
CLOSE, PING, PONG = 8, 9, 10
_DATA = {CONTINUATION, TEXT, BINARY}
_CONTROL = {CLOSE, PING, PONG}
LIMIT = 16 * 1024 * 1024
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    wire: bytes
    opcode: int
    final: bool
    payload: bytes


def accept(key: str) -> str:
    digest = hashlib.sha1((key + _GUID).encode(), usedforsecurity=False).digest()
    return base64.b64encode(digest).decode()


def _mask(data: bytes, key: bytes) -> bytes:
    return bytes(map(operator.xor, data, itertools.cycle(key)))


def frame(opcode: int, payload: bytes, *, final: bool = True, masked: bool = True) -> Frame:
    size = len(payload)
    bit = 0x80 if masked else 0
    first = bytes([(0x80 if final else 0) | opcode])
    if size < 126:
        header = first + bytes([bit | size])
    elif size < 65536:
        header = first + bytes([bit | 126]) + size.to_bytes(2, "big")
    else:
        header = first + bytes([bit | 127]) + size.to_bytes(8, "big")
    key = os.urandom(4) if masked else b""
    wire = header + key + (_mask(payload, key) if masked else payload)
    return Frame(wire, opcode, final, payload)


def _exact(reader: IO[bytes], size: int) -> bytes:
    data = reader.read(size)
    if len(data) != size:
        raise WebSocketError("the frame stopped before its end")
    return data


def read_frame(reader: IO[bytes], *, masked: bool) -> Frame:
    head = _exact(reader, 2)
    first, second = head
    opcode, final = first & 0x0F, bool(first & 0x80)
    if first & 0x70 or opcode not in (_DATA | _CONTROL) or bool(second & 0x80) != masked:
        raise WebSocketError("the frame header is not valid")
    size = second & 0x7F
    if size >= 126:
        extension = _exact(reader, 2 if size == 126 else 8)
        size = int.from_bytes(extension, "big")
        if size < (126 if len(extension) == 2 else 65536) or size >= 2**63:
            raise WebSocketError("the frame length is not valid")
        head += extension
    if size > LIMIT:
        raise WebSocketError("the frame is too large")
    if opcode in _CONTROL and (not final or size > 125 or (opcode == CLOSE and size == 1)):
        raise WebSocketError("the control frame is not valid")
    key = _exact(reader, 4) if masked else b""
    data = _exact(reader, size)
    return Frame(head + key + data, opcode, final, _mask(data, key) if masked else data)


def from_wire(data: bytes, *, masked: bool) -> Frame:
    source = io.BytesIO(data)
    found = read_frame(source, masked=masked)
    if source.read(1):
        raise WebSocketError("a record part contains more than one frame")
    return found


class TextMessage:
    """One text message, which can have continuation frames and control frames between them."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.started = self.done = False

    def add(self, part: Frame) -> None:
        if part.opcode in _CONTROL:
            return
        if self.done or part.opcode != (CONTINUATION if self.started else TEXT):
            raise WebSocketError("expected one text message")
        self.started = True
        if len(self.data) + len(part.payload) > LIMIT:
            raise WebSocketError("the text message is too large")
        self.data += part.payload
        self.done = part.final

    def text(self) -> bytes:
        if not self.done:
            raise WebSocketError("the text message has no final frame")
        data = bytes(self.data)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise WebSocketError("the text message is not UTF-8") from None
        return data


def exchange(
    conn: http.client.HTTPConnection,
    path: str,
    headers: dict[str, str],
    body: bytes,
    observe: Callable[[str, Frame], None],
) -> bytes:
    """Send one text message. Record the wire frames and return the agent's complete text bytes."""
    if len(body) > LIMIT:
        raise WebSocketError("the request message is too large")
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        raise WebSocketError("the request message is not UTF-8") from None
    key = base64.b64encode(os.urandom(16)).decode()
    sent = {k: v for k, v in headers.items() if not k.lower().startswith("sec-websocket-")}
    sent.update(
        {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": key,
        }
    )
    conn.request("GET", path, headers=sent)
    response = conn.getresponse()
    reader, sock = response.fp, conn.sock
    connection = (response.getheader("Connection") or "").lower().split(",")
    if (
        response.status != 101
        or "upgrade" not in {part.strip() for part in connection}
        or (response.getheader("Upgrade") or "").lower() != "websocket"
        or response.getheader("Sec-WebSocket-Accept") != accept(key)
        or response.getheader("Sec-WebSocket-Extensions") is not None
        or response.getheader("Sec-WebSocket-Protocol") is not None
        or reader is None
        or sock is None
    ):
        raise WebSocketError(
            f"the agent did not accept the WebSocket upgrade (HTTP {response.status})"
        )

    def write(opcode: int, data: bytes) -> None:
        part = frame(opcode, data)
        observe("to_agent", part)
        sock.sendall(part.wire)

    write(TEXT, body)
    reply = TextMessage()
    while not reply.done:
        part = read_frame(reader, masked=False)
        observe("from_agent", part)
        if part.opcode == PING:
            write(PONG, part.payload)
        if part.opcode == CLOSE:
            write(CLOSE, part.payload)
            raise WebSocketError("the agent closed before a full reply")
        reply.add(part)
    data = reply.text()

    # Give the peer a short chance to answer the close after the full reply is recorded.
    close = frame(CLOSE, b"\x03\xe8")
    observe("to_agent", close)
    deadline = time.monotonic() + 1
    try:
        sock.sendall(close.wire)
    except OSError:
        return data
    while (left := deadline - time.monotonic()) > 0:
        sock.settimeout(left)
        try:
            part = read_frame(reader, masked=False)
        except (OSError, WebSocketError):
            break
        observe("from_agent", part)
        if part.opcode == CLOSE:
            break
        reply.add(part)
    return data

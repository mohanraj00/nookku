"""Validate the part evidence of a streamed tap exchange."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any, NamedTuple

from . import websocket
from .adapters import OpenAIAdapter, make
from .record import STREAM_PARTS, RecordError


class _Part(NamedTuple):
    ts: float
    data: bytes | websocket.Frame
    direction: str | None


def _part(row: dict[str, Any]) -> _Part:
    data = base64.b64decode(row["base64"], validate=True)
    if not data or row["sha256"] != hashlib.sha256(data).hexdigest():
        raise ValueError("the part hash does not match its bytes")
    ts = row["ts"]
    if not 0 <= ts < 1e15:
        raise ValueError("the part time is not valid")
    if row["type"] == "stream_part":
        return _Part(ts, data, None)
    direction = row["direction"]
    if direction not in ("to_agent", "from_agent"):
        raise ValueError("the frame direction is not valid")
    frame = websocket.from_wire(data, masked=direction == "to_agent")
    if frame.opcode != row["opcode"] or frame.final != row["final"]:
        raise ValueError("the frame header does not match the recorded opcode and final flag")
    return _Part(ts, frame, direction)


def _websocket_messages(group: list[_Part]) -> tuple[bytes, bytes, float | None]:
    sent, received = websocket.TextMessage(), websocket.TextMessage()
    first = None
    for part in group:
        if not isinstance(part.data, websocket.Frame):
            raise ValueError("the WebSocket session has a part that is not a frame")
        if part.direction == "to_agent":
            sent.add(part.data)
        else:
            received.add(part.data)
            if first is None and received.started:
                first = part.ts
    return sent.text(), received.text(), first


def _check(group: list[_Part], row: dict[str, Any]) -> None:
    protocol = row.get("stream_protocol")
    if protocol == "sse":
        if any(not isinstance(part.data, bytes) for part in group):
            raise ValueError("the SSE stream has a WebSocket frame")
        raw = b"".join(part.data for part in group if isinstance(part.data, bytes))
        first = group[0].ts if group else None
        if row["reply"] is not None and OpenAIAdapter().stream_reply(raw) != row["reply"]:
            raise ValueError("the stream reply does not match")
    elif protocol == "websocket":
        sent, raw, first = _websocket_messages(group)
        config = row.get("stream_adapter")
        if not isinstance(config, dict):
            raise ValueError("the WebSocket exchange has no adapter")
        name = config.get("name")
        message_field = config.get("message_field", "text")
        reply_field = config.get("reply_field", "reply")
        if (
            not isinstance(name, str)
            or not isinstance(message_field, str)
            or not isinstance(reply_field, str)
        ):
            raise ValueError("the WebSocket exchange has an invalid adapter field")
        adapter = make(name, message_field, reply_field)
        if adapter.message(sent) != row["input"] or adapter.reply(raw) != row["reply"]:
            raise ValueError("the WebSocket messages do not match the exchange")
    else:
        raise ValueError("the stream protocol is not valid")
    stream = row.get("stream")
    started = row.get("started")
    if not isinstance(started, (int, float)) or not 0 <= started < 1e15:
        raise ValueError("the stream start time is not valid")
    seconds = None if first is None else round(max(0.0, first - started), 3)
    if (
        not isinstance(stream, dict)
        or stream["bytes"] != len(raw)
        or stream["sha256"] != hashlib.sha256(raw).hexdigest()
        or row.get("first_part_seconds", "absent") != seconds
    ):
        raise ValueError("the stream parts do not match the exchange")


def validate(rows: list[tuple[int, dict[str, Any]]], path: Path) -> None:
    groups: dict[str, list[_Part]] = {}
    ended: set[str] = set()
    for n, row in rows:
        try:
            if row["type"] in STREAM_PARTS:
                key = row["stream_id"]
                group = groups.setdefault(key, [])
                if not key or key in ended or row["index"] != len(group) + 1:
                    raise ValueError("the stream part is out of order")
                group.append(_part(row))
            elif row["type"] == "exchange" and (
                {"stream_id", "stream_protocol", "stream_adapter", "first_part_seconds"}
                & row.keys()
            ):
                key = row.get("stream_id")
                if not key or key in ended:
                    raise ValueError("the stream reference is invalid")
                _check(groups.pop(key, []), row)
                ended.add(key)
        except (ValueError, RecursionError) as error:
            raise RecordError("record_invalid", path, f"line {n}: {error}") from None
    if groups:
        for n, row in rows:
            if row["type"] in STREAM_PARTS and row["stream_id"] in groups:
                raise RecordError(
                    "record_invalid", path, f"line {n}: the stream part has no exchange"
                )

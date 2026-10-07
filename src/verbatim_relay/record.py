"""The record format of SPEC.md section 2: read, validate and append rows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "0.2"
VERSIONS = ("0.1", "0.2")
# A surrogate code point. In a decoded Python string, each one is a lone surrogate.
_SURROGATE = re.compile("[\ud800-\udfff]")


def lone_surrogate(text: str) -> str | None:
    """Name the first lone surrogate in the text, or return None if the text has none.

    A record text holds only Unicode scalar values (SPEC.md section 2). UTF-8 cannot encode a
    lone surrogate, so this check must occur before a hash or a write.
    """
    found = _SURROGATE.search(text)
    if found is None:
        return None
    return f"a lone surrogate U+{ord(found.group()):04X} at character {found.start()}"


def sha256(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Exchange:
    line: int
    input: str
    status: int | None
    reply: str | None


@dataclass(frozen=True)
class Unparsed:
    line: int
    method: str
    path: str
    error: str


@dataclass(frozen=True)
class ModelSession:
    line: int
    harness: str
    session: str
    pid: int | None
    inferred: bool


@dataclass(frozen=True)
class Turn:
    line: int
    said: str
    shown: str | None


@dataclass(frozen=True)
class BlockedCall:
    line: int
    tool: str
    detail: str


class RecordError(Exception):
    """A record is missing (kind `record_missing`) or invalid (kind `record_invalid`)."""

    def __init__(self, kind: str, path: Path, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.kind = kind


# type name -> {field: allowed types}; a text field also requires its hash field
_STR, _NUM, _INT_OR_NONE, _STR_OR_NONE = (str,), (int, float), (int, type(None)), (str, type(None))
_BOOL = (bool,)
_TEXT_FIELDS = {"input", "reply", "said", "shown"}
_SCHEMA: dict[str, dict[str, dict[str, tuple[type, ...]]]] = {
    "tap": {
        "exchange": {"ts": _NUM, "input": _STR, "status": _INT_OR_NONE, "reply": _STR_OR_NONE},
        "unparsed": {"ts": _NUM, "method": _STR, "path": _STR, "error": _STR},
        "model_session": {
            "ts": _NUM,
            "harness": _STR,
            "session": _STR,
            "pid": _INT_OR_NONE,
            "inferred": _BOOL,
        },
    },
    "relay": {
        "turn": {"ts": _NUM, "harness": _STR, "said": _STR, "shown": _STR_OR_NONE},
        "blocked_call": {"ts": _NUM, "harness": _STR, "tool": _STR, "detail": _STR},
    },
}
# Types and optional fields that a "0.1" row must not have.
_SINCE_02 = {"model_session", "started", "originator"}
# Optional fields: (row type, field) -> allowed types
_OPTIONAL: dict[tuple[str, str], tuple[type, ...]] = {
    ("exchange", "started"): _NUM,
    ("model_session", "originator"): _STR,
    ("turn", "ok"): _BOOL,
    ("turn", "session"): _STR,
}


def _validate(kind: str, path: Path, n: int, raw: str) -> dict[str, Any]:
    def bad(message: str) -> RecordError:
        return RecordError("record_invalid", path, f"line {n}: {message}")

    try:
        row = json.loads(raw)
    except json.JSONDecodeError as e:
        raise bad(f"not JSON ({e.msg})") from None
    if not isinstance(row, dict):
        raise bad("not a JSON object")
    for name, value in row.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        found = lone_surrogate(name) or lone_surrogate(text)
        if found:
            raise bad(f"field {name!r} has {found}, which is not a Unicode scalar value")
    if row.get("v") not in VERSIONS:
        raise bad(f"version {row.get('v')!r}, expected one of {', '.join(VERSIONS)}")
    fields = _SCHEMA[kind].get(row.get("type"))  # type: ignore[arg-type]
    if fields is None:
        raise bad(f"unknown type {row.get('type')!r} in a {kind} record")
    for name, types in fields.items():
        if name not in row:
            raise bad(f"missing field {name!r}")
        value = row[name]
        if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
            raise bad(f"field {name!r} has the wrong type")
        if name in _TEXT_FIELDS and row.get(f"{name}_sha256", "absent") != sha256(
            value if isinstance(value, str) else None
        ):
            raise bad(f"field {name}_sha256 does not match {name!r}")
    if row["type"] == "exchange":
        ok = row["status"] is not None and 200 <= row["status"] < 300
        if ok != (row["reply"] is not None):
            raise bad("'reply' must be a string for a 2xx status and null for any other status")
    for (kind_, name), types in _OPTIONAL.items():
        value = row.get(name)
        if row["type"] != kind_ or name not in row:
            continue
        if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
            raise bad(f"field {name!r} has the wrong type")
    if row["v"] == "0.1" and ({row["type"]} | set(row)) & _SINCE_02:
        raise bad("a field or a type of version 0.2 in a version 0.1 row")
    if "error" in row and not isinstance(row["error"], str):
        raise bad("field 'error' has the wrong type")
    return row


def _read(kind: str, path: Path) -> list[tuple[int, dict[str, Any]]]:
    try:
        data = path.read_bytes()
    except OSError as e:
        raise RecordError("record_missing", path, e.strerror or "cannot read") from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RecordError("record_invalid", path, "not UTF-8") from None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [(n, _validate(kind, path, n, raw)) for n, raw in enumerate(lines, 1)]


def read_tap(path: Path) -> list[Exchange | Unparsed | ModelSession]:
    rows: list[Exchange | Unparsed | ModelSession] = []
    for n, r in _read("tap", path):
        if r["type"] == "exchange":
            rows.append(Exchange(n, r["input"], r["status"], r["reply"]))
        elif r["type"] == "model_session":
            rows.append(ModelSession(n, r["harness"], r["session"], r["pid"], r["inferred"]))
        else:
            rows.append(Unparsed(n, r["method"], r["path"], r["error"]))
    return rows


def read_relay(path: Path) -> list[Turn | BlockedCall]:
    rows: list[Turn | BlockedCall] = []
    for n, r in _read("relay", path):
        if r["type"] == "turn":
            rows.append(Turn(n, r["said"], r["shown"]))
        else:
            rows.append(BlockedCall(n, r["tool"], r["detail"]))
    return rows


def _hashed(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"v": VERSION, "ts": time.time()}
    for key, value in row.items():
        out[key] = value
        if key in _TEXT_FIELDS:
            out[f"{key}_sha256"] = sha256(value)
    return out


class Writer:
    """Append rows to a record. Each row is one write, flushed to disk before the call returns."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, row: dict[str, Any]) -> None:
        line = json.dumps(_hashed(row), ensure_ascii=False) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

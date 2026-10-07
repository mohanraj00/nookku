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
    ok: bool | None = None
    session: str | None = None


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
_SINCE_02 = {"model_session", "started", "originator", "stream"}
_HEX64 = re.compile(r"[0-9a-f]{64}")
# Optional fields: (row type, field) -> allowed types
_OPTIONAL: dict[tuple[str, str], tuple[type, ...]] = {
    ("exchange", "started"): _NUM,
    ("model_session", "originator"): _STR,
    ("turn", "ok"): _BOOL,
    ("turn", "session"): _STR,
}


def _stream_info(value: Any) -> bool:
    """True if the value is a `stream` object: the SHA-256 and the size of the raw body."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("sha256"), str)
        and _HEX64.fullmatch(value["sha256"]) is not None
        and type(value.get("bytes")) is int
        and value["bytes"] >= 0
    )


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
        if "stream" in row and not _stream_info(row["stream"]):
            raise bad("field 'stream' has the wrong type")
        # A failed stream (SPEC.md section 2.1) has a 2xx status, no reply and an error.
        failed = ok and row["reply"] is None and "stream" in row and "error" in row
        if ok != (row["reply"] is not None) and not failed:
            raise bad(
                "'reply' must be a string for a 2xx status, and null for any other status "
                "or for a failed stream"
            )
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


def read_rows(kind: str, path: Path, missing_ok: bool = False) -> list[tuple[int, dict[str, Any]]]:
    """Each row of a tap record (kind `tap`) or a relay record (kind `relay`), with its line.

    This is the one reader of the two records. An invalid line or a wrong hash stops the read with
    a RecordError that names the file and the line. With missing_ok, a file that does not exist
    gives no rows.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        if missing_ok and isinstance(e, FileNotFoundError):
            return []
        raise RecordError("record_missing", path, e.strerror or "cannot read") from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RecordError("record_invalid", path, "not UTF-8") from None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [(n, _validate(kind, path, n, raw)) for n, raw in enumerate(lines, 1)]


def read_tap(path: Path, missing_ok: bool = False) -> list[Exchange | Unparsed | ModelSession]:
    rows: list[Exchange | Unparsed | ModelSession] = []
    for n, r in read_rows("tap", path, missing_ok):
        if r["type"] == "exchange":
            rows.append(Exchange(n, r["input"], r["status"], r["reply"]))
        elif r["type"] == "model_session":
            rows.append(ModelSession(n, r["harness"], r["session"], r["pid"], r["inferred"]))
        else:
            rows.append(Unparsed(n, r["method"], r["path"], r["error"]))
    return rows


def read_relay(path: Path, missing_ok: bool = False) -> list[Turn | BlockedCall]:
    rows: list[Turn | BlockedCall] = []
    for n, r in read_rows("relay", path, missing_ok):
        if r["type"] == "turn":
            rows.append(Turn(n, r["said"], r["shown"], r.get("ok"), r.get("session")))
        else:
            rows.append(BlockedCall(n, r["tool"], r["detail"]))
    return rows


def turns(path: Path, missing_ok: bool = False) -> list[Turn]:
    """The turns of a relay record, with the error rule of read_rows."""
    return [r for r in read_relay(path, missing_ok) if isinstance(r, Turn)]


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

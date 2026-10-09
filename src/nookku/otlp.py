"""The OTLP/HTTP receiver of SPEC.md section 7.5.

During a test, the bridge runs this receiver and gives its address to the entry. The receiver takes
OpenTelemetry traces and logs as JSON or protobuf, and writes one row for each span and each log
record to otel.jsonl. It drops metrics, the spans of the harnesses, and the personal attributes.

The protobuf decoder covers only the OTLP trace and log messages (opentelemetry-proto v1), with the
standard library. It turns a protobuf body into the dict of the OTLP JSON form, so one function
reads both forms.
"""

from __future__ import annotations

import base64
import gzip
import json
import struct
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import stdio
from .record import json_text

FILE = "otel.jsonl"
VERSION = 1
MAX_BODY = 16 * 1024 * 1024
# The harness log events that the receiver keeps (SPEC.md section 7.5).
HARNESS_EVENTS = {"user_prompt", "tool_decision", "tool_result", "assistant_response", "api_error"}


class DecodeError(ValueError):
    pass


# Protobuf wire format.


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    out = shift = 0
    while True:
        if i >= len(buf) or shift > 63:
            raise DecodeError("a varint ends early")
        b = buf[i]
        i += 1
        out |= (b & 0x7F) << shift
        if b < 0x80:
            return out, i
        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """Each field of a message: (number, wire type, value). A length-delimited value is bytes."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        number, wire = key >> 3, key & 7
        value: int | bytes
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 1:
            if i + 8 > len(buf):
                raise DecodeError("a 64-bit field ends early")
            value, i = buf[i : i + 8], i + 8
        elif wire == 2:
            size, i = _varint(buf, i)
            if i + size > len(buf):
                raise DecodeError("a length-delimited field ends early")
            value, i = buf[i : i + size], i + size
        elif wire == 5:
            if i + 4 > len(buf):
                raise DecodeError("a 32-bit field ends early")
            value, i = buf[i : i + 4], i + 4
        else:
            raise DecodeError(f"wire type {wire} is not supported")
        yield number, wire, value


def _signed(n: int) -> int:
    return n - (1 << 64) if n >= 1 << 63 else n


def _u64(value: bytes) -> int:
    return int(struct.unpack("<Q", value)[0])


def _str(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


# A schema maps a field number to (JSON name, kind, repeated). A kind is "string", "bytes" (hex),
# "base64", "varint", "int64", "bool", "double", "fixed64" or a nested schema.
Schema = dict[int, tuple[str, Any, bool]]
ANY: Schema = {}
KEY_VALUE: Schema = {1: ("key", "string", False), 2: ("value", ANY, False)}
ANY.update(
    {
        1: ("stringValue", "string", False),
        2: ("boolValue", "bool", False),
        3: ("intValue", "int64", False),
        4: ("doubleValue", "double", False),
        5: ("arrayValue", {1: ("values", ANY, True)}, False),
        6: ("kvlistValue", {1: ("values", KEY_VALUE, True)}, False),
        7: ("bytesValue", "base64", False),
    }
)
RESOURCE: Schema = {1: ("attributes", KEY_VALUE, True)}
SCOPE: Schema = {
    1: ("name", "string", False),
    2: ("version", "string", False),
    3: ("attributes", KEY_VALUE, True),
}
EVENT: Schema = {
    1: ("timeUnixNano", "fixed64", False),
    2: ("name", "string", False),
    3: ("attributes", KEY_VALUE, True),
}
STATUS: Schema = {2: ("message", "string", False), 3: ("code", "varint", False)}
SPAN: Schema = {
    1: ("traceId", "bytes", False),
    2: ("spanId", "bytes", False),
    4: ("parentSpanId", "bytes", False),
    5: ("name", "string", False),
    6: ("kind", "varint", False),
    7: ("startTimeUnixNano", "fixed64", False),
    8: ("endTimeUnixNano", "fixed64", False),
    9: ("attributes", KEY_VALUE, True),
    11: ("events", EVENT, True),
    15: ("status", STATUS, False),
}
TRACES: Schema = {
    1: (
        "resourceSpans",
        {
            1: ("resource", RESOURCE, False),
            2: ("scopeSpans", {1: ("scope", SCOPE, False), 2: ("spans", SPAN, True)}, True),
        },
        True,
    )
}
LOG_RECORD: Schema = {
    1: ("timeUnixNano", "fixed64", False),
    11: ("observedTimeUnixNano", "fixed64", False),
    2: ("severityNumber", "varint", False),
    3: ("severityText", "string", False),
    5: ("body", ANY, False),
    6: ("attributes", KEY_VALUE, True),
    9: ("traceId", "bytes", False),
    10: ("spanId", "bytes", False),
    12: ("eventName", "string", False),
}
LOGS: Schema = {
    1: (
        "resourceLogs",
        {
            1: ("resource", RESOURCE, False),
            2: (
                "scopeLogs",
                {1: ("scope", SCOPE, False), 2: ("logRecords", LOG_RECORD, True)},
                True,
            ),
        },
        True,
    )
}
WIRE = {"string": 2, "bytes": 2, "base64": 2, "varint": 0, "int64": 0, "bool": 0, "double": 1}
WIRE["fixed64"] = 1


def decode(buf: bytes, schema: Schema) -> dict[str, Any]:
    """A protobuf message as the dict of its OTLP JSON form. Unknown fields are skipped."""
    out: dict[str, Any] = {}
    for number, wire, value in _fields(buf):
        if number not in schema:
            continue
        name, kind, repeated = schema[number]
        expected = 2 if isinstance(kind, dict) else WIRE[kind]
        if wire != expected:
            raise DecodeError(f"field {name} has wire type {wire}, not {expected}")
        if isinstance(kind, dict):
            v: Any = decode(value, kind)
        elif kind == "string":
            v = _str(value)
        elif kind == "bytes":
            v = value.hex()
        elif kind == "base64":
            v = base64.b64encode(value).decode()
        elif kind == "varint":
            v = value
        elif kind == "int64":
            v = str(_signed(value))
        elif kind == "bool":
            v = bool(value)
        elif kind == "double":
            v = struct.unpack("<d", value)[0]
        else:
            v = str(_u64(value))
        if repeated:
            out.setdefault(name, []).append(v)
        else:
            out[name] = v
    return out


# The OTLP JSON form to rows.


def value(v: Any) -> Any:
    """The Python value of an AnyValue."""
    if not isinstance(v, dict):
        return None
    if "stringValue" in v:
        return v["stringValue"]
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in v:
        return v["doubleValue"]
    if "arrayValue" in v:
        return [value(x) for x in (v["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in v:
        return attributes((v["kvlistValue"] or {}).get("values", []))
    if "bytesValue" in v:
        return v["bytesValue"]
    return None


def private(key: str) -> bool:
    """True for an attribute that names a person or an organization (SPEC.md section 7.5)."""
    low = key.lower()
    return low.startswith(("user.", "organization.")) or "email" in low


def attributes(kvs: Any) -> dict[str, Any]:
    """The attributes as a dict, without the personal attributes."""
    out: dict[str, Any] = {}
    for kv in kvs if isinstance(kvs, list) else []:
        if isinstance(kv, dict) and isinstance(kv.get("key"), str) and not private(kv["key"]):
            out[kv["key"]] = value(kv.get("value"))
    return out


def _seconds(nanos: Any) -> float | None:
    try:
        n = int(nanos)
    except (TypeError, ValueError):
        return None
    # int / int is rounded once. int / 1e9 makes n a float first and loses the last digits.
    return n / 1_000_000_000 if n else None


def _hex(v: Any) -> str | None:
    """An id of the JSON form is hex already. An empty id is null."""
    return v.lower() if isinstance(v, str) and v else None


def harness_of(service: str | None) -> str | None:
    """The harness that sent a row, from its service.name."""
    if service == "claude-code":
        return "claude-code"
    if isinstance(service, str) and service.startswith("codex"):
        return "codex"
    return None


def event_name(record: dict[str, Any], attrs: dict[str, Any]) -> str | None:
    # Codex puts a source location in eventName, and the event name in the event.name attribute.
    name = attrs.get("event.name") or record.get("eventName")
    return name if isinstance(name, str) and name else None


def short(name: str | None) -> str | None:
    """claude_code.tool_result and codex.tool_result are both tool_result."""
    return name.rsplit(".", 1)[-1] if name else None


def _scopes(resource: dict[str, Any], key: str) -> Iterator[tuple[dict[str, Any], Any, Any]]:
    res = attributes((resource.get("resource") or {}).get("attributes"))
    for scope in resource.get(key) or []:
        if isinstance(scope, dict):
            yield res, (scope.get("scope") or {}).get("name"), scope


def rows(body: dict[str, Any], received: float) -> list[dict[str, Any]]:
    """The otel.jsonl rows of one request in the OTLP JSON form, traces or logs."""
    out: list[dict[str, Any]] = []
    for resource in body.get("resourceSpans") or []:
        for res, scope, ss in _scopes(resource, "scopeSpans"):
            if harness_of(res.get("service.name")) is not None:
                continue
            for sp in ss.get("spans") or []:
                status = sp.get("status") or {}
                code = status.get("code", 0)
                code = {"STATUS_CODE_OK": 1, "STATUS_CODE_ERROR": 2}.get(code, code)
                events = [
                    {
                        "time": _seconds(e.get("timeUnixNano")),
                        "name": e.get("name"),
                        "attributes": attributes(e.get("attributes")),
                    }
                    for e in sp.get("events") or []
                ]
                out.append(
                    {
                        "v": VERSION,
                        "type": "span",
                        "received": received,
                        "service": res.get("service.name"),
                        "resource": res,
                        "scope": scope,
                        "trace_id": _hex(sp.get("traceId")),
                        "span_id": _hex(sp.get("spanId")),
                        "parent_span_id": _hex(sp.get("parentSpanId")),
                        "name": sp.get("name"),
                        "start": _seconds(sp.get("startTimeUnixNano")),
                        "end": _seconds(sp.get("endTimeUnixNano")),
                        "attributes": attributes(sp.get("attributes")),
                        "events": events,
                        "status": {
                            "code": code if isinstance(code, int) else 0,
                            "message": status.get("message") or None,
                        },
                    }
                )
    for resource in body.get("resourceLogs") or []:
        for res, scope, sl in _scopes(resource, "scopeLogs"):
            harness = harness_of(res.get("service.name"))
            for lr in sl.get("logRecords") or []:
                attrs = attributes(lr.get("attributes"))
                name = event_name(lr, attrs)
                if harness is not None and short(name) not in HARNESS_EVENTS:
                    continue
                t = _seconds(lr.get("timeUnixNano")) or _seconds(lr.get("observedTimeUnixNano"))
                out.append(
                    {
                        "v": VERSION,
                        "type": "log",
                        "received": received,
                        "service": res.get("service.name"),
                        "resource": res,
                        "scope": scope,
                        "time": t,
                        "event_name": name,
                        "severity": lr.get("severityText") or None,
                        "body": value(lr.get("body")),
                        "attributes": attrs,
                        "trace_id": _hex(lr.get("traceId")),
                        "span_id": _hex(lr.get("spanId")),
                    }
                )
    return out


def parse(path: str, ctype: str, encoding: str, raw: bytes) -> dict[str, Any] | None:
    """The OTLP JSON form of a request body, or None for a path that the receiver drops."""
    if encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as e:
            raise DecodeError(f"gzip: {e}") from None
    elif encoding not in ("", "identity"):
        raise DecodeError(f"content encoding {encoding} is not supported")
    schema = {"/v1/traces": TRACES, "/v1/logs": LOGS}.get(path)
    if schema is None:
        return None
    if "json" in ctype:
        try:
            body = json.loads(raw)
        except ValueError as e:
            raise DecodeError(f"JSON: {e}") from None
        if not isinstance(body, dict):
            raise DecodeError("JSON: the body is not an object")
        return body
    if "protobuf" in ctype:
        return decode(raw, schema)
    raise DecodeError(f"content type {ctype or '(none)'} is not supported")


class Receiver(ThreadingHTTPServer):
    """The receiver. Each request is one write to otel.jsonl."""

    daemon_threads = False
    block_on_close = True

    def __init__(self, listen: tuple[str, int], record: Path) -> None:
        super().__init__(listen, Handler)
        self.record = record
        self.lock = threading.Lock()
        self.last = time.time()

    def server_bind(self) -> None:
        stdio.bind(self)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}"

    def write(self, new: list[dict[str, Any]]) -> None:
        text = "".join(json_text(r) + "\n" for r in new)
        with self.lock:
            self.last = time.time()
            if text:
                with self.record.open("a", encoding="utf-8") as fh:
                    fh.write(text)

    def quiet(
        self, gap: float = 0.5, limit: float = 2.0, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        """Wait until no request came for `gap` seconds, or `limit` seconds passed."""
        end = time.time() + limit
        while time.time() < end and time.time() - self.last < gap:
            sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    server: Receiver

    def do_POST(self) -> None:
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        encoding = self.headers.get("Content-Encoding", "").strip().lower()
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            self._answer(413, ctype, f"the body is larger than {MAX_BODY} bytes")
            return
        raw = self.rfile.read(size)
        received = time.time()
        path = self.path.split("?")[0]
        try:
            body = parse(path, ctype, encoding, raw)
            if body is None:
                known = path == "/v1/metrics"
                self.server.write([])
                self._answer(200 if known else 404, ctype, None if known else "unknown path")
                return
            self.server.write(rows(body, received))
        except DecodeError as e:
            row = {
                "v": VERSION,
                "type": "error",
                "received": received,
                "path": path,
                "detail": str(e),
            }
            self.server.write([row])
            self._answer(400, ctype, str(e))
            return
        self._answer(200, ctype, None)

    def _answer(self, status: int, ctype: str, error: str | None) -> None:
        if "json" in ctype or error is not None:
            data = json.dumps({"error": error} if error else {}).encode()
            kind = "application/json"
        else:
            data, kind = b"", "application/x-protobuf"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def environment(url: str) -> dict[str, str]:
    """The variables that send the entry's OpenTelemetry data to the receiver (SPEC.md 7.5)."""
    return {
        "OTEL_EXPORTER_OTLP_ENDPOINT": url,
        # Each OTLP/HTTP SDK can send protobuf. Some cannot send JSON.
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_BSP_SCHEDULE_DELAY": "500",
        "OTEL_BLRP_SCHEDULE_DELAY": "500",
        "OTEL_LOGS_EXPORT_INTERVAL": "500",
        "OTEL_TRACES_EXPORT_INTERVAL": "500",
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_LOG_USER_PROMPTS": "1",
        "OTEL_LOG_TOOL_DETAILS": "1",
    }

"""Export a test as OTLP traces with the pinned OpenTelemetry GenAI conventions."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import struct
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from . import otlp, performance, trace
from .record import RecordError, loads, read_manifest

SEMCONV = "1.38.0"
_HEADERS = "OTEL_EXPORTER_OTLP_TRACES_HEADERS"
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_RESERVED = {"connection", "content-length", "content-type", "host", "transfer-encoding"}
_RESPONSE: otlp.Schema = {
    1: ("partialSuccess", {1: ("rejectedSpans", "int64", False)}, False),
}


class ExportError(ValueError):
    pass


def _stamp(value: Any) -> int | None:
    if type(value) in (int, float) and 0 <= value < 10_000_000_000:
        return round(float(value) * 1_000_000_000)
    return None


def _name(value: Any) -> str | None:
    return value[:512] if isinstance(value, str) and value and value.isprintable() else None


def _id(value: str, digits: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:digits]


def _attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "value": {"intValue": str(value)} if type(value) is int else {"stringValue": value},
        }
        for key, value in values.items()
        if value is not None
    ]


def _source(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    line = source.get("line")
    return {
        "nookku.source.file": _name(source.get("file")),
        "nookku.source.line": line if type(line) is int and 0 < line <= performance.MOST else None,
    }


class _Export:
    def __init__(self, test: str, started: int) -> None:
        self.id = _id(f"nookku:{test}:{started}", 32)
        self.spans: list[dict[str, Any]] = []

    def add(
        self,
        name: str,
        started: int,
        ended: int,
        source: str,
        parent: dict[str, Any] | None = None,
        kind: int = 1,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        span = {
            "traceId": self.id,
            "spanId": _id(f"{self.id}:{len(self.spans)}", 16),
            "name": name,
            "kind": kind,
            "startTimeUnixNano": str(started),
            "endTimeUnixNano": str(max(started, ended)),
            "attributes": _attributes({"nookku.source": source, **(attributes or {})}),
        }
        if parent is not None:
            span["parentSpanId"] = parent["spanId"]
        self.spans.append(span)
        return span

    def result(self) -> dict[str, Any]:
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": _attributes(
                            {"service.name": "nookku", "nookku.gen_ai.semconv.version": SEMCONV}
                        )
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "nookku.gen_ai", "version": SEMCONV},
                            "spans": self.spans,
                        }
                    ],
                }
            ]
        }


def _call_span(
    export: _Export,
    parent: dict[str, Any],
    operation: str,
    source: str,
    ts: Any,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    at = _stamp(ts)
    if at is None:
        at = int(parent["startTimeUnixNano"])
    title = attributes.get("gen_ai.response.model") or attributes.get("gen_ai.tool.name")
    return export.add(
        f"{operation} {title}" if title else operation,
        at,
        at,
        source,
        parent,
        kind=3 if operation == "chat" else 1,
        attributes={"gen_ai.operation.name": operation, **attributes},
    )


def _session_calls(
    export: _Export,
    folder: Path,
    manifest: dict[str, Any],
    root: dict[str, Any],
    turns: dict[int, dict[str, Any]],
    windows: list[tuple[float, float]],
) -> None:
    sessions = manifest.get("model_sessions")
    for session in sessions if isinstance(sessions, list) else []:
        if not isinstance(session, dict):
            continue
        harness, rel = session.get("harness"), session.get("file")
        if (
            not isinstance(harness, str)
            or harness not in performance.READERS
            or not isinstance(rel, str)
        ):
            continue
        path = (folder / rel).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            continue
        for call in performance.READERS[harness](path):
            ts = call["ts"]
            parent = turns.get(trace._turn(ts, windows) or 0, root)
            _call_span(
                export,
                parent,
                "chat",
                "session",
                ts,
                {
                    "nookku.source.file": _name(rel),
                    "gen_ai.usage.input_tokens": call["input_tokens"],
                    "gen_ai.usage.output_tokens": call["output_tokens"],
                },
            )


def _item_span(export: _Export, parent: dict[str, Any], item: dict[str, Any]) -> None:
    harness, kind = item.get("harness"), item.get("kind")
    evidence = _source(item.get("source"))
    if harness in ("model_api", "gateway") and item.get("role") == "assistant":
        info = item["input"] if isinstance(item.get("input"), dict) else {}
        read_usage = (
            performance.anthropic_tokens
            if performance._anthropic_usage(item, info)
            else performance.openai_tokens
        )
        used = (None, None) if "cut" in info else read_usage(info.get("usage"))
        span = _call_span(
            export,
            parent,
            "chat",
            "proxy" if harness == "model_api" else "gateway",
            item.get("ts"),
            {
                **evidence,
                "gen_ai.response.model": _name(info.get("model")),
                "gen_ai.usage.input_tokens": used[0],
                "gen_ai.usage.output_tokens": used[1],
            },
        )
    elif kind in ("tool_call", "http", "query") and not item.get("harness_internal"):
        source = (
            "app_otel"
            if harness in ("otel", "driver")
            else "proxy"
            if harness in ("backend", "mcp", "database", "model_api")
            else "session"
        )
        span = _call_span(
            export,
            parent,
            "execute_tool",
            source,
            item.get("ts"),
            {**evidence, "gen_ai.tool.name": _name(item.get("name")) or kind},
        )
    else:
        return
    status = item.get("exit_code")
    if item.get("error") is not None or (type(status) is int and status >= 400):
        span["status"] = {"code": 2}


def build(folder: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Build OTLP JSON from the validated tap record and rebuilt trace and findings."""
    manifest = read_manifest(folder)
    exchanges = trace._exchanges(folder / "tap.jsonl")
    bounds = trace.windows(exchanges)
    begin = _stamp(manifest.get("started"))
    if begin is None and exchanges:
        begin = _stamp(exchanges[0].get("started")) or _stamp(exchanges[0].get("ts"))
    start = begin if begin is not None else 0
    stop = _stamp(manifest.get("ended"))
    export = _Export(folder.name, start)
    root = export.add("nookku test", start, stop or start, "tap")
    turns = {}
    prior = start
    for n, exchange in enumerate(exchanges, 1):
        started, ended = _stamp(exchange.get("started")), _stamp(exchange.get("ts"))
        t0 = prior if started is None else started
        t1 = t0 if ended is None else max(t0, ended)
        turns[n] = export.add(
            "invoke_agent",
            t0,
            t1,
            "tap",
            root,
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "nookku.turn": n,
                "nookku.source.file": "tap.jsonl",
            },
        )
        prior = t1
    _session_calls(export, folder, manifest, root, turns, bounds)
    path = folder / "trace.jsonl"
    for line, item in trace._lines(path, Counter()):
        if not isinstance(item, dict):
            raise RecordError("record_invalid", path, f"line {line}: not a trace item")
        _item_span(export, turns.get(item.get("turn") or 0, root), item)

    root["startTimeUnixNano"] = str(min(int(s["startTimeUnixNano"]) for s in export.spans))
    root["endTimeUnixNano"] = str(max(int(s["endTimeUnixNano"]) for s in export.spans))
    for finding in report["findings"]:
        parent = turns.get(finding.get("turn") or 0, root)
        parent.setdefault("events", []).append(
            {
                "timeUnixNano": parent["endTimeUnixNano"],
                "name": "gen_ai.evaluation.result",
                "attributes": _attributes(
                    {
                        "gen_ai.evaluation.name": _name(finding.get("check")),
                        "gen_ai.evaluation.score.label": "fail",
                        **_source(finding.get("source")),
                    }
                ),
            }
        )
    return export.result()


def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def _protobuf(message: dict[str, Any], schema: otlp.Schema) -> bytes:
    """Encode the field kinds used by the export with the receiver's OTLP schema."""
    out = bytearray()
    for number, (name, kind, repeated) in schema.items():
        if name not in message:
            continue
        values = message[name] if repeated else [message[name]]
        for value in values:
            wire = 2 if isinstance(kind, dict) else otlp.WIRE[kind]
            if isinstance(kind, dict):
                data = _protobuf(value, kind)
            elif kind == "bytes":
                data = bytes.fromhex(value)
            elif kind == "string":
                data = value.encode()
            elif kind == "fixed64":
                data = struct.pack("<Q", int(value))
            elif kind in ("varint", "int64"):
                data = _varint(int(value))
            else:
                raise ExportError(f"unsupported OTLP field kind {kind}")
            out += _varint(number << 3 | wire)
            if wire == 2:
                out += _varint(len(data))
            out += data
    return bytes(out)


def _headers() -> dict[str, str]:
    raw = os.environ.get(_HEADERS, os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", ""))
    headers = {"Content-Type": "application/x-protobuf"}
    for pair in raw.split(",") if raw else []:
        key, eq, value = pair.partition("=")
        key, value = unquote(key.strip()), unquote(value.strip())
        if (
            not eq
            or not _HEADER_NAME.fullmatch(key)
            or key.lower() in _RESERVED
            or any(not 32 <= ord(c) <= 126 for c in value)
        ):
            raise ExportError(f"{_HEADERS} has an invalid header")
        headers[key] = value
    return headers


def send(endpoint: str, data: dict[str, Any]) -> None:
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        raise ExportError("the OTLP endpoint URL is not valid") from None
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.fragment
        or (url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"))
    ):
        raise ExportError("the OTLP endpoint must use HTTPS or HTTP on this computer")
    path = url.path if url.path not in ("", "/") else "/v1/traces"
    if url.query:
        path += "?" + url.query
    cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = cls(url.hostname, port, timeout=30)
    try:
        conn.request("POST", path, _protobuf(data, otlp.TRACES), _headers())
        reply = conn.getresponse()
        if reply.status != 200:
            raise ExportError(f"the OTLP collector returned HTTP {reply.status}")
        raw = reply.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ExportError("the OTLP collector response is too large")
        if "json" in (reply.getheader("Content-Type") or ""):
            ack = loads(raw) if raw else {}
        else:
            ack = otlp.decode(raw, _RESPONSE)
        rejected = ack.get("partialSuccess", {}).get("rejectedSpans", 0)
        try:
            count = int(rejected)
        except (TypeError, ValueError, OverflowError):
            raise ExportError("the OTLP collector response is not valid") from None
        if count:
            raise ExportError("the OTLP collector rejected spans")
    except (OSError, http.client.HTTPException, UnicodeError, TypeError, AttributeError) as e:
        raise ExportError(
            f"could not send spans to the OTLP collector ({type(e).__name__})"
        ) from None
    except (json.JSONDecodeError, otlp.DecodeError):
        raise ExportError("the OTLP collector response is not valid") from None
    finally:
        conn.close()


def write(path: Path, folder: Path, data: dict[str, Any]) -> None:
    if path.resolve().is_relative_to(folder.resolve()):
        raise ExportError("choose an OTLP output file outside the test folder")
    fd, temporary = tempfile.mkstemp(prefix=".nookku-otlp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

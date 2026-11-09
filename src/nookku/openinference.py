"""Import app spans and compare them with independent proxy evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import otlp
from .egress_spans import _time
from .record import RecordError, json_text, loads

FILE = "openinference.jsonl"
LIMIT = 32 * 1024 * 1024
SKEW = 1.0
_MODEL = {"LLM", "DECISION", "GENERATION", "EMBEDDING"}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(*values: Any) -> str | None:
    return next((v for v in values if isinstance(v, str) and v.strip() and v.isprintable()), None)


def _seconds(value: Any) -> float | None:
    if type(value) in (int, float) and 0 <= value < 1e15:
        return float(value)
    return _time(value)


def _http_path(url: str) -> str | None:
    try:
        return urlsplit(url).path or "/"
    except ValueError:
        return None


def _call(kind: str, name: str, attrs: dict[str, Any], model: Any) -> list[str] | None:
    method = _text(attrs.get("http.request.method"), attrs.get("http.method"))
    url = _text(attrs.get("url.full"), attrs.get("http.url"), attrs.get("url.path"))
    if method and url and (path := _http_path(url)) is not None:
        return ["http", f"{method.upper()} {path}"]
    operation = _text(attrs.get("db.operation.name"), attrs.get("db.operation"))
    statement = _text(attrs.get("db.query.text"), attrs.get("db.statement"))
    if operation or statement:
        return ["query", (operation or statement or "").split()[0].upper()]
    if kind == "TOOL":
        tool = _text(attrs.get("tool.name"), attrs.get("mcp.tool.name"), name)
        return ["tool", tool] if tool else None
    if kind in _MODEL:
        found = _text(attrs.get("llm.model_name"), attrs.get("embedding.model_name"), model)
        return ["model", found] if found else None
    return None


def _span(row: dict[str, Any], form: str) -> dict[str, Any]:
    if form == "langfuse":
        attrs = _object(row.get("metadata"))
        attrs = {**attrs, **_object(attrs.get("attributes"))}
        kind = _text(attrs.get("openinference.span.kind"), row.get("type"))
        ids = row.get("traceId"), row.get("id")
        start, end = _seconds(row.get("startTime")), _seconds(row.get("endTime"))
    elif form == "otlp":
        attrs = _object(row.get("attributes"))
        kind = _text(attrs.get("openinference.span.kind"))
        ids = row.get("trace_id"), row.get("span_id")
        start, end = _seconds(row.get("start")), _seconds(row.get("end"))
    else:
        attrs = {
            **_object(row.get("attributes")),
            **{
                k.removeprefix("attributes."): v
                for k, v in row.items()
                if k.startswith("attributes.")
            },
        }
        kind = _text(attrs.get("openinference.span.kind"), row.get("span_kind"))
        context = _object(row.get("context"))
        ids = (
            _text(row.get("context.trace_id"), context.get("trace_id")),
            _text(row.get("context.span_id"), context.get("span_id")),
        )
        start, end = _seconds(row.get("start_time")), _seconds(row.get("end_time"))
    trace_id, span_id = (_text(v) for v in ids)
    name = _text(row.get("name"))
    if not trace_id or not span_id or name is None or start is None or end is None or end < start:
        raise ValueError("an export row has invalid ids, name or times")
    kind = (kind or "SPAN").upper()
    return {
        "v": 1,
        "source": form,
        "trace_id": trace_id,
        "span_id": span_id,
        "name": name,
        "kind": kind,
        "start": start,
        "end": end,
        "call": _call(kind, name, attrs, row.get("model")),
    }


def _read(path: Path) -> bytes:
    try:
        with path.open("rb") as fh:
            data = fh.read(LIMIT + 1)
    except OSError as e:
        raise RecordError("record_missing", path, f"cannot read it: {e.strerror}") from None
    if len(data) > LIMIT:
        raise RecordError("record_invalid", path, "the span file is too large")
    return data


def _input(data: bytes) -> tuple[list[Any], str]:
    text = data.decode("utf-8")
    try:
        value = loads(text)
    except json.JSONDecodeError:
        values = [loads(line) for line in text.split("\n") if line.strip()]
        return values, "auto"
    if isinstance(value, list):
        return value, "auto"
    if isinstance(value, dict) and isinstance(value.get("resourceSpans"), list):
        return otlp.rows(value, 0.0), "otlp"
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        if _object(value.get("meta")).get("cursor"):
            raise ValueError("the export has more pages; combine the observations into one array")
        return list(value["data"]), "langfuse"
    if isinstance(value, dict) and ("start_time" in value or "startTime" in value):
        return [value], "auto"
    raise ValueError("expected an export of spans")


def import_bytes(path: Path) -> bytes:
    """Normalize an export to the fields that the trace and the match use."""
    try:
        records, form = _input(_read(path))
        found: dict[tuple[str, str], dict[str, Any]] = {}
        for raw in records:
            if not isinstance(raw, dict):
                raise ValueError("an export row is not an object")
            source = form
            if source == "auto":
                source = "langfuse" if "startTime" in raw else "phoenix"
            span = _span(raw, source)
            found.setdefault((span["trace_id"], span["span_id"]), span)
        return "".join(json_text(s) + "\n" for s in found.values()).encode()
    except (ValueError, TypeError, AttributeError) as e:
        raise RecordError("record_invalid", path, str(e)) from None


def read(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        lines = _read(path).decode("utf-8").split("\n")
        for n, line in enumerate(lines, 1):
            if not line:
                continue
            row = loads(line)
            if not isinstance(row, dict) or row.get("v") != 1:
                raise ValueError("an unsupported span row")
            if any(_text(row.get(k)) is None for k in ("trace_id", "span_id", "name", "kind")):
                raise ValueError("a span has invalid text fields")
            start, end = row.get("start"), row.get("end")
            if (
                not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not 0 <= start <= end < 1e15
            ):
                raise ValueError("a span has invalid times")
            call = row.get("call")
            if call is not None and (
                not isinstance(call, list) or len(call) != 2 or not all(_text(x) for x in call)
            ):
                raise ValueError("a span has an invalid call key")
            out.append({**row, "line": n})
    except ValueError as e:
        raise RecordError("record_invalid", path, str(e)) from None
    return out


def _proxy_call(item: dict[str, Any]) -> tuple[str, str] | None:
    harness, kind = item["harness"], item["kind"]
    name = _text(item["name"])
    if harness == "backend" and kind == "http" and name:
        return "http", name
    if harness == "database" and kind == "query" and name:
        return "query", name
    if harness == "mcp" and kind == "tool_call" and name:
        return "tool", name
    if harness == "model_api" and kind == "message" and item["role"] == "assistant":
        model = _text(_object(item["input"]).get("model"))
        return ("model", model) if model else None
    return None


def missing(items: list[dict[str, Any]], spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match calls once by key, turn and time. Give one finding per uncovered proxy call."""
    by_line = {span["line"]: span for span in spans}
    candidates: dict[tuple[int, tuple[str, str]], list[dict[str, Any]]] = {}
    for item in items:
        if item["harness"] != "openinference" or item["turn"] is None:
            continue
        span = by_line[item["source"]["line"]]
        if span.get("call") is not None:
            candidates.setdefault((item["turn"], tuple(span["call"])), []).append(span)
    out: list[dict[str, Any]] = []
    for item in items:
        key, ts, turn = _proxy_call(item), item["ts"], item["turn"]
        if key is None or turn is None or not isinstance(ts, (int, float)) or not 0 <= ts < 1e15:
            continue
        pool = candidates.get((turn, key), [])
        best = min(
            (s for s in pool if s["start"] - SKEW <= ts <= s["end"] + SKEW),
            key=lambda s: (abs(s["start"] - ts), s["line"]),
            default=None,
        )
        if best is not None:
            pool.remove(best)
        else:
            out.append(
                {
                    "check": "proxy_call_without_span",
                    "turn": turn,
                    "detail": f"{key[1]}: no matching span in the export",
                    "harness": item["harness"],
                    "session": item["session"],
                    "source": item["source"],
                }
            )
    return out

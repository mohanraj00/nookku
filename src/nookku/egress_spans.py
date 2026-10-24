"""The egress spans of Koodam as a trace source (SPEC.md section 8.8).

The Koodam egress proxy writes 1 span for each external call of a pod. The proxy is outside the
pod, so a call that goes around the proxies of nookku still has a span. The tester exports the
spans with `koodam trace` and gives the file to `nookku trace --egress`. The trace then reads
`egress.jsonl` in the test folder, with the version rules of the span contracts v1 and v2.
The reader uses no field that v2 removes or adds: `claimedRun`, `claimedUser`, `claimed`, and the
`path` of an `http` span.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .discovery import driver_address
from .model_api import APIS
from .record import RecordError

FILE = "egress.jsonl"
# The versions of the span contract that this reader knows. A span with no `v` is version 1.
VERSIONS = (1, 2)
VERSION = VERSIONS[-1]
# The kind of a model call of the harness through the gateway. The trace skips it.
LLM = "llm"
# An RFC 3339 time, with a fraction of any length. Python 3.10 cannot parse each such fraction.
RFC3339 = re.compile(
    r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)", re.IGNORECASE
)


def _time(value: Any) -> float | None:
    """Unix seconds from an RFC 3339 time, for example 2026-10-23T09:14:02.118Z, or None."""
    m = RFC3339.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        return None
    zone = "+00:00" if m[3].upper() == "Z" else m[3]
    try:
        whole = datetime.datetime.fromisoformat(m[1].upper() + zone).timestamp()
    except ValueError:
        return None
    # float() takes a fraction of any length. int() refuses more than 4300 digits.
    return whole + (float("0." + m[2]) if m[2] else 0.0)


def host_name(value: Any) -> str | None:
    """The host of a span `host` or `sni` value, with no port, in lowercase, with no dot at the
    end. `api.github.com:443` gives `api.github.com`, and `[::1]:443` gives `::1`."""
    if not isinstance(value, str):
        return None
    if value.startswith("["):
        end = value.find("]")
        value = value[1:end] if end > 0 else value
    elif value.count(":") == 1:
        value = value.split(":")[0]
    value = value.lower().rstrip(".")
    return value or None


def _version(span: dict[str, Any]) -> Any:
    """The contract version of a span: 1 if it has no `v`."""
    return span.get("v", VERSIONS[0])


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read(
    path: Path, start: Any, end: Any, ignore: list[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The spans of egress.jsonl in a test folder (parse)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise RecordError("record_missing", path, f"cannot read it: {e.strerror}") from None
    return parse(data, path, start, end, ignore)


def parse(
    data: bytes, path: Path, start: Any, end: Any, ignore: list[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The spans of the bytes of an egress file that the checks use, and the counts for
    findings.json.

    A span is kept if it is version 1 or 2, has a valid `time` in the window from `start` to `end`
    (both ends included; a bound that is not a number is open) and a `result`, is not of the kind
    `llm`, and its host is not in `ignore`. Each other line is counted by its reason. A span with
    a higher version stops the read with a RecordError, because its fields can have a new
    meaning."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RecordError("record_invalid", path, "not UTF-8") from None
    skip = {h for h in (host_name(x) for x in ignore) if h is not None}
    raws = text.split("\n")
    if raws[-1] == "":
        raws.pop()
    spans: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    rows = 0
    for n, raw in enumerate(raws, 1):
        if not raw.strip():
            ignored["blank"] += 1
            continue
        rows += 1
        try:
            span = json.loads(raw)
        except (ValueError, RecursionError):  # RecursionError: JSON that nests too deep
            span = None
        if not isinstance(span, dict):
            ignored["invalid_json"] += 1
            continue
        v = _version(span)
        if _number(v) and v > VERSION:
            raise RecordError(
                "record_invalid",
                path,
                f"line {n}: the span has the contract version {v}. This nookku reads version 1 "
                f"and version {VERSION} only (SPEC.md section 8.8). Use a nookku that reads "
                f"version {v}.",
            )
        ts = _time(span.get("time"))
        if (
            not (_number(v) and v in VERSIONS)
            or ts is None
            or not isinstance(span.get("result"), str)
        ):
            ignored["invalid"] += 1
            continue
        if (_number(start) and ts < start) or (_number(end) and ts > end):
            ignored["outside_window"] += 1
            continue
        if span.get("kind") == LLM:
            ignored[LLM] += 1
            continue
        host = host_name(span.get("host")) or host_name(span.get("sni"))
        if host is not None and host in skip:
            ignored["egress_ignore"] += 1
            continue
        spans.append({"line": n, "ts": ts, "host": host, "span": span})
    hosts = sorted({s["host"] for s in spans if s["host"] is not None})
    return spans, {
        "file": FILE,
        "rows": rows,
        "spans": len(spans),
        "hosts": hosts,
        "ignored": dict(ignored),
    }


def _url_host(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        return host_name(urlsplit(url).hostname)
    except ValueError:
        return None


def answer_hosts(answer: Any) -> set[str] | None:
    """The hosts of the egress answer of a test (SPEC.md section 7.11), or None if the manifest
    has no answer. A model API with no `url` has the host of the default URL of its API."""
    if not isinstance(answer, dict):
        return None
    out: set[str] = set()

    def parts(key: str) -> list[dict[str, Any]]:
        items = answer.get(key)
        return [p for p in items if isinstance(p, dict)] if isinstance(items, list) else []

    for p in parts("model_apis"):
        url = p.get("url")
        if url is None and p.get("api") in APIS:
            url = APIS[p["api"]][1]
        out.add(_url_host(url) or "")
    for key in ("backends", "mcp_servers"):
        out |= {_url_host(p.get("url")) or "" for p in parts(key)}
    for p in parts("databases"):
        where = driver_address(p.get("address"))
        if where is not None:
            out.add(host_name(where[0]) or "")
    out.discard("")
    return out


def _where(s: dict[str, Any]) -> dict[str, Any]:
    source = {"file": FILE, "line": s["line"]}
    return {"harness": "egress", "session": s["host"] or "", "source": source}


def not_in_discovery(spans: list[dict[str, Any]], hosts: set[str] | None) -> list[dict[str, Any]]:
    """The `egress_not_in_discovery` findings: 1 for each host of the spans that the egress answer
    does not have, at its first span. A test with no egress answer gives none. The match is by
    host: 1 span of a TLS connection can hold many calls."""
    if hosts is None:
        return []
    count: Counter[str] = Counter(s["host"] for s in spans if s["host"] is not None)
    out = []
    for s in spans:
        host = s["host"]
        if host is None or host in hosts or host not in count:
            continue
        n = count.pop(host)
        what = "1 span" if n == 1 else f"{n} spans"
        detail = f"{host}: {what}, and the egress answer has no part with this host"
        finding = {"check": "egress_not_in_discovery", "turn": None, "detail": detail}
        out.append({**finding, **_where(s)})
    return out


def denied(
    spans: list[dict[str, Any]], turn_of: Callable[[float], int | None]
) -> list[dict[str, Any]]:
    """The `egress_denied` findings: 1 for each span with the result `denied`. The check reads
    `result` only. `reason` is free text, so the detail shows it and no rule reads it."""
    out = []
    for s in spans:
        span = s["span"]
        if span.get("result") != "denied":
            continue
        kind = span.get("kind") if isinstance(span.get("kind"), str) else "span"
        port = span.get("port")
        target = (s["host"] or "no host") + (f" port {port}" if isinstance(port, str) else "")
        reason = span.get("reason")
        detail = f"{kind} {target}: denied" + (f" ({reason})" if isinstance(reason, str) else "")
        finding = {"check": "egress_denied", "turn": turn_of(s["ts"]), "detail": detail}
        out.append({**finding, **_where(s)})
    return out


def copy_in(data: bytes, folder: Path) -> None:
    """Write the bytes of an egress file to egress.jsonl in a test folder. The new file replaces
    the name, so a symlink at egress.jsonl is replaced and its target does not change."""
    fd, tmp = tempfile.mkstemp(prefix=".egress-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, folder / FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

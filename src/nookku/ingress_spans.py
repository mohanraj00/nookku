"""Ingress spans as a trace source (SPEC.md section 8.12).

An ingress proxy in front of an app can write 1 span for each request to the app: 1 JSON line
with a time, an HTTP status and an outcome. The tester gives the file to `nookku trace --ingress`.
The trace then reads `ingress.jsonl` in the test folder.

A span has no body and no path. Thus a span cannot replace a row of tap.jsonl, and the trace gives
only counts and the turn of each span by its time. One source of such spans is the App ingress
span of Koodam (contract v1, `docs/app-ingress-spans.md` in Koodam).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .egress_spans import _number, _time
from .record import RecordError

FILE = "ingress.jsonl"
# The versions of the span format that this reader knows. A span with no `v` is version 1.
VERSIONS = (1,)
VERSION = VERSIONS[-1]


def read(
    path: Path, start: Any, end: Any, turn: Callable[[float], int | None], turns: int
) -> dict[str, Any]:
    """The counts of ingress.jsonl in a test folder (parse)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise RecordError("record_missing", path, f"cannot read it: {e.strerror}") from None
    return parse(data, path, start, end, turn, turns)


def parse(
    data: bytes,
    path: Path,
    start: Any,
    end: Any,
    turn: Callable[[float], int | None],
    turns: int,
) -> dict[str, Any]:
    """The counts of the bytes of an ingress file, for findings.json.

    A span is kept if it is version 1 and has a valid `time` in the window from `start` to `end`
    (both ends included; a bound that is not a number is open), an integer `status` and a string
    `outcome`. Each other line is counted by its reason. A span with a higher version stops the
    read with a RecordError, because its fields can have a new meaning. `turn` gives the turn of a
    time, and `turns` is the count of the turns of the test."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RecordError("record_invalid", path, "not UTF-8") from None
    raws = text.split("\n")
    if raws[-1] == "":
        raws.pop()
    ignored: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    in_turn = [0] * turns
    rows = spans = no_turn = 0
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
        v = span.get("v", VERSIONS[0])
        if _number(v) and v > VERSION:
            raise RecordError(
                "record_invalid",
                path,
                f"line {n}: the span has the format version {v}. This nookku reads version "
                f"{VERSION} only (SPEC.md section 8.12). Use a nookku that reads version {v}.",
            )
        ts = _time(span.get("time"))
        status = span.get("status")
        if (
            not (_number(v) and v in VERSIONS)
            or ts is None
            or not isinstance(status, int)
            or isinstance(status, bool)
            or not isinstance(span.get("outcome"), str)
        ):
            ignored["invalid"] += 1
            continue
        if (_number(start) and ts < start) or (_number(end) and ts > end):
            ignored["outside_window"] += 1
            continue
        spans += 1
        outcomes[span["outcome"]] += 1
        k = turn(ts)
        if k is not None and 1 <= k <= turns:
            in_turn[k - 1] += 1
        else:
            no_turn += 1
    return {
        "file": FILE,
        "rows": rows,
        "spans": spans,
        "outcomes": dict(sorted(outcomes.items())),
        "turns": in_turn,
        "no_turn": no_turn,
        "ignored": dict(ignored),
    }

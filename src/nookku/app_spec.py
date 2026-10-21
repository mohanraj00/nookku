"""The trace points of the app spec, and the check that each one occurred (SPEC.md 7.2, 8.6).

The bridge reads the `Trace points` table of the spec files at the start of a test and writes
its rows into the manifest. The trace checks each row with a `When` form that it knows against
the items of each turn. It needs no model, so a test can check the result each time.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

SECTION = "trace points"
COLUMNS = ("name", "source", "when")
SOURCES = ("session", "backend", "model_api", "otel")
SESSION_HARNESSES = ("claude-code", "codex")
# The most trace points that the bridge records from all spec files (docs/limits.md).
MAX_POINTS = 200
# The most records of trace_points_unread, with the record of the limit of trace points.
MAX_RECORDS = 200
# CommonMark: 0 to 3 spaces before a heading or a code fence.
HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*))?$")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
CLOSE_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
EACH_TURN = re.compile(r"each turn", re.IGNORECASE)
# 9 digits at most: a longer number is not a turn of a test, and `int` stays fast.
ONE_TURN = re.compile(r"turn ([1-9][0-9]{0,8})", re.IGNORECASE)
EACH_CALL = re.compile(r"each (\S+) tool call", re.IGNORECASE)
NO_TABLE = "The section has no table with the columns Name, Source and When."
NO_ROWS = "The table of the section has no rows."
LIMIT = (
    f"The spec has more than {MAX_POINTS} trace points. This row and the next rows are not read."
)


def _cells(line: str) -> list[str] | None:
    """The cells of a Markdown table row, or None if the line has no `|`. The `|` at the start
    and at the end are optional, as in GitHub Markdown. A `\\|` is a `|` in a cell."""
    line = line.strip()
    if not re.search(r"(?<!\\)\|", line):
        return None
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    parts = re.split(r"(?<!\\)\|", line)
    return [p.strip().replace("\\|", "|") for p in parts]


def _plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def _heading(line: str) -> str | None:
    """The text of a Markdown heading line with no closing `#` marks, or None if the line is
    not a heading. The parse time is linear in the length of the line."""
    m = HEADING.match(line)
    if m is None:
        return None
    text = (m.group(2) or "").rstrip()
    bare = text.rstrip("#")
    if bare != text and (bare == "" or bare[-1] in " \t"):
        text = bare.rstrip()
    return text


def read(files: list[tuple[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """The trace points of the spec files, and a record of each part of a `Trace points`
    section that is not a trace point. `files` holds the path and the text of each file, in
    the order of the config. A section starts at a heading of any level with the text `Trace
    points`. It ends at the next heading or after its first table. The header row must have
    the columns Name, Source and When, in any order, and can have more columns. The reader
    skips the lines of a fenced code block."""
    reader = _Reader()
    for path, text in files:
        reader.file(path, text)
    return reader.points, reader.records()


class _Reader:
    def __init__(self) -> None:
        self.points: list[dict[str, str]] = []
        self.kept: list[dict[str, Any]] = []
        self.more = 0
        self.limit: dict[str, Any] | None = None

    def note(self, path: str, n: int, problem: str) -> None:
        if len(self.kept) < MAX_RECORDS:
            self.kept.append({"file": path, "line": n, "problem": problem})
        else:
            self.more += 1

    def records(self) -> list[dict[str, Any]]:
        """The records, 200 at most. The record of the limit of trace points always stays. If
        there are more records, the last kept record gives the count of the others."""
        tail = [self.limit] if self.limit else []
        room = MAX_RECORDS - len(tail)
        kept = self.kept
        if len(kept) + self.more > room:
            first, more = kept[room - 1], len(kept) + self.more - room
            problem = f"This part and {more} more parts of the sections are not trace points."
            kept = [*kept[: room - 1], {**first, "problem": problem}]
        return kept + tail

    def file(self, path: str, text: str) -> None:
        start: int | None = None
        columns: list[str] | None = None
        rows = 0
        fence: str | None = None

        def close() -> None:
            if start is not None and (columns is None or rows == 0):
                self.note(path, start, NO_TABLE if columns is None else NO_ROWS)

        for n, line in enumerate(text.splitlines(), 1):
            if fence is not None:
                end = CLOSE_FENCE.fullmatch(line)
                if end and end.group(1).startswith(fence) and set(end.group(1)) == {fence[0]}:
                    fence = None
                continue
            if m := FENCE.match(line):
                fence = m.group(1)
                if columns is not None:
                    close()
                    start, columns = None, None
                continue
            heading = _heading(line)
            cells = None if heading is not None else _cells(line)
            if heading is not None or (cells is None and columns is not None):
                close()
                start, columns = None, None
            if heading is not None:
                if heading.lower() == SECTION:
                    start, rows = n, 0
                continue
            if start is None or cells is None:
                continue
            if columns is None:
                columns = [_plain(c).lower() for c in cells]
                if not all(c in columns for c in COLUMNS):
                    columns = None
                    close()
                    start = None
                continue
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue
            rows += 1
            self.row(path, n, columns, cells)
        close()

    def row(self, path: str, n: int, columns: list[str], cells: list[str]) -> None:
        row = dict(zip(columns, cells, strict=False))
        if len(cells) != len(columns):
            self.note(
                path, n, f"The row has {len(cells)} cells, and the header has {len(columns)}."
            )
        elif not _plain(row["name"]):
            self.note(path, n, "The row has no Name.")
        elif len(self.points) >= MAX_POINTS:
            if self.limit is None:
                self.limit = {"file": path, "line": n, "problem": LIMIT}
        else:
            name, source = _plain(row["name"]), _plain(row["source"])
            self.points.append({"name": name, "source": source, "when": row["when"]})


def rule(point: dict[str, Any]) -> tuple[str, Any] | None:
    """The form of the When of a trace point: ("each_turn", None), ("turn", N) or
    ("each_call", tool). None if the trace cannot check it: an unknown source or another When.
    """
    if point.get("source") not in SOURCES:
        return None
    when = _plain(str(point.get("when", ""))).removesuffix(".").strip()
    if EACH_TURN.fullmatch(when):
        return ("each_turn", None)
    if m := ONE_TURN.fullmatch(when):
        return ("turn", int(m.group(1)))
    if m := EACH_CALL.fullmatch(when):
        return ("each_call", m.group(1))
    return None


def _tool_names(it: dict[str, Any]) -> list[str]:
    """The names of a tool call: its name and, for an MCP tool, its full name
    `mcp__<server>__<tool>`."""
    names = [str(it["name"])]
    if it.get("server"):
        names.append(f"mcp__{it['server']}__{it['name']}")
    return names


def _keys(it: dict[str, Any]) -> list[tuple[str, str]]:
    """The (source, name) of each trace point that a trace item shows
    (docs/reference/app-spec.md, Trace points)."""
    kind, harness, role = str(it["kind"]), str(it["harness"]), it["role"]
    if harness in SESSION_HARNESSES:
        if kind == "tool_call" and it["name"] is not None:
            return [("session", n) for n in _tool_names(it)]
        return [("session", str(role))] if kind == "message" and role else []
    if kind == "http":
        return [("backend", f"{it['session']} {it['name']}")]
    if harness == "model_api":
        return [("model_api", str(it["session"]))] if role == "assistant" else []
    if harness == "otel" and kind in ("span", "log"):
        return [("otel", str(it["name"]))]
    return []


class Index:
    """The count of the items of each trace point and of each app tool call in each turn. The
    check reads the items one time, so its cost is the items plus the trace points."""

    def __init__(self, items: list[dict[str, Any]], turns: int) -> None:
        self.turns = turns
        self.seen: Counter[tuple[str, str, int]] = Counter()
        self.calls: dict[str, Counter[int]] = {}
        for it in items:
            turn = it["turn"]
            if turn is None:
                continue
            for source, name in _keys(it):
                self.seen[(source, name, turn)] += 1
            app_call = it["kind"] == "tool_call" and not it["harness_internal"]
            if app_call and it["harness"] in SESSION_HARNESSES and it["name"] is not None:
                for name in _tool_names(it):
                    self.calls.setdefault(name, Counter())[turn] += 1

    def need(self, point: dict[str, Any]) -> dict[int, int] | None:
        """The count of items that each turn needs for the trace point, or None if the trace
        cannot check its When. A `Turn N` after the last turn needs nothing."""
        form = rule(point)
        if form is None:
            return None
        if form[0] == "each_turn":
            return dict.fromkeys(range(1, self.turns + 1), 1)
        if form[0] == "turn":
            return {form[1]: 1} if form[1] <= self.turns else {}
        return dict(sorted(self.calls.get(form[1], Counter()).items()))


def missing(
    points: list[dict[str, str]], items: list[dict[str, Any]], turns: int
) -> list[tuple[int, str]]:
    """The turn and the detail of each trace point that did not occur in a turn where its When
    needs it. A turn needs as many items as its When gives: 1 for `Each turn` and `Turn N`, and
    1 for each tool call for `Each <tool> tool call`."""
    index, out = Index(items, turns), []
    for point in points:
        form = rule(point)
        for turn, count in (index.need(point) or {}).items():
            found = index.seen[(point["source"], point["name"], turn)]
            if found < count:
                detail = f"{point['name']} ({point['source']}): {found} of {count} items"
                if form is not None and form[0] == "each_call":
                    calls = "tool call" if count == 1 else "tool calls"
                    detail += f" for {count} {form[1]} {calls}"
                out.append((turn, f"{detail} in this turn. When: {_plain(point['when'])}"))
    return out


def summary(points: Any, items: list[dict[str, Any]], turns: int) -> list[dict[str, Any]] | None:
    """Each trace point of the manifest with `needed`, the count of items that the turns of
    the test needed, and `checked`, true if `needed` is 1 or more. `needed` is null if the trace
    cannot check the When. None if the manifest has no valid trace point."""
    index = Index(items, turns)
    out = []
    for p in valid(points):
        need = index.need(p)
        needed = None if need is None else sum(need.values())
        out.append({**p, "checked": bool(needed), "needed": needed})
    return out or None


def valid(points: Any) -> list[dict[str, str]]:
    """The trace points of a manifest that have a string name, source and when."""
    if not isinstance(points, list):
        return []
    keys = ("name", "source", "when")
    return [
        {k: p[k] for k in keys}
        for p in points
        if isinstance(p, dict) and all(isinstance(p.get(k), str) for k in keys)
    ]


def unread(records: Any) -> list[str]:
    """The detail of each record of the manifest key `trace_points_unread`, 200 at most. If
    there are more, the last detail gives their count."""
    if not isinstance(records, list):
        return []
    out = []
    for r in records:
        if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("file", "problem")):
            line = r.get("line")
            where = f" line {line}" if isinstance(line, int) else ""
            out.append(f"{r['file']}{where}: {r['problem']} The trace does not check it.")
    if len(out) > MAX_RECORDS:
        more = len(out) - MAX_RECORDS + 1
        out = [*out[: MAX_RECORDS - 1], f"{more} more records of trace_points_unread."]
    return out

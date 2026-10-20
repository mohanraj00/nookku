"""The trace points of the app spec, and the check that each one occurred (SPEC.md 7.2, 8.6).

The bridge reads the `Trace points` table of the spec files at the start of a test and writes
its rows into the manifest. The trace checks each row with a `When` form that it knows against
the items of each turn. It needs no model, so a test can check the result each time.
"""

from __future__ import annotations

import re
from typing import Any

SECTION = "trace points"
HEADER = ["name", "source", "when"]
SOURCES = ("session", "backend", "model_api", "otel")
SESSION_HARNESSES = ("claude-code", "codex")
EACH_TURN = re.compile(r"each turn", re.IGNORECASE)
ONE_TURN = re.compile(r"turn ([1-9][0-9]*)", re.IGNORECASE)
EACH_CALL = re.compile(r"each (\S+) tool call", re.IGNORECASE)


def _cells(line: str) -> list[str] | None:
    """The cells of a Markdown table row, or None if the line is not a row. A `\\|` is a `|`
    in a cell."""
    line = line.strip()
    if not (line.startswith("|") and line.endswith("|") and len(line) > 1):
        return None
    parts = re.split(r"(?<!\\)\|", line[1:-1])
    return [p.strip().replace("\\|", "|") for p in parts]


def _plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def read(texts: list[str]) -> list[dict[str, str]]:
    """The rows of the first table under each `## Trace points` heading of the texts, in the
    order of the texts. The table must have the columns Name, Source and When. A row with
    another count of cells, or with an empty Name, is not a trace point."""
    out = []
    for text in texts:
        inside, table = False, None
        for line in text.splitlines():
            heading = re.match(r"(#{1,6})\s+(.*?)\s*#*\s*$", line)
            if heading and len(heading.group(1)) <= 2:
                inside, table = heading.group(2).strip().lower() == SECTION, None
                continue
            if not inside:
                continue
            cells = _cells(line)
            if cells is None:
                if table is not None:
                    inside = False
                continue
            if table is None:
                table = [c.lower() for c in cells] == HEADER
                if not table:
                    inside = False
                continue
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue
            if len(cells) == len(HEADER) and _plain(cells[0]):
                name, source, when = cells
                out.append({"name": _plain(name), "source": _plain(source), "when": when})
    return out


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


def matches(point: dict[str, str], it: dict[str, Any]) -> bool:
    """True if a trace item shows the trace point (docs/reference/app-spec.md, Trace points)."""
    name, source = point["name"], point["source"]
    kind, harness, role = str(it["kind"]), str(it["harness"]), it["role"]
    if source == "session":
        if harness not in SESSION_HARNESSES:
            return False
        tool = kind == "tool_call" and it["name"] == name
        return tool or (kind == "message" and role == name)
    if source == "backend":
        return kind == "http" and f"{it['session']} {it['name']}" == name
    if source == "model_api":
        return harness == "model_api" and role == "assistant" and it["session"] == name
    return harness == "otel" and kind in ("span", "log") and it["name"] == name


def _tool_calls(items: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    return [
        it
        for it in items
        if it["harness"] in SESSION_HARNESSES
        and it["kind"] == "tool_call"
        and it["name"] == tool
        and not it["harness_internal"]
    ]


def missing(
    points: list[dict[str, str]], items: list[dict[str, Any]], turns: int
) -> list[tuple[int, str]]:
    """The turn and the detail of each trace point that did not occur in a turn where its When
    needs it. A turn needs as many items as its When gives: 1 for `Each turn` and `Turn N`, and
    1 for each tool call for `Each <tool> tool call`. A `Turn N` after the last turn needs
    nothing."""
    out = []
    for point in points:
        form = rule(point)
        if form is None:
            continue
        seen = [it["turn"] for it in items if matches(point, it)]
        need = dict.fromkeys(range(1, turns + 1), 1) if form[0] == "each_turn" else {}
        if form[0] == "turn" and form[1] <= turns:
            need[form[1]] = 1
        if form[0] == "each_call":
            for it in _tool_calls(items, form[1]):
                if it["turn"] is not None:
                    need[it["turn"]] = need.get(it["turn"], 0) + 1
        for turn in sorted(need):
            found = seen.count(turn)
            if found < need[turn]:
                detail = f"{point['name']} ({point['source']}): {found} of {need[turn]} items"
                if form[0] == "each_call":
                    calls = "tool call" if need[turn] == 1 else "tool calls"
                    detail += f" for {need[turn]} {form[1]} {calls}"
                out.append((turn, f"{detail} in this turn. When: {_plain(point['when'])}"))
    return out


def summary(points: Any) -> list[dict[str, Any]] | None:
    """Each trace point of the manifest with `checked`: true if the trace checks its When.
    None if the manifest has no trace points."""
    if not isinstance(points, list):
        return None
    return [{**p, "checked": rule(p) is not None} for p in valid(points)]


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

"""The audit of SPEC.md section 3: compare the relay record with the tap record."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from verbatim_relay.record import (
    BlockedCall,
    Exchange,
    RecordError,
    Turn,
    Unparsed,
    read_relay,
    read_tap,
)

CHECKS = [
    "altered_input",
    "injected_input",
    "duplicate_send",
    "out_of_order",
    "not_delivered",
    "altered_reply",
    "unshown_reply",
]
EXCERPT = 24


@dataclass
class Finding:
    kind: str
    relay_line: int | None
    tap_line: int | None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "class": self.kind,
            "relay_line": self.relay_line,
            "tap_line": self.tap_line,
            "evidence": self.evidence,
        }


@dataclass
class Report:
    exit: int
    turns: int = 0
    exchanges: int = 0
    blocked_calls: int = 0
    breaks: list[Finding] = field(default_factory=list)
    notes: list[Finding] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "v": "0.1",
            "exit": self.exit,
            "turns": self.turns,
            "exchanges": self.exchanges,
            "blocked_calls": self.blocked_calls,
            "breaks": [b.as_dict() for b in self.breaks],
            "notes": [n.as_dict() for n in self.notes],
            "errors": self.errors,
            "skipped": self.skipped,
        }


def difference(expected: str, actual: str) -> dict[str, Any]:
    """Locate the first character where two texts differ, with an excerpt of each side."""
    i = next(
        (k for k, (a, b) in enumerate(zip(expected, actual, strict=False)) if a != b),
        min(len(expected), len(actual)),
    )
    start = max(0, i - EXCERPT // 2)
    return {
        "first_difference": i,
        "expected": expected[start : start + EXCERPT],
        "actual": actual[start : start + EXCERPT],
        "expected_length": len(expected),
        "actual_length": len(actual),
    }


def _anchors(turns: list[Turn], exchanges: list[Exchange]) -> list[tuple[int, int]]:
    """Return index pairs of a longest common subsequence, built in file order (SPEC 3.2 step 1)."""
    n, m = len(turns), len(exchanges)
    longest = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if turns[i].said == exchanges[j].input:
                longest[i][j] = 1 + longest[i + 1][j + 1]
            else:
                longest[i][j] = max(longest[i + 1][j], longest[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if turns[i].said == exchanges[j].input and longest[i][j] == 1 + longest[i + 1][j + 1]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif longest[i + 1][j] == longest[i][j]:
            i += 1
        else:
            j += 1
    return pairs


def compare(turns: list[Turn], exchanges: list[Exchange]) -> tuple[list[Finding], list[Finding]]:
    """Return (breaks, notes) for two valid records."""
    breaks: list[Finding] = []
    anchors = _anchors(turns, exchanges)
    pairs = list(anchors)
    free_t = [i for i in range(len(turns)) if i not in {a for a, _ in anchors}]
    free_e = [j for j in range(len(exchanges)) if j not in {b for _, b in anchors}]

    # Step 2: a message that arrived at another position.
    for i in list(free_t):
        j = next((j for j in free_e if exchanges[j].input == turns[i].said), None)
        if j is not None:
            free_t.remove(i)
            free_e.remove(j)
            pairs.append((i, j))
            breaks.append(Finding("out_of_order", turns[i].line, exchanges[j].line))

    # Step 3: an extra copy of a message that the tester typed.
    said = {t.said for t in turns}
    for j in [j for j in free_e if exchanges[j].input in said]:
        free_e.remove(j)
        breaks.append(Finding("duplicate_send", None, exchanges[j].line))

    # Step 4: pair what is left in each gap between adjacent anchors as changed input.
    bounds = [(-1, -1), *anchors, (len(turns), len(exchanges))]
    for (ti, ej), (tk, ek) in pairwise(bounds):
        gap_t = [i for i in free_t if ti < i < tk]
        gap_e = [j for j in free_e if ej < j < ek]
        for i, j in zip(gap_t, gap_e, strict=False):
            free_t.remove(i)
            free_e.remove(j)
            pairs.append((i, j))
            breaks.append(
                Finding(
                    "altered_input",
                    turns[i].line,
                    exchanges[j].line,
                    difference(turns[i].said, exchanges[j].input),
                )
            )

    # Step 5: what is still left.
    breaks += [Finding("injected_input", None, exchanges[j].line) for j in free_e]
    breaks += [Finding("not_delivered", turns[i].line, None) for i in free_t]

    # Step 6: the reply of each pair.
    notes: list[Finding] = []
    for i, j in pairs:
        t, e = turns[i], exchanges[j]
        if e.status is None or not 200 <= e.status < 300:
            notes.append(Finding("agent_error", t.line, e.line, {"status": e.status}))
        elif t.shown is None:
            breaks.append(Finding("unshown_reply", t.line, e.line))
        elif t.shown != e.reply:
            assert e.reply is not None  # record.py rejects a 2xx exchange without a reply
            breaks.append(Finding("altered_reply", t.line, e.line, difference(e.reply, t.shown)))

    def order(f: Finding) -> tuple[int, int, int]:
        big = 1 << 30
        return (
            f.relay_line or big,
            f.tap_line or big,
            CHECKS.index(f.kind) if f.kind in CHECKS else 0,
        )

    return sorted(breaks, key=order), sorted(notes, key=order)


def audit(tap_path: Path, relay_path: Path) -> Report:
    errors, tap_rows, relay_rows = [], None, None
    for name, path, reader in (("tap", tap_path, read_tap), ("relay", relay_path, read_relay)):
        try:
            rows = reader(path)
        except RecordError as e:
            errors.append({"class": e.kind, "record": name, "detail": str(e)})
            continue
        if name == "tap":
            tap_rows = rows
        else:
            relay_rows = rows
    for row in tap_rows or []:
        if isinstance(row, Unparsed):
            errors.append(
                {
                    "class": "tap_unparsed",
                    "record": "tap",
                    "detail": f"line {row.line}: {row.method} {row.path}: {row.error}",
                }
            )
    if errors:
        return Report(exit=2, errors=errors, skipped=list(CHECKS))
    assert tap_rows is not None and relay_rows is not None
    turns = [r for r in relay_rows if isinstance(r, Turn)]
    exchanges = [r for r in tap_rows if isinstance(r, Exchange)]
    breaks, notes = compare(turns, exchanges)
    return Report(
        exit=1 if breaks else 0,
        turns=len(turns),
        exchanges=len(exchanges),
        blocked_calls=sum(isinstance(r, BlockedCall) for r in relay_rows),
        breaks=breaks,
        notes=notes,
    )


def render(report: Report) -> str:
    """A short text report for a terminal."""
    out = []
    if report.errors:
        out += [f"ERROR {e['class']}: {e['detail']}" for e in report.errors]
        out.append("Skipped checks: " + ", ".join(report.skipped))
        out.append("Result: the audit cannot run (exit 2)")
        return "\n".join(out)
    for b in report.breaks:
        where = f"relay line {b.relay_line or '-'}, tap line {b.tap_line or '-'}"
        line = f"BREAK {b.kind:<15} {where}"
        if "first_difference" in b.evidence:
            ev = b.evidence
            line += (
                f": first difference at character {ev['first_difference']}:"
                f" expected {ev['expected']!r}, got {ev['actual']!r}"
            )
        out.append(line)
    for n in report.notes:
        out.append(f"NOTE  {n.kind:<15} relay line {n.relay_line}, tap line {n.tap_line}")
    out.append(
        f"{report.turns} turns, {report.exchanges} exchanges, "
        f"{report.blocked_calls} blocked model calls, {len(report.breaks)} breaks"
    )
    out.append("Result: " + ("clean (exit 0)" if report.exit == 0 else "breaks found (exit 1)"))
    return "\n".join(out)

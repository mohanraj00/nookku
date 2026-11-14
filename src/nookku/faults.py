"""The seeded faults of the trace checks (ADR 0002, #546). A seeded fault is a trace case of
the conformance suite that expects a finding of a check. `nookku faults` runs the trace on the
records of each case, with no model, and names each fault that a check misses."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import __version__, trace
from .record import RecordError

# The file of a trace case that names its seeded faults: the check and the turn of each one.
FILE = "faults.json"
# The cases of the trace in a checkout of the repo.
CASES = Path("conformance") / "trace"


def declared(case: Path) -> list[dict[str, Any]]:
    """The seeded faults of a trace case, from its faults.json. Raise ValueError if the file is
    not valid."""
    try:
        data = json.loads((case / FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"{case / FILE}: {e}") from None
    faults = data.get("faults") if isinstance(data, dict) else None
    if not isinstance(faults, list) or not faults or not all(map(_valid, faults)):
        raise ValueError(f"{case / FILE}: faults must be a list of a check and a turn")
    return [{"check": f["check"], "turn": f["turn"]} for f in faults]


def _valid(fault: Any) -> bool:
    return (
        isinstance(fault, dict)
        and fault.get("check") in trace.CHECKS
        and "turn" in fault
        and (fault["turn"] is None or type(fault["turn"]) is int)
    )


def _found(case: Path) -> tuple[set[tuple[str, int | None]], str | None]:
    """The check and the turn of each finding of the trace of a case, or the error."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "test"
        shutil.copytree(case, folder, ignore=shutil.ignore_patterns("expect_*", FILE))
        try:
            report = trace.build(folder)
        except RecordError as e:
            return set(), str(e).replace(str(folder), case.name)
    return {(f["check"], f["turn"]) for f in report["findings"]}, None


def run(cases: Path) -> dict[str, Any]:
    """Run the trace on each case of `cases` that has a faults.json. The result has each fault
    and its result, each check with no seeded fault, and `ok`. Raise ValueError if a faults.json
    is not valid, or if `cases` has no case."""
    folders = sorted(p for p in cases.iterdir() if (p / FILE).is_file())
    if not folders:
        raise ValueError(f"{cases} has no trace case with a file {FILE}")
    faults: list[dict[str, Any]] = []
    for case in folders:
        expected = declared(case)
        found, error = _found(case)
        for f in expected:
            hit = (f["check"], f["turn"]) in found
            faults.append({"case": case.name, **f, "found": hit, "error": error})
    seeded = {f["check"] for f in faults}
    missed = [f for f in faults if not f["found"]]
    unseeded = [c for c in trace.CHECKS if c not in seeded]
    return {
        "nookku": __version__,
        "cases": len(folders),
        "checks": len(trace.CHECKS),
        "faults": faults,
        "missed": len(missed),
        "unseeded": unseeded,
        "ok": not missed and not unseeded,
    }


def render(result: dict[str, Any]) -> str:
    """The text report: one line for each fault, then the result."""
    lines = []
    for f in result["faults"]:
        state = "found " if f["found"] else "MISSED"
        turn = "no turn" if f["turn"] is None else f"turn {f['turn']}"
        line = f"{state} {f['check']} ({turn}) in {f['case']}"
        lines.append(line + (f": {f['error']}" if f["error"] else ""))
    for check in result["unseeded"]:
        lines.append(f"NO FAULT {check}: no trace case has a seeded fault of this check")
    n = len(result["faults"])
    lines.append(
        f"Nookku {result['nookku']}: {n - result['missed']} of {n} seeded faults found in "
        f"{result['cases']} trace cases. {result['checks'] - len(result['unseeded'])} of "
        f"{result['checks']} checks have a seeded fault."
    )
    return "\n".join(lines)

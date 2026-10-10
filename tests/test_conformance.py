import json
from pathlib import Path

import pytest

from nookku.audit import audit
from nookku.record import RecordError, read_rows

ROOT = Path(__file__).resolve().parent.parent
CASES = sorted((ROOT / "conformance" / "cases").iterdir())


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case(case: Path) -> None:
    expect = json.loads((case / "expect.json").read_text())
    report = audit(case / "tap.jsonl", case / "relay.jsonl")
    assert report.exit == expect["exit"]
    if report.exit == 2:
        assert sorted({e["class"] for e in report.errors}) == expect["errors"]
        return
    got = [[b.kind, b.relay_line, b.tap_line] for b in report.breaks]
    assert sorted(got, key=str) == sorted(expect["breaks"], key=str)
    notes = [[n.kind, n.relay_line, n.tap_line] for n in report.notes]
    assert notes == expect.get("notes", [])
    assert report.blocked_calls == expect.get("blocked_calls", 0)
    assert report.model_sessions == expect.get("model_sessions", 0)


def _valid(tmp_path: Path, line: str) -> bool:
    path = tmp_path / "relay.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    try:
        read_rows("relay", path)
    except RecordError:
        return False
    return True


def test_the_reader_takes_each_relay_line_of_the_table(tmp_path: Path) -> None:
    # The table holds each line of the conformance cases, and if the reader takes it.
    rows = json.loads((ROOT / "tests" / "tables.json").read_text("utf-8"))["relay_lines"]
    want = set()
    for relay in (ROOT / "conformance" / "cases").glob("*/relay.jsonl"):
        lines = relay.read_text(encoding="utf-8").split("\n")
        want.update(lines[:-1] if lines[-1] == "" else lines)
    assert sorted(line for line, _ in rows) == sorted(want)
    for line, valid in rows:
        assert [line, _valid(tmp_path, line)] == [line, valid]

import json
from pathlib import Path

import pytest

from verbatim_relay.audit import audit

CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "cases").iterdir())


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

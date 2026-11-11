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
    script = next(case.glob("script.json*"), None)
    report = audit(case / "tap.jsonl", case / "relay.jsonl", script)
    assert report.exit == expect["exit"]
    if report.exit == 2:
        assert sorted({e["class"] for e in report.errors}) == expect["errors"]
        if "reader_error" in expect:
            with pytest.raises(RecordError) as caught:
                read_rows("tap", case / "tap.jsonl")
            assert caught.value.kind == "record_invalid"
            assert str(caught.value) == f"{case / 'tap.jsonl'}: {expect['reader_error']}"
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


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_the_reader_refuses_a_constant_that_is_not_json(tmp_path: Path, constant: str) -> None:
    # json.loads accepts these constants, but JSON.parse refuses them (#96).
    path = tmp_path / "tap.jsonl"
    row = '{"v": "0.2", "type": "unparsed", "ts": %s, "method": "POST", "path": "/", "error": "x"}'
    path.write_text(row % constant + "\n", encoding="utf-8")
    with pytest.raises(RecordError, match=f"line 1: {constant} is not a JSON value"):
        read_rows("tap", path)


@pytest.mark.parametrize("unparsed", [False, True])
@pytest.mark.parametrize(
    "field, value, reason",
    [
        ("index", 3, "out of order"),
        ("sha256", "0" * 64, "hash does not match"),
        ("opcode", 0, "frame header does not match"),
        ("final", True, "frame header does not match"),
        ("direction", "sideways", "direction is not valid"),
    ],
)
def test_a_linked_failure_still_checks_each_part(tmp_path, unparsed, field, value, reason):
    case = ROOT / "conformance" / "cases" / "websocket_linked_failure_then_clean" / "tap.jsonl"
    rows = [json.loads(line) for line in case.read_text().splitlines()]
    rows[1][field] = value
    if unparsed:
        rows[3] = {
            "v": "0.2",
            "type": "unparsed",
            "ts": 1.0,
            "method": "POST",
            "path": "/",
            "error": "no full reply",
            "stream_id": "ws-stock",
            "stream_protocol": "websocket",
        }
    path = tmp_path / "tap.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(RecordError, match=reason):
        read_rows("tap", path)

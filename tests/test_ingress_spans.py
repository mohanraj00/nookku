import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from nookku import ingress_spans, seal, trace
from nookku.cli import main
from nookku.record import RecordError

CASES = Path(__file__).resolve().parent.parent / "conformance" / "trace"
TEST = "20261023-090000-ks01"
T0 = 1791273600.0  # 2026-10-06T08:00:00Z
PATH = Path("spans.jsonl")


def folder(tmp_path: Path) -> Path:
    """The case ingress_spans with no ingress.jsonl, as a sealed test folder of a project."""
    f = tmp_path / ".nookku" / "tests" / TEST
    shutil.copytree(
        CASES / "ingress_spans", f, ignore=shutil.ignore_patterns("expect_*", "ingress.jsonl")
    )
    trace.build(f)
    seal.write(f)
    return f


def spans_file(tmp_path: Path, case: str = "ingress_spans") -> Path:
    path = tmp_path / "spans.jsonl"
    shutil.copy(CASES / case / "ingress.jsonl", path)
    return path


def span(**fields: Any) -> dict[str, Any]:
    row = {"v": 1, "time": "2026-10-06T08:00:11Z", "status": 200, "outcome": "ok"}
    return {**row, **fields}


def counts(*rows: Any, start: Any = None, end: Any = None, turns: int = 0) -> dict[str, Any]:
    data = "".join(json.dumps(r) + "\n" for r in rows).encode()
    return ingress_spans.parse(data, PATH, start, end, lambda ts: None, turns)


def test_the_trace_copies_the_spans_counts_them_and_seals_them(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    assert "ingress" not in json.loads((f / "findings.json").read_text())
    spans = spans_file(tmp_path)
    assert main(["trace", TEST, "--root", str(tmp_path), "--ingress", str(spans)]) == 0
    assert (f / ingress_spans.FILE).read_bytes() == spans.read_bytes()
    expect = json.loads((CASES / "ingress_spans" / "expect_findings.json").read_text())
    assert json.loads((f / "findings.json").read_text()) == expect
    assert seal.verify(f)["intact"]
    capsys.readouterr()
    # The next rebuild reads the copy, with no --ingress.
    assert main(["trace", TEST, "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ingress"] == expect["ingress"]


def test_the_spans_add_no_finding_and_no_trace_item(tmp_path: Path) -> None:
    f = folder(tmp_path)
    before = json.loads((f / "findings.json").read_text())
    items = (f / "trace.jsonl").read_bytes()
    spans = spans_file(tmp_path)
    assert main(["trace", TEST, "--root", str(tmp_path), "--ingress", str(spans)]) == 0
    after = json.loads((f / "findings.json").read_text())
    assert after.pop("ingress")["spans"] > 0
    assert after == before
    assert (f / "trace.jsonl").read_bytes() == items


def test_a_span_of_version_2_stops_the_trace_and_copies_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    before = (f / "findings.json").read_bytes()
    spans = spans_file(tmp_path, "ingress_spans_version_two")
    assert main(["trace", TEST, "--root", str(tmp_path), "--ingress", str(spans)]) == 2
    err = capsys.readouterr().err
    assert "the trace was not rebuilt" in err
    assert "line 2: the span has the format version 2" in err
    assert not (f / ingress_spans.FILE).exists()
    assert (f / "findings.json").read_bytes() == before
    assert seal.verify(f)["intact"]


def test_a_missing_spans_file_stops_the_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    missing = tmp_path / "none.jsonl"
    assert main(["trace", TEST, "--root", str(tmp_path), "--ingress", str(missing)]) == 2
    assert f"the trace was not rebuilt. {missing}" in capsys.readouterr().err
    assert not (f / ingress_spans.FILE).exists()


def test_the_copy_replaces_a_symlink_and_not_its_target(tmp_path: Path) -> None:
    f = folder(tmp_path)
    target = tmp_path / "target.jsonl"
    target.write_text("keep\n")
    (f / ingress_spans.FILE).symlink_to(target)
    seal.write(f)
    spans = spans_file(tmp_path)
    assert main(["trace", TEST, "--root", str(tmp_path), "--ingress", str(spans)]) == 0
    assert target.read_text() == "keep\n"
    assert not (f / ingress_spans.FILE).is_symlink()


def test_a_span_with_no_version_is_version_1() -> None:
    row = span()
    del row["v"]
    assert counts(row)["spans"] == 1


@pytest.mark.parametrize("v", ["1", True, 0.5, 0, None, [1]])
def test_a_span_with_a_version_that_is_not_1_or_above_1_is_invalid(v: object) -> None:
    assert counts(span(v=v)) == {
        "file": "ingress.jsonl",
        "rows": 1,
        "spans": 0,
        "outcomes": {},
        "turns": [],
        "no_turn": 0,
        "ignored": {"invalid": 1},
    }


@pytest.mark.parametrize("v", [2, 1.5, 10**30])
def test_a_span_of_a_version_above_1_is_refused(v: object) -> None:
    with pytest.raises(RecordError, match="line 2: the span has the format version"):
        counts(span(), span(v=v, time="2020-01-01T00:00:00Z"), start=T0, end=T0 + 100)


@pytest.mark.parametrize(
    "fields",
    [
        {"time": "yesterday"},
        {"time": None},
        {"status": "200"},
        {"status": True},
        {"status": 200.5},
        {"status": None},
        {"outcome": None},
        {"outcome": 7},
    ],
)
def test_a_span_needs_a_time_an_integer_status_and_an_outcome(fields: dict[str, Any]) -> None:
    info = counts(span(**fields))
    assert info["spans"] == 0
    assert info["ignored"] == {"invalid": 1}


def test_the_reader_ignores_each_field_that_it_does_not_know() -> None:
    info = counts(span(kind="app-ingress", app="shop", caller="tester", durationMs=3.4, new=[1]))
    assert info["spans"] == 1
    assert info["outcomes"] == {"ok": 1}


def test_the_reader_accepts_each_outcome_word() -> None:
    info = counts(span(), span(status=401, outcome="signature"), span(status=429, outcome="new"))
    assert info["outcomes"] == {"new": 1, "ok": 1, "signature": 1}


def test_the_window_includes_both_ends() -> None:
    rows = [span(time=t) for t in ("2026-10-06T07:59:59.999Z", "2026-10-06T08:00:00Z")]
    rows += [span(time=t) for t in ("2026-10-06T08:01:40Z", "2026-10-06T08:01:40.001Z")]
    info = counts(*rows, start=T0, end=T0 + 100)
    assert info["spans"] == 2
    assert info["ignored"] == {"outside_window": 2}


def test_a_span_is_in_the_turn_of_its_time() -> None:
    def turn(ts: float) -> int | None:
        return 2 if ts >= T0 + 30 else None

    rows = [span(), span(time="2026-10-06T08:00:31Z"), span(time="2026-10-06T08:00:32Z")]
    data = "".join(json.dumps(r) + "\n" for r in rows).encode()
    info = ingress_spans.parse(data, PATH, T0, T0 + 100, turn, 2)
    assert info["turns"] == [0, 2]
    assert info["no_turn"] == 1


def test_a_file_that_is_not_utf_8_is_refused() -> None:
    with pytest.raises(RecordError, match="not UTF-8"):
        ingress_spans.parse(b"\xff\n", PATH, None, None, lambda ts: None, 0)


def test_a_line_that_is_not_an_object_is_counted() -> None:
    data = b'[1]\nnot JSON\n\n   \n{"v": 1}\n'
    info = ingress_spans.parse(data, PATH, None, None, lambda ts: None, 0)
    assert info["rows"] == 3
    assert info["ignored"] == {"invalid_json": 2, "blank": 2, "invalid": 1}

import json
import shutil
from pathlib import Path

import pytest

from nookku import config, egress_spans, seal, trace
from nookku.cli import main
from nookku.record import RecordError

CASES = Path(__file__).resolve().parent.parent / "conformance" / "trace"
TEST = "20261023-090000-ks01"


def folder(tmp_path: Path) -> Path:
    """The case egress_spans with no egress.jsonl, as a sealed test folder of a project."""
    f = tmp_path / ".nookku" / "tests" / TEST
    shutil.copytree(
        CASES / "egress_spans", f, ignore=shutil.ignore_patterns("expect_*", "egress.jsonl")
    )
    trace.build(f)
    seal.write(f)
    return f


def spans_file(tmp_path: Path, case: str = "egress_spans") -> Path:
    path = tmp_path / "spans.jsonl"
    shutil.copy(CASES / case / "egress.jsonl", path)
    return path


def test_the_trace_copies_the_spans_checks_them_and_seals_them(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    spans = spans_file(tmp_path)
    assert main(["trace", TEST, "--root", str(tmp_path), "--egress", str(spans)]) == 0
    assert (f / egress_spans.FILE).read_bytes() == spans.read_bytes()
    expect = json.loads((CASES / "egress_spans" / "expect_findings.json").read_text())
    assert json.loads((f / "findings.json").read_text()) == expect
    out = capsys.readouterr().out
    assert "egress_denied (egress): connect pay.toy.test port 8443: denied (port)" in out
    assert seal.verify(f)["intact"]
    # The next rebuild reads the copy, with no --egress.
    assert main(["trace", TEST, "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["egress_denied"] == 2


def test_a_span_of_version_3_stops_the_trace_and_copies_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    before = (f / "findings.json").read_bytes()
    spans = spans_file(tmp_path, "egress_spans_version_three")
    assert main(["trace", TEST, "--root", str(tmp_path), "--egress", str(spans)]) == 2
    err = capsys.readouterr().err
    assert "the trace was not rebuilt" in err
    assert "line 2: the span has the contract version 3" in err
    assert not (f / egress_spans.FILE).exists()
    assert (f / "findings.json").read_bytes() == before
    assert seal.verify(f)["intact"]


def test_a_missing_spans_file_stops_the_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    missing = tmp_path / "none.jsonl"
    assert main(["trace", TEST, "--root", str(tmp_path), "--egress", str(missing)]) == 2
    assert f"the trace was not rebuilt. {missing}" in capsys.readouterr().err
    assert not (f / egress_spans.FILE).exists()


def test_a_changed_test_folder_takes_no_spans(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    (f / "tap.jsonl").write_text('{"changed": true}\n')
    spans = spans_file(tmp_path)
    assert main(["trace", TEST, "--root", str(tmp_path), "--egress", str(spans)]) == 2
    assert not (f / egress_spans.FILE).exists()


def test_the_copy_replaces_a_symlink_and_not_its_target(tmp_path: Path) -> None:
    f = tmp_path / "test"
    f.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("keep")
    (f / egress_spans.FILE).symlink_to(target)
    egress_spans.copy_in(b'{"v": 1}\n', f)
    assert target.read_text() == "keep"
    assert not (f / egress_spans.FILE).is_symlink()
    assert (f / egress_spans.FILE).read_bytes() == b'{"v": 1}\n'
    assert [p.name for p in f.iterdir()] == [egress_spans.FILE]


@pytest.mark.parametrize(
    "value, seconds",
    [
        ("2026-10-23T09:14:02Z", 1792746842.0),
        ("2026-10-23T09:14:02.5Z", 1792746842.5),
        ("2026-10-23T09:14:02.118Z", 1792746842.118),
        ("2026-10-23t11:14:02.118+02:00", 1792746842.118),
        ("2026-10-23T09:14:02.123456789Z", 1792746842.123456789),
        ("2026-10-23T09:14:02." + "1" * 5000 + "Z", 1792746842.111111),
    ],
)
def test_each_rfc_3339_time_gives_its_unix_time(value: str, seconds: float) -> None:
    assert egress_spans._time(value) == pytest.approx(seconds, abs=1e-6)


@pytest.mark.parametrize("value", [None, 1792746842, "2026-10-23", "2026-10-23T09:14:02", "x"])
def test_a_time_that_is_not_rfc_3339_is_not_a_time(value: object) -> None:
    assert egress_spans._time(value) is None


@pytest.mark.parametrize(
    "value, host",
    [
        ("api.github.com:443", "api.github.com"),
        ("Stock.Toy.Test.", "stock.toy.test"),
        ("[::1]:443", "::1"),
        ("::1", "::1"),
        ("", None),
        (None, None),
    ],
)
def test_the_host_of_a_span_has_no_port(value: object, host: str | None) -> None:
    assert egress_spans.host_name(value) == host


@pytest.mark.parametrize("v", ["1", "2", 0, 1.5, True, None])
def test_a_span_with_a_version_that_is_not_1_2_or_above_2_is_invalid(v: object) -> None:
    line = {"v": v, "time": "2026-10-23T09:14:02Z", "kind": "connect", "result": "ok"}
    spans, info = egress_spans.parse(json.dumps(line).encode(), Path("x"), None, None, [])
    assert (spans, info["ignored"]) == ([], {"invalid": 1})


def test_the_trace_reads_spans_of_version_1_and_version_2_in_one_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = folder(tmp_path)
    spans = spans_file(tmp_path, "egress_spans_version_two")
    assert main(["trace", TEST, "--root", str(tmp_path), "--egress", str(spans)]) == 0
    expect = json.loads((CASES / "egress_spans_version_two" / "expect_findings.json").read_text())
    assert json.loads((f / "findings.json").read_text()) == expect
    assert seal.verify(f)["intact"]


V2 = {"v": 2, "time": "2026-10-23T09:14:02Z", "claimed": True, "result": "ok"}


def test_a_span_of_version_2_with_no_claim_values_is_kept() -> None:
    line = {**V2, "kind": "connect", "host": "stock.toy.test:443", "sni": "stock.toy.test"}
    spans, info = egress_spans.parse(json.dumps(line).encode(), Path("x"), None, None, [])
    assert [s["host"] for s in spans] == ["stock.toy.test"]
    assert spans[0]["span"] == line
    assert info["ignored"] == {}


def test_an_http_span_of_version_2_with_no_path_is_kept_and_checked() -> None:
    line = {**V2, "kind": "http", "method": "POST", "host": "mail.toy.test", "port": "80"}
    line["result"] = "denied"
    spans, _ = egress_spans.parse(json.dumps(line).encode(), Path("x"), None, None, [])
    assert [s["host"] for s in spans] == ["mail.toy.test"]
    found = egress_spans.denied(spans, lambda ts: 1)
    assert [x["detail"] for x in found] == ["http mail.toy.test port 80: denied"]
    assert egress_spans.not_in_discovery(spans, set())[0]["session"] == "mail.toy.test"


@pytest.mark.parametrize("v", [3, 2.5, 10])
def test_a_span_of_a_version_above_2_is_refused(v: object) -> None:
    lines = [{**V2, "kind": "connect"}, {**V2, "v": v, "kind": "connect"}]
    data = "".join(json.dumps(x) + "\n" for x in lines).encode()
    with pytest.raises(RecordError) as e:
        egress_spans.parse(data, Path("x"), None, None, [])
    assert f"line 2: the span has the contract version {v}." in str(e.value)
    assert "reads version 1 and version 2 only" in str(e.value)


def test_the_window_includes_both_ends() -> None:
    lines = [
        {"time": t, "kind": "connect", "host": "stock.toy.test:443", "result": "ok"}
        for t in ("2026-10-23T09:14:01.999Z", "2026-10-23T09:14:02Z", "2026-10-23T09:14:03Z")
    ]
    data = "".join(json.dumps(x) + "\n" for x in lines).encode()
    start = 1792746842.0
    spans, info = egress_spans.parse(data, Path("x"), start, start + 1, [])
    assert [s["line"] for s in spans] == [2, 3]
    assert info["ignored"] == {"outside_window": 1}


def test_a_file_that_is_not_utf_8_is_refused() -> None:
    with pytest.raises(egress_spans.RecordError, match="not UTF-8"):
        egress_spans.parse(b"\xff\n", Path("x"), None, None, [])


@pytest.mark.parametrize(
    "value, ok",
    [
        ([], True),
        (["github.com", "pypi.org"], True),
        ("github.com", False),
        ([""], False),
        (["git hub.com"], False),
        ([1], False),
        (["\udc00"], False),
    ],
)
def test_the_config_key_egress_ignore_is_a_list_of_host_names(value: object, ok: bool) -> None:
    if ok:
        assert config.check({"egress_ignore": value})["egress_ignore"] == value
        assert trace.trace_keys({"trace": {"egress_ignore": value}})["egress_ignore"] == value
    else:
        with pytest.raises(config.ConfigError, match="'egress_ignore' must be a list of host"):
            config.check({"egress_ignore": value})
        assert trace.trace_keys({"trace": {"egress_ignore": value}})["egress_ignore"] == []

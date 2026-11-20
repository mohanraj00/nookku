"""The seam test of the release samples (scripts/release_samples.py, #578). These tests use
lines that a person wrote. The script itself reads the lines of a release."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest

TAG = "v9.9.9"
NAMES = ("egress-spans.jsonl", "gateway-log.jsonl", "app-ingress-spans.jsonl")
SPAN = {
    "v": 2,
    "time": "2026-10-23T09:14:02Z",
    "claimed": True,
    "result": "ok",
    "host": "example.com",
}
LOG = {
    "request_id": "req-1",
    "call_type": "acompletion",
    "startTime": "2026-10-06T08:00:11.000Z",
    "endTime": "2026-10-06T08:00:12.000Z",
    "metadata": {"user_api_key_alias": "toy-shop-key"},
    "status": "success",
}
REQUEST = {
    "v": 1,
    "time": "2026-10-06T08:00:11.118Z",
    "kind": "app-ingress",
    "app": "shop",
    "method": "POST",
    "status": 200,
    "outcome": "ok",
    "durationMs": 3.412,
}


@pytest.fixture
def samples(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("release_samples")


def _lines(*rows: object) -> bytes:
    return "".join(json.dumps(r) + "\n" for r in rows).encode()


def _run(
    samples,
    spans: bytes,
    logs: bytes,
    pins: dict[str, str] | None = None,
    ingress: bytes | None = None,
) -> dict:
    ingress = _lines(REQUEST) if ingress is None else ingress
    files = {samples.SPANS: spans, samples.LOGS: logs, samples.INGRESS: ingress}
    pins = pins or {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    return samples.check(TAG, pins, files.__getitem__)


def test_the_readers_read_the_samples_of_the_pinned_release(samples) -> None:
    llm = dict(SPAN, kind="llm")
    spans, logs = _lines(SPAN, dict(SPAN, v=1), llm), _lines(LOG, dict(LOG, call_type="health"))
    result = _run(samples, spans, logs)
    assert result["pass"] and result["koodam"] == TAG
    assert result["files"][samples.SPANS] == {
        "sha256": hashlib.sha256(spans).hexdigest(),
        "bytes": len(spans),
    }
    assert result["spans"] == {
        "rows": 3,
        "spans": 2,
        "ignored": {"llm": 1},
        "versions": {"1": 1, "2": 1},
        "hosts": 1,
    }
    assert result["gateway"] == {
        "logs": 2,
        "model_calls": 1,
        "call_types": {"acompletion": 1, "health": 1},
    }
    assert result["ingress"] == {"rows": 1, "spans": 1, "ignored": {}, "outcomes": {"ok": 1}}


def test_the_ingress_reader_counts_each_outcome_of_the_sample(samples) -> None:
    refused = dict(REQUEST, status=401, outcome="signature")
    result = _run(samples, _lines(SPAN), _lines(LOG), ingress=_lines(REQUEST, REQUEST, refused))
    assert result["ingress"]["spans"] == 3
    assert result["ingress"]["outcomes"] == {"ok": 2, "signature": 1}
    assert result["ingress_versions"] == [1]


@pytest.mark.parametrize(
    ("rows", "text"),
    [
        ((dict(REQUEST, v=2),), "S4: the ingress span reader cannot read the sample"),
        ((REQUEST, dict(REQUEST, status="200")), "has lines that the reader refuses"),
        ((REQUEST, "not a span"), "has lines that the reader refuses"),
        ((), "has no span that the reader keeps"),
    ],
)
def test_an_ingress_sample_that_the_reader_refuses_stops_the_check(
    samples, rows: tuple, text: str
) -> None:
    with pytest.raises(samples.Stop) as stop:
        _run(samples, _lines(SPAN), _lines(LOG), ingress=_lines(*rows))
    assert text in str(stop.value)
    if rows and isinstance(rows[0], dict) and rows[0]["v"] == 2:
        assert "line 1: the span has the format version 2" in str(stop.value)


def test_a_file_with_another_sha256_stops_the_check(samples) -> None:
    pins = {
        samples.SPANS: "0" * 64,
        samples.LOGS: hashlib.sha256(_lines(LOG)).hexdigest(),
        samples.INGRESS: hashlib.sha256(_lines(REQUEST)).hexdigest(),
    }
    with pytest.raises(
        samples.Stop, match=rf"S1: {samples.SPANS} of the release {TAG} has the SHA-256"
    ):
        _run(samples, _lines(SPAN), _lines(LOG), pins)


def test_a_new_contract_version_stops_the_check_with_the_message_of_the_reader(samples) -> None:
    with pytest.raises(samples.Stop) as stop:
        _run(samples, _lines(SPAN, dict(SPAN, v=3)), _lines(LOG))
    text = str(stop.value)
    assert f"the sample of the release {TAG}" in text
    assert "line 2: the span has the contract version 3" in text
    assert "This nookku reads version 1 and version 2 only" in text


@pytest.mark.parametrize(
    ("spans", "text"),
    [
        (b"not json\n", "lines that the reader refuses: {'invalid_json': 1}"),
        (_lines(dict(SPAN, time="soon")), "lines that the reader refuses: {'invalid': 1}"),
        (_lines(dict(SPAN, kind="llm")), "has no span that the reader keeps"),
        (b"", "has no span that the reader keeps"),
    ],
)
def test_a_span_sample_that_the_reader_refuses_stops_the_check(
    samples, spans: bytes, text: str
) -> None:
    with pytest.raises(samples.Stop, match="S2: ") as stop:
        _run(samples, spans, _lines(LOG))
    assert text in str(stop.value)


@pytest.mark.parametrize(
    ("logs", "text"),
    [
        (b"{}\nnot json\n", "line 2 of the gateway log is not JSON"),
        (_lines(LOG, 5), "log 2 of gateway-log.jsonl of the release v9.9.9 is not an object"),
        (
            _lines(dict(LOG, startTime=None)),
            "log 1 of gateway-log.jsonl of the release v9.9.9 has no start time",
        ),
        (_lines(dict(LOG, metadata={})), "has no start time or no key alias"),
        (_lines(dict(LOG, call_type="health")), "has no model call that the reader knows"),
        (b"", "has no model call that the reader knows"),
    ],
)
def test_a_log_sample_that_the_reader_refuses_stops_the_check(
    samples, logs: bytes, text: str
) -> None:
    with pytest.raises(samples.Stop, match="S3: ") as stop:
        _run(samples, _lines(SPAN), logs)
    assert text in str(stop.value)


@pytest.mark.parametrize(
    ("tag", "pins"),
    [
        ("", dict.fromkeys(NAMES, "0" * 64)),
        (TAG, {**dict.fromkeys(NAMES, "0" * 64), "egress-spans.jsonl": ""}),
        (TAG, dict.fromkeys(NAMES[:2], "0" * 64)),
        (TAG, {"egress-spans.jsonl": "0" * 64}),
    ],
)
def test_a_pin_with_no_tag_or_no_sha256_stops_the_check(
    samples, tag: str, pins: dict[str, str]
) -> None:
    with pytest.raises(samples.Stop, match="No release is pinned"):
        samples.check(tag, pins, lambda name: b"")


def test_the_script_reads_a_folder_and_writes_the_result(
    samples, tmp_path: Path, monkeypatch, capsys
) -> None:
    files = {
        samples.SPANS: _lines(SPAN),
        samples.LOGS: _lines(LOG),
        samples.INGRESS: _lines(REQUEST),
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    monkeypatch.setattr(samples, "KOODAM_TAG", TAG)
    monkeypatch.setattr(
        samples, "SAMPLES", {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
    )
    out = tmp_path / "out" / "results.json"
    assert samples.main(["--dir", str(tmp_path), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["koodam"] == TAG
    (tmp_path / samples.LOGS).unlink()
    assert samples.main(["--dir", str(tmp_path), "--out", str(out)]) == 1
    assert "gateway-log.jsonl: cannot read it" in capsys.readouterr().err

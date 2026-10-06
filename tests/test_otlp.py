import gzip
import json
import urllib.request
from pathlib import Path

import pytest

from verbatim_relay import otlp
from verbatim_relay.stdio import start_in_thread

CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "otlp").iterdir())


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_conformance(case: Path) -> None:
    request = json.loads((case / "request.json").read_text())
    expect = json.loads((case / "expect.json").read_text())
    body = (case / "body.bin").read_bytes()
    if request["encoding"] == "gzip":
        body = gzip.compress(body)
    args = (request["path"], request["type"], request["encoding"] or "", body)
    if expect["error"]:
        with pytest.raises(otlp.DecodeError, match=expect["error"]):
            otlp.parse(*args)
        return
    parsed = otlp.parse(*args)
    if expect["rows"] is None:
        assert parsed is None
    else:
        assert parsed is not None
        assert otlp.rows(parsed, expect["received"]) == expect["rows"]


def post(url: str, path: str, body: bytes, ctype: str, encoding: str = "") -> int:
    headers = {"Content-Type": ctype}
    if encoding:
        headers["Content-Encoding"] = encoding
    req = urllib.request.Request(url + path, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return e.code


def test_the_receiver_writes_rows_and_errors(tmp_path: Path) -> None:
    record = tmp_path / "otel.jsonl"
    receiver = otlp.Receiver(("127.0.0.1", 0), record)
    start_in_thread(receiver)
    try:
        case = Path(CASES[0].parent / "logs_protobuf_gzip")
        body = gzip.compress((case / "body.bin").read_bytes())
        assert post(receiver.url, "/v1/logs", body, "application/x-protobuf", "gzip") == 200
        assert post(receiver.url, "/v1/metrics", b"{}", "application/json") == 200
        assert post(receiver.url, "/v1/traces", b"{", "application/json") == 400
        assert post(receiver.url, "/v1/other", b"{}", "application/json") == 404
        bad = gzip.compress(b"x")[:-3]
        assert post(receiver.url, "/v1/logs", bad, "application/x-protobuf", "gzip") == 400
    finally:
        receiver.shutdown()
        receiver.server_close()
    rows = [json.loads(x) for x in record.read_text().splitlines()]
    assert [r["type"] for r in rows] == ["log", "log", "log", "error", "error"]
    assert "example.com" not in record.read_text()


def test_the_environment_points_to_the_receiver() -> None:
    env = otlp.environment("http://127.0.0.1:4318")
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:4318"
    assert env["OTEL_METRICS_EXPORTER"] == "none"
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"


def test_quiet_waits_for_the_last_request(tmp_path: Path) -> None:
    receiver = otlp.Receiver(("127.0.0.1", 0), tmp_path / "otel.jsonl")
    try:
        slept: list[float] = []
        receiver.last = 0.0
        receiver.quiet(sleep=slept.append)
        assert slept == []
    finally:
        receiver.server_close()

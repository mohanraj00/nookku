import json
from pathlib import Path

import pytest

from nookku import openinference, seal
from nookku.cli import main
from nookku.record import Writer, loads

CASE = Path(__file__).resolve().parents[1] / "conformance/openinference/missing-stock-span.json"
TEST = "20261109-100000-ab12"


@pytest.mark.parametrize("source", ["phoenix", "langfuse"])
def test_a_proxy_call_without_an_exported_span_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    case = loads(CASE.read_bytes())
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = tmp_path / ".nookku" / "tests" / TEST
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"started": 0.5, "ended": 2.5}\n')
    Writer(folder / "tap.jsonl").append(
        {
            "type": "exchange",
            "input": "Is the teapot in stock?",
            "reply": "The teapot is in stock.",
            "status": 200,
            "started": 1.0,
            "ts": 2.0,
        }
    )
    rows = [{"type": "call", "backend": "stock", "status": 200, **c} for c in case["calls"]]
    (folder / "backend.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert seal.write(folder) is None
    export = tmp_path / "spans.json"
    export.write_text(json.dumps(case[source]))
    assert (
        main(["trace", "--root", str(tmp_path), TEST, "--json", "--openinference", str(export)])
        == 0
    )
    report = loads(capsys.readouterr().out)
    assert report["openinference"]["spans"] == 1
    assert report["findings"] == [case["finding"]]
    text = (folder / "openinference.jsonl").read_text()
    assert "toy-credential" not in text and "toy prompt text" not in text
    trace = [loads(line) for line in (folder / "trace.jsonl").read_text().splitlines()]
    imported = next(it for it in trace if it["harness"] == "openinference")
    assert imported["turn"] == 1
    assert imported["source"] == {"file": "openinference.jsonl", "line": 1}
    assert seal.verify(folder)["intact"]


def _otlp_span(span_id: str, name: str, start: str, end: str, attrs: dict[str, str]) -> dict:
    return {
        "traceId": "00000000000000000000000000000001",
        "spanId": span_id,
        "name": name,
        "kind": 3,
        "startTimeUnixNano": start,
        "endTimeUnixNano": end,
        "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
    }


def _resource(service: str) -> dict:
    return {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]}


def test_an_otlp_export_reads_only_app_spans_and_a_late_span_gives_no_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    case = loads(CASE.read_bytes())
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = tmp_path / ".nookku" / "tests" / TEST
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"started": 0.5, "ended": 2.5}\n')
    Writer(folder / "tap.jsonl").append(
        {
            "type": "exchange",
            "input": "Is the teapot in stock?",
            "reply": "The teapot is in stock.",
            "status": 200,
            "started": 1.0,
            "ts": 2.0,
        }
    )
    rows = [{"type": "call", "backend": "stock", "status": 200, **c} for c in case["calls"]]
    (folder / "backend.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    stock = {"http.request.method": "GET", "url.full": "https://stock.toy.test/stock"}
    export = {
        "resourceSpans": [
            {
                "resource": _resource("toy-shop"),
                "scopeSpans": [
                    {
                        "spans": [
                            _otlp_span(
                                "0000000000000001", "read stock", "1100000000", "1250000000", stock
                            ),
                            # After the reply and before the end of the test: no turn.
                            _otlp_span("0000000000000002", "close", "2250000000", "2300000000", {}),
                        ]
                    }
                ],
            },
            {
                "resource": _resource("claude-code"),
                "scopeSpans": [
                    {
                        "spans": [
                            _otlp_span(
                                "0000000000000003", "harness", "1500000000", "1600000000", {}
                            )
                        ]
                    }
                ],
            },
        ],
        "resourceLogs": [
            {
                "resource": _resource("toy-shop"),
                "scopeLogs": [
                    {
                        "logRecords": [
                            {"timeUnixNano": "1200000000", "body": {"stringValue": "toy log"}}
                        ]
                    }
                ],
            }
        ],
    }
    path = tmp_path / "spans.json"
    path.write_text(json.dumps(export))
    assert (
        main(["trace", "--root", str(tmp_path), TEST, "--json", "--openinference", str(path)]) == 0
    )
    report = loads(capsys.readouterr().out)
    assert report["openinference"]["spans"] == 2
    assert report["findings"] == [case["finding"]]
    trace = [loads(line) for line in (folder / "trace.jsonl").read_text().splitlines()]
    late = [it for it in trace if it["harness"] == "openinference" and it["name"] == "close"]
    assert len(late) == 1 and late[0]["turn"] is None


def _phoenix_row(name: str, start: float, end: float, attrs: dict[str, str]) -> dict:
    return {
        "name": name,
        "span_kind": "CHAIN",
        "context.trace_id": "t1",
        "context.span_id": "s1",
        "start_time": start,
        "end_time": end,
        "attributes": attrs,
    }


def test_a_span_with_multi_line_sql_and_a_tab_in_its_name_is_read() -> None:
    sql = "SELECT name,\n\tstock\nFROM toys\r\nWHERE id = 1"
    span = openinference._span(_phoenix_row("read\tstock", 1.0, 1.2, {"db.statement": sql}), "")
    assert span["name"] == "read\tstock"
    assert span["call"] == ["query", "SELECT"]


@pytest.mark.parametrize("start", [1.79e12, 1.79e18, openinference.SECONDS_LIMIT])
def test_a_number_time_that_is_not_unix_seconds_is_refused(start: float) -> None:
    with pytest.raises(ValueError, match="invalid ids, name or times"):
        openinference._span(_phoenix_row("read stock", start, start + 1, {}), "")

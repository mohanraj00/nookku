import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from nookku import otlp, stdio
from nookku.cli import main
from nookku.record import Writer, loads

CASE = Path(__file__).resolve().parents[1] / "conformance" / "genai" / "toy-export.json"
TEST = "20261109-100000-ab13"


def test_genai_export_writes_and_sends_the_same_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = loads(CASE.read_bytes())
    folder = tmp_path / ".nookku" / "tests" / TEST
    session = folder / "sessions" / "claude-code" / "toy.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(json.dumps(case["model"]) + "\n", encoding="utf-8")
    manifest = {
        "test": TEST,
        "model_sessions": [
            {
                "harness": "claude-code",
                "session": "toy",
                "file": str(session.relative_to(folder)),
                "inferred": False,
            }
        ],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    Writer(folder / "tap.jsonl").append(case["turn"])
    (folder / "backend.jsonl").write_text(json.dumps(case["backend"]) + "\n", encoding="utf-8")

    received = {}

    class Receive(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.update(
                path=self.path,
                headers=dict(self.headers.items()),
                body=self.rfile.read(int(self.headers["Content-Length"])),
            )
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    class Collector(HTTPServer):
        def server_bind(self) -> None:
            stdio.bind(self)

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "Authorization=Basic%20toy-credential")
    with Collector(("127.0.0.1", 0), Receive) as collector:
        thread = threading.Thread(target=collector.serve_forever, daemon=True)
        thread.start()
        target = tmp_path / "traces.json"
        try:
            assert (
                main(
                    [
                        "trace",
                        "--root",
                        str(tmp_path),
                        TEST,
                        "--otlp-file",
                        str(target),
                        "--otlp-endpoint",
                        f"http://127.0.0.1:{collector.server_port}/v1/traces",
                    ]
                )
                == 0
            )
        finally:
            collector.shutdown()

    raw = target.read_text()
    data = loads(raw)
    assert "toy-credential" not in raw
    assert case["turn"]["input"] not in raw
    assert case["turn"]["reply"] not in raw
    assert received["path"] == "/v1/traces"
    assert received["headers"]["Authorization"] == "Basic toy-credential"
    assert received["headers"]["Content-Type"] == "application/x-protobuf"
    assert otlp.decode(received["body"], otlp.TRACES) == data

    resource = data["resourceSpans"][0]
    scope = resource["scopeSpans"][0]
    assert scope["scope"]["version"] == "1.38.0"
    spans = scope["spans"]
    root, turn, *children = spans
    assert all(s["traceId"] == root["traceId"] for s in spans)
    assert turn["parentSpanId"] == root["spanId"]
    assert all(s["parentSpanId"] == turn["spanId"] for s in children)
    attrs = [otlp.attributes(s["attributes"]) for s in spans[1:]]
    assert sorted([a["gen_ai.operation.name"], a["nookku.source"]] for a in attrs) == sorted(
        case["operations"]
    )
    assert [
        otlp.attributes(e["attributes"])["gen_ai.evaluation.name"]
        for e in turn["events"]
        if e["name"] == "gen_ai.evaluation.result"
    ] == case["findings"]

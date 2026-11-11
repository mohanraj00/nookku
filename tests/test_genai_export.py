import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from nookku import genai_export, otlp, stdio
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
    assert all(s["startTimeUnixNano"] == s["endTimeUnixNano"] for s in children)


SPANS: dict[str, Any] = {"resourceSpans": []}


def _collect(status: int, body: bytes, kind: str) -> HTTPServer:
    class Reply(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("Content-Type", kind)
            if status == 302:
                self.send_header("Location", "http://127.0.0.1:9/v1/traces")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    class Collector(HTTPServer):
        def server_bind(self) -> None:
            stdio.bind(self)

    server = Collector(("127.0.0.1", 0), Reply)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test/v1/traces",
        "https://user:secret@example.test/v1/traces",
        "https://example.test/v1/traces#part",
        "ftp://127.0.0.1/v1/traces",
    ],
)
def test_an_endpoint_that_is_not_safe_is_refused_before_a_request(endpoint: str) -> None:
    with pytest.raises(genai_export.ExportError, match="HTTPS or HTTP on this computer"):
        genai_export.send(endpoint, SPANS)


@pytest.mark.parametrize(
    ("status", "body", "kind", "error"),
    [
        (503, b"", "text/plain", "returned HTTP 503"),
        (302, b"", "text/plain", "returned HTTP 302"),
        (200, b'{"partialSuccess": {"rejectedSpans": 1}}', "application/json", "rejected spans"),
        (200, bytes([0x0A, 0x02, 0x08, 0x01]), "application/x-protobuf", "rejected spans"),
        (200, b'{"partialSuccess": {"rejectedSpans": "x"}}', "application/json", "not valid"),
        (200, b"{", "application/json", "not valid"),
        (200, b"x" * 1_048_577, "application/x-protobuf", "too large"),
    ],
)
def test_a_collector_refusal_is_an_export_error(
    status: int, body: bytes, kind: str, error: str
) -> None:
    server = _collect(status, body, kind)
    try:
        with pytest.raises(genai_export.ExportError, match=error):
            genai_export.send(f"http://127.0.0.1:{server.server_port}/v1/traces", SPANS)
    finally:
        server.shutdown()
        server.server_close()


def test_a_json_reply_with_no_rejected_spans_is_accepted() -> None:
    server = _collect(200, b'{"partialSuccess": {}}', "application/json")
    try:
        genai_export.send(f"http://127.0.0.1:{server.server_port}/v1/traces", SPANS)
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "value", ["Authorization", "Host=toy", "bad name=x", "Authorization=a%0Ab"]
)
def test_an_invalid_header_variable_is_refused(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", value)
    with pytest.raises(genai_export.ExportError, match="has an invalid header"):
        genai_export.send("http://127.0.0.1:9/v1/traces", SPANS)


def test_an_output_file_in_the_test_folder_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / TEST
    folder.mkdir()
    with pytest.raises(genai_export.ExportError, match="outside the test folder"):
        genai_export.write(folder / "traces.json", folder, SPANS)
    assert list(folder.iterdir()) == []

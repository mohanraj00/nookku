"""Proof that the client trace records the queue calls of the app (SPEC.md sections 7.11 and 8.6).

A toy shop app puts each order on a RabbitMQ queue and sends a mail to the customer. RabbitMQ runs
in Docker, and the mail goes to a toy SMTP server of the proof. The app uses the OpenTelemetry
instrumentation of pika and the OTLP exporter over HTTP. These packages go into a new virtual
environment of the app, not into Nookku. The egress answer gives the queue `record: driver` and
the mail `record: none`.

The proof runs 2 tests, with 1 message each. In test A the app turns on the instrumentation, so a
span of the queue comes. In test B the app turns it off, so the trace gives `other_without_span`.
For each test, the proof checks the manifest, the start text, the spans of the queue, the
findings, the lines of the transcript that the report reads, the evaluation prompt and the seal.
It needs no model, but it needs Docker and the network to install the packages.

usage: python scripts/proof_queue_trace.py
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import json_lines  # noqa: E402

from nookku import __version__, bridge, discovery, evaluation, seal  # noqa: E402
from nookku.record import loads  # noqa: E402

IMAGE = "rabbitmq:4.1-alpine"
# The packages of the app, with the versions that the proof records.
PACKAGES = [
    "pika==1.3.2",
    "opentelemetry-sdk==1.44.0",
    "opentelemetry-exporter-otlp-proto-http==1.44.0",
    "opentelemetry-instrumentation-pika==0.65b0",
]
ORDERS = {"name": "orders", "kind": "rabbitmq", "detail": "the order queue", "record": "driver"}
MAIL = {"name": "mail", "kind": "smtp", "detail": "sends the order mail", "record": "none"}
MESSAGE = "Please order the teapot set."
WANT = {"check": "other_without_span", "turn": None, "detail": "orders: no span of its client"}
REPLY = "Your order of the teapot set is on the queue. A mail is on its way."

# The app instruments pika before it connects, if TOY_SHOP_TRACE is 1. It flushes the spans
# before each reply, so that the receiver has them when the test ends.
ENTRY = """
import json, os, smtplib, sys

import pika
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.pika import PikaInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider(resource=Resource.create({"service.name": "toy-shop"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
if os.environ["TOY_SHOP_TRACE"] == "1":
    PikaInstrumentor().instrument()

connection = pika.BlockingConnection(pika.URLParameters(os.environ["TOY_SHOP_AMQP"]))
channel = connection.channel()
channel.queue_declare(queue="orders")
host, port = os.environ["TOY_SHOP_SMTP"].split(":")

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    order = {"sku": "teapot-set", "qty": 1}
    channel.basic_publish(exchange="", routing_key="orders", body=json.dumps(order))
    with smtplib.SMTP(host, int(port), timeout=10) as mail:
        mail.sendmail("shop@toy.test", ["kim@toy.test"], "Subject: order\\r\\n\\r\\nThank you.")
    provider.force_flush()
    reply = {"v": 1, "id": request["id"], "reply": "@REPLY@"}
    sys.stdout.write(json.dumps(reply) + "\\n")
    sys.stdout.flush()
""".replace("@REPLY@", REPLY)


class ToySmtp(socketserver.StreamRequestHandler):
    """A toy SMTP server: it accepts each mail and keeps nothing."""

    def handle(self) -> None:
        self.wfile.write(b"220 toy.test\r\n")
        data = False
        for line in self.rfile:
            if data:
                if line in (b".\r\n", b".\n"):
                    data = False
                    self.wfile.write(b"250 ok\r\n")
                continue
            verb = line[:4].upper()
            if verb == b"DATA":
                data = True
                self.wfile.write(b"354 go on\r\n")
            elif verb == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


def app_python(project: Path) -> Path:
    """A new virtual environment for the app, with the packages of the client trace."""
    venv = project / ".venv"
    subprocess.run(["uv", "venv", "-q", "--python", sys.executable, str(venv)], check=True)
    python = venv / "bin" / "python"
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(python), *PACKAGES], check=True)
    return python


def start_rabbitmq() -> tuple[str, int]:
    """Start RabbitMQ in Docker on a free port of 127.0.0.1. Return the container and the port."""
    run = ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::5672", IMAGE]
    container = subprocess.run(run, capture_output=True, text=True, check=True).stdout.strip()
    port_text = subprocess.run(
        ["docker", "port", container, "5672/tcp"], capture_output=True, text=True, check=True
    ).stdout
    port = int(port_text.splitlines()[0].rsplit(":", 1)[1])
    # The Docker port accepts a connection before RabbitMQ listens, so the check waits for the
    # Connection.Start frame of AMQP 0-9-1 (frame type 1).
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
                conn.sendall(b"AMQP\x00\x00\x09\x01")
                if conn.recv(1) == b"\x01":
                    return container, port
        except OSError:
            pass
        time.sleep(1)
    subprocess.run(["docker", "stop", container], capture_output=True)
    sys.exit("RabbitMQ did not start in 120 seconds")


def queue_spans(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"turn": it["turn"], "name": it["name"], "input": it["input"]}
        for it in items
        if it["harness"] == "otel"
        and it["kind"] == "span"
        and isinstance(it["input"], dict)
        and it["input"].get("messaging.system") == "rabbitmq"
    ]


def one_test(project: Path, traced: bool) -> dict[str, Any]:
    os.environ["TOY_SHOP_TRACE"] = "1" if traced else "0"
    discovery.register(project, discovery.make(other=[ORDERS, MAIL]))
    cur = bridge.start(project)
    try:
        start_text = bridge.egress_text(Path(cur["dir"]))
        shown, ok = bridge.send(cur, MESSAGE)
    finally:
        bridge.end(project)
    folder = Path(cur["dir"])
    manifest = loads((folder / "manifest.json").read_text())
    items = json_lines((folder / "trace.jsonl").read_text())
    findings = loads((folder / "findings.json").read_text())
    text = evaluation.transcript(folder)
    return {
        "ok": ok,
        "reply": shown,
        "unseen": manifest["egress"]["unseen"],
        "client_trace": manifest["egress"].get("client_trace"),
        "start_text": start_text.splitlines(),
        "queue_spans": queue_spans(items),
        "counts": {
            k: findings["counts"][k] for k in ("other_without_span", "unseen_call", "span_error")
        },
        "findings": [f for f in findings["findings"] if f["check"] == "other_without_span"],
        "transcript_lines": [
            x for x in text.splitlines() if "other_without_span" in x or "rabbitmq" in x
        ],
        "prompt_has_client_rows": "`client_trace`" in evaluation.prompt(folder),
        "seal_intact": seal.verify(folder)["intact"],
    }


def main() -> int:
    project = Path(tempfile.mkdtemp(prefix="nookku-queue-"))
    (project / ".nookku").mkdir()
    (project / "entry.py").write_text(ENTRY)
    python = app_python(project)
    config = {"entry": [str(python), "entry.py"], "models": []}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ToySmtp)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    container, port = start_rabbitmq()
    os.environ["TOY_SHOP_AMQP"] = f"amqp://guest:guest@127.0.0.1:{port}/%2F"
    os.environ["TOY_SHOP_SMTP"] = f"127.0.0.1:{smtp.server_address[1]}"
    try:
        traced = one_test(project, True)
        untraced = one_test(project, False)
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True)
        smtp.shutdown()
    rabbitmq = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{index .RepoDigests 0}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    client_line = next((x for x in traced["start_text"] if "spans of its client" in x), "")
    none_line = "The test does not record the calls of these other parts: mail."
    checks = {
        # The start text names both parts, and the manifest names the queue in client_trace.
        "start_text": all(
            "- other orders: rabbitmq, the order queue (driver trace)" in t["start_text"]
            and "- other mail: smtp, sends the order mail (no proxy)" in t["start_text"]
            and none_line in t["start_text"]
            and "not each byte of the message" in client_line
            for t in (traced, untraced)
        ),
        "manifest": all(
            t["client_trace"] == ["orders"] and t["unseen"] == ["mail"] for t in (traced, untraced)
        ),
        "replies": all(t["ok"] and t["reply"] == REPLY for t in (traced, untraced)),
        # Test A: a span of the queue in turn 1, and no finding.
        "span": any(s["turn"] == 1 for s in traced["queue_spans"])
        and traced["counts"]["other_without_span"] == 0
        and any("rabbitmq" in x for x in traced["transcript_lines"]),
        # Test B: no span of the queue, so the trace gives the finding, and the transcript has it.
        "finding": untraced["queue_spans"] == []
        and untraced["findings"] == [WANT]
        and any("orders: no span of its client" in x for x in untraced["transcript_lines"]),
        "report": all(t["prompt_has_client_rows"] for t in (traced, untraced)),
        "seal": all(t["seal_intact"] for t in (traced, untraced)),
    }
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
            "rabbitmq": rabbitmq or IMAGE,
            "app_packages": PACKAGES,
        },
        "answer_other": [ORDERS, MAIL],
        "traced": traced,
        "untraced": untraced,
        "checks": checks,
        "pass": all(checks.values()),
    }
    out = ROOT / "proofs" / "queue-trace" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(checks))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

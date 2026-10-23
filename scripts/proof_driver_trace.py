"""Proof that the driver trace gives the database calls of the app (SPEC.md sections 7.11 and 8.4).

A toy shop app reads its stock from a SQLite file. The app uses the OpenTelemetry instrumentation
of the sqlite3 driver and the OTLP exporter over HTTP. These packages go into a new virtual
environment of the app, not into Nookku. The egress answer gives the database `record: driver`. A
test sends one message, and the app runs 2 queries. The proof checks the manifest, the driver
queries of the trace and their database name, the `unseen_call` and `driver_without_span`
counts, the lines of the transcript that the report reads, and the seal. It needs no model, but
it needs the network to install the packages.

usage: python scripts/proof_driver_trace.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import json_lines  # noqa: E402

from nookku import __version__, bridge, discovery, evaluation, seal  # noqa: E402

# The packages of the app, with the versions that the proof records.
PACKAGES = [
    "opentelemetry-sdk==1.44.0",
    "opentelemetry-exporter-otlp-proto-http==1.44.0",
    "opentelemetry-instrumentation-sqlite3==0.65b0",
]

# The app instruments the driver before it connects. It flushes the spans before each reply, so
# that the receiver has them when the test ends.
ENTRY = """
import json, sqlite3, sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider(resource=Resource.create({"service.name": "toy-shop"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
SQLite3Instrumentor().instrument()

db = sqlite3.connect("stock.db")
db.execute("CREATE TABLE IF NOT EXISTS stock (sku TEXT, qty INTEGER)")
db.execute("DELETE FROM stock")
db.execute("INSERT INTO stock VALUES ('teapot-set', 3)")
db.commit()
provider.force_flush()

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    cur = db.cursor()
    cur.execute("SELECT qty FROM stock WHERE sku = ?", ("teapot-set",))
    (qty,) = cur.fetchone()
    provider.force_flush()
    reply = {"v": 1, "id": request["id"], "reply": f"{qty} teapot sets left."}
    sys.stdout.write(json.dumps(reply) + "\\n")
    sys.stdout.flush()
"""


def app_python(project: Path) -> Path:
    """A new virtual environment for the app, with the packages of the driver trace."""
    venv = project / ".venv"
    subprocess.run(["uv", "venv", "-q", "--python", sys.executable, str(venv)], check=True)
    python = venv / "bin" / "python"
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(python), *PACKAGES], check=True)
    return python


def main() -> int:
    project = Path(tempfile.mkdtemp(prefix="nookku-driver-"))
    (project / ".nookku").mkdir()
    (project / "entry.py").write_text(ENTRY)
    python = app_python(project)
    config = {"entry": [str(python), "entry.py"], "models": []}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    part = {"name": "stock", "kind": "sqlite", "env": None, "address": "stock.db"}
    discovery.register(project, discovery.make(databases=[{**part, "record": "driver"}]))
    cur = bridge.start(project)
    try:
        shown, ok = bridge.send(cur, "Do you have the teapot set?")
    finally:
        bridge.end(project)
    folder = Path(cur["dir"])
    manifest = json.loads((folder / "manifest.json").read_text())
    items = json_lines((folder / "trace.jsonl").read_text())
    queries = [
        {"turn": it["turn"], "session": it["session"], "name": it["name"], "input": it["input"]}
        for it in items
        if it["kind"] == "query" and it["harness"] == "driver"
    ]
    findings = json.loads((folder / "findings.json").read_text())
    text = evaluation.transcript(folder)
    lines = [x for x in text.splitlines() if "(driver trace from the app process)" in x]
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
            "app_packages": PACKAGES,
        },
        "reply": shown,
        "unseen": manifest["egress"]["unseen"],
        "driver": manifest["egress"]["driver"],
        "proxies": manifest["egress"]["proxies"],
        "driver_queries": queries,
        "unseen_call": findings["counts"]["unseen_call"],
        "driver_without_span": findings["counts"]["driver_without_span"],
        "transcript_lines": lines,
        "transcript_says_no_rows": evaluation.DRIVER_RESULT in text,
        "seal_intact": seal.verify(folder)["intact"],
    }
    turn = [q for q in queries if q["turn"] == 1]
    result["pass"] = (
        ok
        and shown == "3 teapot sets left."
        and result["unseen"] == []
        and result["driver"] == ["stock"]
        and len(turn) == 1
        and turn[0]["input"]["query"] == "SELECT qty FROM stock WHERE sku = ?"
        # The span has no db.name: the query gets the name of the database in the answer.
        and turn[0]["session"] == "stock"
        and result["unseen_call"] == 0
        and result["driver_without_span"] == 0
        and len(lines) == len(queries)
        and result["transcript_says_no_rows"]
        and result["seal_intact"]
    )
    out = ROOT / "proofs" / "driver-trace" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

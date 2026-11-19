"""Proof that nookku finds a call that an in-app trace tool does not show (#524, SPEC.md 8.10).

A toy shop app reads the stock of a teapot set and then reserves it, at a toy stock service. The
app sends its spans to Phoenix with the OpenTelemetry SDK and the OTLP exporter over HTTP. It
makes a span for the stock read, and no span for the reserve call: that is the planted call.
The backend proxy of the test records both calls.

After the test, the proof reads the spans back from the REST API of Phoenix, writes them as an
array of JSON records, and runs `nookku trace --openinference` with that file. It checks that
Phoenix has a span for the stock read and no span for the reserve call, and that the trace gives
`proxy_call_without_span` for the reserve call only.

Phoenix runs from PyPI in a new virtual environment, on 127.0.0.1. The packages of the app go into
another new virtual environment. Nookku gets no new package. The proof needs no model, but it
needs the network to install the packages.

usage: python scripts/proof_inapp_trace.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from proof_common import json_lines  # noqa: E402
from toy_stock_server import StockServer  # noqa: E402

from nookku import __version__, bridge, discovery, seal  # noqa: E402
from nookku.cli import main as cli  # noqa: E402
from nookku.record import loads  # noqa: E402

# The trace tool, with the version that the proof records.
PHOENIX = "arize-phoenix==21.0.0"
# The packages of the app.
PACKAGES = ["opentelemetry-sdk==1.44.0", "opentelemetry-exporter-otlp-proto-http==1.44.0"]
PROJECT = "toy-shop"
MESSAGE = "Please reserve the teapot set."
REPLY = "The teapot set is reserved for you. 3 are in stock."
WANT = {
    "check": "proxy_call_without_span",
    "turn": 1,
    "detail": "POST /reserve: no matching span in the export",
    "harness": "backend",
    "session": "stock",
}

# The app makes a span for the stock read and no span for the reserve call. It flushes the spans
# before each reply, so that Phoenix has them when the test ends.
ENTRY = """
import json, os, sys, urllib.request

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

resource = Resource.create({"service.name": "toy-shop", "openinference.project.name": "@PROJECT@"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint=os.environ["TOY_SHOP_PHOENIX"] + "/v1/traces")
provider.add_span_processor(SimpleSpanProcessor(exporter))
tracer = provider.get_tracer("toy-shop")
base = os.environ["STOCK_URL"]

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    url = base + "/stock"
    attributes = {
        "openinference.span.kind": "CHAIN",
        "http.request.method": "GET",
        "url.full": url,
    }
    with tracer.start_as_current_span("read stock", attributes=attributes):
        stock = json.loads(urllib.request.urlopen(url, timeout=10).read())
    # The planted call: the app reserves the teapot set with no span.
    reserve = urllib.request.Request(
        base + "/reserve",
        data=json.dumps({"sku": stock["sku"]}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(reserve, timeout=10).read()
    provider.force_flush()
    reply = {"v": 1, "id": request["id"], "reply": "@REPLY@"}
    sys.stdout.write(json.dumps(reply) + "\\n")
    sys.stdout.flush()
""".replace("@PROJECT@", PROJECT).replace("@REPLY@", REPLY)


def venv(folder: Path, packages: list[str]) -> Path:
    """A new virtual environment with the packages. Return its bin folder."""
    subprocess.run(["uv", "venv", "-q", "--python", sys.executable, str(folder)], check=True)
    python = folder / "bin" / "python"
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(python), *packages], check=True)
    return folder / "bin"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def start_phoenix(bin_dir: Path, work: Path) -> tuple[subprocess.Popen[bytes], str]:
    """Start Phoenix on 127.0.0.1 with its data in `work`. Return the process and its URL."""
    port = free_port()
    env = {
        **os.environ,
        "PHOENIX_HOST": "127.0.0.1",
        "PHOENIX_PORT": str(port),
        "PHOENIX_GRPC_PORT": str(free_port()),
        "PHOENIX_WORKING_DIR": str(work),
        "PHOENIX_TELEMETRY_ENABLED": "false",
    }
    log = (work / "phoenix.log").open("wb")
    proc = subprocess.Popen(
        [str(bin_dir / "phoenix"), "serve"], env=env, stdout=log, stderr=subprocess.STDOUT
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            sys.exit(f"Phoenix stopped with exit code {proc.returncode}: see {work}/phoenix.log")
        try:
            with urllib.request.urlopen(url + "/v1/projects", timeout=5) as r:
                if r.status == 200:
                    return proc, url
        except OSError:
            pass
        time.sleep(1)
    proc.kill()
    sys.exit("Phoenix did not start in 180 seconds")


def phoenix_spans(url: str) -> list[dict[str, Any]]:
    """Each span of the project in Phoenix, from its REST API, page by page."""
    out: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = "?limit=100" + (f"&cursor={cursor}" if cursor else "")
        with urllib.request.urlopen(f"{url}/v1/projects/{PROJECT}/spans{query}", timeout=30) as r:
            page = json.loads(r.read())
        out += page["data"]
        cursor = page.get("next_cursor")
        if not cursor:
            return out


def calls_of(spans: list[dict[str, Any]]) -> list[str]:
    """The method and the path of each span with an HTTP call, as `METHOD /path`."""
    out = []
    for span in spans:
        attrs = span.get("attributes") or {}
        method, url = attrs.get("http.request.method"), attrs.get("url.full")
        if isinstance(method, str) and isinstance(url, str):
            out.append(f"{method} {urllib.parse.urlsplit(url).path}")
    return out


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-inapp-"))
    phoenix_bin = venv(work / "phoenix-venv", [PHOENIX])
    project = work / "shop"
    (project / ".nookku").mkdir(parents=True)
    (project / "entry.py").write_text(ENTRY)
    app_bin = venv(project / ".venv", PACKAGES)
    config = {"entry": [str(app_bin / "python"), "entry.py"], "models": []}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    proc, url = start_phoenix(phoenix_bin, work)
    os.environ["TOY_SHOP_PHOENIX"] = url
    try:
        with StockServer() as stock:
            backends = [{"name": "stock", "env": "STOCK_URL", "url": stock.url}]
            discovery.register(project, discovery.make(backends=backends))
            cur = bridge.start(project)
            try:
                shown, ok = bridge.send(cur, MESSAGE)
            finally:
                bridge.end(project)
            seen = [f"{r['method']} {r['path']}" for r in stock.seen]
        spans = phoenix_spans(url)
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    folder = Path(cur["dir"])
    export = work / "phoenix-spans.json"
    export.write_text(json.dumps(spans, indent=1) + "\n")
    rebuilt = cli(["trace", folder.name, "--root", str(project), "--openinference", str(export)])
    backend_calls = [
        f"{r['method']} {r['path']}"
        for r in json_lines((folder / "backend.jsonl").read_text())
        if r.get("type") == "call"
    ]
    findings = loads((folder / "findings.json").read_text())
    found = [
        {k: f[k] for k in WANT}
        for f in findings["findings"]
        if f["check"] == "proxy_call_without_span"
    ]
    span_calls = calls_of(spans)
    checks = {
        "reply": ok and shown == REPLY,
        # The stock service got both calls, and the backend proxy recorded both.
        "proxy": seen == ["GET /stock", "POST /reserve"] and backend_calls == seen,
        # Phoenix shows the stock read and does not show the reserve call.
        "phoenix": span_calls == ["GET /stock"],
        "trace_rebuilt": rebuilt == 0
        and findings.get("openinference", {}).get("spans") == len(spans),
        # The trace finds the reserve call, and only that call.
        "finding": found == [WANT],
        "seal": seal.verify(folder)["intact"],
    }
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
            "phoenix": PHOENIX,
            "app_packages": PACKAGES,
        },
        "model_used": False,
        "method": "scripts/proof_inapp_trace.py",
        "stock_service_calls": seen,
        "backend_calls": backend_calls,
        "phoenix_spans": [
            {
                "name": s.get("name"),
                "span_kind": s.get("span_kind"),
                "attributes": {
                    k: v
                    for k, v in (s.get("attributes") or {}).items()
                    if k in ("openinference.span.kind", "http.request.method", "url.full")
                },
            }
            for s in spans
        ],
        "phoenix_calls": span_calls,
        "findings": found,
        "checks": checks,
        "pass": all(checks.values()),
    }
    out = ROOT / "proofs" / "inapp-trace" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(checks))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

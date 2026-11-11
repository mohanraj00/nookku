"""Plant one missing span for a toy stock call and run the trace import."""

from __future__ import annotations

import contextlib
import datetime
import http.client
import io
import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from nookku import __version__, backend, bridge
from nookku.cli import main as cli
from nookku.record import Writer, loads

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from toy_stock_server import StockServer  # noqa: E402

CASE = ROOT / "conformance" / "openinference" / "missing-stock-span.json"
TEST = "20261109-100000-ab12"


def stamp(value: float) -> str:
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat()


def main() -> int:
    case = loads(CASE.read_bytes())
    with TemporaryDirectory(prefix="nookku-oi-") as work:
        root = Path(work)
        folder = root / ".nookku" / "tests" / TEST
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"test": TEST}) + "\n", encoding="utf-8")
        started = time.time()
        with StockServer() as stock:
            proxies = backend.Proxies(
                [backend.Backend("stock", "STOCK_URL", stock.url)], folder / backend.FILE
            )
            proxies.start()
            try:
                host, port = proxies.proxies[0].server_address
                for call in case["calls"]:
                    conn = http.client.HTTPConnection(host, port, timeout=10)
                    try:
                        conn.request(call["method"], call["path"])
                        assert conn.getresponse().read()
                    finally:
                        conn.close()
            finally:
                proxies.stop()
        Writer(folder / "tap.jsonl").append(
            {
                "type": "exchange",
                "started": started,
                "status": 200,
                "input": "Is the teapot in stock?",
                "reply": "The teapot is in stock.",
            }
        )
        first = loads((folder / backend.FILE).read_text().split("\n")[0])
        span = {
            **case["phoenix"][0],
            "start_time": stamp(first["started"]),
            "end_time": stamp(first["ts"]),
        }
        export = root / "app-spans.json"
        export.write_text(json.dumps([span]), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli(
                ["trace", "--root", str(root), TEST, "--json", "--openinference", str(export)]
            )
        report = loads(output.getvalue()) if code == 0 else {}
        findings = report.get("findings")
        spans = report.get("openinference", {}).get("spans")
        passed = code == 0 and spans == 1 and findings == [case["finding"]]
    proof = {
        "date": datetime.date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "claude_code": bridge._version("claude"),
            "codex": bridge._version("codex"),
        },
        "method": "scripts/proof_openinference.py",
        "case": str(CASE.relative_to(ROOT)),
        "model_used": False,
        "passed": passed,
        "exported_spans": spans,
        "findings": findings,
    }
    out = ROOT / "proofs" / "openinference" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if passed else 'FAIL'}: {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Proof that the backend proxy forwards each byte without change (SPEC.md section 7.6).

A toy stock service runs on a local port. A test runs an entry that, for one message, makes 3 calls
to the service through the proxy: a binary POST, a UTF-8 GET and a POST of 2 MiB. The service
answers each call with other bytes. The proof compares the SHA-256 of each body at 3 places: the
entry, the service and backend.jsonl. It needs no model, so its result is the same on each run.

usage: python scripts/proof_backend.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import json_lines  # noqa: E402

from nookku import __version__, backend, bridge, seal, stdio  # noqa: E402

SEEN: list[dict[str, str]] = []

# The entry sends the 3 calls for one message and replies with the SHA-256 of what it sent and got.
ENTRY = """
import hashlib, json, os, sys, urllib.request

def sha(b):
    return hashlib.sha256(b).hexdigest()

url = os.environ["STOCK_URL"]
calls = [
    ("POST", "/scan", bytes(range(256)) * 4 + b"\\x00\\xff"),
    ("GET", "/stock?sku=teapot-set&note=%E2%82%AC", None),
    ("POST", "/import", ("teapot set €80, order 5120\\n" * 80000).encode()),
]
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = []
    for method, path, body in calls:
        req = urllib.request.Request(url + path, data=body, method=method)
        req.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req, timeout=30) as r:
            got = r.read()
        out.append({"sent": sha(body or b""), "got": sha(got)})
    reply = {"v": 1, "id": request["id"], "reply": json.dumps(out)}
    sys.stdout.write(json.dumps(reply) + "\\n")
    sys.stdout.flush()
"""


class Stock(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        answer = hashlib.sha256(self.path.encode()).digest() * 64 + "€ left: 3".encode()
        SEEN.append(
            {
                "path": self.path,
                "got": hashlib.sha256(body).hexdigest(),
                "sent": hashlib.sha256(answer).hexdigest(),
            }
        )
        self.send_response_only(200)
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    do_POST = do_GET


class StockServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        stdio.bind(self)


def main() -> int:
    stock = StockServer(("127.0.0.1", 0), Stock)
    threading.Thread(target=stock.serve_forever, daemon=True).start()
    project = Path(tempfile.mkdtemp(prefix="nookku-backend-"))
    (project / ".nookku").mkdir()
    (project / "entry.py").write_text(ENTRY)
    config = {
        "entry": [sys.executable, "entry.py"],
        "models": [],
        "otel": False,
        "backends": [
            {
                "name": "stock",
                "env": "STOCK_URL",
                "url": f"http://127.0.0.1:{stock.server_address[1]}",
            }
        ],
    }
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    cur = bridge.start(project)
    try:
        shown, ok = bridge.send(cur, "Scan, check and import the teapot sets.")
    finally:
        bridge.end(project)
        stock.shutdown()
        stock.server_close()
    folder = Path(cur["dir"])
    entry = json.loads(shown) if ok else []
    rows = json_lines((folder / backend.FILE).read_text())
    calls = []
    for i, (e, s, r) in enumerate(zip(entry, SEEN, rows, strict=True)):
        calls.append(
            {
                "call": i + 1,
                "path": s["path"],
                "request_size": r["request_body"]["size"],
                "response_size": r["response_body"]["size"],
                "request_same": e["sent"] == s["got"] == r["request_body"]["sha256"],
                "response_same": s["sent"] == e["got"] == r["response_body"]["sha256"],
                "record_cut": r["request_body"]["cut"] or r["response_body"]["cut"],
            }
        )
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
        },
        "calls": calls,
        "seal_intact": seal.verify(folder)["intact"],
    }
    result["pass"] = (
        len(calls) == 3
        and all(c["request_same"] and c["response_same"] for c in calls)
        and result["seal_intact"]
    )
    out = ROOT / "proofs" / "backend" / "results.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

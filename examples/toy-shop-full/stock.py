"""The stock service of the full toy shop: it holds the stock and the reservations.

    python examples/toy-shop-full/stock.py [port]

The state is in stock.json (or $TOY_STOCK_STATE). It uses only the standard library.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


class StockService(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, state: Path) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.state = state
        self.lock = threading.Lock()

    def server_bind(self) -> None:
        # Bind without the name lookup of HTTPServer, which can take seconds on macOS.
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: StockService
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _answer(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response_only(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        sku = parse_qs(url.query).get("sku", [""])[0]
        items = json.loads(self.server.state.read_text(encoding="utf-8"))
        if url.path != "/stock" or sku not in items:
            self._answer(404, {"error": f"no such item: {sku}"})
            return
        self._answer(200, {"sku": sku, "left": items[sku]["left"]})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path != "/reserve":
            self._answer(404, {"error": "no such path"})
            return
        ask = json.loads(raw)
        with self.server.lock:
            items = json.loads(self.server.state.read_text(encoding="utf-8"))
            item = items.get(ask.get("sku"))
            if item is None or item["left"] < ask.get("qty", 0):
                self._answer(409, {"error": "not enough stock"})
                return
            item["left"] -= ask["qty"]
            done = {
                "reservation": f"RS-{secrets.token_hex(3).upper()}",
                "order": ask.get("order"),
                "qty": ask["qty"],
            }
            item.setdefault("reservations", []).append(done)
            text = json.dumps(items, indent=1, ensure_ascii=False) + "\n"
            self.server.state.write_text(text, encoding="utf-8")
        self._answer(200, {**done, "sku": ask["sku"], "left": item["left"]})


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9001
    state = Path(os.environ.get("TOY_STOCK_STATE", Path(__file__).with_name("stock.json")))
    server = StockService(port, state)
    print(f"stock service on {server.url}, state {state}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()

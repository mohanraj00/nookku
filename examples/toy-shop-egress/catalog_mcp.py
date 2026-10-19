"""The catalog MCP server of the toy shop, over HTTP at /mcp. Standard library only.

It has 1 tool, `find_product`, with the price and the stock of a product. A POST to /mcp holds
one JSON-RPC message, and the response is JSON. The server has no event stream, so a GET gets
405.

usage: python3 catalog_mcp.py [PORT]   (default 9310)
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import toy_mcp

PORT = 9310
PRODUCTS = {
    "teapot-set": {"name": "Teapot set", "price_eur": 80, "in_stock": 3},
    "wooden-train": {"name": "Wooden train set", "price_eur": 45, "in_stock": 0},
    "mug": {"name": "Mug", "price_eur": 8, "in_stock": 12},
}
TOOLS = [
    {
        "name": "find_product",
        "description": "The price in EUR and the stock of a toy shop product. Give a part of "
        "its name, for example 'train'.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        "annotations": {"readOnlyHint": True},
    }
]


def run(tool: str, args: dict[str, Any]) -> tuple[Any, bool]:
    word = str(args.get("name", "")).lower()
    found = [
        {"sku": sku, **p}
        for sku, p in PRODUCTS.items()
        if word and (word in sku or word in p["name"].lower())
    ]
    return (found, False) if found else (f"no product matches {word!r}", True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/mcp":
            self._send(404, b"")
            return
        size = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(size))
        except ValueError:
            request = None
        response = toy_mcp.answer(request, "catalog", TOOLS, run)
        if response is None:
            self._send(202, b"")
        else:
            self._send(200, json.dumps(response).encode(), "application/json")

    def do_GET(self) -> None:
        self._send(405, b"")

    def do_DELETE(self) -> None:
        self._send(405, b"")

    def _send(self, status: int, body: bytes, kind: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


class CatalogServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = PORT) -> None:
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/mcp"


if __name__ == "__main__":
    server = CatalogServer(int(sys.argv[1]) if len(sys.argv) > 1 else PORT)
    print(f"catalog MCP server on {server.url}", flush=True)
    server.serve_forever()

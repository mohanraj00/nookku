"""The toy shop chat agent as an HTTP server, for the tap in HTTP mode. Standard library only.

POST {"text": "<message>"} to http://127.0.0.1:8700/ and it answers {"reply": "<text>"}.

usage: python examples/toy-shop/http_agent.py [PORT]
"""

from __future__ import annotations

import json
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import answer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        text = json.loads(body).get("text", "")
        out = json.dumps({"reply": answer(text)}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class Server(ThreadingHTTPServer):
    def server_bind(self) -> None:
        # HTTPServer looks up the host name here, and the lookup can take seconds. The toy shop
        # does not use the name, so it skips the lookup and listens at once.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8700
    print(f"toy shop agent on http://127.0.0.1:{port}/", file=sys.stderr)
    Server(("127.0.0.1", port), Handler).serve_forever()

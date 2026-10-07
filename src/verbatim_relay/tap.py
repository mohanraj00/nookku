"""The tap of SPEC.md section 4: a proxy that forwards without change and writes the tap record."""

from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from verbatim_relay.adapters import Adapter, AdapterError
from verbatim_relay.record import Writer, lone_surrogate

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
NOT_FORWARDED = HOP_BY_HOP | {"host", "accept-encoding", "content-length"}
NOT_RETURNED = HOP_BY_HOP | {"content-length"}
TIMEOUT = 300


class Tap(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, listen: tuple[str, int], agent: str, record: Path, adapter: Adapter) -> None:
        parts = urlsplit(agent)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"the agent URL must be http or https: {agent!r}")
        self.scheme, self.agent_host = parts.scheme, parts.hostname
        self.agent_port = parts.port or (443 if parts.scheme == "https" else 80)
        self.base_path = parts.path.rstrip("/")
        self.writer, self.adapter = Writer(record), adapter
        super().__init__(listen, _Handler)

    def connect(self) -> http.client.HTTPConnection:
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.agent_host, self.agent_port, timeout=TIMEOUT)


class _Handler(BaseHTTPRequestHandler):
    server: Tap
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.send_response_only(status)
        for name, value in headers:
            if name.lower() not in NOT_RETURNED:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode()
        self._send(status, [("Content-Type", "application/json")], body)

    def _forward(self) -> None:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self._error(411, "verbatim-relay needs a Content-Length request body")
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        tap, method, path = self.server, self.command, self.path
        recorded = tap.adapter.accepts(method, path)
        refusal = tap.adapter.refuse(body) if recorded else None
        if refusal:
            self._error(501, refusal)
            return
        message, parse_error = None, None
        if recorded:
            try:
                message = tap.adapter.message(body)
            except AdapterError as e:
                parse_error = f"request: {e}"
            found = None if message is None else lone_surrogate(message)
            if found:
                # The record cannot hold the message. The tap marks it as unparsed.
                message, parse_error = None, f"request: the message has {found}"

        headers = {k: v for k, v in self.headers.items() if k.lower() not in NOT_FORWARDED}
        headers["Accept-Encoding"] = "identity"
        conn = tap.connect()
        try:
            conn.request(method, tap.base_path + path, body=body if body else None, headers=headers)
            resp = conn.getresponse()
            status, out_headers, out = resp.status, resp.getheaders(), resp.read()
        except (OSError, http.client.HTTPException) as e:
            if message is not None:
                tap.writer.append(
                    {
                        "type": "exchange",
                        "input": message,
                        "status": None,
                        "reply": None,
                        "error": f"agent unreachable: {e}",
                    }
                )
            elif recorded:
                tap.writer.append(
                    {
                        "type": "unparsed",
                        "method": method,
                        "path": path,
                        "error": parse_error or "unknown",
                    }
                )
            self._error(502, f"verbatim-relay tap: the agent is unreachable: {e}")
            return
        finally:
            conn.close()

        if recorded:
            if message is None:
                tap.writer.append(
                    {
                        "type": "unparsed",
                        "method": method,
                        "path": path,
                        "error": parse_error or "unknown",
                    }
                )
            elif 200 <= status < 300:
                try:
                    reply = tap.adapter.reply(out)
                except AdapterError as e:
                    tap.writer.append(
                        {
                            "type": "unparsed",
                            "method": method,
                            "path": path,
                            "error": f"response: {e}",
                        }
                    )
                else:
                    found = lone_surrogate(reply)
                    if found:
                        # The record cannot hold the reply, so the relay gets an error.
                        note = f"the agent reply has {found}"
                        tap.writer.append(
                            {
                                "type": "exchange",
                                "input": message,
                                "status": None,
                                "reply": None,
                                "error": note,
                            }
                        )
                        self._error(502, f"verbatim-relay tap: {note}")
                        return
                    tap.writer.append(
                        {"type": "exchange", "input": message, "status": status, "reply": reply}
                    )
            else:
                tap.writer.append(
                    {
                        "type": "exchange",
                        "input": message,
                        "status": status,
                        "reply": None,
                        "error": f"HTTP {status}",
                    }
                )
        self._send(status, out_headers, out)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _forward


def serve(tap: Tap) -> None:
    host, port = tap.server_address[:2]
    host = host.decode() if isinstance(host, bytes) else host
    print(
        f"verbatim-relay tap: listening on http://{host}:{port}/ "
        f"-> {tap.scheme}://{tap.agent_host}:{tap.agent_port}{tap.base_path}/",
        file=sys.stderr,
    )
    print(f"verbatim-relay tap: writing {tap.writer.path}", file=sys.stderr)
    try:
        tap.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tap.server_close()


def start_in_thread(tap: Tap) -> threading.Thread:
    thread = threading.Thread(target=tap.serve_forever, daemon=True)
    thread.start()
    return thread

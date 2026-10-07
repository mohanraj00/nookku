"""The tap of SPEC.md section 4: a proxy that forwards without change and writes the tap record."""

from __future__ import annotations

import hashlib
import http.client
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from verbatim_relay.adapters import Adapter, AdapterError, StreamError, is_stream
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
            status, out_headers = resp.status, resp.getheaders()
            if is_stream(resp.getheader("Content-Type")) and method != "HEAD":
                self._stream(resp, recorded, message, parse_error)
                return
            out = resp.read()
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

    def _stream(
        self,
        resp: http.client.HTTPResponse,
        recorded: bool,
        message: str | None,
        parse_error: str | None,
    ) -> None:
        """Send each part of an SSE response to the caller when it comes (SPEC.md section 4.1).

        The tap writes the row when the stream ends, before the end of the response to the caller.
        This function catches each error itself, because the caller already has the status.
        """
        length = resp.getheader("Content-Length")
        caller = True
        try:
            self.send_response_only(resp.status)
            for name, value in resp.getheaders():
                if name.lower() not in NOT_RETURNED:
                    self.send_header(name, value)
            if length is None:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", length)
            self.end_headers()
            self.wfile.flush()
        except OSError:
            caller = False
        raw = bytearray()
        failure = None
        while True:
            try:
                part = resp.read1(65536)
            except (OSError, http.client.HTTPException) as e:
                failure = f"the stream from the agent stopped: {e}"
                break
            if not part:
                break
            raw += part
            if caller:
                # The record keeps all of the stream, also if the caller went away.
                try:
                    chunk = part if length is not None else b"%x\r\n%s\r\n" % (len(part), part)
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except OSError:
                    caller = False
        if failure is None and length is not None and resp.length:
            # read1 gives b"" at an early end of a body with a Content-Length. It does not raise.
            failure = f"the stream from the agent stopped after {len(raw)} of {length} bytes"
        if recorded:
            self._stream_row(resp.status, bytes(raw), message, parse_error, failure)
        if caller and failure is None and length is None:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                pass
        # After a failure, the caller gets an incomplete body, the same as from the agent.
        if failure is not None or not caller:
            self.close_connection = True

    def _stream_row(
        self,
        status: int,
        raw: bytes,
        message: str | None,
        parse_error: str | None,
        failure: str | None,
    ) -> None:
        """Write the row of a streamed response. A failed stream gets no reply, only an error."""
        tap, method, path = self.server, self.command, self.path
        unparsed = {"type": "unparsed", "method": method, "path": path}
        if message is None:
            tap.writer.append({**unparsed, "error": parse_error or "unknown"})
            return
        row: dict[str, object] = {"type": "exchange", "input": message, "status": status}
        row["reply"] = None
        if not 200 <= status < 300:
            row["error"] = f"HTTP {status}"
        elif failure is not None:
            row["error"] = failure
        else:
            try:
                row["reply"] = tap.adapter.stream_reply(raw)
            except StreamError as e:
                row["error"] = str(e)
            except AdapterError as e:
                tap.writer.append({**unparsed, "error": f"response: {e}"})
                return
        row["stream"] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        tap.writer.append(row)

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

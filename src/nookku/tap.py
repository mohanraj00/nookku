"""The tap of SPEC.md section 4: a proxy that forwards without change and writes the tap record."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from nookku.adapters import Adapter, AdapterError, StreamError, is_stream
from nookku.record import Writer, lone_surrogate
from nookku.stdio import TIMEOUT

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


class Tap(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        listen: tuple[str, int],
        agent: str,
        record: Path,
        adapter: Adapter,
        timeout: float = TIMEOUT,
    ) -> None:
        parts = urlsplit(agent)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"the agent URL must be http or https: {agent!r}")
        self.scheme, self.agent_host = parts.scheme, parts.hostname
        self.agent_port = parts.port or (443 if parts.scheme == "https" else 80)
        self.base_path = parts.path.rstrip("/")
        self.writer, self.adapter, self.timeout = Writer(record), adapter, timeout
        super().__init__(listen, _Handler)

    def connect(self) -> http.client.HTTPConnection:
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.agent_host, self.agent_port, timeout=self.timeout)


def _expire(conn: http.client.HTTPConnection, expired: threading.Event) -> None:
    """Stop a read from the agent at the deadline. The read then fails or returns early."""
    expired.set()
    if conn.sock is not None:
        with contextlib.suppress(OSError):
            conn.sock.shutdown(socket.SHUT_RDWR)


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
            self._error(411, "nookku needs a Content-Length request body")
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
        # The socket timeout starts again after each read. This timer gives one deadline for the
        # whole response, so an agent that sends a byte at a time still gets a 504.
        expired = threading.Event()
        timer = threading.Timer(tap.timeout or TIMEOUT, _expire, (conn, expired))
        timer.daemon = True
        timer.start()
        try:
            self._exchange(conn, body, headers, recorded, message, parse_error, expired)
        finally:
            timer.cancel()
            conn.close()

    def _exchange(
        self,
        conn: http.client.HTTPConnection,
        body: bytes,
        headers: dict[str, str],
        recorded: bool,
        message: str | None,
        parse_error: str | None,
        expired: threading.Event,
    ) -> None:
        """Send the request to the agent, then send its response to the caller and write the row."""
        tap, method, path = self.server, self.command, self.path
        try:
            conn.request(method, tap.base_path + path, body=body if body else None, headers=headers)
            resp = conn.getresponse()
            status, out_headers = resp.status, resp.getheaders()
            streamed = is_stream(resp.getheader("Content-Type")) and method != "HEAD"
            out = b"" if streamed else resp.read()
            if expired.is_set() and not streamed:
                raise TimeoutError
        except (OSError, http.client.HTTPException) as e:
            # After the agent timeout, the tap answers 504 before the relay timeout (SPEC.md 4.3).
            late = isinstance(e, TimeoutError) or expired.is_set()
            why = f"the agent sent no response in {tap.timeout:g} s" if late else None
            if message is not None:
                tap.writer.append(
                    {
                        "type": "exchange",
                        "input": message,
                        "status": None,
                        "reply": None,
                        "error": why or f"agent unreachable: {e}",
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
            if why:
                self._error(504, f"nookku tap: {why}")
            else:
                self._error(502, f"nookku tap: the agent is unreachable: {e}")
            return
        if streamed:
            # The stream sends the status first, so it runs outside the try above. Thus no handler
            # sends a second status after the headers.
            self._stream(resp, recorded, message, parse_error, expired)
            return

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
                        self._error(502, f"nookku tap: {note}")
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
        expired: threading.Event,
    ) -> None:
        """Send each part of an SSE response to the caller when it comes (SPEC.md section 4.1).

        The tap writes the row when the stream ends, before the end of the response to the caller.
        The caller already has the status, so no error here sends a second status. If the tap
        cannot write the row, it writes the error to stderr and closes the connection. It does not
        send the end of a chunked body, so the caller gets an incomplete body.
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
        # With a Content-Length, the caller has a full response only with the last byte. The tap
        # holds that byte until the row is in the record, so a failed write leaves it incomplete.
        held = b""
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
                    if length is not None:
                        data = held + part
                        chunk, held = data[:-1], data[-1:]
                    else:
                        chunk = b"%x\r\n%s\r\n" % (len(part), part)
                    if chunk:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except OSError:
                    caller = False
        if expired.is_set():
            # The deadline of the tap stopped the read, so the stream is not complete (SPEC.md 4.3).
            failure = f"the agent sent no full response in {self.server.timeout:g} s"
        elif failure is None and length is not None and resp.length:
            # read1 gives b"" at an early end of a body with a Content-Length. It does not raise.
            failure = f"the stream from the agent stopped after {len(raw)} of {length} bytes"
        if recorded:
            try:
                self._stream_row(resp.status, bytes(raw), message, parse_error, failure)
            except OSError as e:
                print(f"nookku tap: cannot write the record: {e}", file=sys.stderr)
                self.close_connection = True
                return
        if caller and held:
            try:
                self.wfile.write(held)
                self.wfile.flush()
            except OSError:
                caller = False
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
        f"nookku tap: listening on http://{host}:{port}/ "
        f"-> {tap.scheme}://{tap.agent_host}:{tap.agent_port}{tap.base_path}/",
        file=sys.stderr,
    )
    print(f"nookku tap: writing {tap.writer.path}", file=sys.stderr)
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

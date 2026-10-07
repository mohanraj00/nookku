"""The backend proxies of SPEC.md section 7.6.

During a test, the bridge runs one recording proxy for each backend in the configuration, and gives
the entry the proxy URL in the backend's environment variable. The proxy forwards each request to
the real URL and sends the response back with no change. It writes one row for each call to
backend.jsonl, without the values of secret headers and secret query parameters.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import http.client
import json
import threading
import time
import zlib
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus, urlsplit

from . import stdio
from .record import json_text
from .tap import HOP_BY_HOP

FILE = "backend.jsonl"
VERSION = 1
TIMEOUT = 120
# A body larger than this goes into the record cut. The app always gets all of the bytes.
RECORD_LIMIT = 1024 * 1024
# The rule for the names of secret headers and secret query parameters: a name in SECRET_HEADERS
# or SECRET_NAMES, or a name that contains a part in SECRET_PARTS. Case does not apply.
SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie"}
SECRET_NAMES = {"auth", "sig"}
SECRET_PARTS = ("key", "token", "secret", "password", "signature")
REMOVED = "<removed>"
# The app does not know that it speaks to a proxy, so the proxy headers go through.
NOT_FORWARDED = (HOP_BY_HOP - {"proxy-authorization"}) | {"host", "content-length"}
NOT_RETURNED = (HOP_BY_HOP - {"proxy-authenticate"}) | {"content-length"}
# At the end of the test, the time to wait for the calls that did not end.
DRAIN = 10.0
ENDED = "the test ended before the backend answered"


@dataclass
class Backend:
    name: str
    env: str
    url: str


def parse(raw: Any) -> list[Backend]:
    """The `backends` key of the configuration. Raise ValueError if it is not valid."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("'backends' must be a list")
    out: list[Backend] = []
    for b in raw:
        if not isinstance(b, dict) or not all(
            isinstance(b.get(k), str) for k in ("name", "env", "url")
        ):
            raise ValueError("each backend needs the strings 'name', 'env' and 'url'")
        if urlsplit(b["url"]).scheme not in ("http", "https") or not urlsplit(b["url"]).hostname:
            raise ValueError(f"backend {b['name']}: 'url' must be an http or https URL")
        out.append(Backend(b["name"], b["env"], b["url"].rstrip("/")))
    names = [b.name for b in out]
    if len(set(names)) != len(names) or len({b.env for b in out}) != len(out):
        raise ValueError("each backend needs its own 'name' and 'env'")
    return out


def secret(name: str) -> bool:
    low = name.lower()
    return low in SECRET_HEADERS or low in SECRET_NAMES or any(p in low for p in SECRET_PARTS)


def headers_row(items: list[tuple[str, str]]) -> list[list[str]]:
    """The headers as [name, value] pairs, in their order, with the secret values removed."""
    return [[k, REMOVED if secret(k) else v] for k, v in items]


def query_row(query: str) -> str:
    """The query with the values of the secret parameters removed. Each name, each `=` and each
    `&` stays, in its order. The rule reads the decoded name, for example `api%5Fkey`."""
    parts = []
    for part in query.split("&"):
        name, eq, _ = part.partition("=")
        parts.append(name + eq if eq and secret(unquote_plus(name)) else part)
    return "&".join(parts)


def decode(data: bytes, encoding: str | None) -> bytes | None:
    """The decoded bytes of a gzip or deflate body, or None."""
    if encoding not in ("gzip", "deflate") or not data:
        return None
    try:
        return gzip.decompress(data) if encoding == "gzip" else zlib.decompress(data)
    except (OSError, EOFError, zlib.error):
        return None


def body_row(data: bytes, encoding: str | None = None) -> dict[str, Any]:
    """A body in the record: its size, its SHA-256 and its text (UTF-8) or base64.

    For a gzip or deflate body, `text` is the decoded body, so that the record can be read.
    """
    out: dict[str, Any] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    shown = decode(data, encoding)
    if shown is not None:
        out["decoded"] = encoding
    else:
        shown = data
    out["cut"] = len(shown) > RECORD_LIMIT
    shown = shown[:RECORD_LIMIT]
    try:
        out["text"] = shown.decode("utf-8")
    except UnicodeDecodeError:
        out["base64"] = base64.b64encode(shown).decode()
    return out


def read_chunked(rfile: Any) -> bytes:
    """A request body with Transfer-Encoding: chunked."""
    out = b""
    while True:
        line = rfile.readline(65537)
        size = int(line.split(b";")[0].strip() or b"0", 16)
        if size == 0:
            while rfile.readline(65537) not in (b"\r\n", b"\n", b""):
                pass
            return out
        out += rfile.read(size)
        rfile.readline(65537)


class Proxy(ThreadingHTTPServer):
    """One recording proxy for one backend."""

    daemon_threads = True
    # True: send each part of the response to the app when it comes (SPEC.md section 7.7).
    streaming = False

    def __init__(self, backend: Backend, record: Path, lock: threading.Condition) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.backend = backend
        self.record = record
        self.lock = lock
        # The rows of the calls that did not end, by their id.
        self.open: dict[int, dict[str, Any]] = {}
        self.closed = False
        target = urlsplit(backend.url)
        self.scheme = target.scheme
        self.host = target.hostname or ""
        self.port = target.port
        self.base_path = target.path.rstrip("/")
        self.host_header = target.netloc

    def server_bind(self) -> None:
        stdio.bind(self)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}"

    def connect(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=TIMEOUT)
        return http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT)

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        """Add to the row of a new call. A subclass can change it."""

    def complete(self, row: dict[str, Any], body: bytes, encoding: str | None) -> None:
        """Add to the row of a call that has its response. A subclass can change it."""

    def begin(self, row: dict[str, Any]) -> bool:
        """Add the call to the open calls. Return False if the proxy is closed."""
        with self.lock:
            if self.closed:
                return False
            self.open[id(row)] = row
            return True

    def end(self, row: dict[str, Any]) -> None:
        """Write the row of the call, if the proxy did not write it at the end of the test."""
        with self.lock:
            if self.open.pop(id(row), None) is not None:
                self._write(row)
            self.lock.notify_all()

    def close(self) -> None:
        """Write a row for each open call, then write no more rows. Hold the lock."""
        for row in self.open.values():
            row.update(ts=time.time(), error=ENDED)
            self._write(row)
        self.open.clear()
        self.closed = True

    def _write(self, row: dict[str, Any]) -> None:
        with self.record.open("a", encoding="utf-8") as fh:
            fh.write(json_text(row) + "\n")


class Handler(BaseHTTPRequestHandler):
    server: Proxy
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self._forward()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_GET

    def _forward(self) -> None:
        started = time.time()
        proxy, method = self.server, self.command
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            body = read_chunked(self.rfile)
        else:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path, _, query = self.path.partition("?")
        sent = [(k, v) for k, v in self.headers.items() if k.lower() not in NOT_FORWARDED]
        row: dict[str, Any] = {
            "v": VERSION,
            "type": "call",
            "backend": proxy.backend.name,
            "started": started,
            "ts": None,
            "method": method,
            "path": path,
            "query": query_row(query) if query else None,
            "request_headers": headers_row(sent),
            "request_body": body_row(body, self.headers.get("Content-Encoding")),
            "status": None,
            "response_headers": None,
            "response_body": None,
            "error": None,
        }
        proxy.describe(row, sent, body)
        if not proxy.begin(row):
            data = json.dumps({"error": "verbatim-relay backend proxy: the test ended"}).encode()
            self._send(503, [("Content-Type", "application/json")], data)
            return
        conn = proxy.connect()
        try:
            # The low-level calls send each header of the app once, in its order, and add no
            # Accept-Encoding header.
            conn.putrequest(
                method, proxy.base_path + self.path, skip_host=True, skip_accept_encoding=True
            )
            conn.putheader("Host", proxy.host_header)
            for name, value in sent:
                conn.putheader(name, value)
            if body or method in ("POST", "PUT", "PATCH"):
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body or None)
            resp = conn.getresponse()
            if proxy.streaming:
                self._stream(resp, row)
                return
            status, out_headers, out = resp.status, resp.getheaders(), resp.read()
        except (OSError, http.client.HTTPException) as e:
            row.update(ts=time.time(), error=f"the backend did not answer: {e}")
            proxy.end(row)
            data = json.dumps({"error": f"verbatim-relay backend proxy: {e}"}).encode()
            self._send(502, [("Content-Type", "application/json")], data)
            return
        finally:
            conn.close()
        returned = [(k, v) for k, v in out_headers if k.lower() not in NOT_RETURNED]
        encoding = next((v for k, v in out_headers if k.lower() == "content-encoding"), None)
        row.update(
            ts=time.time(),
            status=status,
            response_headers=headers_row(returned),
            response_body=body_row(out, encoding),
        )
        proxy.complete(row, out, encoding)
        proxy.end(row)
        length = next((v for k, v in out_headers if k.lower() == "content-length"), None)
        self._send(status, returned, out, length if method == "HEAD" else None)

    def _stream(self, resp: http.client.HTTPResponse, row: dict[str, Any]) -> None:
        """Send each part of the response to the app when it comes, then write the row.

        This function catches each error itself, because the app already has the status.
        """
        proxy, out_headers = self.server, resp.getheaders()
        returned = [(k, v) for k, v in out_headers if k.lower() not in NOT_RETURNED]
        length = resp.getheader("Content-Length")
        bodyless = self.command == "HEAD" or resp.status in (204, 304)
        chunked = length is None and not bodyless
        app = True
        try:
            self.send_response_only(resp.status)
            for name, value in returned:
                self.send_header(name, value)
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            elif length is not None:
                self.send_header("Content-Length", length)
            self.end_headers()
            self.wfile.flush()
        except OSError:
            app = False
        parts: list[bytes] = []
        error = None
        while not bodyless:
            try:
                part = resp.read1(65536)
            except (OSError, http.client.HTTPException) as e:
                error = f"the stream stopped: {e}"
                break
            if not part:
                break
            parts.append(part)
            if app:
                # The record keeps all of the stream, also if the app went away.
                try:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part) if chunked else part)
                    self.wfile.flush()
                except OSError:
                    app = False
        left = resp.length if length is not None and not bodyless else None
        if error is None and left:
            # read1 gives b"" at an early end of a body with a Content-Length. It does not raise.
            error = f"the stream stopped: the API sent {int(length or 0) - left} of {length} bytes"
        if app and chunked and error is None:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                pass
        if error is not None or not app:
            self.close_connection = True
        out = b"".join(parts)
        encoding = resp.getheader("Content-Encoding")
        row.update(
            ts=time.time(),
            status=resp.status,
            response_headers=headers_row(returned),
            response_body=body_row(out, encoding),
            error=error,
        )
        proxy.complete(row, out, encoding)
        proxy.end(row)

    def _send(
        self, status: int, headers: list[tuple[str, str]], body: bytes, length: str | None = None
    ) -> None:
        self.send_response_only(status)
        for name, value in headers:
            self.send_header(name, value)
        # A HEAD response has no body, but it keeps the Content-Length of the backend.
        self.send_header("Content-Length", length if length is not None else str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


class Proxies:
    """The proxies of a test, with one record file."""

    def __init__(self, backends: list[Backend], record: Path, kind: type[Proxy] = Proxy) -> None:
        self.lock = threading.Condition()
        self.proxies = [kind(b, record, self.lock) for b in backends]

    def start(self) -> dict[str, str]:
        """Start each proxy. Return the variables that give the entry the proxy URLs."""
        for p in self.proxies:
            stdio.start_in_thread(p)
        return {p.backend.env: p.url for p in self.proxies}

    def stop(self) -> None:
        """Stop each proxy. Wait up to DRAIN seconds for the open calls, so that each call has
        its row before the trace and the seal. Then write a row with the error ENDED for each
        call that did not end."""
        for p in self.proxies:
            p.shutdown()
        deadline = time.monotonic() + DRAIN
        with self.lock:
            while any(p.open for p in self.proxies) and time.monotonic() < deadline:
                self.lock.wait(deadline - time.monotonic())
            for p in self.proxies:
                p.close()
        for p in self.proxies:
            p.server_close()

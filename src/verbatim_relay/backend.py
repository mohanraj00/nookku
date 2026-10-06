"""The backend proxies of SPEC.md section 7.6.

During a test, the bridge runs one recording proxy for each backend in the configuration, and gives
the entry the proxy URL in the backend's environment variable. The proxy forwards each request to
the real URL and sends the response back with no change. It writes one row for each call to
backend.jsonl, without the values of secret headers.
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
from urllib.parse import urlsplit

from . import stdio
from .tap import HOP_BY_HOP

FILE = "backend.jsonl"
VERSION = 1
TIMEOUT = 120
# A body larger than this goes into the record cut. The app always gets all of the bytes.
RECORD_LIMIT = 1024 * 1024
SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie"}
SECRET_PARTS = ("key", "token", "secret")
REMOVED = "<removed>"
NOT_FORWARDED = HOP_BY_HOP | {"host", "content-length"}
NOT_RETURNED = HOP_BY_HOP | {"content-length"}


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
    return low in SECRET_HEADERS or any(p in low for p in SECRET_PARTS)


def headers_row(items: list[tuple[str, str]]) -> list[list[str]]:
    """The headers as [name, value] pairs, in their order, with the secret values removed."""
    return [[k, REMOVED if secret(k) else v] for k, v in items]


def body_row(data: bytes, encoding: str | None = None) -> dict[str, Any]:
    """A body in the record: its size, its SHA-256 and its text (UTF-8) or base64.

    For a gzip or deflate body, `text` is the decoded body, so that the record can be read.
    """
    out: dict[str, Any] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    shown = data
    if encoding in ("gzip", "deflate") and data:
        try:
            shown = gzip.decompress(data) if encoding == "gzip" else zlib.decompress(data)
            out["decoded"] = encoding
        except (OSError, EOFError, zlib.error):
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

    def __init__(self, backend: Backend, record: Path, lock: threading.Lock) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.backend = backend
        self.record = record
        self.lock = lock
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

    def write(self, row: dict[str, Any]) -> None:
        with self.lock, self.record.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


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
            "query": query or None,
            "request_headers": headers_row(sent),
            "request_body": body_row(body, self.headers.get("Content-Encoding")),
            "status": None,
            "response_headers": None,
            "response_body": None,
            "error": None,
        }
        conn = proxy.connect()
        try:
            headers = dict(sent)
            headers["Host"] = proxy.host_header
            target = proxy.base_path + self.path
            conn.request(
                method,
                target,
                body=body if body or method in ("POST", "PUT", "PATCH") else None,
                headers=headers,
            )
            resp = conn.getresponse()
            status, out_headers, out = resp.status, resp.getheaders(), resp.read()
        except (OSError, http.client.HTTPException) as e:
            row.update(ts=time.time(), error=f"the backend did not answer: {e}")
            proxy.write(row)
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
        proxy.write(row)
        length = next((v for k, v in out_headers if k.lower() == "content-length"), None)
        self._send(status, returned, out, length if method == "HEAD" else None)

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

    def __init__(self, backends: list[Backend], record: Path) -> None:
        lock = threading.Lock()
        self.proxies = [Proxy(b, record, lock) for b in backends]

    def start(self) -> dict[str, str]:
        """Start each proxy. Return the variables that give the entry the proxy URLs."""
        for p in self.proxies:
            stdio.start_in_thread(p)
        return {p.backend.env: p.url for p in self.proxies}

    def stop(self) -> None:
        for p in self.proxies:
            p.shutdown()
            p.server_close()

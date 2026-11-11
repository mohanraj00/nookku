"""The backend proxies of SPEC.md section 7.6.

During a test, the bridge runs one recording proxy for each backend in the configuration, and gives
the entry the proxy URL in the backend's environment variable. The proxy forwards each request to
the real URL and sends each part of the response back with no change when it comes. It writes one
row for each call to backend.jsonl, without the values of secret headers and secret query
parameters. The row keeps only the first bytes of a large body.
"""

from __future__ import annotations

import base64
import codecs
import contextlib
import hashlib
import http.client
import json
import re
import socket
import threading
import time
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus, urlsplit

from . import stdio
from .config import DEFAULT_BODY_LIMIT, BodyLimit, Config
from .proxy_socket import LimitedServer, send_refusal
from .record import json_text
from .tap import HOP_BY_HOP

FILE = "backend.jsonl"
VERSION = 1
TIMEOUT = 120
# The default of the config key record_limit: a body larger than this goes into the record cut.
# The app always gets all of the bytes (SPEC.md section 7.6).
RECORD_LIMIT = Config.record_limit
# The rule for the names of secret headers and secret query parameters: a name in SECRET_HEADERS
# or SECRET_NAMES, or a name that contains a part in SECRET_PARTS. Case does not apply.
SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie"}
SECRET_NAMES = {"auth", "sig"}
SECRET_PARTS = ("key", "token", "secret", "password", "signature")
REMOVED = "<removed>"
# The app does not know that it speaks to a proxy, so the proxy headers go through.
NOT_FORWARDED = (HOP_BY_HOP - {"proxy-authorization"}) | {"host", "content-length"}
NOT_RETURNED = (HOP_BY_HOP - {"proxy-authenticate"}) | {"content-length"}
# The default of the config key body_limit: the most bytes of a request body that a proxy reads.
# The proxy holds all of a request body in memory before it forwards it, so it refuses a longer
# body and forwards none of it. This bound is a chosen value, not a measurement (SPEC.md section
# 7.6).
BODY_LIMIT = DEFAULT_BODY_LIMIT
# The proxies of one test hold at most BODIES_TIMES times body_limit bytes of request bodies at one
# time. Thus many parallel requests do not use more memory than this. The proxy refuses a request
# whose body does not fit, with status 503. This bound is a chosen value, not a measurement
# (SPEC.md section 7.6).
BODIES_TIMES = 4
# The most trailer lines after the last chunk of a request body. This is the count of header lines
# that http.server accepts. The proxy drops the trailer lines (SPEC.md section 7.6).
TRAILERS = 100
# The most bytes of chunk extensions in one request, including their semicolons.
CHUNK_EXTENSIONS = 65536
# The most bytes of one line of a chunked body, with its line end.
LINE = 65537
DIGITS = re.compile(r"[0-9]+")
HEX = re.compile(rb"[0-9A-Fa-f]+")
REFUSED = "the proxy refused the request"
# After a refusal, the proxy reads and drops the rest of the body while the app still sends it.
# Thus the close does not reset the connection before the app reads the refusal. The drain ends at
# the end of the Content-Length, at the end of the connection, after DROP_TIME seconds with no
# byte, or after the larger of DROP_BYTES and DROP_TIMES times body_limit. These bounds are chosen
# values, not measurements (SPEC.md section 7.6).
DROP_BYTES = 256 * 1024 * 1024
DROP_TIMES = 4
DROP_TIME = 1.0
# At the end of the test, the time to wait for the calls that did not end.
DRAIN = 10.0
ENDED = "the test ended before the backend answered"
STREAM_ENDED = "the test ended before the stream ended"


@dataclass
class Backend:
    name: str
    env: str
    url: str


def from_answer(parts: list[dict[str, Any]]) -> list[Backend]:
    """The backends of a discovery answer (SPEC.md section 7.11). discovery.parse checked them."""
    return [Backend(p["name"], p["env"], p["url"].rstrip("/")) for p in parts]


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


def decode(data: bytes, encoding: str | None, limit: int, partial: bool = False) -> bytes | None:
    """The decoded bytes of a gzip or deflate body, or None. The decode stops after `limit` + 1
    bytes, so a small body that decodes to many bytes does not use the memory of the test. A
    longer result than `limit` thus shows that the decoded body is longer. With `partial`, a body
    that stops early gives the bytes that it decodes. Else it gives None, as a broken body does.
    """
    if encoding not in ("gzip", "deflate") or not data:
        return None
    out: list[bytes] = []
    room, rest = limit + 1, data
    try:
        # A gzip body can have more than one member, and each member starts a new decoder.
        while rest and room > 0:
            decoder = zlib.decompressobj(31 if encoding == "gzip" else 15)
            part = decoder.decompress(rest, room)
            out.append(part)
            room -= len(part)
            if not decoder.eof:
                if room > 0 and not partial:
                    return None
                break
            rest = decoder.unused_data if encoding == "gzip" else b""
    except zlib.error:
        return None
    return b"".join(out)


def body_row(
    data: bytes, encoding: str | None = None, limit: int | None = None, cut: bool = False
) -> dict[str, Any]:
    """A body in the record: its size, its SHA-256 and its text (UTF-8) or base64.

    For a gzip or deflate body, `text` is the decoded body, so that the record can be read. The
    record keeps the first `limit` bytes, or RECORD_LIMIT bytes if `limit` is None. `cut` is True
    if `data` is only the start of the body.
    """
    limit = RECORD_LIMIT if limit is None else limit
    out: dict[str, Any] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    shown = decode(data, encoding, limit)
    if shown is not None:
        out["decoded"] = encoding
    else:
        shown = data
    out["cut"] = cut or len(shown) > limit
    shown = shown[:limit]
    if out["cut"]:
        # The cut can split a UTF-8 character. The text then ends before that character.
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            decoder.decode(shown)
            shown = shown[: len(shown) - len(decoder.getstate()[0])]
        except UnicodeDecodeError:
            pass  # The body is not UTF-8, so the row keeps all of its start as base64.
    try:
        out["text"] = shown.decode("utf-8")
    except UnicodeDecodeError:
        out["base64"] = base64.b64encode(shown).decode()
    return out


class StreamBody:
    """A stream size, its SHA-256 and its first `keep` bytes."""

    def __init__(self, keep: int, encoding: str | None) -> None:
        self.keep = keep
        self.encoding = encoding
        self.size = 0
        self.digest = hashlib.sha256()
        self._prefix = bytearray()

    def add(self, part: bytes) -> None:
        self.size += len(part)
        self.digest.update(part)
        if self.kept < self.keep:
            part = part[: self.keep - self.kept]
            self._prefix.extend(part)

    @property
    def kept(self) -> int:
        return len(self._prefix)

    @property
    def data(self) -> bytes:
        return bytes(self._prefix)

    @property
    def cut(self) -> bool:
        return self.size > self.kept

    def row(self, *, incomplete: bool = False) -> dict[str, Any]:
        data = self.data
        if not self.cut and not incomplete:
            return body_row(data, self.encoding, self.keep)
        # The proxy did not keep all of the stream. The row shows its first bytes as they came.
        body = body_row(data, None, self.keep, cut=True)
        body.update(size=self.size, sha256=self.digest.hexdigest(), cut=True)
        return body


class Refused(Exception):
    """A request or upload that the proxy rejects with an HTTP status and reason."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


def too_long(limit: int) -> Refused:
    return Refused(413, f"the body is longer than {limit} bytes")


def stopped() -> Refused:
    return Refused(400, "the body stopped before its end")


def busy(budget: Budget) -> Refused:
    return Refused(
        503, f"the proxies hold too many bytes of request bodies (at most {budget.size})"
    )


class Budget:
    """The bytes of the request bodies that the proxies of one test hold at one time. A proxy takes
    the bytes of a body before it reads them, and gives them back after it forwards the body."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.used = 0
        self._lock = threading.Lock()

    def take(self, count: int) -> bool:
        """Take `count` bytes. Return False, and take none, if they do not fit."""
        with self._lock:
            if self.used + count > self.size:
                return False
            self.used += count
            return True

    def give(self, count: int) -> None:
        with self._lock:
            self.used -= count


def read_chunked(rfile: Any, limit: int, budget: Budget | None = None) -> bytes:
    """A request body with Transfer-Encoding: chunked. Raise Refused if the body has more than
    `limit` bytes, if a chunk is not valid, if the body stops before its last chunk, if it has more
    than TRAILERS trailer lines, or if a chunk does not fit in `budget`. The body takes its bytes
    from `budget`. If this function raises, it gives them back."""
    out = bytearray()
    part = b""
    taken = 0
    extensions = 0
    try:
        while True:
            line, size = chunk_head(rfile)
            extensions = add_extensions(line, extensions)
            if size == 0:
                for _ in trailer_lines(rfile):
                    pass  # The buffered path drops the trailers.
                return bytes(out)
            if len(out) + size > limit:
                raise too_long(limit)
            if budget is not None:
                if not budget.take(size):
                    raise busy(budget)
                taken += size
            part = rfile.read(size)
            if len(part) < size:
                raise stopped()
            out += part
            chunk_end(rfile)
    except BaseException:
        # The traceback keeps this frame. Free the bytes that it holds before the budget gets
        # them back.
        out.clear()
        part = b""
        if budget is not None:
            budget.give(taken)
        raise


def chunk_head(rfile: Any, *, strict: bool = False) -> tuple[bytes, int]:
    line: bytes = rfile.readline(LINE)
    if not line.endswith(b"\n"):
        raise stopped() if len(line) < LINE else Refused(400, "a chunk size is not valid")
    size = line.split(b";", 1)[0].strip()
    if not HEX.fullmatch(size) or (strict and not line.endswith(b"\r\n")):
        raise Refused(400, "a chunk size is not valid")
    return line, int(size, 16)


def add_extensions(line: bytes, total: int) -> int:
    """Add the chunk extension bytes of a size line to `total`. Raise Refused above the cap."""
    _, sep, extension = line.rstrip(b"\n").removesuffix(b"\r").partition(b";")
    total += len(sep) + len(extension)
    if total > CHUNK_EXTENSIONS:
        raise Refused(400, f"the body has more than {CHUNK_EXTENSIONS} bytes of chunk extensions")
    return total


def chunk_end(rfile: Any, *, strict: bool = False) -> bytes:
    line: bytes = rfile.readline(LINE)
    if line == b"\r\n" or (not strict and line == b"\n"):
        return line
    raise Refused(400, "a chunk does not end with a line end")


def trailer_lines(rfile: Any, *, strict: bool = False) -> Iterator[bytes]:
    for i in range(TRAILERS + 1):
        line = rfile.readline(LINE)
        if line == b"\r\n" or (not strict and line in (b"\n", b"")):
            yield line
            return
        if not line.endswith(b"\n"):
            raise stopped() if len(line) < LINE else Refused(400, "a trailer line is too long")
        if i == TRAILERS:
            raise Refused(400, f"the body has more than {TRAILERS} trailer lines")
        if strict and (
            not line.endswith(b"\r\n")
            or line[:1] in (b" ", b"\t")
            or line.partition(b":")[0].strip().lower() in (b"content-length", b"transfer-encoding")
        ):
            raise Refused(400, "a trailer line is not valid")
        yield line


def chunked(headers: Any) -> bool:
    return "chunked" in headers.get("Transfer-Encoding", "").lower()


def declared(headers: Any, limit: int | None) -> int:
    """Read the one nonnegative Content-Length, or 0 if absent. Check the limit when given."""
    lengths = {v.strip() for v in headers.get_all("Content-Length") or []}
    if not lengths:
        return 0
    length = lengths.pop()
    if lengths or not DIGITS.fullmatch(length):
        raise Refused(400, "the Content-Length is not one count of 0 or more")
    try:
        size = int(length.lstrip("0") or "0")
    except ValueError:
        raise Refused(400, "the Content-Length is too long to read") from None
    if limit is not None and size > limit:
        raise too_long(limit)
    return size


def read_body(headers: Any, rfile: Any, limit: int, budget: Budget | None = None) -> bytes:
    """The request body. Raise Refused if it has more than `limit` bytes, if its framing is not
    valid, if it stops before its end, or if it does not fit in `budget`. The proxy reads no byte
    of a body that is too long or that does not fit. The body takes its bytes from `budget`, and
    the caller gives them back. If this function raises, it gives them back."""
    if chunked(headers):
        return read_chunked(rfile, limit, budget)
    size = declared(headers, limit)
    if budget is not None and not budget.take(size):
        raise busy(budget)
    data = b""
    try:
        data = rfile.read(size)
        if len(data) < size:
            raise stopped()
        return bytes(data)
    except BaseException:
        # The traceback keeps this frame. Free the bytes that it holds before the budget gets
        # them back.
        data = b""
        if budget is not None:
            budget.give(size)
        raise


def stream_length(headers: Any) -> int | None:
    """Read the framing of a streamed request. None means chunked."""
    encodings = headers.get_all("Transfer-Encoding") or []
    if not encodings:
        return declared(headers, None)
    if (
        len(encodings) != 1
        or encodings[0].strip().lower() != "chunked"
        or headers.get_all("Content-Length")
    ):
        raise Refused(400, "the streamed request framing is not valid")
    return None


def payload_parts(rfile: Any, size: int) -> Iterator[tuple[bytes, bool]]:
    """Read at most one block at a time and mark it as payload."""
    while size:
        part = rfile.read1(min(size, 65536))
        if not part:
            raise stopped()
        yield part, True
        size -= len(part)


def upload_parts(rfile: Any, length: int | None) -> Iterator[tuple[bytes, bool]]:
    """Yield each wire part with a flag that says if it counts as body bytes."""
    try:
        if length is not None:
            yield from payload_parts(rfile, length)
            return
        extensions = 0
        while True:
            line, size = chunk_head(rfile, strict=True)
            extensions = add_extensions(line, extensions)
            yield line, False
            if not size:
                break
            yield from payload_parts(rfile, size)
            yield chunk_end(rfile, strict=True), False
        for line in trailer_lines(rfile, strict=True):
            yield line, False
    except OSError:
        raise stopped() from None


class Proxy(LimitedServer, HTTPServer):
    """One recording proxy for one backend."""

    target_field = "backend"
    # The most bytes of a body that the record keeps, or None for RECORD_LIMIT. The proxy keeps
    # no more bytes of a response. The row still has the size and the SHA-256 of all of them.
    keep: int | None = None
    # The most bytes of a request body that the proxy reads and forwards.
    body_limit = BODY_LIMIT
    stream_requests = False

    def __init__(self, backend: Backend, record: Path, lock: threading.Condition) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.backend = backend
        self.record = record
        self.lock = lock
        # The rows of the calls that did not end, by their id.
        self.open: dict[int, dict[str, Any]] = {}
        # The bytes of each open stream, by the id of its row. The app gets the status before the
        # body ends, so at the end of the test the row of an open stream keeps the status, the
        # headers and the bytes that came, with the error STREAM_ENDED.
        self.streams: dict[int, StreamBody] = {}
        self.uploads: dict[int, StreamBody] = {}
        self.closed = False
        # The bytes of the request bodies that the proxy holds. Proxies gives one budget to all of
        # the proxies of a test.
        self.budget = Budget(BODIES_TIMES * BODY_LIMIT)
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

    @property
    def limit(self) -> int:
        return RECORD_LIMIT if self.keep is None else self.keep

    def connect(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=TIMEOUT)
        return http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT)

    def refuse_connection(self, request: socket.socket, reason: str) -> None:
        row = {
            "v": VERSION,
            "type": "connection_refused",
            self.target_field: self.backend.name,
            "ts": time.time(),
            "status": 503,
            "error": reason,
        }
        data = json.dumps({"error": reason}).encode()
        send_refusal(
            request,
            b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n"
            b"Content-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (len(data), data),
        )
        with self.lock:
            if self.closed:
                return
        # The listener writes this row. Do not hold up other proxies or fail the accept loop.
        # stop() waits for the listener before it closes the record.
        with contextlib.suppress(OSError):
            self._write(row)

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        """Add to the row of a new call. A subclass can change it."""

    def complete(
        self, row: dict[str, Any], body: bytes, encoding: str | None, cut: bool = False
    ) -> None:
        """Add to the row of a call that has its response. A subclass can change it. `body` is
        the start of the response that the proxy kept, and `cut` is True if it is not all of it."""

    def begin(self, row: dict[str, Any], upload: StreamBody | None = None) -> bool:
        """Add the call to the open calls. Return False if the proxy is closed."""
        with self.lock:
            if self.closed:
                return False
            self.open[id(row)] = row
            if upload is not None:
                self.uploads[id(row)] = upload
            return True

    def finish_upload(self, row: dict[str, Any]) -> None:
        with self.lock:
            upload = self.uploads.pop(id(row), None)
            if upload is not None:
                row["request_body"] = upload.row()

    def end(
        self,
        row: dict[str, Any],
        fields: dict[str, Any],
        body: bytes | None = None,
        encoding: str | None = None,
        cut: bool = False,
    ) -> None:
        """Add `fields` to the row of the call, complete it with `body` if given, and write it.
        If the proxy wrote the row at the end of the test, do none of this. Hold the lock, so
        that the end of the test and the call do not change the row at the same time."""
        with self.lock:
            self.streams.pop(id(row), None)
            upload = self.uploads.pop(id(row), None)
            if self.open.pop(id(row), None) is not None:
                if upload is not None:
                    row["request_body"] = upload.row(incomplete=True)
                row.update(fields)
                if body is not None:
                    self.complete(row, body, encoding, cut)
                self._write(row)
            self.lock.notify_all()

    def close(self) -> None:
        """Write a row for each open call, then write no more rows. Hold the lock."""
        for key, row in self.open.items():
            stream = self.streams.get(key)
            upload = self.uploads.get(key)
            if upload is not None:
                row["request_body"] = upload.row(incomplete=True)
            if stream is not None:
                row.update(ts=time.time(), response_body=stream.row(), error=STREAM_ENDED)
                # The stream did not end, so the bytes that came are the start of the response.
                self.complete(row, stream.data, stream.encoding, cut=True)
            else:
                row.update(ts=time.time(), error=ENDED)
            self._write(row)
        self.open.clear()
        self.streams.clear()
        self.uploads.clear()
        self.closed = True

    def _write(self, row: dict[str, Any]) -> None:
        with self.record.open("a", encoding="utf-8") as fh:
            fh.write(json_text(row) + "\n")


class Handler(BaseHTTPRequestHandler):
    server: Proxy
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    # A refusal that the proxy found before the body, for a request with Expect: 100-continue.
    early: Refused | None = None
    # The bytes of the request body that this handler took from the budget of the proxy.
    held = 0

    def handle_expect_100(self) -> bool:
        """Send 100 Continue, except for a request that the proxy refuses from its headers. Such a
        request gets the refusal at once, with no 100 Continue, so that the app sends no body."""
        try:
            if self.server.stream_requests:
                stream_length(self.headers)
            elif not chunked(self.headers):
                size = declared(self.headers, self.server.body_limit)
                if not self.server.budget.take(size):
                    raise busy(self.server.budget)
                self.held = size
        except Refused as e:
            self.early = e
            return True
        return super().handle_expect_100()

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        finally:
            # A reservation can precede a failed write of 100 Continue or an unknown method.
            self._give_back()

    def do_GET(self) -> None:
        self._call()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_GET

    def _give_back(self) -> None:
        """Give the bytes of the request body back to the budget of the proxy."""
        if self.held:
            self.server.budget.give(self.held)
            self.held = 0

    def _call(self) -> None:
        started = time.time()
        proxy, method = self.server, self.command
        refused, self.early = self.early, None
        upload = None
        length = None
        body = b""
        try:
            if refused is not None:
                raise refused
            if proxy.stream_requests:
                length = stream_length(self.headers)
                upload = StreamBody(proxy.limit, self.headers.get("Content-Encoding"))
            else:
                budget = None if self.held else proxy.budget
                body = read_body(self.headers, self.rfile, proxy.body_limit, budget)
                self.held = len(body)
        except Refused as e:
            # The proxy did not read all of the body, so the connection cannot take one more
            # request. The refusal keeps no traceback, so no frame of the read stays alive
            # during the drain.
            body, refused = b"", e.with_traceback(None)
            self.close_connection = True
        path, _, query = self.path.partition("?")
        omit = (
            NOT_FORWARDED - {"trailer"} if upload is not None and length is None else NOT_FORWARDED
        )
        sent = [(k, v) for k, v in self.headers.items() if k.lower() not in omit]
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
            "request_body": None
            if refused is not None or upload is not None
            else body_row(body, self.headers.get("Content-Encoding"), proxy.limit),
            "status": None,
            "response_headers": None,
            "response_body": None,
            "error": None,
        }
        proxy.describe(row, sent, body)
        if not proxy.begin(row, upload):
            data = json.dumps({"error": "nookku backend proxy: the test ended"}).encode()
            self._send(503, [("Content-Type", "application/json")], data)
            return
        if refused is not None:
            # A refused request never goes to the backend. The row records the refusal.
            proxy.end(row, {"ts": time.time(), "error": f"{REFUSED}: {refused}"})
            self._refuse(refused)
            return
        conn = proxy.connect()
        try:
            try:
                # The low-level calls send each header of the app once, in its order, and add no
                # Accept-Encoding header.
                conn.putrequest(
                    method, proxy.base_path + self.path, skip_host=True, skip_accept_encoding=True
                )
                conn.putheader("Host", proxy.host_header)
                for name, value in sent:
                    conn.putheader(name, value)
                if upload is not None:
                    if length is None:
                        conn.putheader(
                            "Transfer-Encoding", self.headers["Transfer-Encoding"].strip()
                        )
                    elif "Content-Length" in self.headers:
                        conn.putheader("Content-Length", self.headers["Content-Length"].strip())
                    elif method in ("POST", "PUT", "PATCH"):
                        conn.putheader("Content-Length", "0")
                    conn.endheaders()
                    self._upload(conn, upload, length)
                    proxy.finish_upload(row)
                else:
                    if body or method in ("POST", "PUT", "PATCH"):
                        conn.putheader("Content-Length", str(len(body)))
                    conn.endheaders(body or None)
                # The body went to the backend, so the proxy holds it no more.
                body = b""
                self._give_back()
                resp = conn.getresponse()
            except Refused as e:
                conn.close()
                self.close_connection = True
                proxy.end(row, {"ts": time.time(), "error": f"the request stream stopped: {e}"})
                self._refuse(e)
                return
            except (OSError, http.client.HTTPException) as e:
                if upload is not None:
                    self.close_connection = True
                proxy.end(row, {"ts": time.time(), "error": f"the backend did not answer: {e}"})
                data = json.dumps({"error": f"nookku backend proxy: {e}"}).encode()
                self._send(502, [("Content-Type", "application/json")], data)
                return
            self._stream(resp, row)
        finally:
            conn.close()

    def _upload(
        self, conn: http.client.HTTPConnection, upload: StreamBody, length: int | None
    ) -> None:
        proxy = self.server
        for part, payload in upload_parts(self.rfile, length):
            with proxy.lock:
                if proxy.closed:
                    raise Refused(503, "the test ended")
                if payload:
                    upload.add(part)
            conn.send(part)

    def _stream(self, resp: http.client.HTTPResponse, row: dict[str, Any]) -> None:
        """Send each part of the response to the app when it comes, then write the row.

        This function catches each error itself, because the app already has the status.
        """
        proxy, out_headers = self.server, resp.getheaders()
        returned = [(k, v) for k, v in out_headers if k.lower() not in NOT_RETURNED]
        bodyless = self.command == "HEAD" or resp.status in (204, 304)
        # A response with no body keeps the Content-Length of the backend. Else the framing to the
        # app comes from http.client, which reads the body: a chunked body, or a Content-Length
        # that is not one valid count, goes to the app chunked. Thus the app never gets a length
        # that does not agree with the bytes that follow it.
        if bodyless:
            length = resp.getheader("Content-Length")
        else:
            length = str(resp.length) if resp.length is not None and not resp.chunked else None
        # An HTTP/1.0 client does not read chunks. It gets the body with no framing, and the end of
        # the connection ends the body.
        unframed = length is None and not bodyless and self.request_version == "HTTP/1.0"
        chunked = length is None and not bodyless and not unframed
        if unframed:
            self.close_connection = True
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
        encoding = resp.getheader("Content-Encoding")
        stream = StreamBody(proxy.limit, encoding)
        with proxy.lock:
            row.update(status=resp.status, response_headers=headers_row(returned))
            proxy.streams[id(row)] = stream
        error = None
        while not bodyless:
            try:
                part = resp.read1(65536)
            except (OSError, http.client.HTTPException) as e:
                error = f"the stream stopped: {e}"
                break
            if not part:
                break
            with proxy.lock:
                stream.add(part)
            if app:
                # The row counts all of the stream, also if the app went away.
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
        fields = {
            "ts": time.time(),
            "status": resp.status,
            "response_headers": headers_row(returned),
            "response_body": stream.row(),
            "error": error,
        }
        proxy.end(row, fields, stream.data, encoding, stream.cut)

    def _refuse(self, refused: Refused) -> None:
        """Send the refusal to the app, then read and drop the rest of the body (see DROP_BYTES).
        The proxy keeps no dropped byte."""
        data = json.dumps({"error": f"nookku backend proxy: {refused}"}).encode()
        headers = [("Content-Type", "application/json"), ("Connection", "close")]
        limit = self.server.body_limit
        left = max(DROP_BYTES, DROP_TIMES * limit)
        if (
            refused.status in (413, 503)
            and not self.server.stream_requests
            and not chunked(self.headers)
        ):
            # The proxy read no byte of the body, so the Content-Length gives the rest.
            left = min(left, int(self.headers["Content-Length"].strip()))
        try:
            self._send(refused.status, headers, data)
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
            # The timeout applies to each read: the drain ends after DROP_TIME seconds with no
            # byte.
            self.connection.settimeout(DROP_TIME)
            while left > 0:
                part = self.rfile.read1(min(left, 65536))
                if not part:
                    break
                left -= len(part)
        except OSError:
            pass  # The app went away, or it sent no byte for DROP_TIME. The row has the refusal.

    def _send(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.send_response_only(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


class Proxies:
    """The proxies of a test, with one record file."""

    def __init__(
        self,
        backends: list[Backend],
        record: Path,
        kind: type[Proxy] = Proxy,
        keep: int | None = None,
        body_limit: BodyLimit = BODY_LIMIT,
        budget: Budget | None = None,
    ) -> None:
        """`keep` is the most bytes of a body that the record keeps, or None for the default.
        `body_limit` sets the buffered limit, or "stream" for streamed backend uploads.
        The buffered proxies share `budget`. If it is None, make a budget for these proxies."""
        self.lock = threading.Condition()
        buffered_limit = BODY_LIMIT if body_limit == "stream" else body_limit
        self.budget = Budget(BODIES_TIMES * buffered_limit) if budget is None else budget
        self.proxies = [kind(b, record, self.lock) for b in backends]
        for p in self.proxies:
            if keep is not None:
                p.keep = keep
            p.body_limit = buffered_limit
            p.stream_requests = body_limit == "stream" and kind is Proxy
            p.budget = self.budget

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

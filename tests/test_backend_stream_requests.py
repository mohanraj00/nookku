"""A toy stock service reads a streamed upload without holding the whole file."""

import hashlib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from nookku import backend, bridge, stdio

CASE = json.loads(
    (Path(__file__).resolve().parents[1] / "conformance/proxy/stream-upload.json").read_text()
)
PREFIX = CASE["prefix"].encode()


class StockUpload(HTTPServer):
    def __init__(self, wire_size: int, first_size: int) -> None:
        super().__init__(("127.0.0.1", 0), ReceiveUpload)
        self.wire_size = wire_size
        self.first_size = first_size
        self.first = threading.Event()
        self.complete = threading.Event()
        self.digest = hashlib.sha256()
        self.size = 0
        self.framing: tuple[str | None, str | None, str | None] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def server_bind(self) -> None:
        stdio.bind(self)

    def __enter__(self):
        stdio.start_in_thread(self)
        return self

    def __exit__(self, *exc):
        self.shutdown()
        self.server_close()


class ReceiveUpload(BaseHTTPRequestHandler):
    server: StockUpload

    def do_POST(self) -> None:
        stock = self.server
        stock.framing = (
            self.headers.get("Content-Length"),
            self.headers.get("Transfer-Encoding"),
            self.headers.get("Trailer"),
        )
        first = self.rfile.read(stock.first_size)
        stock.digest.update(first)
        stock.size = len(first)
        stock.first.set()
        while stock.size < stock.wire_size:
            part = self.rfile.read1(min(65536, stock.wire_size - stock.size))
            if not part:
                break
            stock.digest.update(part)
            stock.size += len(part)
        stock.complete.set()
        if stock.size == stock.wire_size:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    do_PUT = do_PATCH = do_GET = do_POST


def proxy_for(stock: StockUpload, root: Path) -> backend.Proxies:
    config = root / bridge.CONFIG_FILE
    config.parent.mkdir()
    config.write_text(json.dumps({"entry": ["toy-shop"], "body_limit": CASE["body_limit"]}))
    loaded = bridge.load_config(root)
    return backend.Proxies(
        [backend.Backend("stock", "STOCK_URL", stock.url)],
        root / backend.FILE,
        keep=CASE["record_limit"],
        body_limit=loaded.body_limit,
    )


def upload_head(framing: bytes, method: str = "POST") -> bytes:
    return (
        f"{method} /stock HTTP/1.1\r\nHost: shop\r\nConnection: close\r\n".encode()
        + framing
        + b"\r\n"
    )


@pytest.mark.parametrize("chunked", [False, True])
def test_an_upload_larger_than_the_buffer_limit_streams_with_its_framing(
    tmp_path: Path, chunked: bool
) -> None:
    block = b"x" * 65536
    repeats = backend.BODY_LIMIT // len(block)
    size = len(PREFIX) + repeats * len(block)
    if chunked:
        head = b"Transfer-Encoding: chunked\r\nTrailer: X-Stock\r\n"
        chunk_head = f"{size:X};kind=toy\r\n".encode()
        tail = b"\r\n0\r\nX-Stock: teapot\r\n\r\n"
        expected_framing = (None, "chunked", "X-Stock")
    else:
        head = f"Content-Length: {size}\r\n".encode()
        chunk_head = tail = b""
        expected_framing = (str(size), None, None)

    first = chunk_head + PREFIX
    with StockUpload(size + len(chunk_head) + len(tail), len(first)) as stock:
        proxies = proxy_for(stock, tmp_path)
        proxies.start()
        try:
            with socket.create_connection(proxies.proxies[0].server_address, timeout=5) as app:
                app.sendall(upload_head(head) + first)
                assert stock.first.wait(3), "the first part did not reach the stock service"
                digest = hashlib.sha256(PREFIX)
                wire_digest = hashlib.sha256(first)
                for _ in range(repeats):
                    app.sendall(block)
                    digest.update(block)
                    wire_digest.update(block)
                app.sendall(tail)
                wire_digest.update(tail)
                with app.makefile("rb") as reply:
                    assert reply.read().startswith(b"HTTP/1.1 200 ")
        finally:
            proxies.stop()
    assert stock.framing == expected_framing
    assert stock.digest.digest() == wire_digest.digest()
    row = json.loads((tmp_path / backend.FILE).read_text())
    assert row["error"] is None
    assert row["request_body"] == {
        "size": size,
        "sha256": digest.hexdigest(),
        "cut": True,
        "text": (PREFIX + block[:2]).decode(),
    }


@pytest.mark.parametrize("chunked", [False, True])
def test_an_early_end_records_the_body_prefix(tmp_path: Path, chunked: bool) -> None:
    length = CASE["incomplete_length"]
    if chunked:
        framing = b"Transfer-Encoding: chunked\r\n"
        chunk_head = b"%x\r\n" % length
    else:
        framing = b"Content-Length: %d\r\n" % length
        chunk_head = b""
    first = chunk_head + PREFIX
    with StockUpload(length + len(chunk_head), len(first)) as stock:
        proxies = proxy_for(stock, tmp_path)
        proxies.start()
        try:
            with socket.create_connection(proxies.proxies[0].server_address, timeout=5) as app:
                app.sendall(upload_head(framing) + first)
                assert stock.first.wait(3)
                app.shutdown(socket.SHUT_WR)
                with app.makefile("rb") as reply:
                    assert reply.read().startswith(
                        f"HTTP/1.1 {CASE['incomplete_status']} ".encode()
                    )
                assert stock.complete.wait(3)
        finally:
            proxies.stop()
    assert stock.size == len(first)
    row = json.loads((tmp_path / backend.FILE).read_text())
    assert row["error"] == CASE["incomplete_error"]
    assert row["request_body"] == {
        "size": len(PREFIX),
        "sha256": CASE["incomplete_sha256"],
        "cut": True,
        "text": PREFIX.decode(),
    }


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "GET"])
def test_an_unframed_empty_request_keeps_the_buffered_framing(tmp_path: Path, method: str) -> None:
    with StockUpload(0, 0) as stock:
        proxies = proxy_for(stock, tmp_path)
        proxies.start()
        try:
            with socket.create_connection(proxies.proxies[0].server_address, timeout=5) as app:
                app.sendall(upload_head(b"", method))
                with app.makefile("rb") as reply:
                    assert reply.read().startswith(b"HTTP/1.1 200 ")
        finally:
            proxies.stop()
    assert stock.framing == (None if method == "GET" else "0", None, None)

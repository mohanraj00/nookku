import base64
import gzip
import hashlib
import http.client
import json
import os
import socket
import socketserver
import threading
import time
from pathlib import Path

import pytest
from toy_model_server import ModelServer
from toy_stock_server import StockServer

from nookku import backend


def proxy_for(stock: StockServer, tmp_path: Path, url: str | None = None) -> backend.Proxies:
    b = backend.Backend("stock", "STOCK_URL", url or stock.url)
    return backend.Proxies([b], tmp_path / backend.FILE)


def request(url: str, method: str, path: str, body: bytes | None, headers: dict) -> tuple:
    host, port = url.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    out = (resp.status, resp.getheaders(), resp.read())
    conn.close()
    return out


def rows(tmp_path: Path) -> list[dict]:
    return [json.loads(x) for x in (tmp_path / backend.FILE).read_text().splitlines()]


def test_the_proxy_forwards_each_byte(tmp_path: Path) -> None:
    sent = os.urandom(4096) + "€ teapot\u2028\r\n".encode()
    with StockServer() as stock:
        stock.answer_body = os.urandom(2048) + b"\x00\xff"
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            headers = {"Content-Type": "application/octet-stream", "X-Shop-Order": "5120  x"}
            status, got_headers, got = request(
                env["STOCK_URL"], "POST", "/stock?sku=a%20b", sent, headers
            )
        finally:
            proxies.stop()
    assert status == 200 and got == stock.answer_body
    assert ("X-Stock-Trace", "a b  c") in got_headers
    seen = stock.seen[0]
    assert (seen["method"], seen["path"], seen["body"]) == ("POST", "/stock?sku=a%20b", sent)
    assert ("X-Shop-Order", "5120  x") in seen["headers"]
    row = rows(tmp_path)[0]
    assert row["request_body"]["size"] == len(sent) and "base64" in row["request_body"]
    assert row["response_body"]["size"] == len(stock.answer_body)
    assert (row["backend"], row["method"], row["path"], row["query"]) == (
        "stock",
        "POST",
        "/stock",
        "sku=a%20b",
    )


def test_secret_headers_reach_the_backend_but_not_the_record(tmp_path: Path) -> None:
    with StockServer() as stock:
        stock.answer_headers.append(("Set-Cookie", "session=s3cr3t"))
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            headers = {
                "Authorization": "Bearer t0k3n",
                "Proxy-Authorization": "Basic cHIweHk=",
                "X-Api-Key": "k3y",
                "X-Order": "5120",
            }
            request(env["STOCK_URL"], "GET", "/stock", None, headers)
        finally:
            proxies.stop()
    assert ("Authorization", "Bearer t0k3n") in stock.seen[0]["headers"]
    assert ("Proxy-Authorization", "Basic cHIweHk=") in stock.seen[0]["headers"]
    text = (tmp_path / backend.FILE).read_text()
    assert all(s not in text for s in ("t0k3n", "cHIweHk", "k3y", "s3cr3t"))
    row = rows(tmp_path)[0]
    assert ["X-Order", "5120"] in row["request_headers"]
    assert ["Authorization", backend.REMOVED] in row["request_headers"]


def test_secret_query_values_reach_the_backend_but_not_the_record(tmp_path: Path) -> None:
    with StockServer() as stock:
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            request(env["STOCK_URL"], "GET", "/stock?sku=mug&api_key=toy-123", None, {})
        finally:
            proxies.stop()
    assert stock.seen[0]["path"] == "/stock?sku=mug&api_key=toy-123"
    assert "toy-123" not in (tmp_path / backend.FILE).read_text()
    assert rows(tmp_path)[0]["query"] == "sku=mug&api_key="


def test_repeated_and_encoded_secret_query_names(tmp_path: Path) -> None:
    query = "token=a1&sku=mug&token=b2&api%5Fkey=c3&Sig=d4&q=&flag&auth=e5&keep=f6"
    with StockServer() as stock:
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            request(env["STOCK_URL"], "GET", "/stock?" + query, None, {})
        finally:
            proxies.stop()
    assert stock.seen[0]["path"] == "/stock?" + query
    want = "token=&sku=mug&token=&api%5Fkey=&Sig=&q=&flag&auth=&keep=f6"
    assert rows(tmp_path)[0]["query"] == want


def test_a_large_body_is_cut_in_the_record_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backend, "RECORD_LIMIT", 10)
    with StockServer() as stock:
        stock.answer_body = b"0123456789abcdef"
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            _, _, got = request(env["STOCK_URL"], "GET", "/stock", None, {})
        finally:
            proxies.stop()
    assert got == b"0123456789abcdef"
    body = rows(tmp_path)[0]["response_body"]
    assert body == {**body, "size": 16, "cut": True, "text": "0123456789"}


def test_a_gzip_response_is_decoded_in_the_record_only(tmp_path: Path) -> None:
    with StockServer() as stock:
        stock.answer_body = gzip.compress(b'{"left": 3}')
        stock.answer_headers = [("Content-Encoding", "gzip")]
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            _, _, got = request(
                env["STOCK_URL"], "GET", "/stock", None, {"Accept-Encoding": "gzip"}
            )
        finally:
            proxies.stop()
    assert got == stock.answer_body
    assert rows(tmp_path)[0]["response_body"]["text"] == '{"left": 3}'


def test_a_backend_that_does_not_answer_gives_502_and_a_row(tmp_path: Path) -> None:
    b = backend.Backend("payments", "PAY_URL", "http://127.0.0.1:9")
    proxies = backend.Proxies([b], tmp_path / backend.FILE)
    env = proxies.start()
    try:
        status, _, _ = request(env["PAY_URL"], "POST", "/payments", b"{}", {})
    finally:
        proxies.stop()
    assert status == 502
    row = rows(tmp_path)[0]
    assert row["status"] is None and row["error"].startswith("the backend did not answer")


def test_a_chunked_request_and_a_base_path(tmp_path: Path) -> None:
    with StockServer() as stock:
        proxies = proxy_for(stock, tmp_path, stock.url + "/api/")
        env = proxies.start()
        try:
            host, port = env["STOCK_URL"].removeprefix("http://").split(":")
            conn = http.client.HTTPConnection(host, int(port), timeout=10)
            conn.request("POST", "/stock", body=iter([b"tea", b"pot"]), encode_chunked=True)
            assert conn.getresponse().read() == stock.answer_body
            conn.close()
        finally:
            proxies.stop()
    assert (stock.seen[0]["path"], stock.seen[0]["body"]) == ("/api/stock", b"teapot")


def test_https_uses_tls_and_the_config_is_checked() -> None:
    lock = threading.Lock()
    p = backend.Proxy(
        backend.Backend("pay", "PAY_URL", "https://pay.example.com:8443"), Path("x"), lock
    )
    try:
        assert isinstance(p.connect(), http.client.HTTPSConnection)
        assert p.host_header == "pay.example.com:8443"
    finally:
        p.server_close()
    found = backend.from_answer([{"name": "a", "env": "A", "url": "http://x/"}])
    assert found == [backend.Backend("a", "A", "http://x")]


def test_repeated_headers_go_through_and_no_header_is_added(tmp_path: Path) -> None:
    with StockServer() as stock:
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            host, port = env["STOCK_URL"].removeprefix("http://").split(":")
            conn = http.client.HTTPConnection(host, int(port), timeout=10)
            conn.putrequest("GET", "/stock", skip_accept_encoding=True)
            conn.putheader("X-Shop-Tag", "teapot")
            conn.putheader("X-Shop-Tag", "mug")
            conn.endheaders()
            conn.getresponse().read()
            conn.close()
        finally:
            proxies.stop()
    seen = stock.seen[0]["headers"]
    assert [v for k, v in seen if k == "X-Shop-Tag"] == ["teapot", "mug"]
    assert not any(k.lower() == "accept-encoding" for k, _ in seen)


def call_in_thread(url: str) -> threading.Thread:
    t = threading.Thread(target=request, args=(url, "GET", "/stock", None, {}))
    t.start()
    return t


def wait_for_call(stock: StockServer) -> None:
    for _ in range(200):
        if stock.seen:
            return
        time.sleep(0.01)
    raise AssertionError("the backend got no call")


def test_stop_waits_for_an_open_call(tmp_path: Path) -> None:
    with StockServer() as stock:
        stock.delay = 0.5
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        t = call_in_thread(env["STOCK_URL"])
        wait_for_call(stock)
        proxies.stop()
        assert [r["status"] for r in rows(tmp_path)] == [200]
        t.join()


def test_a_call_that_does_not_end_gets_a_row_and_no_second_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backend, "DRAIN", 0.2)
    with StockServer() as stock:
        stock.delay = 1.0
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        t = call_in_thread(env["STOCK_URL"])
        wait_for_call(stock)
        proxies.stop()
        assert [(r["status"], r["error"]) for r in rows(tmp_path)] == [(None, backend.ENDED)]
        t.join()
    assert len(rows(tmp_path)) == 1


class NotedProxy(backend.Proxy):
    """A proxy that adds a text with a lone surrogate to each row."""

    def describe(self, row: dict, headers: list[tuple[str, str]], body: bytes) -> None:
        row["note"] = "a mug \ud83d"


def test_a_lone_surrogate_in_a_row_is_written_as_its_escape(tmp_path: Path) -> None:
    # The proxy reads headers as Latin-1 and bodies as strict UTF-8, so no wire text gives a lone
    # surrogate. A subclass row gives one to the writer.
    with StockServer() as stock:
        b = backend.Backend("stock", "STOCK_URL", stock.url)
        proxies = backend.Proxies([b], tmp_path / backend.FILE, NotedProxy)
        env = proxies.start()
        try:
            status, _, _ = request(env["STOCK_URL"], "GET", "/stock?sku=mug", None, {})
        finally:
            proxies.stop()
    assert status == 200
    assert rows(tmp_path)[0]["note"] == "a mug \\ud83d"


def test_a_response_larger_than_the_limit_goes_to_the_app_and_the_row_is_cut(
    tmp_path: Path,
) -> None:
    answer = os.urandom(300_000)
    with StockServer() as stock:
        stock.answer_body = answer
        b = backend.Backend("stock", "STOCK_URL", stock.url)
        proxies = backend.Proxies([b], tmp_path / backend.FILE, keep=100)
        env = proxies.start()
        try:
            _, _, got = request(env["STOCK_URL"], "GET", "/stock", None, {})
        finally:
            proxies.stop()
    assert got == answer
    body = rows(tmp_path)[0]["response_body"]
    assert (body["size"], body["sha256"], body["cut"]) == (
        len(answer),
        hashlib.sha256(answer).hexdigest(),
        True,
    )
    assert base64.b64decode(body["base64"]) == answer[:100]


def test_a_stream_body_keeps_only_its_first_bytes() -> None:
    stream = backend.StreamBody(10, None)
    for _ in range(1000):
        stream.add(b"0123456789abcdef")
    assert (stream.size, stream.kept, stream.data, stream.cut) == (16000, 10, b"0123456789", True)
    assert sum(len(p) for p in stream.parts) == 10


def test_the_start_of_a_cut_gzip_body_is_decoded() -> None:
    text = os.urandom(2000).hex().encode()
    data = gzip.compress(text)[:1000]
    assert backend.decode(data, "gzip", 100_000) is None
    assert backend.decode(data, "gzip", 100) == text[:101]
    assert backend.decode(data, "gzip", 19, partial=True) == text[:20]
    assert backend.decode(b"not gzip", "gzip", 20, partial=True) is None
    two = gzip.compress(b"tea") + gzip.compress(b"pot")
    assert backend.decode(two, "gzip", 100) == b"teapot"


def test_a_gzip_bomb_decodes_only_up_to_the_limit(tmp_path: Path) -> None:
    bomb = gzip.compress(bytes(50 * 1024 * 1024))
    assert len(bomb) < 100_000
    assert backend.decode(bomb, "gzip", 1000) == bytes(1001)
    body = backend.body_row(bomb, "gzip", 1000)
    assert (body["size"], body["cut"], body["decoded"], body["text"]) == (
        len(bomb),
        True,
        "gzip",
        "\0" * 1000,
    )
    with StockServer() as stock:
        stock.answer_body = bomb
        stock.answer_headers = [("Content-Encoding", "gzip")]
        b = backend.Backend("stock", "STOCK_URL", stock.url)
        proxies = backend.Proxies([b], tmp_path / backend.FILE, keep=100_000)
        env = proxies.start()
        try:
            _, _, got = request(env["STOCK_URL"], "GET", "/stock", None, {})
        finally:
            proxies.stop()
    assert got == bomb
    # The bomb is shorter than the limit, so the proxy keeps all of it and decodes it with the
    # same bound.
    assert rows(tmp_path)[0]["response_body"] == backend.body_row(bomb, "gzip", 100_000)


class RawBackend(socketserver.TCPServer):
    """A backend that sends one response as raw bytes, also a response that breaks the framing
    rules of HTTP."""

    allow_reuse_address = True

    def __init__(self, answer: bytes) -> None:
        self.answer = answer
        super().__init__(("127.0.0.1", 0), RawHandler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class RawHandler(socketserver.BaseRequestHandler):
    server: RawBackend

    def handle(self) -> None:
        self.request.recv(65536)
        self.request.sendall(self.server.answer)


FORGED = b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nforged"


@pytest.mark.parametrize(
    "head",
    [
        b"Transfer-Encoding: chunked\r\nContent-Length: 5\r\n",
        b"Transfer-Encoding: chunked\r\nContent-Length: -1\r\n",
        b"Transfer-Encoding: chunked\r\nContent-Length: five\r\n",
    ],
)
def test_the_app_gets_the_framing_of_the_bytes_and_not_a_wrong_length(
    tmp_path: Path, head: bytes
) -> None:
    data = b"HELLO" + FORGED
    answer = b"HTTP/1.1 200 OK\r\n" + head + b"\r\n%x\r\n%s\r\n0\r\n\r\n" % (len(data), data)
    server = RawBackend(answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        proxies = proxy_for(None, tmp_path, server.url)  # type: ignore[arg-type]
        env = proxies.start()
        try:
            host, port = env["STOCK_URL"].removeprefix("http://").split(":")
            with socket.create_connection((host, int(port)), timeout=10) as conn:
                conn.sendall(b"GET /stock HTTP/1.1\r\nHost: x\r\n\r\n")
                got = b""
                while not got.endswith(b"0\r\n\r\n"):
                    part = conn.recv(65536)
                    if not part:
                        break
                    got += part
        finally:
            proxies.stop()
    finally:
        server.shutdown()
        server.server_close()
    head_part, _, rest = got.partition(b"\r\n\r\n")
    assert b"content-length" not in head_part.lower()
    assert b"transfer-encoding: chunked" in head_part.lower()
    # The forged response is inside the one chunked body, so the app reads it as body bytes.
    assert rest == b"%x\r\n%s\r\n0\r\n\r\n" % (len(data), data)


def test_a_body_that_streams_at_the_end_of_the_test_keeps_its_status_and_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backend, "DRAIN", 0.2)
    with ModelServer() as server:
        server.parts = [b"first part, ", b"last part"]
        server.release.clear()
        b = backend.Backend("stock", "STOCK_URL", server.url)
        proxies = backend.Proxies([b], tmp_path / backend.FILE)
        env = proxies.start()
        host, port = env["STOCK_URL"].removeprefix("http://").split(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=10)
        conn.request("POST", "/stock", body=b"{}")
        resp = conn.getresponse()
        # The app has the status and the first part before the body ends.
        assert resp.status == 200 and resp.read1(65536) == b"first part, "
        proxies.stop()
        server.release.set()
        conn.close()
    row = rows(tmp_path)[0]
    assert (row["status"], row["error"]) == (200, backend.STREAM_ENDED)
    assert row["response_body"]["text"] == "first part, "


def test_an_http_1_0_client_gets_the_body_with_no_chunks(tmp_path: Path) -> None:
    server = RawBackend(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nhello toy shop")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        proxies = proxy_for(None, tmp_path, server.url)  # type: ignore[arg-type]
        env = proxies.start()
        try:
            host, port = env["STOCK_URL"].removeprefix("http://").split(":")
            with socket.create_connection((host, int(port)), timeout=10) as conn:
                conn.sendall(b"GET /stock HTTP/1.0\r\nConnection: keep-alive\r\n\r\n")
                got = b""
                while part := conn.recv(65536):
                    got += part
        finally:
            proxies.stop()
    finally:
        server.shutdown()
        server.server_close()
    head, _, rest = got.partition(b"\r\n\r\n")
    assert b"transfer-encoding" not in head.lower() and rest == b"hello toy shop"


def test_a_cut_in_a_character_keeps_the_text_before_it() -> None:
    stream = backend.StreamBody(5, None)
    stream.add("abcdé more".encode())
    body = stream.row()
    assert (body["cut"], body["text"], body["size"]) == (True, "abcd", 11)
    assert "base64" not in body
    assert backend.body_row(b"\xff\xfe\xfd\xfc\xfb\xfa", None, 3)["base64"] == "//79"


def raw_request(url: str, data: bytes) -> bytes:
    """Send `data` as it is, end the write side, and give all of the answer."""
    host, port = url.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=10) as s:
        s.sendall(data)
        s.shutdown(socket.SHUT_WR)
        out = b""
        while part := s.recv(65536):
            out += part
    return out


def limited(stock: StockServer, tmp_path: Path, limit: int) -> backend.Proxies:
    proxies = proxy_for(stock, tmp_path)
    proxies.proxies[0].body_limit = limit
    return proxies


def test_a_body_longer_than_the_limit_is_refused_and_not_forwarded(tmp_path: Path) -> None:
    with StockServer() as stock:
        proxies = limited(stock, tmp_path, 1000)
        env = proxies.start()
        try:
            # A body of exactly the limit goes through.
            status, _, _ = request(env["STOCK_URL"], "POST", "/stock", b"t" * 1000, {})
            assert status == 200
            refused, _, got = request(env["STOCK_URL"], "POST", "/stock", b"t" * 1001, {})
            host, port = env["STOCK_URL"].removeprefix("http://").split(":")
            conn = http.client.HTTPConnection(host, int(port), timeout=10)
            conn.request("POST", "/stock", body=iter([b"t" * 600] * 2), encode_chunked=True)
            chunked = conn.getresponse()
            assert chunked.status == 413
            conn.close()
        finally:
            proxies.stop()
    assert refused == 413
    assert json.loads(got) == {
        "error": "nookku backend proxy: the body is longer than 1000 bytes"
    }
    # Only the body of the limit reached the backend.
    assert [len(s["body"]) for s in stock.seen] == [1000]
    first, *others = rows(tmp_path)
    assert first["status"] == 200 and first["request_body"]["size"] == 1000
    assert len(others) == 2
    for row in others:
        assert row["error"] == "the proxy refused the request: the body is longer than 1000 bytes"
        assert row["request_body"] is None and row["status"] is None
        assert row["response_body"] is None and row["ts"] is not None


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"Content-Length: -1\r\n\r\nteapot", "the Content-Length is not one count of 0 or more"),
        (b"Content-Length: +6\r\n\r\nteapot", "the Content-Length is not one count of 0 or more"),
        (
            b"Content-Length: 6\r\nContent-Length: 7\r\n\r\nteapot",
            "the Content-Length is not one count of 0 or more",
        ),
        (b"Content-Length: 10\r\n\r\nteapot", "the body stopped before its end"),
        (b"Transfer-Encoding: chunked\r\n\r\n-6\r\nteapot\r\n0\r\n\r\n", "a chunk size is not valid"),
        (b"Transfer-Encoding: chunked\r\n\r\n0x6\r\nteapot\r\n0\r\n\r\n", "a chunk size is not valid"),
        (b"Transfer-Encoding: chunked\r\n\r\n6\r\ntea", "the body stopped before its end"),
        (b"Transfer-Encoding: chunked\r\n\r\n6\r\nteapot\r\n", "the body stopped before its end"),
        (
            b"Transfer-Encoding: chunked\r\n\r\n3\r\nteapot\r\n0\r\n\r\n",
            "a chunk does not end with a line end",
        ),
    ],
)
def test_a_body_with_framing_that_is_not_valid_is_refused(
    tmp_path: Path, data: bytes, reason: str
) -> None:
    with StockServer() as stock:
        proxies = proxy_for(stock, tmp_path)
        env = proxies.start()
        try:
            got = raw_request(env["STOCK_URL"], b"POST /stock HTTP/1.1\r\nHost: shop\r\n" + data)
        finally:
            proxies.stop()
    # A part of the body never goes to the backend, also if the app stops.
    assert stock.seen == []
    assert got.startswith(b"HTTP/1.1 400 ")
    assert got.endswith(json.dumps({"error": f"nookku backend proxy: {reason}"}).encode())
    [row] = rows(tmp_path)
    assert row["error"] == f"the proxy refused the request: {reason}"
    assert row["request_body"] is None


def test_the_proxy_reads_no_byte_of_a_body_that_is_too_long() -> None:
    class Source:
        def read(self, size: int) -> bytes:
            raise AssertionError("the proxy read the body")

    headers = http.client.HTTPMessage()
    headers["Content-Length"] = str(backend.BODY_LIMIT + 1)
    with pytest.raises(backend.Refused) as e:
        backend.read_body(headers, Source(), backend.BODY_LIMIT)
    assert e.value.status == 413
    assert backend.Proxy.body_limit == backend.BODY_LIMIT == 64 * 1024 * 1024

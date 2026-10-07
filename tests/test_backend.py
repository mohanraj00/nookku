import gzip
import http.client
import json
import os
import threading
import time
from pathlib import Path

import pytest
from toy_stock_server import StockServer

from verbatim_relay import backend


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
    assert backend.parse(None) == []
    with pytest.raises(ValueError, match="own 'name'"):
        backend.parse(
            [
                {"name": "a", "env": "A", "url": "http://x"},
                {"name": "a", "env": "B", "url": "http://y"},
            ]
        )
    with pytest.raises(ValueError, match="http or https"):
        backend.parse([{"name": "a", "env": "A", "url": "ftp://x"}])


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

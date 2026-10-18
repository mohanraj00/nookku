import json
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from toy_pg_server import PASSWORD, PgServer, message

from nookku import db_proxy, discovery, trace

PART = {"name": "shop-db", "kind": "postgres", "env": "DATABASE_URL", "address": None}
SSL = (8).to_bytes(4, "big") + db_proxy.SSL_REQUEST.to_bytes(4, "big")
STARTUP = b"user\0shop\0database\0shop\0\0"
STARTUP = (len(STARTUP) + 8).to_bytes(4, "big") + (196608).to_bytes(4, "big") + STARTUP
SIMPLE = "SELECT left FROM stock WHERE sku = 'teapot-set'"
EXTENDED = "SELECT left FROM stock WHERE sku = $1"


def bind(value: str) -> bytes:
    data = value.encode()
    body = b"\0\0" + (0).to_bytes(2, "big") + (1).to_bytes(2, "big")
    return message(b"B", body + len(data).to_bytes(4, "big") + data + (0).to_bytes(2, "big"))


# One session of the app: a TLS request, the startup, the password, a simple query, an extended
# query, a query that fails and the end.
SESSION = [
    SSL,
    STARTUP,
    message(b"p", PASSWORD + b"\0"),
    message(b"Q", SIMPLE.encode() + b"\0"),
    message(b"P", b"\0" + EXTENDED.encode() + b"\0\0\0")
    + bind("mug")
    + message(b"E", b"\0" + bytes(4))
    + message(b"S"),
    message(b"Q", b"SELECT * FROM nope\0"),
    message(b"X"),
]
# The bytes after which the app waits: N, R, Z, Z, Z, Z.
WAITS = [b"N", b"R", b"Z", b"Z", b"Z", b"Z", None]


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().split("\n") if x]


def recv_until(sock: socket.socket, end: bytes) -> bytes:
    """The bytes up to a message with the tag `end`, or the single byte N."""
    out = b""
    while True:
        data = sock.recv(65536)
        if not data:
            return out
        out += data
        if end == b"N" and out == b"N":
            return out
        at = 0
        while at + 5 <= len(out):
            size = int.from_bytes(out[at + 1 : at + 5], "big")
            if at + 1 + size > len(out):
                break
            if out[at : at + 1] == end:
                return out
            at += 1 + size


def run(proxy_url: str) -> bytes:
    url = urlsplit(proxy_url)
    got = b""
    with socket.create_connection((url.hostname, url.port), timeout=10) as sock:
        for data, wait in zip(SESSION, WAITS, strict=True):
            sock.sendall(data)
            if wait is not None:
                got += recv_until(sock, wait)
    return got


def start(server: PgServer, tmp_path: Path) -> tuple[db_proxy.Proxy, dict[str, str]]:
    environ = {"DATABASE_URL": server.url + "?sslmode=prefer"}
    (database,) = db_proxy.databases([PART], environ)
    proxy = db_proxy.Proxy(database, tmp_path / db_proxy.FILE, threading.Lock())
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    return proxy, db_proxy.environment([proxy], environ)


def test_the_proxy_changes_no_byte_and_never_records_the_password(tmp_path: Path) -> None:
    with PgServer() as server:
        proxy, env = start(server, tmp_path)
        try:
            got = run(env["DATABASE_URL"])
        finally:
            proxy.stop()
    # The app gets the N of the proxy, then each byte of the server.
    assert got == b"N" + server.sent
    # The server gets each byte of the app, except the TLS request.
    assert server.got == b"".join(SESSION[1:])
    url = urlsplit(env["DATABASE_URL"])
    assert (url.username, url.password, url.port) == (
        "shop",
        PASSWORD.decode(),
        proxy.server_address[1],
    )
    assert url.path == "/shop" and url.query == "sslmode=prefer"
    text = (tmp_path / db_proxy.FILE).read_text()
    assert PASSWORD.decode() not in text
    found = rows(tmp_path / db_proxy.FILE)
    assert found[0]["type"] == "connect" and found[0]["declined"] == ["ssl"]
    assert found[0]["parameters"] == {"user": "shop", "database": "shop"}
    (secret,) = [r for r in found if r.get("tag") == "p"]
    assert secret["fields"] is None and secret["size"] == len(PASSWORD) + 5


def test_the_reader_gives_each_query_with_its_rows_or_its_error(tmp_path: Path) -> None:
    with PgServer() as server:
        proxy, env = start(server, tmp_path)
        try:
            run(env["DATABASE_URL"])
        finally:
            proxy.stop()
    items, info = trace.read_database(tmp_path / db_proxy.FILE)
    assert [(it["kind"], it["name"], it["output"], it["error"]) for it in items] == [
        ("query", "SELECT", '["3"]\nSELECT 1', None),
        ("query", "SELECT", '["12"]\nSELECT 1', None),
        ("query", "SELECT", None, 'relation "nope" does not exist'),
    ]
    assert [it["input"] for it in items] == [
        {"query": SIMPLE, "parameters": None},
        {"query": EXTENDED, "parameters": ["mug"]},
        {"query": "SELECT * FROM nope", "parameters": None},
    ]
    assert {it["harness"] for it in items} == {"database"}
    assert {it["session"] for it in items} == {"shop-db"}
    assert info["items"] == 3 and info["ignored"] == {"connect": 1}


def test_a_database_that_does_not_answer_gives_a_connect_row(tmp_path: Path) -> None:
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    database = db_proxy.Database("shop-db", "DATABASE_URL", "127.0.0.1", port)
    proxy = db_proxy.Proxy(database, tmp_path / db_proxy.FILE, threading.Lock())
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        with socket.create_connection(("127.0.0.1", proxy.server_address[1]), timeout=10) as s:
            assert s.recv(1) == b""
    finally:
        proxy.stop()
    (row,) = rows(tmp_path / db_proxy.FILE)
    assert row["type"] == "connect" and row["error"].startswith("no connection:")


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "has no value"),
        ("mysql://shop@127.0.0.1/shop", "must hold a postgres:// or postgresql:// URL"),
        ("postgresql:///shop?host=/var/run", "must hold a postgres:// or postgresql:// URL"),
        ("postgresql://127.0.0.1:99999/shop", "has a port that is not valid"),
        ("postgresql://127.0.0.1/shop?sslmode=require", "has sslmode=require"),
    ],
)
def test_a_variable_that_is_not_a_postgres_url_stops_the_start(
    value: str | None, text: str
) -> None:
    environ = {} if value is None else {"DATABASE_URL": value}
    with pytest.raises(ValueError, match=text):
        db_proxy.databases([PART], environ)


def test_only_a_postgres_database_with_a_variable_gets_a_proxy() -> None:
    parts = [PART, {**PART, "name": "cart", "env": None}, {**PART, "name": "log", "kind": "sqlite"}]
    environ = {"DATABASE_URL": "postgres://127.0.0.1/shop"}
    assert db_proxy.databases(parts, environ) == [
        db_proxy.Database("shop-db", "DATABASE_URL", "127.0.0.1", 5432)
    ]
    parts[2] = {**parts[2], "env": "LOG_DB"}
    answer = discovery.parse(discovery.make(databases=parts))
    assert [p.proxy for p in discovery.parts(answer)] == [True, False, False]


def test_the_reader_keeps_no_body_of_a_long_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_proxy.backend, "RECORD_LIMIT", 10)
    long = message(b"D", (1).to_bytes(2, "big") + (20).to_bytes(4, "big") + b"x" * 20)
    data = long + message(b"C", b"SELECT 1\0")
    reader = db_proxy.Messages()
    # The long message comes in 3 parts, and a short message follows it in the last part.
    got = [m for part in (data[:3], data[3:12], data[12:]) for m in reader.add(part)]
    assert got == [(b"D", None, len(long) - 1), (b"C", b"SELECT 1\0", 13)]

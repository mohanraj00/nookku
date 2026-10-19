import json
import shutil
import socket
import ssl
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from toy_pg_server import PASSWORD, PgServer, message

from nookku import db_proxy, discovery, trace

ROOT = Path(__file__).resolve().parent.parent
CASES = sorted((ROOT / "conformance" / "database").glob("*.json"))
PART = {
    "name": "shop-db",
    "kind": "postgres",
    "env": "DATABASE_URL",
    "address": None,
    "record": "proxy",
}
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


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home with no ~/.postgresql/root.crt, so that the default root file of libpq is not
    the file of the person who runs the tests."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    return folder


def start(
    server: PgServer,
    tmp_path: Path,
    mode: str | None = "prefer",
    query: str = "",
    env: dict[str, str] | None = None,
) -> tuple[db_proxy.Proxy, dict[str, str]]:
    """Start a proxy to the server. If mode is None, the URL has no sslmode. env holds the other
    variables of the app."""
    url = server.url + (f"?sslmode={mode}{query}" if mode else "?" + query.lstrip("&"))
    environ = {"DATABASE_URL": url, **(env or {})}
    (database,) = db_proxy.databases([PART], environ)
    proxy = db_proxy.Proxy(database, tmp_path / db_proxy.FILE, threading.Lock())
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    return proxy, db_proxy.environment([proxy], environ)


@pytest.mark.parametrize(("mode", "asked"), [("prefer", 1), ("allow", 1), ("disable", 0)])
def test_the_proxy_changes_no_byte_and_never_records_the_password(
    tmp_path: Path, mode: str, asked: int
) -> None:
    with PgServer() as server:
        proxy, env = start(server, tmp_path, mode)
        try:
            got = run(env["DATABASE_URL"])
        finally:
            proxy.stop()
    # The proxy asks the database for TLS, as the sslmode of the app does. This server says N.
    assert server.ssl_requests == asked and not server.tls_used
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
    # The app speaks plain text to the proxy on 127.0.0.1.
    assert url.path == "/shop" and url.query == "sslmode=disable"
    text = (tmp_path / db_proxy.FILE).read_text()
    assert PASSWORD.decode() not in text
    found = rows(tmp_path / db_proxy.FILE)
    assert found[0]["type"] == "connect" and found[0]["declined"] == ["ssl"]
    assert found[0]["parameters"] == {"user": "shop", "database": "shop"}
    (secret,) = [r for r in found if r.get("tag") == "p"]
    assert secret["fields"] is None and secret["size"] == len(PASSWORD) + 5


def certificate(folder: Path, name: str, san: str) -> tuple[Path, Path]:
    """A new self-signed certificate with the common name and the subjectAltName, and its key."""
    if shutil.which("openssl") is None:
        pytest.skip("this test needs openssl")
    key, cert = folder / f"{name}.key", folder / f"{name}.pem"
    subprocess.run(
        [
            *("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1"),
            *("-subj", f"/CN={name}", "-addext", f"subjectAltName={san}"),
            *("-keyout", str(key), "-out", str(cert)),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def tls_context(
    folder: Path, name: str = "db.toy.test", san: str = "DNS:db.toy.test"
) -> ssl.SSLContext:
    """A TLS context of the toy server, with a new self-signed certificate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*certificate(folder, name, san))
    return context


def test_the_proxy_speaks_tls_to_a_database_that_agrees(tmp_path: Path) -> None:
    with PgServer(tls_context(tmp_path)) as server:
        proxy, env = start(server, tmp_path)
        try:
            got = run(env["DATABASE_URL"])
        finally:
            proxy.stop()
    assert server.tls_used
    assert got == b"N" + server.sent
    assert server.got == b"".join(SESSION[1:])


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_each_tls_mode_speaks_tls_to_the_database(tmp_path: Path, mode: str) -> None:
    # The certificate has the address of the URL, so each check passes.
    context = tls_context(tmp_path, "shop-db", "IP:127.0.0.1")
    with PgServer(context) as server:
        root = "" if mode == "require" else f"&sslrootcert={tmp_path / 'shop-db.pem'}"
        proxy, env = start(server, tmp_path, mode, root)
        try:
            got = run(env["DATABASE_URL"])
        finally:
            proxy.stop()
    assert server.tls_used
    assert got == b"N" + server.sent
    assert server.got == b"".join(SESSION[1:])
    assert urlsplit(env["DATABASE_URL"]).query.endswith("sslmode=disable")
    assert proxy.database.sslmode == mode


def stopped(proxy: db_proxy.Proxy, tmp_path: Path) -> dict:
    """Connect an app to the proxy and expect the end of the connection. Give the connect row."""
    try:
        with socket.create_connection(("127.0.0.1", proxy.server_address[1]), timeout=10) as s:
            # The proxy connects to the database before it reads a byte of the app.
            assert s.recv(1) == b""
    finally:
        proxy.stop()
    (row,) = rows(tmp_path / db_proxy.FILE)
    assert row["type"] == "connect" and row["error"].startswith("no connection:")
    return row


@pytest.mark.parametrize(
    ("mode", "root", "text"),
    [
        # The certificate is for db.toy.test, and the URL has 127.0.0.1.
        ("verify-full", "server", "IP address mismatch"),
        # The root certificate is not the one that signed the certificate of the database.
        ("verify-ca", "other", "certificate verify failed"),
        ("verify-full", "other", "certificate verify failed"),
        # require with a root certificate checks the chain as verify-ca does, as libpq does.
        ("require", "other", "certificate verify failed"),
    ],
)
def test_a_certificate_that_does_not_match_stops_the_connection(
    tmp_path: Path, mode: str, root: str, text: str
) -> None:
    certificate(tmp_path, "other", "DNS:other.toy.test")
    with PgServer(tls_context(tmp_path)) as server:
        rootcert = tmp_path / ("db.toy.test.pem" if root == "server" else "other.pem")
        proxy, _ = start(server, tmp_path, mode, f"&sslrootcert={rootcert}")
        row = stopped(proxy, tmp_path)
    assert text in row["error"]
    # No byte of the app went to the database.
    assert server.got == b""


def test_verify_ca_does_not_check_the_host_name(tmp_path: Path) -> None:
    with PgServer(tls_context(tmp_path)) as server:
        root = f"&sslrootcert={tmp_path / 'db.toy.test.pem'}"
        proxy, env = start(server, tmp_path, "verify-ca", root)
        try:
            got = run(env["DATABASE_URL"])
        finally:
            proxy.stop()
    assert server.tls_used and got == b"N" + server.sent


def test_the_default_root_file_of_libpq_makes_require_check_the_chain(
    tmp_path: Path, home: Path
) -> None:
    other, _ = certificate(tmp_path, "other", "DNS:other.toy.test")
    (home / ".postgresql").mkdir()
    (home / ".postgresql" / "root.crt").write_bytes(other.read_bytes())
    with PgServer(tls_context(tmp_path)) as server:
        proxy, _ = start(server, tmp_path, "require")
        row = stopped(proxy, tmp_path)
    assert "certificate verify failed" in row["error"]


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_a_tls_mode_never_falls_back_to_plain_text(tmp_path: Path, mode: str) -> None:
    cert, _ = certificate(tmp_path, "shop-db", "IP:127.0.0.1")
    # This server declines TLS.
    with PgServer() as server:
        proxy, _ = start(server, tmp_path, mode, f"&sslrootcert={cert}")
        row = stopped(proxy, tmp_path)
    assert server.ssl_requests == 1 and server.got == b""
    assert f"sslmode={mode} needs it" in row["error"]


def signed(folder: Path, revoked: bool) -> tuple[ssl.SSLContext, Path, Path]:
    """A TLS context of the toy server, with a certificate that a new root signed, the root
    certificate, and a revocation list of the root. The list holds the certificate if revoked."""
    root, root_key = certificate(folder, "toy-root", "DNS:toy-root")
    key, cert = folder / "db.key", folder / "db.pem"
    (folder / "san.cnf").write_text("subjectAltName=IP:127.0.0.1\n")
    (folder / "index.txt").write_text("")
    (folder / "crlnumber").write_text("01\n")
    (folder / "ca.cnf").write_text(
        "[ca]\ndefault_ca=toy\n[toy]\ndatabase=index.txt\ncrlnumber=crlnumber\n"
        "default_md=sha256\ndefault_crl_days=1\n"
    )
    ca = ("openssl", "ca", "-config", "ca.cnf", "-keyfile", str(root_key), "-cert", str(root))
    steps = [
        (
            *("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=db.toy.test"),
            *("-keyout", str(key), "-out", "db.csr"),
        ),
        (
            *("openssl", "x509", "-req", "-in", "db.csr", "-CA", str(root), "-CAkey"),
            *(str(root_key), "-set_serial", "2", "-days", "1", "-extfile", "san.cnf"),
            *("-out", str(cert)),
        ),
        *([(*ca, "-revoke", str(cert))] if revoked else []),
        (*ca, "-gencrl", "-out", "root.crl"),
    ]
    for step in steps:
        subprocess.run(step, cwd=folder, check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context, root, folder / "root.crl"


@pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
def test_a_revoked_certificate_stops_the_connection(tmp_path: Path, mode: str) -> None:
    context, root, crl = signed(tmp_path, revoked=True)
    with PgServer(context) as server:
        proxy, _ = start(server, tmp_path, mode, f"&sslrootcert={root}&sslcrl={crl}")
        row = stopped(proxy, tmp_path)
    assert "certificate revoked" in row["error"]
    assert server.got == b""


def test_a_certificate_that_the_list_does_not_hold_speaks_tls(tmp_path: Path) -> None:
    context, root, crl = signed(tmp_path, revoked=False)
    with PgServer(context) as server:
        proxy, env = start(
            server, tmp_path, "verify-full", f"&sslrootcert={root}", {"PGSSLCRL": str(crl)}
        )
        try:
            got = run(env["DATABASE_URL"])
        finally:
            proxy.stop()
    assert server.tls_used and got == b"N" + server.sent
    assert proxy.database.crl == str(crl)


def test_pgsslcrl_gives_the_list_if_the_url_has_none(tmp_path: Path) -> None:
    context, root, crl = signed(tmp_path, revoked=True)
    with PgServer(context) as server:
        env = {"PGSSLCRL": str(crl)}
        proxy, _ = start(server, tmp_path, "verify-ca", f"&sslrootcert={root}", env)
        row = stopped(proxy, tmp_path)
    assert "certificate revoked" in row["error"]


def test_the_default_list_of_libpq_stops_a_revoked_certificate(tmp_path: Path, home: Path) -> None:
    context, root, crl = signed(tmp_path, revoked=True)
    (home / ".postgresql").mkdir()
    (home / ".postgresql" / "root.crl").write_bytes(crl.read_bytes())
    with PgServer(context) as server:
        proxy, _ = start(server, tmp_path, "verify-ca", f"&sslrootcert={root}")
        row = stopped(proxy, tmp_path)
    assert "certificate revoked" in row["error"]


def test_ssl_min_protocol_version_stops_an_older_tls(tmp_path: Path) -> None:
    context = tls_context(tmp_path)
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    with PgServer(context) as server:
        proxy, _ = start(server, tmp_path, "require", "&ssl_min_protocol_version=TLSv1.3")
        row = stopped(proxy, tmp_path)
    assert proxy.database.min_tls == "TLSv1.3"
    assert server.got == b""
    assert "no connection:" in row["error"]


@pytest.mark.parametrize("given", ["url", "variable"])
def test_pgsslmode_gives_the_sslmode_if_the_url_has_none(tmp_path: Path, given: str) -> None:
    # The certificate is for db.toy.test, and the URL has 127.0.0.1. With PGSSLMODE=verify-full,
    # the connection stops, as with libpq, and does not change to prefer.
    certificate(tmp_path, "db.toy.test", "DNS:db.toy.test")
    root = tmp_path / "db.toy.test.pem"
    env = {"PGSSLMODE": "verify-full"}
    if given == "url":
        query = f"sslrootcert={root}"
    else:
        query, env["PGSSLROOTCERT"] = "", str(root)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root, tmp_path / "db.toy.test.key")
    with PgServer(context) as server:
        proxy, _ = start(server, tmp_path, None, query, env)
        row = stopped(proxy, tmp_path)
    assert (proxy.database.sslmode, proxy.database.rootcert) == ("verify-full", str(root))
    assert "IP address mismatch" in row["error"]


def test_the_app_url_has_sslmode_disable_and_keeps_the_other_parameters() -> None:
    environ = {
        "DATABASE_URL": "postgresql://shop@db.toy.test/shop?application_name=a%20b+c"
        "&sslmode=require&sslnegotiation=direct&connect_timeout=5&sslcert=/no/shop.crt"
        "&ssl_min_protocol_version=TLSv1.3"
    }
    (database,) = db_proxy.databases([PART], environ)
    proxy = db_proxy.Proxy(database, Path("unused.jsonl"), threading.Lock())
    try:
        url = urlsplit(db_proxy.environment([proxy], environ)["DATABASE_URL"])
    finally:
        proxy.server_close()
    # The app speaks plain text to the proxy, so its URL keeps no TLS parameter. A + stays.
    assert url.query == "application_name=a%20b+c&connect_timeout=5&sslmode=disable"
    assert (url.hostname, url.port) == ("127.0.0.1", proxy.server_address[1])


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


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_the_variable_gives_each_conformance_result(case: Path) -> None:
    data = json.loads(case.read_text(encoding="utf-8"))
    environ = {"DATABASE_URL": data["value"], **data.get("environ", {})}
    expect = data["expect"]
    if "error" in expect:
        with pytest.raises(ValueError) as e:
            db_proxy.databases([PART], environ)
        assert str(e.value) == expect["error"]
        return
    (database,) = db_proxy.databases([PART], environ)
    assert (database.sslmode, database.rootcert) == (expect["sslmode"], expect["rootcert"])
    proxy = SimpleNamespace(database=database, server_address=("127.0.0.1", 5999))
    url = db_proxy.environment([proxy], environ)["DATABASE_URL"]  # type: ignore[list-item]
    assert url == f"postgresql://shop@127.0.0.1:5999/shop?{expect['app_query']}"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "has no value"),
        ("mysql://shop@127.0.0.1/shop", "must hold a postgres:// or postgresql:// URL"),
        ("postgresql:///shop?host=/var/run", "must hold a postgres:// or postgresql:// URL"),
        ("postgresql://127.0.0.1:99999/shop", "has a port that is not valid"),
        ("postgresql://127.0.0.1/shop?sslmode=on", "has sslmode=on, which is not"),
        ("postgresql://127.0.0.1/shop?sslmode=verify-ca", "has sslmode=verify-ca and no root"),
        ("postgresql://127.0.0.1/shop?sslmode=verify-full", "has sslmode=verify-full and no"),
        (
            "postgresql://127.0.0.1/shop?sslmode=verify-full&sslrootcert=/no/root.crt",
            "has an sslrootcert file that does not exist",
        ),
        ("postgresql://db.toy.test/shop?hostaddr=203.0.113.1", "has the query parameter hostaddr"),
        ("postgresql://db.toy.test/shop?host=/var/run", "has the query parameter host"),
        ("postgresql://db.toy.test/shop?port=6543", "has the query parameter port"),
        ("postgresql://db.toy.test/shop?host=", "has the query parameter host"),
        ("postgresql://db.toy.test/shop?service=", "has the query parameter service"),
        ("postgresql://127.0.0.1/shop?gssencmode=require", "has gssencmode=require"),
        # libpq keeps a + in a URL, and reads a relative path from the folder of the app.
        (
            "postgresql://127.0.0.1/shop?sslmode=verify-ca&sslrootcert=/no/a+b.crt",
            "file that does not exist: /no/a\\+b.crt",
        ),
        ("postgresql://127.0.0.1/shop?sslrootcert=root.crt", "relative sslrootcert path"),
        ("postgresql://127.0.0.1/shop?ssl_min_protocol_version=TLSv9", "TLSv9, which is not"),
        ("postgresql://127.0.0.1/shop?ssl_max_protocol_version=tls", "tls, which is not"),
        (
            "postgresql://127.0.0.1/shop?ssl_min_protocol_version=TLSv1.3"
            "&ssl_max_protocol_version=TLSv1.2",
            "TLSv1.3, which is above ssl_max_protocol_version=TLSv1.2",
        ),
        (
            "postgresql://127.0.0.1/shop?ssl_max_protocol_version=TLSv1.1",
            "TLSv1.2, which is above ssl_max_protocol_version=TLSv1.1",
        ),
        ("postgresql://127.0.0.1/shop?requiressl=1", "has requiressl"),
        ("postgresql://127.0.0.1/shop?sslcertmode=require", "has sslcertmode=require"),
    ],
)
def test_a_variable_that_is_not_a_postgres_url_stops_the_start(
    value: str | None, text: str
) -> None:
    environ = {} if value is None else {"DATABASE_URL": value}
    with pytest.raises(ValueError, match=text):
        db_proxy.databases([PART], environ)


@pytest.mark.parametrize(
    ("env", "text"),
    [
        ({"PGSSLMODE": "on"}, "has sslmode=on, which is not"),
        ({"PGSSLMODE": "verify-full"}, "has sslmode=verify-full and no root"),
        ({"PGSSLROOTCERT": "root.crt"}, "relative sslrootcert path"),
        ({"PGSSLROOTCERT": "system"}, "the app has PGSSLROOTCERT=system"),
        ({"PGSSLNEGOTIATION": "direct"}, "the app has PGSSLNEGOTIATION=direct"),
        ({"PGSSLCERTMODE": "require"}, "or PGSSLCERTMODE"),
        ({"PGREQUIRESSL": "1"}, "or PGREQUIRESSL"),
        ({"PGSSLMINPROTOCOLVERSION": "TLSv9"}, "TLSv9, which is not"),
        # libpq would connect the app past the proxy, in plain text.
        ({"PGHOSTADDR": "203.0.113.1"}, "the app has PGHOSTADDR"),
        ({"PGSERVICE": "shop"}, "the app has PGSERVICE"),
        ({"PGGSSENCMODE": "require"}, "has gssencmode=require"),
    ],
)
def test_a_variable_of_libpq_that_the_proxy_refuses_stops_the_start(
    env: dict[str, str], text: str
) -> None:
    environ = {"DATABASE_URL": "postgresql://shop@db.toy.test/shop", **env}
    with pytest.raises(ValueError, match=text):
        db_proxy.databases([PART], environ)


@pytest.mark.parametrize(
    ("query", "text"),
    [
        ("sslcrl=root.crl", "relative sslcrl path"),
        ("sslcrl=/no/root.crl", "sslcrl file that does not exist"),
        ("sslcrldir=/no/crl", "sslcrldir folder that does not"),
    ],
)
def test_a_revocation_list_that_the_proxy_cannot_read_stops_the_start(
    tmp_path: Path, query: str, text: str
) -> None:
    root, _ = certificate(tmp_path, "toy-root", "DNS:toy-root")
    environ = {"DATABASE_URL": f"postgresql://shop@db.toy.test/shop?sslrootcert={root}&{query}"}
    with pytest.raises(ValueError, match=text):
        db_proxy.databases([PART], environ)


def test_the_system_roots_and_no_root_file_load_no_revocation_list(home: Path) -> None:
    # As libpq does: the lists go only with a file of root certificates. A list of a private
    # root then does not stop a database with a public certificate.
    (home / ".postgresql").mkdir()
    (home / ".postgresql" / "root.crl").write_text("")
    for query in ("sslrootcert=system", "sslmode=require&sslcrl=/no/root.crl"):
        environ = {"DATABASE_URL": f"postgresql://shop@db.toy.test/shop?{query}"}
        (database,) = db_proxy.databases([PART], environ)
        assert (database.crl, database.crldir) == (None, None)


def test_a_root_file_loads_the_default_revocation_list(tmp_path: Path, home: Path) -> None:
    root, _ = certificate(tmp_path, "toy-root", "DNS:toy-root")
    (home / ".postgresql").mkdir()
    (home / ".postgresql" / "root.crl").write_text("")
    environ = {"DATABASE_URL": f"postgresql://shop@db.toy.test/shop?sslrootcert={root}"}
    (database,) = db_proxy.databases([PART], environ)
    assert database.crl == str(home / ".postgresql" / "root.crl")


def test_the_url_wins_over_the_variables_of_libpq() -> None:
    environ = {
        "DATABASE_URL": "postgresql://shop@db.toy.test/shop?sslmode=disable",
        "PGSSLMODE": "verify-full",
        "PGSSLCRL": "/no/root.crl",
    }
    (database,) = db_proxy.databases([PART], environ)
    assert (database.sslmode, database.rootcert, database.crl) == ("disable", None, None)


def test_only_a_database_with_record_proxy_gets_a_proxy() -> None:
    driver = {"record": "driver"}
    parts = [
        PART,
        {**PART, **driver, "name": "cart", "env": None, "address": "db:5432/cart"},
        {**PART, **driver, "name": "log", "kind": "sqlite", "env": "LOG_DB"},
        {**PART, **driver, "name": "stock-db", "env": "STOCK_DB_URL", "address": "db:5432/stock"},
    ]
    environ = {"DATABASE_URL": "postgres://127.0.0.1/shop", "STOCK_DB_URL": "postgres://db/stock"}
    assert db_proxy.databases(parts, environ) == [
        db_proxy.Database("shop-db", "DATABASE_URL", "127.0.0.1", 5432, "prefer", None)
    ]
    answer = discovery.parse(discovery.make(databases=parts))
    assert [p.proxy for p in discovery.parts(answer)] == [True, False, False, False]
    assert discovery.drivers(answer) == ["cart", "log", "stock-db"]
    assert discovery.unseen(answer) == []


def test_the_reader_keeps_no_body_of_a_long_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_proxy.backend, "RECORD_LIMIT", 10)
    long = message(b"D", (1).to_bytes(2, "big") + (20).to_bytes(4, "big") + b"x" * 20)
    data = long + message(b"C", b"SELECT 1\0")
    reader = db_proxy.Messages()
    # The long message comes in 3 parts, and a short message follows it in the last part.
    got = [m for part in (data[:3], data[3:12], data[12:]) for m in reader.add(part)]
    assert got == [(b"D", None, len(long) - 1), (b"C", b"SELECT 1\0", 13)]


def data_row(direction: str, tag: str, ts: float, **fields: object) -> dict:
    row = {"v": 1, "type": "message", "database": "shop-db", "connection": 1, "ts": ts}
    return {**row, "direction": direction, "tag": tag, "size": 0, "fields": fields or None}


def test_the_reader_ends_an_execute_at_an_empty_query_or_a_suspended_portal(
    tmp_path: Path,
) -> None:
    query = "SELECT left FROM stock"
    found = [
        data_row("to_server", "P", 1.0, statement="", query=query),
        data_row("to_server", "B", 1.1, portal="", statement="", parameters=[], results=[1]),
        data_row("to_server", "E", 1.2, portal=""),
        data_row("to_server", "E", 1.3, portal=""),
        data_row("from_server", "D", 2.0, values=["\u0000\u0000\u0000\f"]),
        data_row("from_server", "s", 2.1),
        data_row("from_server", "I", 2.2),
        data_row("from_server", "Z", 2.3, status="I"),
    ]
    (tmp_path / db_proxy.FILE).write_text("".join(json.dumps(r) + "\n" for r in found))
    items, _ = trace.read_database(tmp_path / db_proxy.FILE)
    # A binary column of the Bind gives base64 of the bytes of the value.
    assert [(it["output"], it["error"]) for it in items] == [
        ('[{"base64": "AAAADA=="}]', None),
        (None, None),
    ]


def test_the_connect_row_has_no_secret_startup_value() -> None:
    params = {
        "user": "shop",
        "app.api_key": "k1",
        "options": r"-c app.api_key=k2\ k3 --search_path=public -capp.token=k4",
    }
    assert db_proxy.parameters_row(params) == {
        "user": "shop",
        "app.api_key": "<removed>",
        "options": "-c app.api_key=<removed> --search_path=public -capp.token=<removed>",
    }


def test_the_reader_ends_one_batch_at_each_ready(tmp_path: Path) -> None:
    query = "SELECT left FROM stock WHERE sku = $1"
    bind = {"portal": "", "statement": "", "parameters": ["mug"], "results": []}
    found = [
        data_row("to_server", "P", 1.0, statement="", query=query),
        data_row("to_server", "B", 1.1, **bind),
        data_row("to_server", "E", 1.2, portal=""),
        data_row("to_server", "S", 1.3),
        data_row("to_server", "B", 1.4, **bind),
        data_row("to_server", "E", 1.5, portal=""),
        data_row("to_server", "S", 1.6),
        data_row("to_server", "B", 1.7, **bind),
        data_row("to_server", "E", 1.8, portal=""),
        data_row("to_server", "S", 1.9),
        data_row("from_server", "C", 1.95, command="SELECT 0"),
        data_row("from_server", "Z", 1.96, status="I"),
        data_row("from_server", "E", 2.0, message="stock is locked"),
        data_row("from_server", "Z", 2.1, status="I"),
        data_row("from_server", "D", 2.2, values=["12"]),
        data_row("from_server", "C", 2.3, command="SELECT 1"),
        data_row("from_server", "Z", 2.4, status="I"),
    ]
    (tmp_path / db_proxy.FILE).write_text("".join(json.dumps(r) + "\n" for r in found))
    items, _ = trace.read_database(tmp_path / db_proxy.FILE)
    # The error of the second batch does not stop the third batch, after its own Sync. The
    # ReadyForQuery of the first batch comes after its execute has its end.
    assert [(it["output"], it["error"]) for it in items] == [
        ("SELECT 0", None),
        (None, "stock is locked"),
        ('["12"]\nSELECT 1', None),
    ]

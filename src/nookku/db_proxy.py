"""The Postgres proxies of a test (SPEC.md section 7.13): one recording proxy for each Postgres
database of the egress answer that has a variable.

The proxy speaks the Postgres wire protocol to the app and to the database. It copies each byte
of a connection with no change, except at the start: it declines a TLS request of the app, so that
it can read the messages. The app speaks plain text to the proxy, only on 127.0.0.1. The proxy
speaks TLS to the database as the sslmode of the app tells it, and it never falls back to plain
text for require, verify-ca or verify-full. It writes each message of each direction to
database.jsonl. It never writes the password: the variable keeps its value for the app, and the
record keeps only the size of an authentication message of the app.
"""

from __future__ import annotations

import base64
import contextlib
import itertools
import re
import socket
import socketserver
import ssl
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import parse_qsl, unquote_plus, urlsplit, urlunsplit

from nookku import backend
from nookku.record import json_text

FILE = "database.jsonl"
VERSION = 1
KINDS = ("postgres",)
SCHEMES = ("postgres", "postgresql")
DEFAULT_PORT = 5432
# The request codes of a startup packet of the app (the Postgres protocol 3.0).
SSL_REQUEST = 80877103
GSS_REQUEST = 80877104
CANCEL_REQUEST = 80877102
# The sslmode values of libpq. The proxy uses the sslmode of the app to the database.
SSL_MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
# The sslmode values that need TLS. If the database declines TLS, the connection stops.
TLS_MODES = ("require", "verify-ca", "verify-full")
# The sslrootcert value that tells libpq to use the trusted roots of the system.
SYSTEM_ROOTS = "system"
# The query parameters of a URL that give libpq another address than the host of the URL. The
# app would then connect past the proxy.
ADDRESS_KEYS = ("host", "hostaddr", "port", "service")
# A startup packet is short. A longer one is not a packet of the protocol.
STARTUP_LIMIT = 10000
CHUNK = 65536
TIMEOUT = 10.0


class Database(NamedTuple):
    name: str
    env: str
    host: str
    port: int
    # The sslmode of the app URL, or prefer, the default of libpq.
    sslmode: str = "prefer"
    # The file of the root certificates that the proxy trusts, SYSTEM_ROOTS, or None. If it is
    # not None, require checks the certificate as verify-ca does, as libpq does.
    rootcert: str | None = None


def _rootcert(where: str, mode: str, query: dict[str, str]) -> str | None:
    """The root certificates of the URL: sslrootcert, else the default file of libpq if it
    exists. Raise ValueError if verify-ca or verify-full has no root certificates."""
    given = query.get("sslrootcert")
    if given == SYSTEM_ROOTS:
        return given
    if given:
        path = Path(given)
        if not path.is_file():
            raise ValueError(f"{where} has an sslrootcert file that does not exist: {given}")
        return str(path)
    default = Path.home() / ".postgresql" / "root.crt"
    if default.is_file():
        return str(default)
    if mode in ("verify-ca", "verify-full"):
        raise ValueError(
            f"{where} has sslmode={mode} and no root certificate. Give the file of the root "
            "certificate in sslrootcert, or sslrootcert=system."
        )
    return None


def _upstream(part: dict[str, Any], value: str | None) -> Database:
    where = f"the database {part['name']}: the variable {part['env']}"
    if not value:
        raise ValueError(f"{where} has no value. The proxy needs the postgres URL in it.")
    url = urlsplit(value)
    try:
        port = url.port or DEFAULT_PORT
    except ValueError:
        raise ValueError(f"{where} has a port that is not valid") from None
    if url.scheme not in SCHEMES or not url.hostname:
        raise ValueError(f"{where} must hold a postgres:// or postgresql:// URL with a host")
    query = dict(parse_qsl(url.query, keep_blank_values=True))
    moved = [k for k in ADDRESS_KEYS if k in query]
    if moved:
        raise ValueError(
            f"{where} has the query parameter {moved[0]}, which gives another address than "
            "the host of the URL. Give the address only in the host and the port of the URL."
        )
    mode = query.get("sslmode", "prefer")
    if mode not in SSL_MODES:
        raise ValueError(f"{where} has sslmode={mode}, which is not an sslmode of libpq")
    if query.get("gssencmode") == "require":
        raise ValueError(
            f"{where} has gssencmode=require. The proxy speaks no GSSAPI encryption, so give "
            "gssencmode=disable or prefer for the test."
        )
    rootcert = None if mode == "disable" else _rootcert(where, mode, query)
    return Database(part["name"], part["env"], url.hostname, port, mode, rootcert)


def databases(parts: list[dict[str, Any]], environ: Any) -> list[Database]:
    """The Postgres databases of the answer that have a variable, with the upstream address from
    the value of the variable. Raise ValueError if a value is not a postgres URL."""
    return [
        _upstream(p, environ.get(p["env"]))
        for p in parts
        if p["kind"] in KINDS and p["env"] is not None
    ]


def _plain(query: str) -> str:
    """The query with sslmode=disable in place of each sslmode, or at the end. The other
    parameters keep their bytes."""
    parts = [q for q in query.split("&") if q and unquote_plus(q.partition("=")[0]) != "sslmode"]
    return "&".join([*parts, "sslmode=disable"])


def environment(proxies: list[Proxy], environ: Any) -> dict[str, str]:
    """The variable of each database: its URL with the address of the proxy and
    sslmode=disable, because the app speaks plain text to the proxy on 127.0.0.1. The user, the
    password, the database and the other query parameters stay."""
    out = {}
    for p in proxies:
        url = urlsplit(environ[p.database.env])
        user = url.netloc.rpartition("@")[0]
        netloc = (user + "@" if user else "") + f"127.0.0.1:{p.server_address[1]}"
        out[p.database.env] = urlunsplit(url._replace(netloc=netloc, query=_plain(url.query)))
    return out


# One setting in the options parameter: "-c name=value" or "--name=value". A backslash escapes
# a space in the value.
OPTION = re.compile(r"((?:-c\s*|--)([A-Za-z0-9_.-]+)=)((?:\\.|\S)*)")


def parameters_row(params: dict[str, str]) -> dict[str, str]:
    """The startup parameters with the secret values removed: a parameter with a secret name,
    and a setting with a secret name in the options parameter."""
    out = {}
    for k, v in params.items():
        if backend.secret(k):
            v = backend.REMOVED
        elif k == "options":
            v = OPTION.sub(lambda m: m[1] + backend.REMOVED if backend.secret(m[2]) else m[0], v)
        out[k] = v
    return out


def _cstrings(data: bytes) -> list[str]:
    return [s.decode("utf-8", "replace") for s in data.split(b"\0")]


def value(data: bytes | None, binary: bool = False) -> Any:
    """A value of a row or a parameter: its text, None for NULL, or base64 for binary bytes."""
    if data is None:
        return None
    if not binary:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return {"base64": base64.b64encode(data).decode()}


def _values(data: bytes, at: int, formats: list[int]) -> tuple[list[Any], int]:
    count = int.from_bytes(data[at : at + 2], "big")
    at += 2
    out = []
    for i in range(count):
        size = int.from_bytes(data[at : at + 4], "big", signed=True)
        at += 4
        raw = None if size < 0 else data[at : at + size]
        at += max(size, 0)
        fmt = formats[i] if len(formats) > 1 else (formats[0] if formats else 0)
        out.append(value(raw, fmt == 1))
    return out, at


def fields(direction: str, tag: bytes, data: bytes) -> dict[str, Any] | None:
    """The fields of one message that the record keeps, or None. The record never keeps the
    bytes of an authentication message of the app."""
    if len(data) > backend.RECORD_LIMIT:
        return None
    try:
        if direction == "to_server":
            if tag == b"Q":
                return {"query": _cstrings(data)[0]}
            if tag == b"P":
                name, query = _cstrings(data)[:2]
                return {"statement": name, "query": query}
            if tag == b"B":
                portal, statement = _cstrings(data)[:2]
                at = data.index(b"\0", data.index(b"\0") + 1) + 1
                n = int.from_bytes(data[at : at + 2], "big")
                formats = [
                    int.from_bytes(data[at + 2 + 2 * i : at + 4 + 2 * i], "big") for i in range(n)
                ]
                params, at = _values(data, at + 2 + 2 * n, formats)
                count = int.from_bytes(data[at : at + 2], "big")
                results = [
                    int.from_bytes(data[at + 2 + 2 * i : at + 4 + 2 * i], "big")
                    for i in range(count)
                ]
                return {
                    "portal": portal,
                    "statement": statement,
                    "parameters": params,
                    "results": results,
                }
            if tag == b"E":
                return {"portal": _cstrings(data)[0]}
            return None
        if tag == b"T":
            count = int.from_bytes(data[:2], "big")
            names, at = [], 2
            for _ in range(count):
                end = data.index(b"\0", at)
                names.append(data[at:end].decode("utf-8", "replace"))
                at = end + 1 + 18
            return {"columns": names}
        if tag == b"D":
            return {"values": _values(data, 0, [])[0]}
        if tag == b"C":
            return {"command": _cstrings(data)[0]}
        if tag in (b"E", b"N"):
            parts = {s[:1]: s[1:] for s in _cstrings(data) if s}
            keep = {"V": "severity", "C": "code", "M": "message", "D": "detail"}
            return {name: parts[k] for k, name in keep.items() if k in parts}
        if tag == b"Z":
            return {"status": data.decode("ascii", "replace")}
        if tag == b"R":
            return {"auth": int.from_bytes(data[:4], "big")}
    except (ValueError, IndexError):
        return None
    return None


class Messages:
    """The typed messages of one direction of a connection, from the bytes as they come: the tag,
    the body and the size of each message. A message with a body longer than RECORD_LIMIT has no
    body here, because the record keeps no fields of it. Thus a long row uses no memory."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        # The bytes of a long message that did not come yet.
        self.skip = 0

    def add(self, data: bytes) -> Iterator[tuple[bytes, bytes | None, int]]:
        if self.skip:
            n = min(self.skip, len(data))
            self.skip -= n
            data = data[n:]
        self.buffer += data
        while len(self.buffer) >= 5:
            tag, size = bytes(self.buffer[:1]), int.from_bytes(self.buffer[1:5], "big")
            if size - 4 > backend.RECORD_LIMIT:
                yield tag, None, size
                self.skip = max(1 + size - len(self.buffer), 0)
                del self.buffer[: 1 + size]
                continue
            if len(self.buffer) < 1 + size:
                return
            body = bytes(self.buffer[5 : 1 + size])
            del self.buffer[: 1 + size]
            yield tag, body, size


def _context(db: Database) -> ssl.SSLContext:
    """The TLS context of the sslmode. verify-ca checks the chain to a root certificate, and
    verify-full also checks the host name. require checks nothing, but with root certificates it
    checks the chain as verify-ca does. allow and prefer check nothing, as libpq does."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    verify = db.sslmode in ("verify-ca", "verify-full") or (
        db.sslmode == "require" and db.rootcert is not None
    )
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    context.check_hostname = db.sslmode == "verify-full"
    if db.rootcert == SYSTEM_ROOTS:
        context.load_default_certs()
    else:
        context.load_verify_locations(cafile=db.rootcert)
    return context


def _connect(db: Database) -> socket.socket:
    """A connection to the database, with the sslmode of the app. For disable, the connection is
    plain. For allow and prefer, the proxy asks for TLS, and the connection stays plain if the
    database declines. For require, verify-ca and verify-full, a decline or a failed check raises
    OSError: the connection never falls back to plain text."""
    up = socket.create_connection((db.host, db.port), timeout=TIMEOUT)
    if db.sslmode == "disable":
        return up
    try:
        up.sendall((8).to_bytes(4, "big") + SSL_REQUEST.to_bytes(4, "big"))
        answer = up.recv(1)
        if answer == b"N" and db.sslmode not in TLS_MODES:
            return up
        if answer == b"N":
            raise OSError(f"the database declined TLS, and sslmode={db.sslmode} needs it")
        if answer != b"S":
            raise OSError(f"the database gave {answer!r} to the TLS request")
        return _context(db).wrap_socket(up, server_hostname=db.host)
    except BaseException:
        up.close()
        raise


def _read(sock: socket.socket, size: int) -> bytes:
    out = b""
    while len(out) < size:
        data = sock.recv(size - len(out))
        if not data:
            return b""
        out += data
    return out


class Proxy(socketserver.ThreadingTCPServer):
    """One recording proxy for one Postgres database."""

    daemon_threads = True

    def __init__(self, database: Database, record: Path, lock: threading.Lock) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.database = database
        self.record = record
        self.lock = lock
        self.closed = False
        self.ids = itertools.count(1)
        self.sockets: set[socket.socket] = set()

    @property
    def url(self) -> str:
        return f"postgresql://127.0.0.1:{self.server_address[1]}"

    def row(self, connection: int, kind: str, **more: Any) -> None:
        row = {
            "v": VERSION,
            "type": kind,
            "database": self.database.name,
            "connection": connection,
            "ts": time.time(),
            **more,
        }
        with self.lock:
            if self.closed:
                return
            # The recording must never stop the copy.
            with contextlib.suppress(OSError), self.record.open("a", encoding="utf-8") as fh:
                fh.write(json_text(row) + "\n")

    def stop(self) -> None:
        """Stop the proxy after the entry stopped. Write no more rows, and close each open
        connection."""
        self.shutdown()
        with self.lock:
            self.closed = True
            for s in list(self.sockets):
                with contextlib.suppress(OSError):
                    s.shutdown(socket.SHUT_RDWR)
        self.server_close()


class Handler(socketserver.BaseRequestHandler):
    server: Proxy

    def handle(self) -> None:
        proxy, app = self.server, self.request
        n = next(proxy.ids)
        db = proxy.database
        try:
            up = _connect(db)
        except (OSError, ssl.SSLError) as e:
            proxy.row(n, "connect", parameters=None, declined=[], error=f"no connection: {e}")
            return
        up.settimeout(None)
        with proxy.lock:
            proxy.sockets.update((app, up))
        try:
            if self._startup(app, up, n):
                down = threading.Thread(
                    target=self._copy, args=(up, app, "from_server", n), daemon=True
                )
                down.start()
                self._copy(app, up, "to_server", n)
                down.join()
        finally:
            with proxy.lock:
                proxy.sockets.difference_update((app, up))
            up.close()

    def _startup(self, app: socket.socket, up: socket.socket, n: int) -> bool:
        """Read the startup packets of the app. Decline each TLS request, then send the startup
        packet to the database. Return False if the connection ends here."""
        declined: list[str] = []
        while True:
            head = _read(app, 4)
            size = int.from_bytes(head, "big") if head else 0
            if size < 8 or size > STARTUP_LIMIT:
                self.server.row(
                    n, "connect", parameters=None, declined=declined, error="no startup"
                )
                return False
            body = _read(app, size - 4)
            if not body:
                return False
            code = int.from_bytes(body[:4], "big")
            if code in (SSL_REQUEST, GSS_REQUEST):
                # The answer N: the server speaks no TLS here. The app then sends its startup.
                app.sendall(b"N")
                declined.append("ssl" if code == SSL_REQUEST else "gss")
                continue
            up.sendall(head + body)
            if code == CANCEL_REQUEST:
                self.server.row(n, "cancel")
                return False
            words = _cstrings(body[4:])
            params = dict(zip(words[0::2], words[1::2], strict=False))
            params.pop("", None)
            self.server.row(
                n, "connect", parameters=parameters_row(params), declined=declined, error=None
            )
            return True

    def _copy(self, src: socket.socket, dst: socket.socket, direction: str, n: int) -> None:
        """Record each message from src, then copy its bytes to dst. Stop at the end of src. A
        message is in the record before the other side can answer it, so a response row never
        comes before its request row."""
        messages = Messages()
        try:
            while data := src.recv(CHUNK):
                for tag, body, size in messages.add(data):
                    # A password or SASL message of the app: the record keeps its size only.
                    secret = direction == "to_server" and tag == b"p"
                    self.server.row(
                        n,
                        "message",
                        direction=direction,
                        tag=tag.decode("latin-1"),
                        size=size,
                        fields=None if secret or body is None else fields(direction, tag, body),
                    )
                dst.sendall(data)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                dst.shutdown(socket.SHUT_WR)

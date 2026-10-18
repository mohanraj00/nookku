"""The MCP proxies of a test (SPEC.md section 7.12): one recording proxy for each MCP server of
the egress answer that has a variable.

An HTTP server gets a recording proxy with the rules of a backend proxy (SPEC.md section 7.6). The
proxy sends each part of a stream to the app when it comes, because an MCP server can answer with
a stream of events. A stdio server gets a wrapper command in its variable. The wrapper starts the
real command, and copies each byte between the app and the server with no change. It writes each
line of each direction to mcp.jsonl. A part with no variable has no proxy, because nookku cannot
change how the app finds it.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from nookku import backend
from nookku.record import json_text

FILE = "mcp.jsonl"
VERSION = 1
# The bridge writes this file in the test folder at the end of the test. A wrapper writes no row
# after it exists, so that no row comes after the seal.
CLOSED = ".mcp-closed"
CHUNK = 65536
# The value of a stdio server in `proxies` of the egress of the manifest.
STDIO = "stdio"


class HttpProxy(backend.Proxy):
    """A recording proxy for one MCP server over HTTP. Its rows go to mcp.jsonl.

    The variable of the app gets the URL of the proxy with the path and the query of the MCP URL.
    The proxy sends each path of the app with no change, so the server gets its own endpoint.
    """

    streaming = True
    # An MCP server can send a stream with no end. The proxy keeps only the bytes that the record
    # shows (SPEC.md section 7.12).
    keep = backend.RECORD_LIMIT

    def __init__(self, server: backend.Backend, record: Path, lock: threading.Condition) -> None:
        super().__init__(server, record, lock)
        target = urlsplit(server.url)
        self.endpoint = target.path + ("?" + target.query if target.query else "")
        self.base_path = ""

    @property
    def url(self) -> str:
        return super().url + self.endpoint

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        row["server"] = row.pop("backend")
        row["transport"] = "http"


def http_servers(parts: list[dict[str, Any]]) -> list[backend.Backend]:
    """The HTTP servers of the answer that have a variable."""
    return [
        backend.Backend(p["name"], p["env"], p["url"])
        for p in parts
        if p["transport"] == "http" and p["env"] is not None
    ]


def stdio_environment(parts: list[dict[str, Any]], folder: Path) -> dict[str, str]:
    """The variable of each stdio server of the answer that has one: a shell command line that
    starts the wrapper with the real command."""
    out = {}
    for p in parts:
        if p["transport"] != "stdio" or p["env"] is None:
            continue
        argv = [sys.executable, "-m", "nookku", "mcp-stdio", "--folder", str(folder.resolve())]
        out[p["env"]] = shlex.join([*argv, "--name", p["name"], "--", *p["command"]])
    return out


def close(folder: Path) -> None:
    """Stop each wrapper of the test from writing rows."""
    (folder / CLOSED).write_text("", encoding="utf-8")


class Recorder:
    """The lines of one direction of a stdio server, as rows of mcp.jsonl.

    A line can be long, for example a tool result with an image. The recorder keeps only the
    bytes that the record shows, and counts the size and the SHA-256 of the line as they come.
    """

    def __init__(self, folder: Path, name: str, direction: str, lock: threading.Lock) -> None:
        self.folder = folder
        self.name = name
        self.direction = direction
        self.lock = lock
        self._new_line()

    def _new_line(self) -> None:
        self.size = 0
        self.digest = hashlib.sha256()
        self.kept = bytearray()

    def _take(self, data: bytes) -> None:
        self.size += len(data)
        self.digest.update(data)
        room = backend.RECORD_LIMIT - len(self.kept)
        if room > 0:
            self.kept += data[:room]

    def add(self, data: bytes) -> None:
        start = 0
        while (end := data.find(b"\n", start)) >= 0:
            self._take(data[start : end + 1])
            self._row()
            start = end + 1
        if start < len(data):
            self._take(data[start:])

    def finish(self) -> None:
        if self.size:
            self._row()

    def _body(self) -> dict[str, Any]:
        body = backend.body_row(bytes(self.kept))
        if self.size > len(self.kept):
            body.update(size=self.size, sha256=self.digest.hexdigest(), cut=True)
        return body

    def _row(self) -> None:
        body = self._body()
        self._new_line()
        row = {
            "v": VERSION,
            "type": "message",
            "server": self.name,
            "transport": "stdio",
            "ts": time.time(),
            "direction": self.direction,
            "body": body,
        }
        data = (json_text(row) + "\n").encode("utf-8")
        with self.lock:
            if (self.folder / CLOSED).exists():
                return
            # The recording must never stop the copy. One write with O_APPEND keeps the rows of
            # 2 wrappers apart.
            try:
                fd = os.open(self.folder / FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
            except OSError:
                pass


def _write_all(fd: int, data: bytes) -> None:
    while data:
        data = data[os.write(fd, data) :]


def _copy(src: int, dst: int | None, recorder: Recorder, after: Any = None) -> None:
    """Record each line from src, then copy its bytes to dst. Stop at the end of src. A line is
    in the record before the other side can answer it, so a response row never comes before
    its request row."""
    try:
        while True:
            data = os.read(src, CHUNK)
            if not data:
                break
            recorder.add(data)
            if dst is not None:
                try:
                    _write_all(dst, data)
                except OSError:
                    # The reader went away. The record still keeps each line.
                    dst = None
    except OSError:
        pass
    finally:
        recorder.finish()
        if after is not None:
            after()


def run_stdio(folder: Path, name: str, command: list[str]) -> int:
    """`nookku mcp-stdio`: start the real command of a stdio server, copy each byte between the
    app and the server, and record each line. Return the exit code of the server."""
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
    except OSError as e:
        print(f"nookku mcp-stdio: cannot start the MCP server {name}: {e}", file=sys.stderr)
        return 127
    assert proc.stdin is not None and proc.stdout is not None
    lock = threading.Lock()
    to_server = Recorder(folder, name, "to_server", lock)
    from_server = Recorder(folder, name, "from_server", lock)
    stdin = proc.stdin

    def close_stdin() -> None:
        with contextlib.suppress(OSError):
            stdin.close()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: proc.send_signal(signum))
    up = threading.Thread(
        target=_copy, args=(sys.stdin.fileno(), stdin.fileno(), to_server, close_stdin), daemon=True
    )
    up.start()
    _copy(proc.stdout.fileno(), sys.stdout.fileno(), from_server)
    code = proc.wait()
    # The app can still write after the server stopped. Its last line is in the record if it came.
    up.join(timeout=1.0)
    return code

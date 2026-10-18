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
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

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
    """A recording proxy for one MCP server over HTTP. Its rows go to mcp.jsonl."""

    streaming = True

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        row["server"] = row.pop("backend")
        row["transport"] = "http"


def http_servers(parts: list[dict[str, Any]]) -> list[backend.Backend]:
    """The HTTP servers of the answer that have a variable."""
    return [
        backend.Backend(p["name"], p["env"], p["url"].rstrip("/"))
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
    """The lines of one direction of a stdio server, as rows of mcp.jsonl."""

    def __init__(self, folder: Path, name: str, direction: str, lock: threading.Lock) -> None:
        self.folder = folder
        self.name = name
        self.direction = direction
        self.lock = lock
        self.part = b""

    def add(self, data: bytes) -> None:
        self.part += data
        while b"\n" in self.part:
            line, self.part = self.part.split(b"\n", 1)
            self._row(line + b"\n")

    def finish(self) -> None:
        if self.part:
            self._row(self.part)
            self.part = b""

    def _row(self, line: bytes) -> None:
        row = {
            "v": VERSION,
            "type": "message",
            "server": self.name,
            "transport": "stdio",
            "ts": time.time(),
            "direction": self.direction,
            "body": backend.body_row(line),
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
    """Copy each byte from src to dst, and record it. Stop at the end of src."""
    try:
        while True:
            data = os.read(src, CHUNK)
            if not data:
                break
            if dst is not None:
                try:
                    _write_all(dst, data)
                except OSError:
                    # The reader went away. The record still keeps each line.
                    dst = None
            recorder.add(data)
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

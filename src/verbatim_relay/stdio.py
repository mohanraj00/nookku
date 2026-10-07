"""The tap in stdio mode (SPEC.md section 4.2): it starts the agent and talks the agent contract."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import signal
import socketserver
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

from verbatim_relay import contract
from verbatim_relay.record import Writer, lone_surrogate

# The hook kit's UserPromptSubmit deadline is 300 s. The tap must answer well before it.
TIMEOUT = 240.0
TAIL = 20
# The fix for an agent that writes logs on stdout. `verbatim-relay check` prints it too.
STRAY_HINT = "Use verbatim_relay.agent.serve() or write logs to stderr."


class Agent:
    """The agent process. One request at a time, one line in and one line out."""

    def __init__(
        self,
        argv: Sequence[str],
        cwd: Path,
        log: Path,
        timeout: float = TIMEOUT,
        env: dict[str, str] | None = None,
    ):
        self.argv, self.cwd, self.log, self.timeout = list(argv), cwd, log, timeout
        # Variables that the bridge adds to the environment of the agent, for example OTLP.
        self.env = env or {}
        self.failed: str | None = None
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        with self.log.open("ab") as err:
            self.proc = subprocess.Popen(
                self.argv,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=err,
                start_new_session=True,
                env={**os.environ, **self.env} if self.env else None,
            )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in iter(self.proc.stdout.readline, b""):
            self._lines.put(line.removesuffix(b"\n").removesuffix(b"\r"))
        self._lines.put(None)

    def _exited(self) -> str:
        assert self.proc is not None
        try:
            code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.kill()
            code = self.proc.wait()
        self.failed = f"the agent exited (code {code})"
        return self.failed

    def stray(self) -> list[bytes]:
        """The lines that wait on stdout with no request. Call it before each request."""
        out: list[bytes] = []
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return out
            if line is None:
                self._exited()
                return out
            out.append(line)

    def ask(self, line: bytes, rid: str, stray: Callable[[bytes], None]) -> tuple[str, bytes | str]:
        """Send one input line. Return ("line", output) or ("exited" | "timeout", reason).

        The output is the first line for the request id `rid`. Each other line is a stray line,
        and `stray` gets it. The timeout is one deadline for the full request.
        """
        if self.failed:
            return "exited", self.failed
        assert self.proc is not None and self.proc.stdin is not None
        try:
            self.proc.stdin.write(line + b"\n")
            self.proc.stdin.flush()
        except OSError:
            return "exited", self._exited()
        deadline = time.monotonic() + self.timeout
        strays: list[bytes] = []
        while True:
            try:
                out = self._lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                self.kill()
                self.failed = _no_reply(rid, self.timeout, strays)
                return "timeout", self.failed
            if out is None:
                return "exited", self._exited()
            if _is_for(out, rid):
                return "line", out
            strays.append(out)
            stray(out)

    def tail(self) -> str:
        try:
            lines = self.log.read_bytes().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-TAIL:])

    def kill(self, sig: int = signal.SIGKILL) -> None:
        if self.proc is not None and self.proc.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(self.proc.pid, sig)

    def stop(self, grace: float = 5.0) -> None:
        """Close stdin, then SIGTERM the process group, then SIGKILL it."""
        if self.proc is None:
            return
        if self.proc.stdin is not None:
            with contextlib.suppress(OSError):
                self.proc.stdin.close()
        for sig in (None, signal.SIGTERM, signal.SIGKILL):
            if sig is not None:
                self.kill(sig)
            try:
                self.proc.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        # The children of the agent are in its group. Stop the ones that are still alive.
        self.kill(signal.SIGKILL)


def _no_reply(rid: str, timeout: float, strays: list[bytes]) -> str:
    """The error text of a timeout. If the agent printed stray lines, it names them and the fix."""
    if not strays:
        return f"the agent sent no reply in {timeout:g} s, so the tap stopped it"
    count = f"{len(strays)} line" + ("" if len(strays) == 1 else "s")
    first = strays[0][:80].decode("utf-8", errors="replace")
    return (
        f"the agent printed {count} on stdout but no reply line for {rid} in {timeout:g} s, "
        f"so the tap stopped it. {STRAY_HINT} The first line: {first!r}"
    )


def _is_for(line: bytes, rid: str) -> bool:
    """True if the line is a JSON object with the id `rid`. Only such a line can be the reply."""
    try:
        data = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(data, dict) and data.get("id") == rid


class StdioTap(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, listen: tuple[str, int], agent: Agent, record: Path) -> None:
        self.agent, self.writer = agent, Writer(record)
        self.lock = threading.Lock()
        super().__init__(listen, _Handler)

    def server_bind(self) -> None:
        bind(self)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        host = host.decode() if isinstance(host, bytes) else host
        return f"http://{host}:{port}/"


class _Handler(BaseHTTPRequestHandler):
    server: StdioTap
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes) -> None:
        self.send_response_only(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send(status, json.dumps({"error": message}, ensure_ascii=False).encode())

    def _unparsed(self, method: str, path: str, error: str) -> None:
        self.server.writer.append(
            {"type": "unparsed", "method": method, "path": path, "error": error}
        )

    def _stray(self, line: bytes) -> None:
        excerpt = line[:80].decode("utf-8", errors="replace")
        self._unparsed("STDIO", "stdout", f"a stray line on stdout: {excerpt!r}")

    def do_POST(self) -> None:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self._error(411, "verbatim-relay needs a Content-Length request body")
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        tap, path = self.server, self.path
        try:
            rid, message, _ = contract.parse_request(body)
        except contract.ContractError as e:
            self._unparsed("POST", path, f"request: {e}")
            self._error(400, f"verbatim-relay tap: {e}")
            return
        found = lone_surrogate(message)
        if found:
            # The record cannot hold the message, so the agent does not get it.
            self._unparsed("POST", path, f"request: the message has {found}")
            self._error(400, f"verbatim-relay tap: the message has {found}")
            return
        with tap.lock:
            for line in tap.agent.stray():
                self._stray(line)
            started = time.time()
            kind, out = tap.agent.ask(body, rid, self._stray)
            row = {"type": "exchange", "input": message, "started": started}
            if isinstance(out, str):
                tap.writer.append({**row, "status": None, "reply": None, "error": out})
                tail = tap.agent.tail()
                detail = f"{out}\nThe last lines of app.log:\n{tail}" if tail else out
                self._error(504 if kind == "timeout" else 502, f"verbatim-relay tap: {detail}")
                return
            try:
                reply, error = contract.parse_reply(out, rid)
            except contract.ContractError as e:
                self._unparsed("POST", path, f"reply: {e}")
                self._error(502, f"verbatim-relay tap: {e}")
                return
            # parse_reply gives exactly one string: the reply or the error.
            what, text = ("error", error) if error is not None else ("reply", reply or "")
            found = lone_surrogate(text)
            if found:
                note = f"the agent {what} has {found}"
                tap.writer.append({**row, "status": None, "reply": None, "error": note})
                self._error(502, f"verbatim-relay tap: {note}")
                return
            if error is None:
                tap.writer.append({**row, "status": 200, "reply": reply})
                self._send(200, out)
            else:
                tap.writer.append({**row, "status": 500, "reply": None, "error": error})
                self._send(500, out)

    def _refuse(self) -> None:
        self._error(405, "verbatim-relay tap: send each message as a POST")

    do_GET = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _refuse


def bind(server: HTTPServer) -> None:
    """Bind an HTTP server with no host name lookup.

    HTTPServer.server_bind() calls socket.getfqdn(), a DNS lookup that can block for many seconds
    on some hosts. The tap and the receiver need no host name.
    """
    socketserver.TCPServer.server_bind(server)
    host, port = server.server_address[:2]
    server.server_name = host.decode() if isinstance(host, bytes) else str(host)
    server.server_port = port


def start_in_thread(tap: socketserver.BaseServer) -> threading.Thread:
    thread = threading.Thread(target=tap.serve_forever, daemon=True)
    thread.start()
    return thread


def serve(tap: StdioTap) -> None:
    print(f"verbatim-relay tap: listening on {tap.url} -> {tap.agent.argv}", file=sys.stderr)
    print(f"verbatim-relay tap: writing {tap.writer.path}", file=sys.stderr)
    tap.agent.start()
    try:
        tap.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tap.server_close()
        tap.agent.stop()

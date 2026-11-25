"""The tap in stdio mode (SPEC.md section 4.2): it starts the agent and talks the agent contract."""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import queue
import secrets
import signal
import socketserver
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

from nookku import contract
from nookku.record import Writer, lone_surrogate
from nookku.state import DURING_HEADER, TOKEN_HEADER

# The agent timeout of both taps, HTTP and stdio. Each tap answers well before the relay
# timeouts (kit.TIMEOUT, state.TIMEOUT), and these end before kit.HOOK_DEADLINE.
TIMEOUT = 240.0
TAIL = 20
# The fix for an agent that writes logs on stdout. `nookku check` prints it too.
STRAY_HINT = "Use nookku.agent.serve() or write logs to stderr."
# The seconds that a second message waits for the agent to get the message before it (SPEC.md
# section 4.2). This is a chosen value. Each wait ends when that message is at the agent.
DURING_WAIT = 10.0
# The variable that gives `nookku tap --cmd` its token. With no value, the tap makes one.
TOKEN_ENV = "NOOKKU_TAP_TOKEN"
# The length of a token that the tap makes. A token from TOKEN_ENV must not be shorter.
TOKEN_MIN = 43


class Agent:
    """The agent process. One line in and one line out for each request. The tap reads the
    reply of one request at a time. It can write the line of a second request during the turn
    of the first one (SPEC.md section 4.2)."""

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
        # The requests whose line the tap wrote during the turn of another request: the request
        # id, and the reply line with its time, or None before the line comes.
        self._early: dict[str, tuple[bytes, float] | None] = {}
        # The state of the turns. `_got`: the ids of the requests whose line the agent got.
        # `_waiting`: the ids of those with no reply line yet. The condition guards all 3.
        self._got: set[str] = set()
        self._waiting: set[str] = set()
        self._turn = threading.Condition()
        self._stdin_lock = threading.Lock()
        self.proc: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None

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
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

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

    def _write(self, line: bytes) -> bool:
        """Write one input line. Return False if the agent does not take it."""
        assert self.proc is not None and self.proc.stdin is not None
        try:
            with self._stdin_lock:
                self.proc.stdin.write(line + b"\n")
                self.proc.stdin.flush()
        except (OSError, ValueError):
            return False
        return True

    def send_during(
        self, line: bytes, rid: str, before: str, wait: float | None = None
    ) -> float | None:
        """Write the input line of request `rid` now, during the turn of request `before`.
        Return the Unix time of the write, or None if the tap must not write the line now.

        First wait until the agent got the line of `before`, for `wait` seconds at most (None
        means DURING_WAIT). Write the line only if the reply line of `before` did not come. The
        check and the write are in one step with the read of a reply line, so the agent gets the
        line before the tap has that reply line. The reader of that turn keeps the reply line
        for `rid`, so it is not a stray line. Then ask(..., sent=<time>) gives the reply when
        the turn of this request comes."""
        with self._turn:
            limit = DURING_WAIT if wait is None else wait
            self._turn.wait_for(lambda: before in self._got, timeout=limit)
            if self.failed or before not in self._waiting:
                return None
            sent = time.time()
            self._early[rid] = None
            self._got.add(rid)
            self._waiting.add(rid)
            self._write(line)
            self._turn.notify_all()
            return sent

    def early_reply(self, rid: str) -> tuple[bytes, float] | None:
        """The reply line of a request of send_during and the time when it came, or None if it
        did not come yet. The request then waits for its line as each other request."""
        with self._turn:
            return self._early.pop(rid, None)

    def _keep(self, line: bytes) -> bool:
        """True if the line is the reply line of a request of send_during. The agent keeps the
        first such line of each request, with its time."""
        with self._turn:
            for rid, got in self._early.items():
                if got is None and _is_for(line, rid):
                    self._early[rid] = (line, time.time())
                    self._waiting.discard(rid)
                    return True
        return False

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
            if not self._keep(line):
                out.append(line)

    def rest(self, wait: float = 1.0) -> list[bytes]:
        """The lines that the agent wrote after its last reply. Call it after stop()."""
        if self._reader is not None:
            self._reader.join(timeout=wait)
        out: list[bytes] = []
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return out
            if line is not None:
                out.append(line)

    def ask(
        self, line: bytes, rid: str, stray: Callable[[bytes], None], sent: float | None = None
    ) -> tuple[str, bytes | str]:
        """Send one input line. Return ("line", output) or ("exited" | "timeout", reason).

        The output is the first line for the request id `rid`. A line for a request of
        send_during stays for that request. Each other line is a stray line, and `stray` gets it.
        The timeout is one deadline for the full request. With `sent`, send_during wrote the
        line at that Unix time, and the deadline counts from it.
        """
        if self.failed:
            return "exited", self.failed
        if sent is None:
            with self._turn:
                # A second message for this request waits until the agent got this line.
                written = self._write(line)
                self._got.add(rid)
                if written:
                    self._waiting.add(rid)
                self._turn.notify_all()
            if not written:
                return "exited", self._exited()
            deadline = time.monotonic() + self.timeout
        else:
            deadline = time.monotonic() + self.timeout - max(0.0, time.time() - sent)
        strays: list[bytes] = []
        while True:
            left = deadline - time.monotonic()
            try:
                # An agent that writes stray lines all the time still gets the timeout.
                if left <= 0:
                    raise queue.Empty
                out = self._lines.get(timeout=left)
            except queue.Empty:
                self.kill()
                self.failed = _no_reply(rid, self.timeout, strays)
                return "timeout", self.failed
            if out is None:
                return "exited", self._exited()
            if _is_for(out, rid):
                with self._turn:
                    # The turn ends: a second message for this request now waits for its turn.
                    self._waiting.discard(rid)
                return "line", out
            if self._keep(out):
                continue
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


def stray_row(line: bytes) -> dict[str, str]:
    """The unparsed row of a stray line on stdout (SPEC.md section 4.2)."""
    excerpt = line[:80].decode("utf-8", errors="replace")
    return {
        "type": "unparsed",
        "method": "STDIO",
        "path": "stdout",
        "error": f"a stray line on stdout: {excerpt!r}",
    }


def write_failed(path: Path, e: OSError) -> str:
    """Write the record path and the OS error to stderr. Return the error text for the caller.

    A caller can be on another computer (--listen), so the text gives only the file name of the
    record (SPEC.md sections 4.1 and 4.2). A name with a byte that is not UTF-8 has a surrogate
    escape, and UTF-8 cannot encode it. The text gives such a byte as a backslash escape."""
    print(f"nookku tap: cannot write the record {path}: {e}", file=sys.stderr)
    name = path.name.encode("utf-8", "backslashreplace").decode("utf-8")
    return (
        f"nookku tap: cannot write the record {name}. The error output of the tap gives the cause."
    )


def new_token() -> str:
    """A random tap token: 32 random bytes as URL-safe text."""
    return secrets.token_urlsafe(32)


class StdioTap(ThreadingHTTPServer):
    """The stdio tap. It accepts a POST only with its token (SPEC.md section 4.2).

    With no `token`, the tap makes a random one. The bridge writes `token` to current.json, and
    a server in the same process can read it here."""

    daemon_threads = True

    def __init__(
        self, listen: tuple[str, int], agent: Agent, record: Path, token: str | None = None
    ) -> None:
        self.agent, self.writer = agent, Writer(record)
        # True if the tap made the token. Only then does serve() write it to stderr.
        self.made_token = not token
        self.token = token or new_token()
        self.lock = threading.Lock()
        super().__init__(listen, _Handler)

    def server_bind(self) -> None:
        bind(self)

    def record_rest(self) -> None:
        """Write a stray row for each line that the agent wrote after its last reply.

        No caller waits for these rows. If a write fails, write the error to stderr and stop, so
        that the end of the test continues (SPEC.md section 4.2)."""
        for line in self.agent.rest():
            try:
                self.writer.append(stray_row(line))
            except OSError as e:
                write_failed(self.writer.path, e)
                return

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        host = host.decode() if isinstance(host, bytes) else host
        return f"http://{host}:{port}/"


class _Handler(BaseHTTPRequestHandler):
    server: StdioTap
    protocol_version = "HTTP/1.1"
    # The first error of a stray row in the current request (_stray).
    lost: OSError | None = None

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

    def _write(self, row: dict[str, object]) -> bool:
        """Write one row. If the write fails, answer 502 with a message that names the record,
        and return False. The caller then sends no other response (SPEC.md section 4.2)."""
        try:
            self.server.writer.append(row)
        except OSError as e:
            self._error(502, write_failed(self.server.writer.path, e))
            return False
        return True

    def _unparsed(self, method: str, path: str, error: str) -> bool:
        return self._write({"type": "unparsed", "method": method, "path": path, "error": error})

    def _stray(self, line: bytes) -> None:
        """Write the row of a stray line. Agent.ask() calls it in a request, so it does not
        answer the caller. It keeps the first write error in self.lost, and then writes no row."""
        if self.lost is not None:
            return
        try:
            self.server.writer.append(stray_row(line))
        except OSError as e:
            self.lost = e

    def _refusal(self) -> str | None:
        """The reason to refuse a request that is not from a relay, or None (SPEC.md 4.2).

        A web page in a browser can send a "simple" POST to a local port. Such a request has an
        Origin header or a Content-Type that is not application/json, and it has no token."""
        if self.headers.get("Origin") is not None:
            return "the tap does not accept a request with an Origin header"
        kind = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if kind != "application/json":
            return "the Content-Type of a request must be application/json"
        given = self.headers.get_all(TOKEN_HEADER) or []
        if not given:
            return f"the request has no {TOKEN_HEADER} header"
        token = self.server.token.encode()
        # Header values are latin-1 text, so each value encodes back to its bytes.
        if len(given) != 1 or not hmac.compare_digest(given[0].encode("latin-1"), token):
            return f"the {TOKEN_HEADER} header is wrong"
        return None

    def _discard(self) -> None:
        """Read and drop the body of a refused request, then close the connection."""
        self.close_connection = True
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            return
        try:
            left = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        while left > 0:
            part = self.rfile.read(min(left, 65536))
            if not part:
                return
            left -= len(part)

    def do_POST(self) -> None:
        refusal = self._refusal()
        if refusal is not None:
            # No row and no line to the agent: the request is not from a relay.
            self._discard()
            self._error(403, f"nookku tap: {refusal}")
            return
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self._error(411, "nookku needs a Content-Length request body")
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        tap, path = self.server, self.path
        try:
            rid, message, _ = contract.parse_request(body)
        except contract.ContractError as e:
            if self._unparsed("POST", path, f"request: {e}"):
                self._error(400, f"nookku tap: {e}")
            return
        found = lone_surrogate(message)
        if found:
            # The record cannot hold the message, so the agent does not get it.
            if self._unparsed("POST", path, f"request: the message has {found}"):
                self._error(400, f"nookku tap: the message has {found}")
            return
        early: float | None = None
        before = self.headers.get(DURING_HEADER)
        if before is not None:
            # A second message: the agent gets it now, during the turn of the message `before`.
            # Its row comes after the row of that message (SPEC.md section 4.2).
            early = tap.agent.send_during(body, rid, before)
        with tap.lock:
            self.lost = None
            replied: float | None = None
            if early is None:
                for line in tap.agent.stray():
                    self._stray(line)
                if self.lost is not None:
                    # The record is not complete, so the agent does not get the message.
                    self._error(502, write_failed(tap.writer.path, self.lost))
                    return
                started = time.time()
                kind, out = tap.agent.ask(body, rid, self._stray)
            else:
                started = early
                got = tap.agent.early_reply(rid)
                if got is not None:
                    # The reply came during the turn of the message before it.
                    kind, out, replied = "line", got[0], got[1]
                else:
                    kind, out = tap.agent.ask(body, rid, self._stray, sent=early)
            if self.lost is not None:
                # The agent got the message, but the caller does not get the reply.
                self._error(502, write_failed(tap.writer.path, self.lost))
                return
            row: dict[str, object] = {"type": "exchange", "input": message, "started": started}
            if replied is not None:
                row["replied"] = replied
            if isinstance(out, str):
                if not self._write({**row, "status": None, "reply": None, "error": out}):
                    return
                tail = tap.agent.tail()
                detail = f"{out}\nThe last lines of app.log:\n{tail}" if tail else out
                self._error(504 if kind == "timeout" else 502, f"nookku tap: {detail}")
                return
            try:
                reply, error = contract.parse_reply(out, rid)
            except contract.ContractError as e:
                if self._unparsed("POST", path, f"reply: {e}"):
                    self._error(502, f"nookku tap: {e}")
                return
            # parse_reply gives exactly one string: the reply or the error.
            what, text = ("error", error) if error is not None else ("reply", reply or "")
            found = lone_surrogate(text)
            if found:
                note = f"the agent {what} has {found}"
                if self._write({**row, "status": None, "reply": None, "error": note}):
                    self._error(502, f"nookku tap: {note}")
                return
            if error is None:
                if self._write({**row, "status": 200, "reply": reply}):
                    self._send(200, out)
            elif self._write({**row, "status": 500, "reply": None, "error": error}):
                self._send(500, out)

    def _refuse(self) -> None:
        self._error(405, "nookku tap: send each message as a POST")

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
    print(f"nookku tap: listening on {tap.url} -> {tap.agent.argv}", file=sys.stderr)
    if tap.made_token:
        print(f"nookku tap: send the header {TOKEN_HEADER}: {tap.token}", file=sys.stderr)
    print(f"nookku tap: writing {tap.writer.path}", file=sys.stderr)
    tap.agent.start()
    try:
        tap.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tap.server_close()
        tap.agent.stop()

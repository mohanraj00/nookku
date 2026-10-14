"""The chat page: a local web page where the tester talks to the agent of a running test (#327).

The page server sends each message with the relay function of the hook (`state.send`), and writes
a `turn` row with the harness `pane` (SPEC.md section 5, "Chat page"). The message never enters the
harness, so the harness model cannot see it. The browser cannot post to the tap itself: it sends
`Origin`, and the tap refuses a request with `Origin` (SPEC.md section 4.2). Thus the page server
sends for the page.

Security: the server listens only on 127.0.0.1. Each URL holds a random token, and only the person
gets the URL: `nookku page` prints it to its terminal. The page file holds only the port and the
pid. Each request must have a correct `Host`, and a correct `Origin` if it has one. A `POST` must
have `Origin`. Each answer has a strict Content Security Policy, and the page loads only its own
files.
"""

from __future__ import annotations

import errno
import hmac
import json
import os
import secrets
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from nookku import kit, notes, script_save, seal, state
from nookku.record import RecordError, Writer, turns

# The harness of a turn that the page sent (SPEC.md section 2.2).
HARNESS = "pane"
HOST = "127.0.0.1"
# The files of the page, in src/nookku/page/, and their media types.
FILES = {
    "": ("index.html", "text/html; charset=utf-8"),
    "app.js": ("app.js", "text/javascript; charset=utf-8"),
    "app.css": ("app.css", "text/css; charset=utf-8"),
    "notes.js": ("notes.js", "text/javascript; charset=utf-8"),
    "notes.css": ("notes.css", "text/css; charset=utf-8"),
    "save.js": ("save.js", "text/javascript; charset=utf-8"),
}
# The page loads only its own files. No inline script, no inline style, no other site.
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # The URL holds the page token, so the browser must not send it to another site.
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# A tester message is text. 1 MiB is much more than a chat message.
MAX_BODY = 1 << 20
# The wait for each read or write on a connection of the browser. The page answers each request
# at once, except a send, and a send does not use the connection while it waits for the tap.
SOCKET_TIMEOUT = 30
CONTROL_REASON = (
    "nookku: the page does not run control prompts. Type {said} in the harness. Nothing was sent."
)
NO_TEST = "nookku: no test runs. Start one in the harness with: nookku start. Nothing was sent."
RELAY_OFF = (
    "nookku: relay mode is off, so the page sends nothing. The test ends, or a person switched "
    "relay mode off. Nothing was sent."
)
NO_MANIFEST = (
    "nookku: the page cannot read manifest.json of the test, so it sends nothing. Nothing was sent."
)
SCRIPTED = "nookku: this test is a scripted test, so the page sends nothing. Nothing was sent."
ENDED = (
    "nookku: the test ended during the send, so the page wrote no turn. The record of the test "
    "is sealed and does not change. Reply or error: {shown}"
)


def page_file(name: str) -> bytes:
    return resources.files("nookku").joinpath("page").joinpath(name).read_bytes()


def _manifest(folder: Path) -> dict[str, Any] | None:
    """The manifest of a test folder, or None if it is missing or not a JSON object."""
    try:
        data = json.loads((folder / "manifest.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _closed(folder: Path) -> bool:
    """True if the test ended, or its end wrote the audit or the seal. Then the record must not
    change."""
    if (folder / "audit.json").exists() or (folder / seal.SEAL).exists():
        return True
    manifest = _manifest(folder)
    return manifest is None or manifest.get("ended") is not None


def refusal(root: Path, said: str) -> str | None:
    """The reason to refuse a message before the page sends it, or None. The rules of the
    prompt are the rules of the hook (`kit.prompt_refusal`). An exact control prompt runs only
    in the harness. The page writes no turn for a refused message."""
    if said.strip() in kit.CONTROL:
        return CONTROL_REASON.format(said=said.strip())
    return kit.prompt_refusal(said, root)


def send(root: Path, said: str) -> dict[str, Any]:
    """Send one message to the running test, and write its turn. Return what the page shows.

    Fail closed: the page sends only to a running test that is not a scripted test, in relay
    mode. If the page cannot send the message, it shows the error, and the turn has the error as
    `shown` with `ok: false`. If the test ended during the send, the page writes no turn. The
    message never goes to a model."""
    reason = refusal(root, said)
    if reason is not None:
        return {"sent": False, "shown": reason, "ok": False}
    if state.current(root) is None:
        return {"sent": False, "shown": NO_TEST, "ok": False}
    # The end of the test takes this lock before it stops the tap, and keeps it until the seal.
    # Thus the end waits for this send, and a later send sees the closed test.
    sends = state.lock_sends(root)
    try:
        return _send_locked(root, said)
    finally:
        os.close(sends)


def _send_locked(root: Path, said: str) -> dict[str, Any]:
    cur = state.current(root)
    if cur is None:
        return {"sent": False, "shown": NO_TEST, "ok": False}
    folder = Path(cur["dir"])
    manifest = _manifest(folder)
    if manifest is None:
        return {"sent": False, "shown": NO_MANIFEST, "ok": False}
    # `nookku end` switches relay mode off before it stops the test.
    if not kit.is_on(root) or _closed(folder):
        return {"sent": False, "shown": RELAY_OFF, "ok": False}
    if manifest.get("script") is not None:
        return {"sent": False, "shown": SCRIPTED, "ok": False}
    shown, ok = kit.checked(*state.send(cur, said))
    if _closed(folder):
        return {"sent": False, "shown": ENDED.format(shown=shown), "ok": False}
    row = {"type": "turn", "harness": HARNESS, "said": said, "shown": shown, "ok": ok}
    Writer(folder / "relay.jsonl").append(row)
    return {"sent": True, "shown": shown, "ok": ok}


def view(root: Path) -> dict[str, Any]:
    """The test and its turns, for the page: the running test, else the latest test."""
    cur = state.current(root)
    folder = Path(cur["dir"]) if cur else state.latest_test(root)
    if folder is None:
        return {"test": None, "turns": [], "error": None}
    manifest = _manifest(folder) or {}
    test = {
        "id": folder.name,
        "running": cur is not None,
        "started": manifest.get("started"),
        "ended": manifest.get("ended"),
    }
    try:
        found = turns(folder / "relay.jsonl", missing_ok=True)
    except RecordError as e:
        return {"test": test, "turns": [], "error": f"nookku: {e}"}
    rows = [{"said": t.said, "shown": t.shown, "ok": t.ok, "harness": t.harness} for t in found]
    return {"test": test, "turns": rows, "error": None}


class PageServer(ThreadingHTTPServer):
    """The page server of one project. It listens only on 127.0.0.1."""

    daemon_threads = True

    def __init__(self, root: Path, port: int = 0, token: str | None = None) -> None:
        super().__init__((HOST, port), _Handler)
        self.root = root
        self.token = token or secrets.token_urlsafe(32)
        # One message at a time, so that each message gets the history of the turns before it.
        self.lock = threading.Lock()
        port = self.server_address[1]
        self.hosts = {f"{HOST}:{port}", f"localhost:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.server_address[1]}/p/{self.token}/"


# The value of _Handler._body after a refusal. JSON gives no value that is this object.
_REFUSED = object()


class _Handler(BaseHTTPRequestHandler):
    server: PageServer
    server_version = "nookku-page"
    sys_version = ""
    # The answers of the page are small, and a keep-alive connection is not necessary.
    protocol_version = "HTTP/1.0"
    timeout = SOCKET_TIMEOUT

    def log_message(self, format: str, *args: Any) -> None:
        # The default log writes each path, and each path holds the page token.
        pass

    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        if self.request_version == "HTTP/0.9":
            # An HTTP/0.9 answer has no headers, so it cannot have the CSP.
            self.close_connection = True
            return False
        return True

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # http.server writes no headers for a request of the version HTTP/0.9, and the version
        # stays HTTP/0.9 if the request line is not valid. Then the error must still have the CSP.
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.0"
        super().send_error(code, message, explain)

    def end_headers(self) -> None:
        # Each answer has the security headers, also an error that http.server makes itself.
        for name, value in HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def _answer(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self._answer(status, body, "application/json; charset=utf-8")

    def _refuse(self, status: int, reason: str) -> None:
        self._json(status, {"error": f"nookku page: {reason}"})

    def _route(self) -> str | None:
        """The part of the path after the token, or None after a refusal. Check the Host, the
        Origin and the token of each request."""
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].lower() not in self.server.hosts:
            self._refuse(403, "wrong Host header")
            return None
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1 or (origins and origins[0].lower() not in self.server.origins):
            self._refuse(403, "wrong Origin header")
            return None
        if self.command == "POST" and not origins:
            self._refuse(403, "a POST needs the Origin header")
            return None
        parts = urlsplit(self.path)
        if parts.query or not parts.path.startswith("/p/"):
            self._refuse(404, "not found")
            return None
        token, sep, rest = parts.path[len("/p/") :].partition("/")
        if not hmac.compare_digest(token.encode(), self.server.token.encode()) or not sep:
            self._refuse(404, "not found")
            return None
        return rest

    def _other(self) -> None:
        self._refuse(405, "the page takes only GET and POST")

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_CONNECT = do_TRACE = _other

    def do_GET(self) -> None:
        rest = self._route()
        if rest is None:
            return
        if rest in FILES:
            name, kind = FILES[rest]
            self._answer(200, page_file(name), kind)
        elif rest == "api/turns":
            self._json(200, view(self.server.root))
        elif rest == notes.VIEW_ROUTE:
            self._json(200, notes.view(self.server.root))
        else:
            self._refuse(404, "not found")

    def _body(self) -> Any:
        """The JSON body of a POST, or _REFUSED after a refusal."""
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind != "application/json":
            self._refuse(415, "the Content-Type must be application/json")
            return _REFUSED
        try:
            size = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._refuse(411, "the request needs a Content-Length")
            return _REFUSED
        if size < 0 or size > MAX_BODY:
            self._refuse(413, "the message is too large")
            return _REFUSED
        try:
            return json.loads(self.rfile.read(size))
        except (ValueError, RecursionError):
            self._refuse(400, "the body is not JSON")
            return _REFUSED

    def do_POST(self) -> None:
        rest = self._route()
        if rest is None:
            return
        if rest not in ("api/send", script_save.ROUTE, notes.ADD_ROUTE):
            self._refuse(404, "not found")
            return
        data = self._body()
        if data is _REFUSED:
            return
        if rest == script_save.ROUTE:
            self._json(*script_save.answer(self.server.root, data))
            return
        if rest == notes.ADD_ROUTE:
            self._note(data)
            return
        said = data.get("said") if isinstance(data, dict) else None
        if not isinstance(said, str):
            self._refuse(400, 'the body needs the text "said"')
            return
        with self.server.lock:
            try:
                answer = send(self.server.root, said)
            except Exception as e:  # each failure must give the page an error, not a reset
                self._json(500, {"sent": False, "ok": False, "shown": f"nookku: {e}"})
                return
        self._json(200, answer)

    def _note(self, data: Any) -> None:
        """Write one note of the tester (SPEC.md section 2.3)."""
        problem = notes.bad_body(data)
        if problem:
            self._refuse(400, problem)
            return
        # No page lock: a note takes the send lock (notes.add), so it cannot go into a sealed test.
        try:
            answer = notes.add(
                self.server.root,
                data["test"],
                data["turn"],
                data.get("rating"),
                data.get("comment"),
            )
        except Exception as e:  # each failure must give the page an error, not a reset
            self._json(500, {"saved": False, "error": f"nookku: {e}"})
            return
        self._json(200, answer)


class PageRunning(Exception):
    """Another page server of the project runs."""


def claim_page_file(root: Path, port: int) -> tuple[Path, int]:
    """Write the page file: the port and the pid of this server, with no token (SPEC.md section
    5). Return its path and the descriptor of the page lock. The server holds the lock for its
    whole life, so a second server cannot take it. Raise PageRunning if another server holds it.
    A page file with no holder of the lock is stale, and this server takes it over."""
    import fcntl

    folder = state.state(root)
    folder.mkdir(parents=True, exist_ok=True)
    lock = os.open(folder / state.PAGE_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock)
        info = state.page_info(root)
        pid = f" (pid {info.get('pid')})" if info else ""
        raise PageRunning(f"a page server of this project runs{pid}") from None
    path = folder / state.PAGE_FILE
    try:
        new = folder / f".{state.PAGE_FILE}.{os.getpid()}"
        fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"port": port, "pid": os.getpid()}) + "\n")
        os.replace(new, path)
    except BaseException:
        os.close(lock)
        raise
    return path, lock


HARNESS_SHELL = ("CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")
IN_HARNESS = (
    "nookku: nookku page runs in a shell of a coding harness ({name} is set). The harness can "
    "show the output to the model, and the page URL gives the model the right to send as you. "
    "Run nookku page in a separate terminal, not with ! in the harness. Nothing was started."
)


def serve(root: Path, port: int = 0, out: TextIO | None = None) -> int:
    """Run the page server until it gets a signal. Print the page URL only to this terminal.
    Never print the tap token."""
    out = out or sys.stdout
    # The URL must never go into a text that the model sees (SPEC.md section 5, "The page URL").
    shell = next((name for name in HARNESS_SHELL if os.environ.get(name)), None)
    if shell is not None:
        print(IN_HARNESS.format(name=shell), file=sys.stderr)
        return 1
    if not 0 <= port <= 65535:
        print(f"nookku: the port {port} is not valid. Use 0 to 65535.", file=sys.stderr)
        return 1
    try:
        server = PageServer(root, port)
    except OSError as e:
        reason = "the port is in use" if e.errno == errno.EADDRINUSE else str(e)
        print(f"nookku: cannot start the page on {HOST}:{port}: {reason}", file=sys.stderr)
        return 1
    try:
        path, lock = claim_page_file(root, server.server_address[1])
    except (PageRunning, OSError) as e:
        server.server_close()
        print(f"nookku: cannot start the page: {e}. Stop that server first.", file=sys.stderr)
        return 1
    # SIGTERM and SIGHUP (the terminal closes) stop the page as Ctrl-C does, so that the page
    # file goes away.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.default_int_handler)
    try:
        print(f"Chat page: {server.url}", file=out, flush=True)
        print("Open this URL in your browser. Stop the page with Ctrl-C.", file=out, flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # A second signal, for example from a wrapper that forwards it, must not stop the cleanup.
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        server.server_close()
        # This server holds the page lock, so the page file is its own file.
        path.unlink(missing_ok=True)
        os.close(lock)
    return 0

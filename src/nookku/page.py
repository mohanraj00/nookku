"""The chat page: a local web page where the tester talks to the agent of a running test (#327).

The page server sends each message with the relay function of the hook (`state.send`), and writes
a `turn` row with the harness `pane` (SPEC.md section 5, "Chat page"). The message never enters the
harness, so the harness model cannot see it. The browser cannot post to the tap itself: it sends
`Origin`, and the tap refuses a request with `Origin` (SPEC.md section 4.2). Thus the page server
sends for the page.

Security: the server listens only on 127.0.0.1. Each URL holds a random token. Each request must
have a correct `Host`, and a correct `Origin` if it has one. A `POST` must have `Origin`. Each
answer has a strict Content Security Policy, and the page loads only its own files.
"""

from __future__ import annotations

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
from typing import Any, ClassVar
from urllib.parse import urlsplit

from nookku import kit, policy, state
from nookku.record import RecordError, Writer, lone_surrogate, turns

# The harness of a turn that the page sent (SPEC.md section 2.2).
HARNESS = "pane"
HOST = "127.0.0.1"
# The files of the page, in src/nookku/page/, and their media types.
FILES = {
    "": ("index.html", "text/html; charset=utf-8"),
    "app.js": ("app.js", "text/javascript; charset=utf-8"),
    "app.css": ("app.css", "text/css; charset=utf-8"),
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
CONTROL_REASON = (
    "nookku: the page does not run control prompts. Type {said} in the harness. Nothing was sent."
)
NO_TEST = "nookku: no test runs. Start one in the harness with: nookku start. Nothing was sent."


def page_file(name: str) -> bytes:
    return resources.files("nookku").joinpath("page").joinpath(name).read_bytes()


def refusal(root: Path, said: Any) -> str | None:
    """The reason to refuse a message before the page sends it, or None. These are the rules of
    the hook (SPEC.md section 5), and the page writes no turn for a refused message."""
    if not isinstance(said, str) or not said.strip():
        return "nookku: the message is empty. Nothing was sent."
    found = lone_surrogate(said)
    if found:
        return f"nookku: nothing was sent. The message has {found}."
    if said.strip() in kit.CONTROL:
        return CONTROL_REASON.format(said=said.strip())
    try:
        limit = policy.read(root)["control_distance"]
    except policy.PolicyError:
        # A broken policy file gives the default, as in the hook.
        limit = policy.KEYS["control_distance"].default
    if kit.near_control(said, limit):
        return kit.NEAR_CONTROL_REASON
    return None


def send(root: Path, said: Any) -> dict[str, Any]:
    """Send one message to the running test, and write its turn. Return what the page shows.

    Fail closed: if the page cannot send the message, it shows the error, and the turn has the
    error as `shown` with `ok: false`. The message never goes to a model."""
    reason = refusal(root, said)
    if reason is not None:
        return {"sent": False, "shown": reason, "ok": False}
    cur = state.current(root)
    if cur is None:
        return {"sent": False, "shown": NO_TEST, "ok": False}
    shown, ok = kit.checked(*state.send(cur, said))
    row = {"type": "turn", "harness": HARNESS, "said": said, "shown": shown, "ok": ok}
    Writer(Path(cur["dir"]) / "relay.jsonl").append(row)
    return {"sent": True, "shown": shown, "ok": ok}


def _manifest(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / "manifest.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def view(root: Path) -> dict[str, Any]:
    """The test and its turns, for the page: the running test, else the latest test."""
    cur = state.current(root)
    folder = Path(cur["dir"]) if cur else state.latest_test(root)
    if folder is None:
        return {"test": None, "turns": [], "error": None}
    manifest = _manifest(folder)
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


class _Handler(BaseHTTPRequestHandler):
    server: PageServer
    server_version = "nookku-page"
    sys_version = ""
    # The answers of the page are small, and a keep-alive connection is not necessary.
    protocol_version = "HTTP/1.0"
    METHODS: ClassVar[set[str]] = {"GET", "POST"}

    def log_message(self, format: str, *args: Any) -> None:
        # The default log writes each path, and each path holds the page token.
        pass

    def _answer(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        for name, value in HEADERS.items():
            self.send_header(name, value)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
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

    def do_GET(self) -> None:
        rest = self._route()
        if rest is None:
            return
        if rest in FILES:
            name, kind = FILES[rest]
            self._answer(200, page_file(name), kind)
        elif rest == "api/turns":
            self._json(200, view(self.server.root))
        else:
            self._refuse(404, "not found")

    def do_POST(self) -> None:
        rest = self._route()
        if rest is None:
            return
        if rest != "api/send":
            self._refuse(404, "not found")
            return
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind != "application/json":
            self._refuse(415, "the Content-Type must be application/json")
            return
        try:
            size = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._refuse(411, "the request needs a Content-Length")
            return
        if size < 0 or size > MAX_BODY:
            self._refuse(413, "the message is too large")
            return
        try:
            data = json.loads(self.rfile.read(size))
        except ValueError:
            self._refuse(400, "the body is not JSON")
            return
        said = data.get("said") if isinstance(data, dict) else None
        with self.server.lock:
            try:
                answer = send(self.server.root, said)
            except Exception as e:  # each failure must give the page an error, not a reset
                self._json(500, {"sent": False, "ok": False, "shown": f"nookku: {e}"})
                return
        self._json(200, answer)


def write_page_file(root: Path, server: PageServer) -> Path:
    """Write the page file of the project: the URL that the guard denies (SPEC.md section 5)."""
    from nookku.bridge import _write_json

    folder = state.state(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / state.PAGE_FILE
    # The URL holds the page token, so only the owner can read the file.
    _write_json(path, {"url": server.url, "pid": os.getpid()}, mode=0o600)
    return path


def serve(root: Path, port: int = 0, out: Any = None) -> int:
    """Run the page server until it gets a signal. Print the page URL. Never print the tap token."""
    out = out or sys.stdout
    try:
        server = PageServer(root, port)
    except OSError as e:
        print(f"nookku: cannot start the page on {HOST}:{port}: {e}", file=sys.stderr)
        return 1
    path = write_page_file(root, server)
    # SIGTERM stops the page as Ctrl-C does, so that the page file goes away.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    print(f"Chat page: {server.url}", file=out, flush=True)
    print("Open this URL in your browser. Stop the page with Ctrl-C.", file=out, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # A second signal, for example from a wrapper that forwards it, must not stop the cleanup.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        server.server_close()
        # Another page server can write the file after this one. Then its file stays.
        if state.page_url(root) == server.url:
            path.unlink(missing_ok=True)
    return 0

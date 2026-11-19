"""The read-only public API of the evaluation dashboard, version 1 (#581, docs/reference/api.md).

`nookku dashboard` serves this API and, with `--site`, the static files of a dashboard on the same
origin. The API reads the files of the test folders and of the gate folders. It changes no file.
Each answer about a file says whether the file is the file of the seal: the seal of the folder is
intact, its copy outside the folder is the same, and the SHA-256 of the bytes that the API read is
the SHA-256 in the copy. A run with a broken seal shows `"seal": "broken"`.

The server binds to 127.0.0.1 by default. It sends no CORS header, so a page of another origin
cannot read an answer. It accepts a request only with a `Host` header of its own address, so a
page of another site cannot read it through a DNS name that points to 127.0.0.1.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from nookku import dashboard, gate, seal, state, verdict
from nookku.record import loads

VERSION = 1
PREFIX = f"/api/v{VERSION}"
REPORT = "report.md"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")
# The policy of each file of the site. The site loads only its own files.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'"
)
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}
NOT_FOUND = "not found"


class NotFound(Exception):
    """A route, a run or a gate run that does not exist."""


def _sealed(folder: Path, name: str, data: bytes | None, base: Path | None = None) -> bool:
    """True if `data` is the file `name` of the seal of `folder`: the seal is intact, its copy is
    the same, and the copy has the SHA-256 of `data`."""
    if data is None:
        return False
    result = seal.verify(folder, base)
    if not result["intact"] or result["copy"] != "same":
        return False
    files = seal.copy_files(folder.name, base)
    return files is not None and files.get(name) == seal.sha256_of(data)


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _json(data: bytes | None) -> tuple[Any, str | None]:
    """The JSON value of the bytes of a file, or None and an error. No file gives no error."""
    if data is None:
        return None, None
    try:
        return loads(data.decode("utf-8")), None
    except (UnicodeDecodeError, ValueError) as e:
        return None, f"not valid JSON: {e}"


def _run_folder(root: Path, run: str) -> Path:
    folder = dashboard.find(root, run)
    if folder is None:
        raise NotFound(f"no run {run}")
    return folder


def _checked(folder: Path) -> tuple[dict[str, Any] | None, str | None]:
    """verdict.checked, with a file that the process cannot read as a problem. Then one run that
    cannot be read does not stop the answer for the other runs."""
    try:
        return verdict.checked(folder)
    except OSError as e:
        return None, f"A file of the run cannot be read: {e.strerror or e}."


def _verified(folder: Path) -> tuple[dict[str, Any] | None, str | None]:
    """gate.verify, with a file that the process cannot read as a problem."""
    try:
        return gate.verify(folder)
    except OSError as e:
        return None, f"A file of the gate run cannot be read: {e.strerror or e}."


def _run(folder: Path, running: str | None) -> dict[str, Any]:
    """The row of a run: the row of the chat dashboard, with the verdict that a process can use."""
    row: dict[str, Any] = dict(dashboard.row(folder, running))
    report: dict[str, Any] | None
    problem: str | None
    if row["state"] == "running":
        report, problem = None, "The run has not ended."
    else:
        report, problem = _checked(folder)
    row["verdict"] = report["verdict"] if report is not None else None
    row["verdict_problem"] = problem
    return row


def runs(root: Path) -> dict[str, Any]:
    """`GET /api/v1/runs`: each run, the newest first."""
    running = dashboard.running_id(root)
    folders = [f for f in state.tests_newest_first(root) if dashboard._is_text(f.name)]
    return {"api": VERSION, "runs": [_run(f, running) for f in folders]}


def run(root: Path, run_id: str) -> dict[str, Any]:
    """`GET /api/v1/runs/<run>`: one run."""
    return {"api": VERSION, "run": _run(_run_folder(root, run_id), dashboard.running_id(root))}


def run_verdict(root: Path, run_id: str) -> dict[str, Any]:
    """`GET /api/v1/runs/<run>/verdict`: the verdict, only if a process can use it (SPEC.md
    section 7.14, "The verdict of an exit code")."""
    folder = _run_folder(root, run_id)
    report, problem = _checked(folder)
    return {"api": VERSION, "run": folder.name, "verdict": report, "problem": problem}


def run_findings(root: Path, run_id: str) -> dict[str, Any]:
    """`GET /api/v1/runs/<run>/findings`: findings.json as the API read it."""
    folder = _run_folder(root, run_id)
    data = _read(folder / verdict.FINDINGS)
    value, error = _json(data)
    if value is not None and not isinstance(value, dict):
        value, error = None, "not a JSON object"
    return {
        "api": VERSION,
        "run": folder.name,
        "findings": value,
        "sealed": _sealed(folder, verdict.FINDINGS, data),
        "error": f"{verdict.FINDINGS}: {error}" if error else None,
    }


def run_evaluation(root: Path, run_id: str) -> dict[str, Any]:
    """`GET /api/v1/runs/<run>/evaluation`: the text of report.md, the report of the evaluation
    (SPEC.md section 9.3). A model writes it, so it is text and no code reads it."""
    folder = _run_folder(root, run_id)
    data = _read(folder / REPORT)
    text = None
    error = None
    if data is not None:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            error = f"{REPORT}: not UTF-8"
    return {
        "api": VERSION,
        "run": folder.name,
        "report": text,
        "sealed": _sealed(folder, REPORT, data),
        "error": error,
    }


def _gate_folders(root: Path) -> list[Path]:
    top = gate.folder_of(root)
    try:
        found = [p for p in top.iterdir() if p.is_dir() and state.is_test_id(p.name)]
    except OSError:
        return []
    return sorted(found, key=lambda p: p.name, reverse=True)


def _gate_folder(root: Path, gate_id: str) -> Path:
    # The id must be the name of a gate folder, so a path of the request never leaves the folder.
    folder = next((f for f in _gate_folders(root) if f.name == gate_id), None)
    if folder is None:
        raise NotFound(f"no gate run {gate_id}")
    return folder


def _gate_row(folder: Path) -> dict[str, Any]:
    """The row of a gate run: its id, its verdict and its subject if a process can use them, and
    the state of its seal."""
    result, problem = _verified(folder)
    seal_state, error = dashboard._seal_state(folder)
    return {
        "id": folder.name,
        "verdict": result.get("verdict") if result is not None else None,
        "subject": result.get("subject") if result is not None else None,
        "tests": len(result.get("tests", [])) if result is not None else None,
        "seal": seal_state,
        "problem": problem or error,
    }


def gates(root: Path) -> dict[str, Any]:
    """`GET /api/v1/gates`: each gate run, the newest first."""
    return {"api": VERSION, "gates": [_gate_row(f) for f in _gate_folders(root)]}


def gate_result(root: Path, gate_id: str) -> dict[str, Any]:
    """`GET /api/v1/gates/<gate>`: result.json of a gate run, only if a process can use it
    (SPEC.md section 7.15)."""
    folder = _gate_folder(root, gate_id)
    result, problem = _verified(folder)
    return {"api": VERSION, "gate": folder.name, "result": result, "problem": problem}


def index() -> dict[str, Any]:
    """`GET /api/v1`: the version and the routes."""
    routes = [
        "runs",
        "runs/<run>",
        "runs/<run>/verdict",
        "runs/<run>/findings",
        "runs/<run>/evaluation",
        "gates",
        "gates/<gate>",
    ]
    return {"api": VERSION, "routes": [f"{PREFIX}/{r}" for r in routes]}


def answer(root: Path, path: str) -> tuple[int, dict[str, Any]]:
    """The status and the JSON answer of an API path, which starts with PREFIX."""
    rest = path[len(PREFIX) :].strip("/")
    parts = [unquote(p) for p in rest.split("/")] if rest else []
    try:
        if not parts:
            return 200, index()
        if parts[0] == "runs" and len(parts) == 1:
            return 200, runs(root)
        if parts[0] == "runs" and len(parts) == 2:
            return 200, run(root, parts[1])
        routes = {
            "verdict": run_verdict,
            "findings": run_findings,
            "evaluation": run_evaluation,
        }
        if parts[0] == "runs" and len(parts) == 3 and parts[2] in routes:
            return 200, routes[parts[2]](root, parts[1])
        if parts[0] == "gates" and len(parts) == 1:
            return 200, gates(root)
        if parts[0] == "gates" and len(parts) == 2:
            return 200, gate_result(root, parts[1])
    except NotFound as e:
        return 404, {"api": VERSION, "error": str(e)}
    return 404, {"api": VERSION, "error": NOT_FOUND}


def hosts_for(host: str, port: int, allowed: list[str]) -> set[str]:
    """The `Host` values that the server accepts: its own address at its port, each loopback name
    if it binds to a loopback address, and each allowed name."""
    names = {host if ":" not in host or host.startswith("[") else f"[{host}]"}
    if host in ("127.0.0.1", "::1", "localhost"):
        names |= set(LOOPBACK)
    out = {f"{n}:{port}".lower() for n in names}
    return out | {a.lower() for a in allowed}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # A page of the kit loads many modules at the same time. With the default queue of 5, the
    # system resets some of these connections.
    request_queue_size = 128

    def __init__(
        self,
        root: Path,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        site: Path | None = None,
        allowed: list[str] | None = None,
        token: str | None = None,
    ) -> None:
        self.root = root
        self.site = site.resolve() if site is not None else None
        self.allowed = list(allowed or [])
        # Each API request must send this token. A new server gets a new token, so a process of
        # another user on the same computer cannot read the records through the port.
        self.token = token or secrets.token_urlsafe(32)
        bare = host.strip("[]")
        # The default family is IPv4, which cannot bind an IPv6 address such as ::1.
        self.address_family = socket.AF_INET6 if ":" in bare else socket.AF_INET
        super().__init__((bare, port), Handler)
        self.hosts = hosts_for(host, self.server_address[1], self.allowed)

    @property
    def url(self) -> str:
        host = self.server_address[0]
        if isinstance(host, bytes):
            host = host.decode()
        shown = f"[{host}]" if ":" in host else host
        return f"http://{shown}:{self.server_address[1]}/"


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "nookku-dashboard"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(
        self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: dict[str, Any], extra: dict[str, str] | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _host_ok(self) -> bool:
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].lower() not in self.server.hosts:
            self._json(403, {"api": VERSION, "error": "wrong Host header"})
            return False
        return True

    def _token_ok(self) -> bool:
        got = self.headers.get_all("Authorization") or []
        want = f"Bearer {self.server.token}".encode()
        if len(got) != 1 or not hmac.compare_digest(got[0].encode("utf-8", "replace"), want):
            extra = {"WWW-Authenticate": "Bearer"}
            self._json(401, {"api": VERSION, "error": "no valid token"}, extra)
            return False
        return True

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if path == PREFIX or path.startswith(PREFIX + "/"):
            if not self._token_ok():
                return
            status, data = answer(self.server.root, path)
            self._json(status, data)
            return
        self._file(path)

    do_HEAD = do_GET

    def _refuse_method(self) -> None:
        self._json(405, {"api": VERSION, "error": "the API is read-only"})

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse_method

    def _file(self, path: str) -> None:
        """A file of the site. The path must name a file in the site folder after symlinks
        resolve."""
        site = self.server.site
        if site is None:
            text = "nookku dashboard: no site. Start it with --site <folder>.\n"
            self._send(404, text.encode(), "text/plain; charset=utf-8")
            return
        rel = unquote(path).lstrip("/")
        target = (site / rel).resolve() if rel else site
        if target.is_dir():
            # Resolve the index file too, because it can be a symlink to a file outside the site.
            target = (target / "index.html").resolve()
        if site not in target.parents or not target.is_file():
            self._json(404, {"api": VERSION, "error": NOT_FOUND})
            return
        kind = TYPES.get(target.suffix.lower())
        if kind is None:
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        try:
            body = target.read_bytes()
        except OSError:
            self._json(404, {"api": VERSION, "error": NOT_FOUND})
            return
        self._send(200, body, kind)

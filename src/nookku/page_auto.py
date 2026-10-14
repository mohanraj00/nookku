"""Start the chat page with a test, and stop it at the end of the test (#328).

`nookku start` (and the prompt `nookku start`, and `nookku mode start`) starts a page server in a
separate process, and the page server opens the page in the browser. The page server stops itself
after the page showed the end of its test. `nookku end` waits for it, and stops it if necessary.

The page URL holds the page token. The URL never goes into a text that the model sees (SPEC.md
section 5, "The page URL"). The start runs in a hook or in a shell, and the model can read their
output. Thus:

- The page server gives the browser a launch URL with a one-time code, not the page URL. The first
  request with the code gets a redirect to the page URL, and the code then has no use. A process
  list can show the launch URL to the model, but not the page URL.
- `nookku start` prints the page URL only if the browser did not open, only to a terminal, and only
  out of a harness shell. Else it prints how to start the page by hand, and no page server runs.
- The page server writes no URL to a file.

A page server that fails, or that does not start, does not stop or change the test: each failure
gives only a line of text, and the test continues.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from nookku import page, state

# The config key that turns the start of the page with the test on or off (SPEC.md section 7.1).
CONFIG_KEY = "page"
# The wait of `nookku start` for the page server to say if the browser opened.
START_WAIT = 10.0
# The wait of the page server for the browser command. A browser command that runs longer got the
# URL, for example a new browser that runs in the foreground.
OPEN_WAIT = 5.0
# The wait of the page server after the end of its test, for the page to show the end. The page
# asks for its turns each second (src/nookku/page/app.js).
END_GRACE = 3.0
# The wait of `nookku end` for the page server to stop by itself. Then it sends SIGTERM, and waits
# STOP_WAIT more.
END_WAIT = END_GRACE + 3.0
STOP_WAIT = 2.0
# The interval of the check of the page server: does its test still run?
WATCH = 0.25

OPENED = "The chat page opened in your browser. It stops at the end of the test."
NO_BROWSER_URL = (
    "The browser did not open. Open this URL of the chat page: {url}\n"
    "Do not give this URL to the harness model. The page stops at the end of the test."
)
NO_BROWSER = (
    "The browser did not open, so the chat page did not start. To use the page, run nookku page "
    "in a separate terminal."
)
FAILED = "nookku: the chat page did not start: {reason}. The test continues."
NOT_STOPPED = "nookku: the chat page (pid {pid}) did not stop. Stop it with: kill {pid}"


def enabled(root: Path) -> bool:
    """True if `start` starts the chat page. The config key `page` is true by default. The plugin
    has no config file, so the default applies."""
    from nookku.config import read_config

    try:
        data = read_config(root) if (state.state(root) / "config.json").exists() else {}
    except Exception:
        # The start reads the config before this, so a broken config stops the start first.
        return True
    return bool(data.get(CONFIG_KEY, True))


def harness_shell() -> str | None:
    """The name of a harness shell variable that is set, or None."""
    return next((name for name in page.HARNESS_SHELL if os.environ.get(name)), None)


def may_print_url() -> bool:
    """True if the output of this command goes only to a person: a terminal out of a harness
    shell. The output of a hook or of a plugin command goes to a pipe."""
    try:
        return sys.stdout.isatty() and harness_shell() is None
    except (AttributeError, ValueError):
        return False


def after_start(root: Path, test: str) -> str | None:
    """Start the chat page of the test that started now. Return the text to show, or None if the
    config turns the page off. Never raise, and never return the URL to a text that the model can
    see."""
    if not enabled(root):
        return None
    try:
        return _start(root, test, may_print_url())
    except Exception as e:  # a failed page must not stop the test
        return FAILED.format(reason=e)


def _start(root: Path, test: str, print_url: bool) -> str:
    read, write = os.pipe()
    command = [sys.executable, "-m", "nookku", "page", "--root", str(root)]
    command += ["--auto-test", test, "--status-fd", str(write)]
    command += ["--print-url"] if print_url else []
    try:
        # A new session: a signal to the group of the hook or of the shell does not reach the
        # page server. No standard stream is shared, so the hook does not wait for the server.
        proc = subprocess.Popen(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=(write,),
            start_new_session=True,
        )
    finally:
        os.close(write)
    state._children[proc.pid] = proc
    try:
        line = _read_line(read, START_WAIT)
    finally:
        os.close(read)
    try:
        status = json.loads(line) if line else None
    except ValueError:
        status = None
    if not isinstance(status, dict):
        if proc.poll() is None:
            _stop(proc.pid)
            return FAILED.format(reason=f"the page server sent no status in {START_WAIT:g} s")
        return FAILED.format(reason=f"the page server stopped with exit code {proc.returncode}")
    if status.get("status") == "opened":
        return OPENED
    if status.get("status") == "no-browser":
        url = status.get("url")
        if print_url and isinstance(url, str):
            return NO_BROWSER_URL.format(url=url)
        # The page server stops now. Leave no process.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(STOP_WAIT)
        return NO_BROWSER
    return FAILED.format(reason=status.get("reason", "an unknown error"))


def _read_line(fd: int, timeout: float) -> bytes:
    """Read one line from fd, until the line end, the end of the file or the timeout."""
    data = b""
    deadline = time.monotonic() + timeout
    while b"\n" not in data:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        part = os.read(fd, 4096)
        if not part:
            break
        data += part
    return data.split(b"\n", 1)[0]


def _stop(pid: int) -> bool:
    """Send SIGTERM to pid and wait STOP_WAIT for it to stop. Return True if it stopped."""
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_WAIT
    while state.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not state.alive(pid)


def after_end(root: Path) -> str | None:
    """Wait for the chat page that `start` started to stop, after the end of its test. Stop it if
    it does not stop in END_WAIT. Return an error text, or None. Never raise. A page that the
    tester started with `nookku page` has no test in its page file, and keeps running."""
    try:
        return _wait_end(root)
    except Exception as e:  # a failed page must not change the end of the test
        return f"nookku: cannot stop the chat page: {e}"


def _wait_end(root: Path) -> str | None:
    info = state.page_info(root)
    if info is None or not isinstance(info.get("test"), str):
        return None
    pid = info.get("pid")
    if type(pid) is not int or pid <= 0 or _runs(root, info["test"]):
        return None
    # The server removes its page file before its process exits, so wait for the process.
    deadline = time.monotonic() + END_WAIT
    while state.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if not state.alive(pid):
        return None
    return None if _stop(pid) else NOT_STOPPED.format(pid=pid)


def _runs(root: Path, test: str) -> bool:
    """True if the test runs. Read current.json and change nothing: `state.current` removes a
    stale file, but the page server only reads the state of a test."""
    try:
        cur = json.loads((state.state(root) / "current.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(cur, dict) and cur.get("test") == test and state.is_bridge(cur)


class AutoPageServer(page.PageServer):
    """The page server that `start` starts. It serves the launch URL one time, and it stops after
    the page showed the end of its test."""

    def __init__(self, root: Path, test: str) -> None:
        super().__init__(root)
        self.RequestHandlerClass = _AutoHandler
        self.test = test
        self.code = secrets.token_urlsafe(32)
        self.code_used = False
        self.code_lock = threading.Lock()
        self.ended = threading.Event()
        self.shown_end = threading.Event()

    @property
    def launch_url(self) -> str:
        return f"http://{page.HOST}:{self.server_address[1]}/o/{self.code}"


class _AutoHandler(page._Handler):
    server: AutoPageServer

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path.startswith("/o/"):
            self._launch(parts.path[len("/o/") :], parts.query)
            return
        ended = self.server.ended.is_set()
        super().do_GET()
        turns = f"/p/{self.server.token}/api/turns"
        if ended and not parts.query and hmac.compare_digest(parts.path.encode(), turns.encode()):
            # The page got its turns after the end of the test, so it shows the end.
            self.server.shown_end.set()

    def _launch(self, code: str, query: str) -> None:
        """The launch URL: one redirect to the page URL, for the first request with the code."""
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].lower() not in self.server.hosts:
            self._refuse(403, "wrong Host header")
            return
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1 or (origins and origins[0].lower() not in self.server.origins):
            self._refuse(403, "wrong Origin header")
            return
        with self.server.code_lock:
            good = not query and hmac.compare_digest(code.encode(), self.server.code.encode())
            first = good and not self.server.code_used
            if good:
                self.server.code_used = True
        if not first:
            self._refuse(404, "not found")
            return
        self.send_response(303)
        self.send_header("Location", f"/p/{self.server.token}/")
        self.send_header("Content-Length", "0")
        self.end_headers()


def _can_open() -> bool:
    """True if a browser can open on this computer. Over SSH, the browser would open on the remote
    computer. On Linux, a browser needs a display."""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _open_browser(url: str) -> bool:
    """Give the URL to the browser. Return False if no browser took it."""
    # With TERM, webbrowser can take a text browser, which needs the terminal of this process.
    os.environ.pop("TERM", None)
    import webbrowser

    result: list[bool] = []

    def run() -> None:
        try:
            result.append(bool(webbrowser.open(url)))
        except Exception:
            result.append(False)

    opener = threading.Thread(target=run, daemon=True)
    opener.start()
    opener.join(OPEN_WAIT)
    # A browser command that runs in the foreground did not return, but it got the URL.
    return result[0] if result else True


def _watch(server: AutoPageServer) -> None:
    """Stop the server after the end of its test: when the page showed the end, or END_GRACE after
    the end."""
    ended_at: float | None = None
    while True:
        if ended_at is None and not _runs(server.root, server.test):
            ended_at = time.monotonic()
            server.ended.set()
        if ended_at is not None and (
            server.shown_end.is_set() or time.monotonic() - ended_at >= END_GRACE
        ):
            server.shutdown()
            return
        time.sleep(WATCH)


def serve(root: Path, test: str, status_fd: int, print_url: bool) -> int:
    """The page server that `start` starts (`nookku page --auto-test`). Write one JSON line to
    status_fd: the status, and the page URL only with print_url. Then serve until the test ends."""
    status = os.fdopen(status_fd, "w")

    def report(data: dict[str, Any]) -> None:
        with contextlib.suppress(OSError):
            status.write(json.dumps(data) + "\n")
            status.close()

    shell = harness_shell()
    if print_url and shell is not None:
        report({"status": "error", "reason": f"{shell} is set, so the URL is not shown"})
        return 1
    try:
        server = AutoPageServer(root, test)
    except OSError as e:
        report({"status": "error", "reason": f"cannot listen on {page.HOST}: {e}"})
        return 1
    try:
        path, lock = page.claim_page_file(root, server.server_address[1], test)
    except (page.PageRunning, OSError) as e:
        server.server_close()
        report({"status": "error", "reason": str(e)})
        return 1
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, signal.default_int_handler)
    # The server serves before the browser opens: a browser command can wait for the page.
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    # The status to report after the cleanup, so that the start sees no page file.
    last: dict[str, Any] | None = None
    try:
        if _can_open() and _open_browser(server.launch_url):
            report({"status": "opened"})
        elif print_url:
            report({"status": "no-browser", "url": server.url})
        else:
            # Nobody has the URL, so the server has no use.
            last = {"status": "no-browser"}
            return 0
        threading.Thread(target=_watch, args=(server,), daemon=True).start()
        # The main thread gets the signals, so it waits in short steps.
        while serving.is_alive():
            serving.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        server.shutdown()
        server.server_close()
        path.unlink(missing_ok=True)
        os.close(lock)
        if last is not None:
            report(last)
    return 0

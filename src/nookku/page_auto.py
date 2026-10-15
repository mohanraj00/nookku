"""Start the chat page with a test, and stop it after the test (#328, #391).

`nookku start` (and the prompt `nookku start`, and `nookku mode start`) starts a page server in a
separate process, and the page server opens the page in the browser. After an end with no
evaluation (`nookku end` in a shell, `nookku mode end` or "End test" on the page), the page server
continues, so the tester can export the test and save it as a script. The prompt `nookku end`, the
end with the evaluation, stops it. The next start also stops it.

The page URL holds the page token. The URL never goes into a text that the model sees (SPEC.md
section 5, "The page URL"). The start runs in a hook or in a shell, and the model can read their
output. Thus:

- The page server gives the browser a launch URL with a one-time code, not the page URL. The first
  request with the code gets the session cookie and a redirect to a path with no secret. A process
  list can show the launch URL to the model, but not the page token. If a second request has the
  code, an other process can have the session, so the page server stops.
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
from typing import Any, TextIO
from urllib.parse import urlsplit

from nookku import page, state

# The wait of `nookku start` for the page server to say if the browser opened.
START_WAIT = 15.0
# The wait of the page server for the browser command. A browser command that runs longer got the
# URL, for example a new browser that runs in the foreground.
OPEN_WAIT = 5.0
# The wait of the page server, from the browser command, for the request of the launch URL. A new
# browser can take seconds to start. With no request, the browser did not open.
LAUNCH_WAIT = 10.0
# The wait of the page server after the first request of the launch URL, for a second request.
# Another process that reads the process list can make the first request before the browser.
REUSE_WAIT = 1.0
# The wait for the page server of an ended test to stop after SIGTERM.
STOP_WAIT = 2.0

OPENED = (
    "The chat page opened in your browser. It stops when you type the prompt nookku end, or at "
    "the next start."
)
NO_BROWSER_URL = (
    "The browser did not open. Open this URL of the chat page: {url}\n"
    "Do not give this URL to the harness model. The page stops when you type the prompt "
    "nookku end, or at the next start."
)
NO_BROWSER = (
    "The browser did not open, so the chat page did not start. To use the page, run nookku chat "
    "in a separate terminal."
)
FAILED = "nookku: the chat page did not start: {reason}. The test continues."
REUSED = (
    "another process used the launch URL of the page first, so the page stopped. To use the "
    "page, run nookku chat in a separate terminal"
)
REUSED_PAGE = (
    "nookku: another process used the launch URL of this chat page first. The chat page "
    "stopped, and its session has no use now. To use the page, run nookku chat in a separate "
    "terminal.\n"
)
NOT_STOPPED = "nookku: the chat page (pid {pid}) did not stop. Stop it with: kill {pid}"


def enabled(root: Path) -> bool:
    """True if `start` starts the chat page. The config key `page` is true by default. The plugin
    has no config file, so the default applies."""
    from nookku.config import Config, ConfigError

    try:
        return Config.load_or_default(root).page
    except ConfigError:
        # The start reads the config before this, so a broken config stops the start first.
        return True


def harness_shell() -> str | None:
    """The name of a harness shell variable that is set, or None."""
    return next((name for name in page.HARNESS_SHELL if os.environ.get(name)), None)


def may_print_url(out: TextIO) -> bool:
    """True if the text goes only to a person: out is a terminal, out of a harness shell. The
    output of a hook or of a plugin command goes to a pipe."""
    try:
        return out.isatty() and harness_shell() is None
    except (AttributeError, ValueError):
        return False


def after_start(root: Path, test: str, out: TextIO) -> str | None:
    """Start the chat page of the test that started now. Return the text to show on out, or None
    if the config turns the page off. Never raise. The text holds the page URL only if out goes
    only to a person."""
    if not enabled(root):
        return None
    try:
        return _start(root, test, may_print_url(out))
    except Exception as e:  # a failed page must not stop the test
        return FAILED.format(reason=e)


def _start(root: Path, test: str, print_url: bool) -> str:
    # The page server of the test before this one can still run. This test replaces it.
    stopped = _stop_ended(root)
    if stopped is not None:
        return FAILED.format(reason=stopped.removeprefix("nookku: "))
    read, write = os.pipe()
    command = [sys.executable, "-m", "nookku", "chat", "--root", str(root)]
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


def after_end(root: Path, stop: bool) -> str | None:
    """After the end of a test: stop the chat page that `start` started, if stop is True and its
    test does not run. The prompt `nookku end`, the end with the evaluation, sets stop. Another end
    keeps the page, so the tester can export the test. Return an error text, or None. Never raise.
    A page that the tester started with `nookku chat` has no test in its page file, and keeps
    running."""
    if not stop:
        return None
    try:
        return _stop_ended(root)
    except Exception as e:  # a failed page must not change the end of the test
        return f"nookku: cannot stop the chat page: {e}"


def _stop_ended(root: Path) -> str | None:
    """Stop the page server that `start` started, if its test does not run. Return an error text,
    or None."""
    info = state.page_info(root)
    if info is None or not isinstance(info.get("test"), str):
        return None
    pid = info.get("pid")
    if type(pid) is not int or pid <= 0 or _runs(root, info["test"]) or not _held(root):
        return None
    # Send a signal only to the page server: it holds the page lock, and the page file still
    # names it. A server writes its own pid into the page file after it takes the lock.
    if not state.alive(pid) or state.page_info(root) != info:
        return None
    return None if _stop(pid) else NOT_STOPPED.format(pid=pid)


def _held(root: Path) -> bool:
    """True if a page server holds the page lock. A page file with no holder of the lock is stale:
    its pid can be a new process with no relation to the page."""
    import fcntl

    try:
        fd = os.open(state.state(root) / state.PAGE_LOCK, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def _runs(root: Path, test: str) -> bool:
    """True if the test runs. Read current.json and change nothing: `state.current` removes a
    stale file, but the page server only reads the state of a test."""
    try:
        cur = json.loads((state.state(root) / "current.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(cur, dict) and cur.get("test") == test and state.is_bridge(cur)


class AutoPageServer(page.PageServer):
    """The page server that `start` starts. It serves the launch URL one time. It stops on
    SIGTERM: from the prompt `nookku end`, or from the next start."""

    def __init__(self, root: Path, test: str) -> None:
        super().__init__(root)
        self.RequestHandlerClass = _AutoHandler
        self.test = test
        self.code = secrets.token_urlsafe(32)
        self.code_used = False
        # Set when the first request with the code got the session.
        self.launched = threading.Event()
        # Set when a second request had the code. Then the server stops.
        self.reused = threading.Event()
        self.code_lock = threading.Lock()

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
        super().do_GET()

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
            again = good and self.server.launched.is_set()
            if good:
                self.server.code_used = True
            if first:
                self.server.launched.set()
                # The session is the only way in. The page token never left this process.
                with self.server.auth_lock:
                    self.server.token_used = True
        if again:
            # Two requests had the code, so one of them was not the browser. Fail closed: the
            # session stops with the process.
            self.server.reused.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            self._answer(409, REUSED_PAGE.encode(), "text/plain; charset=utf-8")
            return
        if not first:
            self._refuse(404, "not found")
            return
        self.redirect_with_session()


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


def _launched(server: AutoPageServer) -> bool:
    """Open the browser, and return True only if a request of the launch URL came in LAUNCH_WAIT.
    Else the launch URL gets no page URL any more: a browser command can return before it opens
    the page, and its arguments can stay in the process list."""
    began = time.monotonic()
    if _can_open() and _open_browser(server.launch_url):
        server.launched.wait(max(0.0, LAUNCH_WAIT - (time.monotonic() - began)))
    with server.code_lock:
        server.code_used = True
    if not server.launched.is_set():
        return False
    # The browser can be the second request. Then the server stops, and the browser did not get
    # the page.
    return not server.reused.wait(REUSE_WAIT)


def serve(root: Path, test: str, status_fd: int, print_url: bool) -> int:
    """The page server that `start` starts (`nookku chat --auto-test`). Write one JSON line to
    status_fd: the status, and the page URL only with print_url. Then serve until a signal stops
    the server."""
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
        if _launched(server):
            report({"status": "opened"})
        elif server.reused.is_set():
            last = {"status": "error", "reason": REUSED}
            return 0
        elif print_url:
            report({"status": "no-browser", "url": server.url})
        else:
            # Nobody has the URL, so the server has no use.
            last = {"status": "no-browser"}
            return 0
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

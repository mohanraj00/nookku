"""Start the chat page with a test, and stop it after the test (#328, #391).

`nookku start` (and the prompt `nookku start`, and `nookku mode start`) starts a page server in a
separate process, and the page server opens the page in the browser. After an end with no
evaluation (`nookku end` in a shell, `nookku mode end` or "End test" on the page), the page server
continues, so the tester can export the test and save it as a script. The prompt `nookku end`, the
end with the evaluation, stops it. The next start also stops it. With no test, it stops itself after
IDLE_LIMIT with no request of the tester (#439). `nookku chat --stop` stops the page server of the
project.

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
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
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
# The time with no request of the tester after which the page server stops, if no test runs (#439).
IDLE_LIMIT = 15 * 60.0
# The time between 2 checks for a running test. A running test counts as a request.
ACTIVE_CHECK = 60.0
# The header of a request that the page makes by itself each few seconds (key.js). Such a poll is
# not a request of the tester, so it does not keep the page server on.
POLL_HEADER = "X-Nookku-Poll"

OPENED = (
    "The chat page opened in your browser. It stops when you type the prompt nookku end, at the "
    "next start, or after 15 minutes with no use and no test."
)
NO_BROWSER_URL = (
    "The browser did not open. Open this URL of the chat page: {url}\n"
    "Do not give this URL to the harness model. The page stops when you type the prompt "
    "nookku end, at the next start, or after 15 minutes with no use and no test."
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
NOT_CONFIRMED = (
    "nookku: nookku cannot confirm that pid {pid} is the chat page, so it sent no signal. If "
    "ps -p {pid} shows a nookku chat page, stop it with: kill {pid}"
)
STOPPED = "The chat page of this project stopped."
NONE_RUNS = "No chat page of this project runs."
NOT_KNOWN = (
    "nookku: a process holds the page lock of this project, but nookku cannot confirm that it is "
    "the chat page, so it sent no signal. Find its pid with: lsof {lock} (macOS), or with: "
    "fuser {lock} (Linux). If ps -p <pid> shows a nookku chat page, stop it with: kill <pid>"
)


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
    if the config turns the page off and no page of an ended test failed to stop. Never raise.
    The text holds the page URL only if out goes only to a person."""
    if not enabled(root):
        # The page of the test before this one can still run. With no page for this test, it must
        # not show this test (SPEC.md section 5).
        try:
            stopped = _stop_ended(root)
        except Exception as e:  # a failed stop must not stop the test
            stopped = f"nookku: cannot stop the chat page: {e}"
        return stopped
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


def _stop(pid: int, start: str | None = None) -> bool:
    """Send SIGTERM to pid and wait STOP_WAIT for it to stop. Return True if it stopped.

    With `start`, send the signal only if pid is the process with this start time. If the OS gives
    a pidfd (Linux), the pidfd holds the process from the check to the signal. If the process
    stops in that time, the signal goes to no process, also if the OS gives its pid to a new
    process. With no pidfd (macOS), the check and the signal are separate steps, as for the entry
    of a stopped bridge."""
    fd = _pidfd(pid) if start is not None else None
    try:
        if start is not None and not state.same_process(pid, start):
            return True  # the process stopped, so no process gets the signal
        if fd is not None:
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(fd, signal.SIGTERM)  # type: ignore[attr-defined,unused-ignore]
            # A pidfd is readable when its process stops.
            return bool(select.select([fd], [], [], STOP_WAIT)[0])
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + STOP_WAIT
        while state.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not state.alive(pid)
    finally:
        if fd is not None:
            os.close(fd)


def _pidfd(pid: int) -> int | None:
    """A pidfd of the process of pid, or None if the OS gives no pidfd (`os.pidfd_open`)."""
    opener = getattr(os, "pidfd_open", None)
    if opener is None or not hasattr(signal, "pidfd_send_signal"):
        return None
    try:
        return int(opener(pid))
    except OSError:  # no such process, or the kernel has no pidfd
        return None


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
    if info is None or not isinstance(info.get("test"), str) or _runs(root, info["test"]):
        return None
    return _stop_server(root, info)


def stop(root: Path) -> tuple[int, str]:
    """`nookku chat --stop`: stop the page server of this project, with the checks of the stop at
    the end of a test. It also stops a page server that `nookku chat` started, and the page server
    of a running test. The test continues. Return the exit code and the text."""
    if not _held(root):
        return 0, NONE_RUNS
    # The absolute path of the lock, so that the command of the text works from each folder.
    not_known = NOT_KNOWN.format(
        lock=shlex.quote(str(state.state(root).resolve() / state.PAGE_LOCK))
    )
    info = state.page_info(root)
    error = not_known if info is None else _stop_server(root, info)
    if error is not None:
        return 1, error
    # _stop_server also sends no signal if the page file names no running pid, or if it changed.
    # Then a process still holds the lock, and "stopped" is not true.
    return (1, not_known) if _held(root) else (0, STOPPED)


def _stop_server(root: Path, info: dict[str, Any]) -> str | None:
    """Stop the page server of the page file info. Return an error text, or None."""
    pid = info.get("pid")
    if type(pid) is not int or pid <= 0 or not _held(root):
        return None
    # Send a signal only to the page server: it holds the page lock, and the page file still
    # names it. A server writes its own pid into the page file after it takes the lock.
    if not state.alive(pid) or state.page_info(root) != info:
        return None
    # The OS can give the pid to a new process. The pid and pid_start identify the server, as for
    # the bridge. A page file of an older version has no pid_start: then send no signal, and tell
    # the tester how to stop the server (#397).
    if not state.same_process(pid, info.get("pid_start")):
        return NOT_CONFIRMED.format(pid=pid)
    return None if _stop(pid, info["pid_start"]) else NOT_STOPPED.format(pid=pid)


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


def _active(root: Path) -> bool:
    """True if a test of the project runs. Read current.json and change nothing."""
    try:
        cur = json.loads((state.state(root) / "current.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(cur, dict) and state.is_bridge(cur)


class AutoPageServer(page.PageServer):
    """The page server that `start` starts. It serves the launch URL one time. It stops on
    SIGTERM: from the prompt `nookku end`, from the next start, or from `nookku chat --stop`. It
    also stops after IDLE_LIMIT with no request of the tester, if no test runs (`idle`)."""

    def __init__(self, root: Path, test: str, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(root)
        self.clock = clock
        # The time of the last request of the tester, or of the last check that saw a test run.
        self.last_use = clock()
        self.last_check = self.last_use
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

    def used(self) -> None:
        """A request of the tester came. The idle time starts again."""
        self.last_use = self.clock()

    def idle(self) -> bool:
        """True if the server must stop: no request of the tester came in IDLE_LIMIT, and no test
        runs. A running test counts as a request, so the idle time starts at the end of the test.
        Check for a running test each ACTIVE_CHECK, and again before the stop."""
        now = self.clock()
        if now - self.last_check >= ACTIVE_CHECK:
            self.last_check = now
            if _active(self.root):
                self.last_use = now
        if now - self.last_use < IDLE_LIMIT:
            return False
        if _active(self.root):
            self.last_use = now
            return False
        return True


class _AutoHandler(page._Handler):
    server: AutoPageServer

    def _route(self) -> str | None:
        rest = super()._route()
        # Only a request with the page key counts. A file of the page loads with the cookie only,
        # and a page on another port of 127.0.0.1 can make the browser send that cookie. A poll of
        # the page does not count.
        if rest is not None and self._has_key() and not self.headers.get_all(POLL_HEADER):
            self.server.used()
        return rest

    def redirect_with_session(self) -> None:
        super().redirect_with_session()
        self.server.used()

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
        while serving.is_alive() and not server.idle():
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

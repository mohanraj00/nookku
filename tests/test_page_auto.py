"""The start of the chat page with a test, and its stop at the end of the test (#328)."""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_page import cookie_only, make_folder, request, session_headers, write_current

from nookku import bridge, kit, page, page_auto, state
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
# The real rule. conftest.py turns the page start off for each other test.
ENABLED = page_auto.enabled
URL = re.compile(r"http://127\.0\.0\.1:\d+/p/[A-Za-z0-9_-]+/")


@pytest.fixture(autouse=True)
def page_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_auto, "enabled", ENABLED)
    for name in page.HARNESS_SHELL:
        monkeypatch.delenv(name, raising=False)
    # No browser opens in a test: over SSH, the page server opens none.
    monkeypatch.setenv("SSH_CONNECTION", "127.0.0.1 1 127.0.0.1 2")


def page_pid(root: Path) -> int | None:
    info = state.page_info(root)
    return info["pid"] if info else None


def wait_gone(pid: int, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while state.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not state.alive(pid)


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """A project with a test that runs: current.json names this process as its bridge."""
    (tmp_path / ".nookku").mkdir()
    folder = make_folder(tmp_path)
    write_current(tmp_path, folder, "http://127.0.0.1:9/", "x" * 43)
    yield tmp_path, folder
    pid = page_pid(tmp_path)
    if pid is not None and state.alive(pid):
        os.kill(pid, signal.SIGKILL)
        wait_gone(pid)


def test_each_wait_ends_before_the_hook_deadline() -> None:
    assert bridge.START_WAIT + page_auto.START_WAIT < kit.HOOK_DEADLINE
    # The page server reports its status before the start stops to wait for it.
    assert page_auto.OPEN_WAIT < page_auto.LAUNCH_WAIT
    assert page_auto.LAUNCH_WAIT + 2 < page_auto.START_WAIT
    end = bridge.END_WAIT + page_auto.END_WAIT + page_auto.STOP_WAIT
    assert end < kit.HOOK_DEADLINE
    # The page asks for its turns each second, so it can show the end in the grace time.
    js = (ROOT / "src" / "nookku" / "page" / "app.js").read_text()
    poll = int(re.search(r"POLL_MS = (\d+);", js).group(1))  # type: ignore[union-attr]
    assert 2 * poll / 1000 < page_auto.END_GRACE < page_auto.END_WAIT


def test_the_launch_url_gives_a_session_one_time_and_a_second_use_stops_the_page(
    tmp_path: Path,
) -> None:
    server = page_auto.AutoPageServer(tmp_path, "t-1")
    stopped = threading.Event()

    def serve() -> None:
        server.serve_forever()
        stopped.set()

    threading.Thread(target=serve, daemon=True).start()
    try:
        path = server.launch_url.split(str(server.server_address[1]), 1)[1]
        assert URL.search(server.launch_url) is None and server.token not in server.launch_url
        wrong_host = request(server, "GET", path, headers={"Host": "example.com"})
        assert wrong_host[0] == 403
        assert request(server, "GET", f"/o/{'a' * 43}")[0] == 404
        assert request(server, "GET", f"{path}?x=1")[0] == 404
        # The wrong requests do not use the code.
        status, headers, _ = request(server, "GET", path)
        # The redirect gives the page key only in the fragment, which the browser sends to no
        # server. The page removes it, so the browser history gets no URL that works.
        assert status == 303
        assert headers["location"] == f"{page.SESSION_PATH}#k={server.page_key}"
        assert "content-security-policy" in headers
        both = session_headers(status, headers)
        assert request(server, "GET", page.SESSION_PATH, headers=cookie_only(both))[0] == 200
        assert request(server, "GET", page.SESSION_PATH + "api/turns", headers=both)[0] == 200
        got = request(server, "GET", page.SESSION_PATH + "api/turns", headers=cookie_only(both))
        assert got[0] == 404
        assert request(server, "GET", f"/p/{server.token}/")[0] == 404
        assert not stopped.is_set()
        # A second request with the code: one of the two was not the browser.
        status, headers, body = request(server, "GET", path)
        assert status == 409 and body.decode() == page_auto.REUSED_PAGE
        assert "set-cookie" not in headers
        assert server.reused.is_set() and stopped.wait(5)
    finally:
        server.shutdown()
        server.server_close()


def test_the_code_after_the_launch_wait_gets_404_and_the_page_runs(tmp_path: Path) -> None:
    server = page_auto.AutoPageServer(tmp_path, "t-1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # No request came in LAUNCH_WAIT, so the code has no use. Nobody got the session.
        server.code_used = True
        path = server.launch_url.split(str(server.server_address[1]), 1)[1]
        assert request(server, "GET", path)[0] == 404
        assert not server.reused.is_set()
        assert request(server, "GET", f"/p/{server.token}/api/turns")[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_the_page_server_stops_after_the_page_shows_the_end(running: Any) -> None:
    root, folder = running
    server = page_auto.AutoPageServer(root, folder.name)
    stopped = threading.Event()

    def serve() -> None:
        server.serve_forever()
        stopped.set()

    threading.Thread(target=serve, daemon=True).start()
    threading.Thread(target=page_auto._watch, args=(server,), daemon=True).start()
    try:
        time.sleep(4 * page_auto.WATCH)
        assert not server.ended.is_set()
        (root / ".nookku" / "current.json").unlink()
        assert server.ended.wait(5)
        began = time.monotonic()
        status, _, body = request(server, "GET", f"/p/{server.token}/api/turns")
        assert status == 200 and json.loads(body)["test"]["running"] is False
        assert stopped.wait(5)
        # The page showed the end, so the server did not wait for the grace time.
        assert time.monotonic() - began < page_auto.END_GRACE
    finally:
        server.server_close()


def test_the_page_server_stops_after_the_grace_time_with_no_page(running: Any) -> None:
    root, folder = running
    server = page_auto.AutoPageServer(root, folder.name)
    threading.Thread(target=page_auto._watch, args=(server,), daemon=True).start()
    (root / ".nookku" / "current.json").unlink()
    began = time.monotonic()
    server.serve_forever()
    server.server_close()
    took = time.monotonic() - began
    assert page_auto.END_GRACE <= took < page_auto.END_GRACE + 2


def test_with_no_browser_and_no_terminal_no_url_and_no_server(running: Any) -> None:
    root, folder = running
    text = page_auto.after_start(root, folder.name, sys.stdout)
    assert text == page_auto.NO_BROWSER
    assert state.page_info(root) is None
    assert not (root / ".nookku" / state.PAGE_FILE).exists()
    servers = [p for p in state._children.values() if "--auto-test" in p.args]
    assert servers and all(p.poll() is not None for p in servers)


def test_the_hook_text_never_holds_the_page_url(
    running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running
    # The output of a hook is a pipe, also in a harness shell.
    monkeypatch.setenv("CLAUDECODE", "1")
    assert not page_auto.may_print_url(sys.stdout)
    text = page_auto.after_start(root, folder.name, sys.stdout)
    assert text is not None and URL.search(text) is None and "/p/" not in text


def test_the_page_server_refuses_to_give_the_url_in_a_harness_shell(
    running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running
    monkeypatch.setenv("CODEX_THREAD_ID", "t")
    text = page_auto._start(root, folder.name, print_url=True)
    assert text == page_auto.FAILED.format(reason="CODEX_THREAD_ID is set, so the URL is not shown")
    assert state.page_info(root) is None


def test_a_start_in_a_terminal_prints_the_url_and_end_stops_the_page(
    running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running
    monkeypatch.setattr(page_auto, "may_print_url", lambda out: True)
    text = page_auto.after_start(root, folder.name, sys.stdout)
    assert text is not None
    url = URL.search(text)
    assert url is not None, text
    info = state.page_info(root)
    assert info is not None and info["test"] == folder.name and state.alive(info["pid"])
    # The page file holds no token and no URL.
    assert url.group(0).split("/")[-2] not in (root / ".nookku" / state.PAGE_FILE).read_text()
    with urllib.request.urlopen(url.group(0) + "api/turns", timeout=10) as resp:
        assert json.loads(resp.read())["test"]["id"] == folder.name
    # A page server of the project runs, so a second start starts no second page.
    again = page_auto.after_start(root, folder.name, sys.stdout)
    assert again is not None and "a page server of this project runs" in again
    assert "The test continues." in again
    (root / ".nookku" / "current.json").unlink()
    began = time.monotonic()
    assert page_auto.after_end(root) is None
    assert time.monotonic() - began < page_auto.END_WAIT
    assert wait_gone(info["pid"], 1) and state.page_info(root) is None


def test_end_does_not_stop_a_page_that_the_tester_started(running: Any) -> None:
    root, _ = running
    (root / ".nookku" / "current.json").unlink()
    path, lock = page.claim_page_file(root, 1)
    try:
        began = time.monotonic()
        assert page_auto.after_end(root) is None
        assert time.monotonic() - began < 1
        assert state.page_info(root) == {"port": 1, "pid": os.getpid()}
    finally:
        path.unlink()
        os.close(lock)


def sleeper(root: Path, test: str) -> subprocess.Popen[bytes]:
    """A process that only sleeps, and a page file of a page server of the test that names it."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    state._children[proc.pid] = proc
    info = {"port": 1, "pid": proc.pid, "test": test}
    (root / ".nookku" / state.PAGE_FILE).write_text(json.dumps(info))
    return proc


def test_end_stops_a_page_server_that_does_not_stop(
    running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running
    # A page server that ignores the end of its test. It holds the page lock.
    proc = sleeper(root, folder.name)
    lock = os.open(root / ".nookku" / state.PAGE_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    (root / ".nookku" / "current.json").unlink()
    monkeypatch.setattr(page_auto, "END_WAIT", 0.5)
    try:
        assert page_auto.after_end(root) is None
    finally:
        os.close(lock)
    assert proc.poll() is not None


def test_end_sends_no_signal_to_the_pid_of_a_stale_page_file(running: Any) -> None:
    root, folder = running
    # The page server died, and a new process with no relation to the page got its pid. No
    # process holds the page lock.
    proc = sleeper(root, folder.name)
    (root / ".nookku" / state.PAGE_LOCK).touch()
    (root / ".nookku" / "current.json").unlink()
    try:
        began = time.monotonic()
        assert page_auto.after_end(root) is None
        assert time.monotonic() - began < 1
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_the_url_goes_only_to_a_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Terminal:
        def isatty(self) -> bool:
            return True

    # stdout can be a terminal while the text goes to a file, for example stderr of --json.
    with (tmp_path / "log").open("w") as log:
        assert not page_auto.may_print_url(log)
    assert page_auto.may_print_url(Terminal())  # type: ignore[arg-type]
    monkeypatch.setenv("CLAUDECODE", "1")
    assert not page_auto.may_print_url(Terminal())  # type: ignore[arg-type]


def test_a_page_that_cannot_start_does_not_stop_the_test(
    running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running

    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError("no process")

    monkeypatch.setattr(subprocess, "Popen", broken)
    monkeypatch.setattr(bridge, "start", lambda root, session=None: {"test": folder.name})
    text = kit.start_test(root)
    assert text.startswith(f"nookku: test {folder.name} started.")
    assert text.endswith("\nnookku: the chat page did not start: no process. The test continues.")
    assert kit.is_on(root)
    monkeypatch.undo()
    assert state.current(root) is not None


def test_a_toy_shop_test_starts_the_page_and_end_leaves_no_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    monkeypatch.setattr(page_auto, "may_print_url", lambda out: True)
    assert main(["start", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    cur = bridge.current(root)
    pid = page_pid(root)
    try:
        assert cur is not None and pid is not None and state.alive(pid)
        assert URL.search(out) is not None
        # A page server that fails does not stop or change the test.
        os.kill(pid, signal.SIGKILL)
        assert wait_gone(pid)
        shown, ok = bridge.send(cur, "What is the refund policy?")
        assert ok and shown.startswith("Our refund policy")
        assert bridge.current(root) is not None and kit.is_on(root)
    finally:
        assert main(["end", "--root", str(root)]) == 0
    assert "ended" in capsys.readouterr().out
    assert not state.alive(pid)


def test_a_toy_shop_end_stops_the_page_after_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    monkeypatch.setattr(page_auto, "may_print_url", lambda out: True)
    assert main(["start", "--root", str(root)]) == 0
    pid = page_pid(root)
    assert pid is not None and state.alive(pid)
    assert main(["end", "--root", str(root)]) == 0
    out = capsys.readouterr()
    assert "did not stop" not in out.err
    assert not state.alive(pid) and state.page_info(root) is None


def test_the_config_key_page_false_starts_no_page(running: Any) -> None:
    root, folder = running
    (root / ".nookku" / "config.json").write_text(json.dumps({"page": False}))
    assert page_auto.after_start(root, folder.name, sys.stdout) is None
    (root / ".nookku" / "config.json").write_text(json.dumps({"page": "no"}))
    with pytest.raises(Exception, match="'page' must be true or false"):
        kit.Config.load(root)


def test_the_page_server_does_not_look_up_the_host_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # socket.getfqdn took seconds on a CI computer, so the page server sent no status in time.
    def slow(name: str = "") -> str:
        raise AssertionError("getfqdn")

    monkeypatch.setattr(socket, "getfqdn", slow)
    server = page_auto.AutoPageServer(tmp_path, "t-1")
    server.server_close()
    assert server.server_name == page.HOST


FETCH = """
import sys, urllib.request
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
with opener.open(sys.argv[2], timeout=10) as resp:
    open(sys.argv[1], "w").write(f"{resp.status} {resp.url}")
"""
# Another process reads the launch URL in the process list, and uses it before the browser.
FIRST = """
import sys, urllib.error, urllib.request
try:
    # This process has no cookie jar, so the redirect to the page gets 404.
    urllib.request.urlopen(sys.argv[2], timeout=10)
except urllib.error.HTTPError as e:
    assert e.code == 404
try:
    urllib.request.urlopen(sys.argv[2], timeout=10)
except urllib.error.HTTPError as e:
    open(sys.argv[1], "w").write(f"{e.code} {e.read().decode()}")
"""


@pytest.fixture
def browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A computer with a display and no SSH. BROWSER names the browser command of a test."""
    monkeypatch.delenv("SSH_CONNECTION")
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    return tmp_path / "browser.txt"


def test_a_browser_that_gets_the_page_opens_it(
    running: Any, browser: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running
    script = root / "fetch.py"
    script.write_text(FETCH)
    monkeypatch.setenv("BROWSER", f"{sys.executable} {script} {browser} %s")
    assert page_auto.after_start(root, folder.name, sys.stdout) == page_auto.OPENED
    info = state.page_info(root)
    assert info is not None
    status, url = browser.read_text().split(" ", 1)
    # The browser got the launch URL, and the redirect gave it the page with its session.
    # The page key comes only in the fragment of the redirect.
    assert status == "200" and url.split("#k=")[0].endswith(page.SESSION_PATH)
    assert url.split("#")[0].split("/")[-2] == "s"


def test_a_second_use_of_the_launch_url_stops_the_page_and_the_start_says_so(
    running: Any, browser: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running
    script = root / "first.py"
    script.write_text(FIRST)
    monkeypatch.setenv("BROWSER", f"{sys.executable} {script} {browser} %s")
    text = page_auto.after_start(root, folder.name, sys.stdout)
    assert text == page_auto.FAILED.format(reason=page_auto.REUSED)
    assert state.page_info(root) is None
    status, body = browser.read_text().split(" ", 1)
    assert status == "409" and body == page_auto.REUSED_PAGE


def test_a_browser_command_that_does_not_get_the_page_gives_no_browser(
    running: Any, browser: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, folder = running
    # The command returns 0, but no request of the launch URL comes.
    monkeypatch.setenv("BROWSER", "true %s")
    began = time.monotonic()
    assert page_auto.after_start(root, folder.name, sys.stdout) == page_auto.NO_BROWSER
    assert page_auto.LAUNCH_WAIT <= time.monotonic() - began < page_auto.START_WAIT
    assert state.page_info(root) is None

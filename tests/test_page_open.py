"""The pane of the Claude Code plugin and "Open chat" (#348). The pane holds no secret, and
`nookku page --open` gives the browser only the session URL, which holds no secret. No route makes
a session or a launch code after the start launch."""

from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_page import make_folder, request, write_current
from test_page_auto import FETCH, page_pid, wait_gone

from nookku import page, page_auto, page_open, state
from nookku.cli import main
from nookku.record import Writer

ENABLED = page_auto.enabled
SECRET_PARTS = ("http://", "/o/", "/p/")


@pytest.fixture(autouse=True)
def no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_auto, "enabled", ENABLED)
    for name in page.HARNESS_SHELL:
        monkeypatch.delenv(name, raising=False)
    # No browser opens in a test: over SSH, the page server opens none.
    monkeypatch.setenv("SSH_CONNECTION", "127.0.0.1 1 127.0.0.1 2")


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """A project with a test that runs: current.json names this process as its bridge."""
    (tmp_path / ".nookku").mkdir()
    folder = make_folder(tmp_path)
    write_current(tmp_path, folder, "http://127.0.0.1:9/", "x" * 43)
    yield tmp_path, folder
    pid = page_pid(tmp_path)
    if pid is not None and pid != os.getpid() and state.alive(pid):
        os.kill(pid, signal.SIGKILL)
        wait_gone(pid)


@pytest.fixture
def browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A computer with a display and no SSH. The browser command fetches the URL with a cookie
    jar, and writes the status and the last URL."""
    monkeypatch.delenv("SSH_CONNECTION")
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    out = tmp_path / "browser.txt"
    script = tmp_path / "fetch.py"
    script.write_text(FETCH)
    monkeypatch.setenv("BROWSER", f"{sys.executable} {script} {out} %s")
    return out


def add_turn(folder: Path, said: str) -> None:
    row = {"type": "turn", "harness": "pane", "said": said, "shown": "ok", "ok": True}
    Writer(folder / "relay.jsonl").append(row)


def test_the_pane_state_of_a_project_with_no_test(tmp_path: Path) -> None:
    assert page_open.pane_state(tmp_path) == {
        "test": None,
        "state": None,
        "turns": None,
        "page": "none",
        "lines": [page_open.PANE_NO_TEST],
        "open": False,
    }


def test_the_pane_state_shows_the_running_test_and_its_turns(running: Any) -> None:
    root, folder = running
    add_turn(folder, "Do you sell mugs?")
    add_turn(folder, "And tea?")
    data = page_open.pane_state(root)
    assert data == {
        "test": folder.name,
        "state": "running",
        "turns": 2,
        "page": "none",
        "lines": [f"Test {folder.name}: running, 2 turns", page_open.PANE_NO_PAGE],
        "open": False,
    }


def test_the_pane_state_shows_the_latest_test_after_its_end(running: Any) -> None:
    root, folder = running
    (root / ".nookku" / "current.json").unlink()
    (folder / "manifest.json").write_text(json.dumps({"started": 1.0, "ended": 2.0}))
    data = page_open.pane_state(root)
    assert data["test"] == folder.name and data["state"] == "ended" and data["turns"] == 0
    assert data["lines"] == [f"Test {folder.name}: ended, 0 turns"] and not data["open"]


def test_status_json_gives_the_pane_state_with_no_secret(
    running: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    root, folder = running
    assert main(["status", "--json", "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    pane = out["pane"]
    assert (pane["test"], pane["state"], pane["turns"], pane["page"]) == (
        folder.name,
        "running",
        0,
        "none",
    )
    assert "x" * 43 not in json.dumps(out)


def test_open_with_no_test_prints_the_step_to_start_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["page", "--open", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out.strip() == page_open.NO_TEST


def test_open_with_a_page_of_nookku_page_names_its_terminal(running: Any) -> None:
    root, _ = running
    _, lock = page.claim_page_file(root, 9)
    try:
        assert page_open.page_state(root) == "manual"
        data = page_open.pane_state(root)
        assert data["lines"][1] == page_open.PANE_MANUAL and not data["open"]
        assert page_open.open_chat(root) == (1, page_open.MANUAL)
    finally:
        os.close(lock)
        (root / ".nookku" / state.PAGE_FILE).unlink()


def test_open_with_no_page_server_starts_none_and_gives_the_step(
    running: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = running
    assert main(["page", "--open", "--root", str(root)]) == 1
    assert capsys.readouterr().out.strip() == page_open.NO_PAGE
    assert page_open.page_state(root) == "none" and state.page_info(root) is None


def record(opened: list[str]) -> Any:
    """A browser that opens each URL. It writes the URL to `opened`."""

    def open_browser(url: str) -> bool:
        opened.append(url)
        return True

    return open_browser


@pytest.fixture
def server(running: Any) -> Iterator[page_auto.AutoPageServer]:
    root, folder = running
    srv = page_auto.AutoPageServer(root, folder.name)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_no_route_makes_a_session_or_a_launch_code_after_the_start_launch(
    server: page_auto.AutoPageServer,
) -> None:
    port = server.server_address[1]
    status, headers, _ = request(server, "GET", f"/o/{server.code}")
    assert status == 303 and "set-cookie" in headers
    code, session = server.code, server.session
    no_origin = {"Origin": ""}
    tries = [
        ("POST", "/o/new", {}, no_origin),
        ("POST", "/o/new", {}, None),
        ("GET", "/o/new", None, None),
        ("GET", f"/o/{secrets.token_urlsafe(32)}", None, None),
        ("GET", page.SESSION_PATH, None, None),
        ("GET", f"/p/{server.token}/", None, None),
        ("POST", f"{page.SESSION_PATH}api/open", {}, None),
    ]
    for method, path, body, headers in tries:
        status, got, _ = request(server, method, path, body, headers)
        assert status >= 400 and "set-cookie" not in got, (method, path)
    assert (server.code, server.session, server.code_used) == (code, session, True)
    assert not server.reused.is_set()
    # The page itself tells a browser with no session how to get one, and gives none.
    status, got, body = request(server, "GET", page.SESSION_PATH)
    assert status == 404 and body.decode() == page.NO_SESSION
    assert "set-cookie" not in got
    # The browser with the session cookie of the start launch opens the session URL.
    cookie = {"Cookie": f"{server.cookie_name}={session}", "Host": f"127.0.0.1:{port}"}
    assert request(server, "GET", page.SESSION_PATH, None, cookie)[0] == 200


def test_open_gives_the_browser_only_the_session_url_and_prints_no_url(
    server: page_auto.AutoPageServer,
    running: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, folder = running
    port = server.server_address[1]
    _, lock = page.claim_page_file(root, port, test=folder.name)
    opened: list[str] = []
    monkeypatch.setattr(page_auto, "_can_open", lambda: True)
    monkeypatch.setattr(page_auto, "_open_browser", record(opened))
    try:
        assert page_open.page_state(root) == "test" and page_open.pane_state(root)["open"]
        code, session = server.code, server.session
        assert main(["page", "--open", "--root", str(root)]) == 0
        out = capsys.readouterr().out
        assert out.strip() == page_open.OPENED
        assert not any(part in out for part in SECRET_PARTS)
        assert opened == [f"http://127.0.0.1:{port}{page.SESSION_PATH}"]
        assert (server.code, server.session, server.code_used) == (code, session, False)
        # A browser that cannot open gets the step, and still no URL.
        monkeypatch.setattr(page_auto, "_open_browser", lambda url: False)
        assert page_open.open_chat(root) == (1, page_open.NO_BROWSER)
    finally:
        os.close(lock)
        (root / ".nookku" / state.PAGE_FILE).unlink()


def test_a_toy_shop_test_shows_its_state_and_open_chat_opens_the_page(
    tmp_path: Path,
    browser: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    toy_shop = Path(__file__).resolve().parent.parent / "examples" / "toy-shop" / "agent.py"
    conf = {"entry": [sys.executable, str(toy_shop)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    assert main(["start", "--root", str(root)]) == 0
    capsys.readouterr()
    opened: list[str] = []
    monkeypatch.setattr(page_auto, "_open_browser", record(opened))
    try:
        # The start launch gave the browser a session.
        status, url = browser.read_text().split(" ", 1)
        # The page key comes only in the fragment of the redirect.
        assert status == "200" and url.split("#k=")[0].endswith(page.SESSION_PATH)
        pane = page_open.pane_state(root)
        assert pane["state"] == "running" and pane["page"] == "test" and pane["open"]
        assert main(["page", "--open", "--root", str(root)]) == 0
        assert capsys.readouterr().out.strip() == page_open.OPENED
        # Open chat gives no key: the new tab asks the open tab of the page for it (key.js).
        assert opened == [url.split("#")[0]]
    finally:
        assert main(["end", "--root", str(root)]) == 0
    capsys.readouterr()
    pane = page_open.pane_state(root)
    assert pane["state"] == "ended" and pane["page"] == "none" and not pane["open"]
    assert main(["page", "--open", "--root", str(root)]) == 1
    assert capsys.readouterr().out.strip() == page_open.NO_TEST

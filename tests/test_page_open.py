"""The pane of the Claude Code plugin and "Open chat" (#348). The pane holds no secret, and
`nookku page --open` gives a new launch URL only to the browser."""

from __future__ import annotations

import json
import os
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
        "open": True,
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


@pytest.fixture
def server(running: Any) -> Iterator[page_auto.AutoPageServer]:
    root, folder = running
    srv = page_auto.AutoPageServer(root, folder.name)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_a_launch_needs_no_origin_json_and_the_right_host(
    server: page_auto.AutoPageServer,
) -> None:
    # A browser always sends Origin with a POST, so a web page cannot ask for a launch.
    assert request(server, "POST", page_open.ROUTE, {})[0] == 403
    no_origin = {"Origin": ""}
    assert request(server, "POST", page_open.ROUTE, {}, no_origin | {"Host": "x.test"})[0] == 403
    text = no_origin | {"Content-Type": "text/plain"}
    assert request(server, "POST", page_open.ROUTE, {}, text)[0] == 415
    assert request(server, "POST", f"{page_open.ROUTE}?x=1", {}, no_origin)[0] == 403


def test_a_launch_with_no_browser_makes_a_new_code_and_answers_no_secret(
    server: page_auto.AutoPageServer,
) -> None:
    old = server.launch_url.split(str(server.server_address[1]), 1)[1]
    status, _, body = request(server, "POST", page_open.ROUTE, {}, {"Origin": ""})
    assert status == 200 and json.loads(body) == {"status": "no-browser"}
    assert server.code not in body.decode() and server.token not in body.decode()
    # The old code has no use, and the new code has no use after the launch wait.
    assert request(server, "GET", old)[0] == 404
    new = server.launch_url.split(str(server.server_address[1]), 1)[1]
    assert new != old and request(server, "GET", new)[0] == 404
    assert not server.reused.is_set()


def test_a_launch_after_the_end_of_the_test_is_refused(server: page_auto.AutoPageServer) -> None:
    server.ended.set()
    status, _, body = request(server, "POST", page_open.ROUTE, {}, {"Origin": ""})
    assert status == 409 and json.loads(body) == {"status": "ended"}


def test_open_starts_the_page_then_gives_the_browser_a_new_launch_and_prints_no_url(
    running: Any, browser: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = running
    # No page server runs, so open starts one, as the start of a test does.
    assert main(["page", "--open", "--root", str(root)]) == 0
    first = capsys.readouterr().out
    assert first.strip() == page_auto.OPENED
    assert page_open.page_state(root) == "test"
    status, url = browser.read_text().split(" ", 1)
    assert status == "200" and url.endswith(page.SESSION_PATH)
    browser.unlink()
    # The page server runs, so open asks it for a new launch code.
    assert main(["page", "--open", "--root", str(root)]) == 0
    second = capsys.readouterr().out
    assert second.strip() == page_open.OPENED
    status, url = browser.read_text().split(" ", 1)
    assert status == "200" and url.endswith(page.SESSION_PATH)
    for text in (first, second):
        assert not any(part in text for part in SECRET_PARTS)


def test_a_toy_shop_test_shows_its_state_and_open_chat_opens_the_page(
    tmp_path: Path, browser: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    toy_shop = Path(__file__).resolve().parent.parent / "examples" / "toy-shop" / "agent.py"
    conf = {"entry": [sys.executable, str(toy_shop)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    assert main(["start", "--root", str(root)]) == 0
    capsys.readouterr()
    try:
        browser.unlink()
        pane = page_open.pane_state(root)
        assert pane["state"] == "running" and pane["page"] == "test" and pane["open"]
        assert main(["page", "--open", "--root", str(root)]) == 0
        assert capsys.readouterr().out.strip() == page_open.OPENED
        status, url = browser.read_text().split(" ", 1)
        assert status == "200" and url.endswith(page.SESSION_PATH)
    finally:
        assert main(["end", "--root", str(root)]) == 0
    capsys.readouterr()
    pane = page_open.pane_state(root)
    assert pane["state"] == "ended" and pane["page"] == "none" and not pane["open"]
    assert main(["page", "--open", "--root", str(root)]) == 1
    assert capsys.readouterr().out.strip() == page_open.NO_TEST

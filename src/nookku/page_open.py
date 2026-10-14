"""The pane of the Claude Code plugin: the state of the test, and "Open chat" (#348).

The pane shows the text of `nookku status --json`. The harness can show a pane or a command
output to the model, so the pane holds no secret: no page URL, no token, no launch code and no
cookie (SPEC.md section 5, "Pane").

"Open chat" runs `nookku page --open`. It never prints a URL. It asks the page server of the
running test to make a new launch code and to give it to the browser. If no page server runs, it
starts one, as the start of a test does. Only the browser gets the new launch URL, so a process
that runs `nookku page --open` gets no secret.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nookku import dashboard, page, page_auto, state
from nookku.record import RecordError, turns

if TYPE_CHECKING:
    from nookku.page_auto import _AutoHandler

# The path of the request for a new launch code. Only a POST with no Origin gets it.
ROUTE = "/o/new"
# The wait of `nookku page --open` for the answer of the page server.
OPEN_ANSWER_WAIT = page_auto.LAUNCH_WAIT + page_auto.REUSE_WAIT + 5.0

OPENED = "The chat page opened in your browser."
NO_TEST = "nookku: no test runs, so the chat page has no test. Start one with: nookku start"
MANUAL = (
    "nookku: the chat page runs from nookku page. Open it with the URL that nookku page printed "
    "in its terminal."
)
OTHER_TEST = (
    "nookku: the chat page of test {test} still runs. It stops in a few seconds. Then try again."
)
PANE_NO_TEST = "No test runs. Start one with: /nookku start"
PANE_PAGE = "Chat page: runs. Open chat opens it in your browser."
PANE_MANUAL = (
    "Chat page: runs from nookku page. Open it with the URL in the terminal of that command."
)
PANE_NO_PAGE = (
    "Chat page: does not run. Press Open chat to start it, or run nookku page in a separate "
    "terminal."
)
ANSWERS = {
    "opened": OPENED,
    "no-browser": (
        "nookku: the browser did not open. The chat page still runs. If it is open in your "
        "browser, use it there."
    ),
    "reused": (
        "nookku: another process used the new launch URL of the chat page first, so the page "
        "stopped. To use the page, run nookku page in a separate terminal."
    ),
    "busy": "nookku: the chat page is already opening in your browser.",
    "ended": "nookku: the test of the chat page ended.",
}


def pane_state(root: Path) -> dict[str, Any]:
    """The data of the pane: the running test, else the latest test, with its state and its count
    of turns, and the state of the chat page. `lines` is the text of the pane, and `open` is true
    if the pane shows "Open chat". The plugin holds no text, so the core gives the lines. Change
    no file."""
    data = _pane_data(root)
    data["lines"] = pane_lines(data)
    data["open"] = data["state"] == "running" and data["page"] != "manual"
    return data


def pane_lines(data: dict[str, Any]) -> list[str]:
    """The text of the pane for the data of pane_state."""
    if data["test"] is None:
        return [PANE_NO_TEST]
    turns = "turns not known" if data["turns"] is None else f"{data['turns']} turns"
    lines = [f"Test {data['test']}: {data['state']}, {turns}"]
    if data["page"] == "test":
        lines.append(PANE_PAGE)
    elif data["page"] == "manual":
        lines.append(PANE_MANUAL)
    elif data["state"] == "running":
        lines.append(PANE_NO_PAGE)
    return lines


def _pane_data(root: Path) -> dict[str, Any]:
    running = dashboard.running_id(root)
    folder = dashboard.find(root, running) if running else state.latest_test(root)
    data: dict[str, Any] = {"test": None, "state": None, "turns": None, "page": page_state(root)}
    if folder is None:
        return data
    if folder.name == running:
        test_state = "running"
    else:
        manifest = state.manifest_of(folder)
        test_state = "unknown" if manifest is None else "stopped"
        if manifest is not None and manifest.get("ended") is not None:
            test_state = "ended"
    count: int | None
    try:
        count = len(turns(folder / "relay.jsonl", missing_ok=True))
    except RecordError:
        count = None
    data.update(test=folder.name, state=test_state, turns=count)
    return data


def page_state(root: Path) -> str:
    """`test` if a page server that a test start started runs, `manual` if a page server of
    `nookku page` runs, else `none`."""
    info = state.page_info(root)
    if info is None or not page_auto._held(root):
        return "none"
    return "test" if isinstance(info.get("test"), str) else "manual"


def open_chat(root: Path) -> tuple[int, str]:
    """`nookku page --open`: give the browser a new launch URL of the chat page of the running
    test. Return the exit code and the text to print. The text never holds a URL."""
    test = dashboard.running_id(root)
    if test is None:
        return 1, NO_TEST
    info = state.page_info(root)
    if info is None or not page_auto._held(root):
        # No page server runs: start one, as the start of a test does. The text has no URL.
        text = page_auto._start(root, test, print_url=False)
        return (0 if text == page_auto.OPENED else 1), text
    if not isinstance(info.get("test"), str):
        return 1, MANUAL
    if info["test"] != test:
        return 1, OTHER_TEST.format(test=info["test"])
    status = _ask(info["port"])
    return (0 if status == "opened" else 1), ANSWERS.get(
        status, f"nookku: the chat page did not open: {status}"
    )


def _ask(port: int) -> str:
    """Ask the page server for a new launch code. Return its status. Go direct to 127.0.0.1, with
    no proxy of the environment."""
    conn = http.client.HTTPConnection(page.HOST, port, timeout=OPEN_ANSWER_WAIT)
    try:
        conn.request(
            "POST",
            ROUTE,
            body=b"{}",
            headers={"Host": f"{page.HOST}:{port}", "Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read())
    except (OSError, ValueError, http.client.HTTPException) as e:
        return f"no answer from the page server ({e})"
    finally:
        conn.close()
    status = data.get("status") if isinstance(data, dict) else None
    return status if isinstance(status, str) else "the page server gave no status"


def relaunch(handler: _AutoHandler) -> None:
    """The answer of the page server to `POST /o/new`: make a new launch code, and give it only to
    the browser. The answer holds only a status.

    A browser always sends `Origin` with a POST, and a POST with `Content-Type: application/json`
    from another site needs a preflight, which the page refuses (405). Thus a web page cannot
    ask for a launch. A local process can ask, but it gets no secret."""
    server = handler.server
    hosts = handler.headers.get_all("Host") or []
    if len(hosts) != 1 or hosts[0].lower() not in server.hosts:
        handler._refuse(403, "wrong Host header")
        return
    if handler.headers.get_all("Origin"):
        handler._refuse(403, "a launch takes no Origin header")
        return
    kind = (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if kind != "application/json":
        handler._refuse(415, "the Content-Type must be application/json")
        return
    if server.ended.is_set():
        handler._json(409, {"status": "ended"})
        return
    if not server.relaunch_lock.acquire(blocking=False):
        handler._json(409, {"status": "busy"})
        return
    try:
        with server.code_lock:
            # The old code has no use now. The session stays, so an open page keeps working.
            server.code = secrets.token_urlsafe(32)
            server.code_used = False
            server.launched.clear()
        if page_auto._launched(server):
            status = "opened"
        elif server.reused.is_set():
            status = "reused"
        else:
            status = "no-browser"
    finally:
        server.relaunch_lock.release()
    with contextlib.suppress(OSError):
        handler._json(200, {"status": status})

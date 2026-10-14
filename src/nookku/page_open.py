"""The pane of the Claude Code plugin: the state of the test, and "Open chat" (#348).

The pane shows the text of `nookku status --json`. The harness can show a pane or a command
output to the model, so the pane holds no secret: no page URL, no token, no launch code and no
cookie (SPEC.md section 5, "Pane").

"Open chat" runs `nookku page --open`. It gives the browser the session URL of the chat page,
`http://127.0.0.1:<port>/p/s/`. This URL holds no token and no code. Only the session cookie of
the start launch opens the page. No route makes a session or a launch code after the start
launch, so a local process that runs `nookku page --open` or calls the page gets no session.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nookku import dashboard, page, page_auto, state
from nookku.record import RecordError, turns

OPENED = (
    "The chat page opened in your browser. If the browser shows no session, use the browser "
    "that opened the page at the start of the test."
)
NO_BROWSER = (
    "nookku: the browser did not open. Open the chat page in the browser that opened it at the "
    "start of the test."
)
NO_PAGE = (
    "nookku: the chat page of the test does not run. Run nookku page in a separate terminal, or "
    "end the test and start a new one."
)
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
    "Chat page: does not run. Run nookku page in a separate terminal, or end the test and "
    "start a new one."
)


def pane_state(root: Path) -> dict[str, Any]:
    """The data of the pane: the running test, else the latest test, with its state and its count
    of turns, and the state of the chat page. `lines` is the text of the pane, and `open` is true
    if the pane shows "Open chat". The plugin holds no text, so the core gives the lines. Change
    no file."""
    data = _pane_data(root)
    data["lines"] = pane_lines(data)
    data["open"] = data["state"] == "running" and data["page"] == "test"
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
    """`nookku page --open`: give the browser the session URL of the chat page of the running
    test. Return the exit code and the text to print. The text never holds a URL. Make no session,
    no launch code and no page server."""
    test = dashboard.running_id(root)
    if test is None:
        return 1, NO_TEST
    info = state.page_info(root)
    if info is None or not page_auto._held(root):
        return 1, NO_PAGE
    if not isinstance(info.get("test"), str):
        return 1, MANUAL
    if info["test"] != test:
        return 1, OTHER_TEST.format(test=info["test"])
    if not page_auto._can_open() or not page_auto._open_browser(session_url(info["port"])):
        return 1, NO_BROWSER
    return 0, OPENED


def session_url(port: int) -> str:
    """The session URL of the chat page. It holds no token and no code."""
    return f"http://{page.HOST}:{port}{page.SESSION_PATH}"

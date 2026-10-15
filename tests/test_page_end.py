"""The "End test" button of the chat page: the route api/end (#391)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_page import cookie_only, make_folder, request, session, start_page, write_current

from nookku import bridge, kit, page, page_end, state
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
END = page.SESSION_PATH + page_end.ROUTE


@pytest.fixture(autouse=True)
def no_harness_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in page.HARNESS_SHELL:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[page.PageServer]:
    (tmp_path / ".nookku").mkdir(exist_ok=True)
    found = start_page(tmp_path)
    yield found
    found.shutdown()
    found.server_close()


def end(server: page.PageServer, body: Any, headers: dict[str, str]) -> tuple[int, Any]:
    status, _, data = request(server, "POST", END, body, headers)
    try:
        return status, json.loads(data)
    except ValueError:
        return status, data


def fake_test(root: Path, **manifest: Any) -> Path:
    """A test in current.json. Its bridge pid is this process, so the end must refuse first."""
    folder = make_folder(root)
    data = {"started": 1_800_000_000.0, "ended": None, **manifest}
    (folder / "manifest.json").write_text(json.dumps(data))
    write_current(root, folder, "http://127.0.0.1:9/", "x" * 43)
    kit.set_mode(root, True)
    return folder


def test_the_end_needs_the_session_the_key_and_the_origin(server: page.PageServer) -> None:
    root = server.root
    folder = fake_test(root)
    both = session(server)
    body = {"test": folder.name}
    # The model has no page key, so it cannot end a test with the page.
    assert end(server, body, {})[0] == 404
    assert end(server, body, cookie_only(both))[0] == 404
    assert end(server, body, {**both, "Origin": "http://127.0.0.1:1"})[0] == 403
    assert end(server, body, {**both, "Origin": ""})[0] == 403
    assert end(server, body, {**both, "Content-Type": "text/plain"})[0] == 415
    assert end(server, {}, both)[0] == 400
    assert end(server, {"test": "a\x00b"}, both)[0] == 400
    # No request ended the test.
    assert state.current(root) is not None and kit.is_on(root)


def test_the_page_ends_only_the_running_test_that_it_shows(server: page.PageServer) -> None:
    root = server.root
    folder = fake_test(root)
    both = session(server)
    status, data = end(server, {"test": "20261013-080000-ffff"}, both)
    assert status == 200 and data["ended"] is False
    assert data["error"] == page_end.OTHER_TEST.format(
        shown="20261013-080000-ffff", running=folder.name
    )
    assert state.current(root) is not None and kit.is_on(root)


@pytest.mark.parametrize(
    ("manifest", "error"),
    [({"script": {"path": "x"}}, page_end.SCRIPTED), ({"check": True}, page_end.CHECK)],
)
def test_the_page_does_not_end_a_scripted_or_a_check_test(
    server: page.PageServer, manifest: dict[str, Any], error: str
) -> None:
    folder = fake_test(server.root, **manifest)
    status, data = end(server, {"test": folder.name}, session(server))
    assert status == 200 and data == {"ended": False, "error": error}
    assert kit.is_on(server.root)


def test_the_page_refuses_the_end_while_it_sends_a_message(server: page.PageServer) -> None:
    folder = fake_test(server.root)
    both = session(server)
    # A send of the page holds this lock while it waits for the reply.
    with server.lock:
        status, data = end(server, {"test": folder.name}, both)
    assert status == 409 and data == {"ended": False, "error": page_end.SENDING}
    assert kit.is_on(server.root)


def test_a_test_that_starts_during_the_end_keeps_relay_mode_on(
    server: page.PageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test A ends in another process and test B starts after the first check of the page. The
    page must not leave B with relay mode off (code review of #403)."""
    root = server.root
    folder = fake_test(root)
    other = root / ".nookku" / "tests" / "20261013-100000-cd34"

    def other_starts(*args: Any, **kwargs: Any) -> None:
        other.mkdir(parents=True)
        write_current(root, other, "http://127.0.0.1:9/", "y" * 43)
        assert not kit.is_on(root)
        return None

    monkeypatch.setattr(bridge, "end", other_starts)
    status, data = end(server, {"test": folder.name}, session(server))
    assert status == 200 and data["ended"] is False
    assert data["error"] == page_end.OTHER_TEST.format(shown=folder.name, running=other.name)
    assert kit.is_on(root)


def test_when_the_bridge_does_not_end_the_test_the_page_says_so(
    server: page.PageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = fake_test(server.root)
    monkeypatch.setattr(bridge, "end", lambda *args, **kwargs: None)
    status, data = end(server, {"test": folder.name}, session(server))
    assert status == 200 and data == {"ended": False, "error": page_end.NOT_ENDED}


def test_with_no_test_the_page_ends_nothing(server: page.PageServer) -> None:
    status, data = end(server, {"test": "20261013-090000-ab12"}, session(server))
    assert status == 200 and data == {"ended": False, "error": page_end.NO_TEST}


def test_a_toy_shop_test_ends_from_the_page_and_the_page_still_exports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    assert main(["start", "--root", str(root)]) == 0
    capsys.readouterr()
    cur = bridge.current(root)
    assert cur is not None
    server = start_page(root)
    try:
        both = session(server)
        status, data = end(server, {"test": cur["test"]}, both)
        assert status == 200 and data["ended"] is True, data
        assert cur["test"] in data["text"]
        # The same end as `nookku end` in a shell: relay mode off, the test sealed.
        assert bridge.current(root) is None and not kit.is_on(root)
        folder = Path(cur["dir"])
        assert state.manifest_of(folder)["ended"] is not None  # type: ignore[index]
        assert state.closed(folder)
        # The test already ended, so a second end ends nothing.
        status, data = end(server, {"test": cur["test"]}, both)
        assert status == 200 and data == {"ended": False, "error": page_end.NO_TEST}
        # The page server still serves the test, and the export works.
        status, _, body = request(server, "GET", page.SESSION_PATH + "api/turns", None, both)
        assert status == 200 and json.loads(body)["test"]["running"] is False
        path = page.SESSION_PATH + f"api/export/{cur['test']}"
        assert request(server, "GET", path, None, both)[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        if bridge.current(root) is not None:
            main(["end", "--root", str(root)])


NODE = shutil.which("node")
# A small DOM for node: only what end_button.js uses.
BUTTON_CHECK = """
const ids = {}; const listeners = {}; const events = []; const sent = [];
class El {
  constructor(id) { this.id = id; this.hidden = false; this.disabled = false; this.attrs = {};
    this.textContent = ""; this.dataset = {}; this.listeners = {}; ids[id] = this; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
  focus() { global.focused = this.id; }
}
for (const id of ["end-test", "endconfirm", "endconfirm-yes", "endconfirm-no", "end-result",
    "test"]) { new El(id); }
ids.endconfirm.hidden = true;
ids.test.dataset.id = "20261013-090000-ab12";
global.CustomEvent = class {
  constructor(type, init) { this.type = type; this.detail = init.detail; }
};
global.document = {
  getElementById: (id) => ids[id],
  addEventListener: (kind, fn) => { (listeners[kind] = listeners[kind] || []).push(fn); },
  dispatchEvent: (e) => events.push(e),
};
let answer = null;
global.fetch = async (url, init) => { sent.push([url, init.method, JSON.parse(init.body)]);
  if (answer === "down") { throw new Error("down"); } return { json: async () => answer }; };
require(process.argv[2]);
listeners.DOMContentLoaded.forEach((fn) => fn());
(async () => {
  const out = {};
  ids["end-test"].listeners.click[0]();
  out.open = !ids.endconfirm.hidden && global.focused === "endconfirm-no";
  ids["endconfirm-no"].listeners.click[0]();
  out.cancel = ids.endconfirm.hidden && sent.length === 0;
  answer = { ended: false, error: "nookku: no test runs, so the page ended nothing." };
  ids["end-test"].listeners.click[0]();
  await ids["endconfirm-yes"].listeners.click[0]();
  out.refused = [ids["end-result"].textContent, ids.endconfirm.hidden, events.length];
  answer = "down";
  // A click on "End test" again opens the confirm again.
  ids["end-test"].listeners.click[0]();
  await ids["endconfirm-yes"].listeners.click[0]();
  out.down = ids["end-result"].textContent;
  answer = { ended: true, text: "ended" };
  // The confirm opened for one test, but the page now shows another test: end nothing.
  ids["end-test"].listeners.click[0]();
  ids.test.dataset.id = "20261013-100000-cd34";
  const before = sent.length;
  await ids["endconfirm-yes"].listeners.click[0]();
  out.changed = [ids["end-result"].textContent, ids.endconfirm.hidden, sent.length - before];
  ids.test.dataset.id = "20261013-090000-ab12";
  ids["end-test"].listeners.click[0]();
  await ids["endconfirm-yes"].listeners.click[0]();
  out.ended = events.map((e) => [e.type, e.detail.test]);
  out.sent = sent;
  process.stdout.write(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
def test_the_button_asks_first_and_sends_only_the_shown_test(tmp_path: Path) -> None:
    harness = tmp_path / "harness.js"
    harness.write_text(BUTTON_CHECK)
    script = ROOT / "src" / "nookku" / "page" / "end_button.js"
    done = subprocess.run(
        [str(NODE), str(harness), str(script)], capture_output=True, text=True, check=True
    )
    out = json.loads(done.stdout)
    # A click shows the confirm, and Cancel sends nothing.
    assert out["open"] is True and out["cancel"] is True
    assert out["refused"] == ["nookku: no test runs, so the page ended nothing.", True, 0]
    assert out["down"] == "nookku: the page server does not answer. The test runs."
    assert out["changed"] == [
        "nookku: the page now shows another test, so the page ended nothing.",
        True,
        0,
    ]
    assert out["ended"] == [["nookku:ended", "20261013-090000-ab12"]]
    assert out["sent"] == [["api/end", "POST", {"test": "20261013-090000-ab12"}]] * 3

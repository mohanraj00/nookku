"""The dashboard of the chat page (#349): one row for each test, read from the test folders."""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from nookku import bridge, dashboard, kit, page, seal
from nookku.audit import audit
from nookku.record import Writer

# 3 toy shop tests. The second one has a changed reply, so its audit has 1 break.
TESTS: list[dict[str, Any]] = [
    {
        "id": "20261013-090000-aa11",
        "started": 1_800_000_000.0,
        "turns": [("Is the mug dishwasher safe?", "Yes.", "Yes.")],
        "findings": [],
    },
    {
        "id": "20261013-091000-bb22",
        "started": 1_800_000_600.0,
        "turns": [
            ("Hi, I want to return order #4471.", "You can return it.", "You can return it."),
            ("Do you ship to Chennai?", "Yes, we ship to Chennai.", "Yes, we ship to Chennai!"),
            ("Thanks.", "You are welcome.", "You are welcome."),
        ],
        "findings": [{"check": "agent_error", "turn": 2, "detail": "status 500"}],
    },
    {
        "id": "20261013-092000-cc33",
        "started": 1_800_001_200.0,
        "turns": [
            ("Can I pay in € or ₹?", "We accept € and ₹.", "We accept € and ₹."),
            ("Is the teapot in stock?", "No.", "No."),
        ],
        "findings": [{"check": "tool_error", "turn": 1, "detail": "stock tool failed"}],
    },
]


def make_test(root: Path, spec: dict[str, Any], sealed: bool = True) -> Path:
    """An ended test folder with its records, its audit, its findings and its seal."""
    folder = root / ".nookku" / "tests" / spec["id"]
    folder.mkdir(parents=True)
    manifest = {"started": spec["started"], "ended": spec["started"] + 60}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    relay, tap = Writer(folder / "relay.jsonl"), Writer(folder / "tap.jsonl")
    for said, reply, shown in spec["turns"]:
        tap.append({"type": "exchange", "input": said, "status": 200, "reply": reply})
        relay.append({"type": "turn", "harness": "pane", "said": said, "shown": shown, "ok": True})
    report = audit(folder / "tap.jsonl", folder / "relay.jsonl").as_dict()
    (folder / "audit.json").write_text(json.dumps(report))
    found = {"test": spec["id"], "findings": spec["findings"]}
    (folder / "findings.json").write_text(json.dumps(found))
    if sealed:
        seal.write(folder)
    return folder


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for spec in TESTS:
        make_test(tmp_path, spec)
    return tmp_path


@pytest.fixture
def server(project: Path) -> Iterator[page.PageServer]:
    srv = page.PageServer(project)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def get(
    srv: page.PageServer, rest: str, headers: dict[str, str] | None = None, token: str = ""
) -> tuple[int, dict[str, str], bytes]:
    port = srv.server_address[1]
    sent = {"Host": f"127.0.0.1:{port}"} | (headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("GET", f"/p/{token or srv.token}/{rest}", headers=sent)
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def get_json(srv: page.PageServer, rest: str) -> dict[str, Any]:
    status, _, body = get(srv, rest)
    assert status == 200, body
    data: dict[str, Any] = json.loads(body)
    return data


def counts_from_files(folder: Path) -> dict[str, Any]:
    """The counts of a test, read from its files here, not with the code of the dashboard."""
    lines = (folder / "relay.jsonl").read_text(encoding="utf-8").splitlines()
    turns = sum(1 for line in lines if json.loads(line)["type"] == "turn")
    breaks = len(json.loads((folder / "audit.json").read_text())["breaks"])
    findings = len(json.loads((folder / "findings.json").read_text())["findings"])
    return {"turns": turns, "breaks": breaks, "findings": findings}


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Each file of the project and of the seal home, with its bytes and its change time."""
    found = {}
    for base in (root, seal.home()):
        for path in sorted(base.rglob("*")):
            if path.is_file():
                found[str(path)] = (path.read_bytes(), path.stat().st_mtime_ns)
    return found


def test_three_tests_show_three_rows_with_the_counts_of_their_files(
    project: Path, server: page.PageServer
) -> None:
    data = get_json(server, "api/tests")
    assert data["error"] is None
    rows = data["tests"]
    assert [r["id"] for r in rows] == [t["id"] for t in reversed(TESTS)]
    for r in rows:
        folder = project / ".nookku" / "tests" / r["id"]
        manifest = json.loads((folder / "manifest.json").read_text())
        assert {k: r[k] for k in ("turns", "breaks", "findings")} == counts_from_files(folder)
        assert r["started"] == manifest["started"] and r["ended"] == manifest["ended"]
        assert r["state"] == "ended"
        assert r["seal"] == "intact"
        assert r["errors"] == []
    by_id = {r["id"]: r for r in rows}
    assert by_id[TESTS[1]["id"]]["breaks"] == 1
    assert by_id[TESTS[0]["id"]]["breaks"] == 0


def test_the_break_filter_shows_only_the_test_with_the_break(server: page.PageServer) -> None:
    rows = get_json(server, "api/tests/all/break/newest")["tests"]
    assert [r["id"] for r in rows] == [TESTS[1]["id"]]
    rows = get_json(server, "api/tests/all/finding/newest")["tests"]
    assert [r["id"] for r in rows] == [TESTS[2]["id"], TESTS[1]["id"]]


def test_the_sort_and_the_state_filter(project: Path, server: page.PageServer) -> None:
    rows = get_json(server, "api/tests/all/all/oldest")["tests"]
    assert [r["id"] for r in rows] == [t["id"] for t in TESTS]
    assert get_json(server, "api/tests/running/all/newest")["tests"] == []
    # A test with no end time and no bridge is a stopped test.
    folder = project / ".nookku" / "tests" / TESTS[0]["id"]
    (folder / "manifest.json").write_text(json.dumps({"started": 1.0, "ended": None}))
    rows = get_json(server, "api/tests/stopped/all/newest")["tests"]
    assert [r["id"] for r in rows] == [TESTS[0]["id"]]
    # The manifest changed after the seal, so the seal is broken.
    assert rows[0]["seal"] == "broken"


def test_a_running_test_shows_as_running_and_its_chat_page_can_send(
    project: Path, server: page.PageServer
) -> None:
    folder = project / ".nookku" / "tests" / "20261013-093000-dd44"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"started": 1_800_001_800.0, "ended": None}))
    cur = {
        "v": 1,
        "test": folder.name,
        "dir": str(folder),
        "tap_url": "http://127.0.0.1:9",
        "pid": os.getpid(),
        "pid_start": bridge.process_start(os.getpid()),
    }
    (project / ".nookku" / "current.json").write_text(json.dumps(cur))
    rows = get_json(server, "api/tests/running/all/newest")["tests"]
    assert [(r["id"], r["turns"], r["breaks"], r["seal"]) for r in rows] == [
        (folder.name, 0, None, "none")
    ]
    assert get_json(server, f"api/turns/{folder.name}")["test"]["running"] is True
    # The chat page of an ended test is read-only: the test does not run.
    ended = get_json(server, f"api/turns/{TESTS[1]['id']}")
    assert ended["test"]["running"] is False
    assert [t["said"] for t in ended["turns"]] == [t[0] for t in TESTS[1]["turns"]]
    assert [t["shown"] for t in ended["turns"]] == [t[2] for t in TESTS[1]["turns"]]


@pytest.mark.parametrize(
    "rest",
    [
        "api/turns/nothing",
        "api/turns/..",
        "api/turns/..%2F..%2Fconfig.json",
        "api/turns/%2Fetc%2Fpasswd",
        "api/turns/",
        "api/tests/all",
        "api/tests/all/all",
        "api/tests/x/all/newest",
        "api/tests/all/x/newest",
        "api/tests/all/all/x",
        "api/tests/all/all/newest/x",
    ],
)
def test_a_wrong_test_id_or_filter_gets_404(server: page.PageServer, rest: str) -> None:
    status, _, body = get(server, rest)
    assert status == 404, body


def test_the_dashboard_changes_no_file(project: Path, server: page.PageServer) -> None:
    # A stale current.json: the chat page removes it, but the dashboard must not.
    stale = {"v": 1, "test": "x", "dir": str(project), "pid": 2**22 + 7, "pid_start": "ps:none"}
    (project / ".nookku" / "current.json").write_text(json.dumps(stale))
    before = snapshot(project)
    for rest in ("dashboard.html", "dashboard.js", "dashboard.css", "api/tests"):
        assert get(server, rest)[0] == 200
    assert get(server, "api/tests/ended/break/oldest")[0] == 200
    for spec in TESTS:
        assert dashboard.find(project, spec["id"]) is not None
    assert snapshot(project) == before


def test_the_dashboard_has_the_checks_and_headers_of_the_page(server: page.PageServer) -> None:
    port = server.server_address[1]
    for rest in ("dashboard.html", "dashboard.js", "dashboard.css", "api/tests"):
        status, headers, _ = get(server, rest)
        assert status == 200
        assert headers["content-security-policy"] == page.CSP
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert get(server, rest, token="x" * 43)[0] == 404
        assert get(server, rest, {"Host": f"evil.test:{port}"})[0] == 403
        assert get(server, rest, {"Origin": "http://evil.test"})[0] == 403
    for rest in ("api/tests", f"api/turns/{TESTS[0]['id']}"):
        assert get(server, rest, token="x" * 43)[0] == 404


def test_a_file_that_cannot_be_read_gives_no_count_and_a_problem(
    project: Path, server: page.PageServer
) -> None:
    folder = project / ".nookku" / "tests" / TESTS[1]["id"]
    (folder / "audit.json").write_text("{not json")
    (folder / "findings.json").write_text("[]")
    with (folder / "relay.jsonl").open("a") as f:
        f.write("not a row\n")
    other = project / ".nookku" / "tests" / TESTS[2]["id"]
    (other / "audit.json").write_text(json.dumps({"exit": 2, "breaks": [], "errors": []}))
    (other / "findings.json").unlink()
    rows = {r["id"]: r for r in get_json(server, "api/tests")["tests"]}
    bad = rows[TESTS[1]["id"]]
    assert (bad["turns"], bad["breaks"], bad["findings"]) == (None, None, None)
    assert len(bad["errors"]) == 3
    assert bad["seal"] == "broken"
    invalid = rows[TESTS[2]["id"]]
    assert invalid["breaks"] is None and invalid["findings"] is None
    assert invalid["errors"] == ["audit.json: a record is missing or not valid (exit 2)"]


def test_a_damaged_test_changes_only_its_own_row(
    project: Path, server: page.PageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python reads NaN and Infinity, but the JSON of the answer cannot hold them.
    folder = project / ".nookku" / "tests" / TESTS[0]["id"]
    (folder / "manifest.json").write_text('{"started": NaN, "ended": 1e999}')
    real = seal.verify

    def verify(test: Path, base: Path | None = None) -> dict[str, Any]:
        if test.name == TESTS[1]["id"]:
            raise PermissionError(13, "Permission denied")
        return real(test, base)

    monkeypatch.setattr(seal, "verify", verify)
    status, _, body = get(server, "api/tests")
    assert status == 200
    # The answer is strict JSON: no NaN and no Infinity.
    rows = {r["id"]: r for r in json.loads(body, parse_constant=pytest.fail)["tests"]}
    assert len(rows) == 3
    times = rows[TESTS[0]["id"]]
    assert times["started"] is None and times["ended"] is None
    assert times["errors"] == [
        "manifest.json: started is not a finite number",
        "manifest.json: ended is not a finite number",
    ]
    unread = rows[TESTS[1]["id"]]
    assert unread["seal"] == "unknown"
    assert unread["errors"] == ["seal: cannot read a file: Permission denied"]
    assert rows[TESTS[2]["id"]]["seal"] == "intact"


def test_the_dashboard_has_no_inline_script_and_no_html_from_text() -> None:
    folder = resources.files("nookku").joinpath("page")
    html = folder.joinpath("dashboard.html").read_text()
    js = folder.joinpath("dashboard.js").read_text()
    css = folder.joinpath("dashboard.css").read_text()
    assert re.findall(r"<script[^>]*>", html) == [
        '<script src="compare.js" defer>',
        '<script src="dashboard.js" defer>',
    ]
    assert not re.search(r"\son\w+=", html)
    assert "style=" not in html
    for text in (html, js, css):
        assert not re.search(r"https?://", text)
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "outerHTML" not in js
    # The chat page links to the dashboard, and the dashboard opens a test with #<id>.
    assert 'href="dashboard.html"' in folder.joinpath("index.html").read_text()
    assert '"./#" + encodeURIComponent(id)' in js
    # A poll answer for an old filter or an old test does not replace the current view.
    assert "if (url !== apiUrl())" in js
    assert "if (url === turnsUrl())" in folder.joinpath("app.js").read_text()


def post_send(srv: page.PageServer, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    port = srv.server_address[1]
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
    }
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("POST", f"/p/{srv.token}/api/send", json.dumps(body), headers)
        resp = conn.getresponse()
        data: dict[str, Any] = json.loads(resp.read())
        return resp.status, data
    finally:
        conn.close()


def test_a_send_goes_only_to_the_test_that_the_page_shows(
    project: Path, server: page.PageServer
) -> None:
    folder = project / ".nookku" / "tests" / "20261013-093000-dd44"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"started": 1_800_001_800.0, "ended": None}))
    cur = {
        "v": 1,
        "test": folder.name,
        "dir": str(folder),
        # Nothing listens on port 9, so a send that passes each check gives an error turn.
        "tap_url": "http://127.0.0.1:9",
        "tap_token": "t" * 43,
        "pid": os.getpid(),
        "pid_start": bridge.process_start(os.getpid()),
    }
    (project / ".nookku" / "current.json").write_text(json.dumps(cur))
    kit.set_mode(project, True)
    # The page shows an older test, and the running test is another one.
    status, answer = post_send(server, {"said": "Is the mug in stock?", "test": TESTS[2]["id"]})
    assert status == 200
    assert answer == {
        "sent": False,
        "shown": page.OTHER_TEST.format(shown=TESTS[2]["id"], running=folder.name),
        "ok": False,
    }
    assert not (folder / "relay.jsonl").exists()
    status, answer = post_send(server, {"said": "Is the mug in stock?", "test": folder.name})
    assert status == 200 and answer["sent"] is True and answer["ok"] is False
    assert len((folder / "relay.jsonl").read_text().splitlines()) == 1
    status, _ = post_send(server, {"said": "Hi", "test": 7})
    assert status == 400

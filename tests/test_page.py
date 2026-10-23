"""The chat page (#327): the bind address, the token, the Host and Origin checks, the CSP, the
exact bytes of each message and reply, fail closed, and the guard rule for the page URL."""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from nookku import bridge, export, kit, page, script, seal, state
from nookku.audit import audit
from nookku.record import Turn, Writer, read_relay
from nookku.stdio import Agent, StdioTap, start_in_thread

ROOT = Path(__file__).resolve().parent.parent
TOY_ENTRY = ROOT / "tests" / "toy_entry.py"
MESSAGES = [
    "Hi, I want to return order #4471.  ",
    "Ünïcödé check: can I pay in € or ₹? Ça marche?",
    "Two questions:\n\n1. Do you ship to Chennai?\n2. Is the mug dishwasher safe?",
    "| item | qty |\n|---|---|\n| mug | 2 |\n| teapot | 0 |",
]


def request(
    server: page.PageServer,
    method: str,
    path: str,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """One request to the page server. The default headers are the headers of the browser."""
    port = server.server_address[1]
    sent = {"Host": f"127.0.0.1:{port}"}
    if method == "POST":
        sent |= {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
    sent |= headers or {}
    data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request(method, path, body=data, headers={k: v for k, v in sent.items() if v})
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def base(server: page.PageServer) -> str:
    return f"/p/{server.token}/"


def session(server: page.PageServer) -> dict[str, str]:
    """Open the page URL as the browser does, and return the headers that the page script sends:
    the Cookie header of the session and the page key from the fragment of the redirect."""
    status, headers, _ = request(server, "GET", base(server))
    return session_headers(status, headers)


def session_headers(status: int, headers: dict[str, str]) -> dict[str, str]:
    """The Cookie header and the page key header of a redirect with a session."""
    assert status == 303
    path, sep, key = headers["location"].partition("#k=")
    assert path == page.SESSION_PATH and sep and key
    return {"Cookie": headers["set-cookie"].split(";", 1)[0], page.PAGE_HEADER: key}


def cookie_only(headers: dict[str, str]) -> dict[str, str]:
    return {"Cookie": headers["Cookie"]}


def start_page(root: Path) -> page.PageServer:
    server = page.PageServer(root)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def write_current(root: Path, folder: Path, tap_url: str, token: str | None) -> dict[str, Any]:
    cur: dict[str, Any] = {
        "v": 1,
        "test": folder.name,
        "dir": str(folder),
        "tap_url": tap_url,
        "pid": os.getpid(),
        "pid_start": bridge.process_start(os.getpid()),
    }
    if token is not None:
        cur[state.TOKEN_KEY] = token
    (root / ".nookku" / "current.json").write_text(json.dumps(cur))
    return cur


def make_folder(root: Path) -> Path:
    folder = root / ".nookku" / "tests" / "20261013-090000-ab12"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"started": 1_800_000_000.0, "ended": None}))
    return folder


@pytest.fixture(autouse=True)
def no_harness_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests can run in a harness shell, but nookku chat refuses to start in one."""
    for name in page.HARNESS_SHELL:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def live(tmp_path: Path) -> Iterator[tuple[Path, page.PageServer, StdioTap, Path]]:
    """A running test of the toy shop entry behind a real stdio tap, and a page server."""
    folder = make_folder(tmp_path)
    agent = Agent([sys.executable, str(TOY_ENTRY)], tmp_path, folder / "app.log", timeout=30)
    tap = StdioTap(("127.0.0.1", 0), agent, folder / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    write_current(tmp_path, folder, tap.url, tap.token)
    kit.set_mode(tmp_path, True)
    server = start_page(tmp_path)
    try:
        yield tmp_path, server, tap, folder
    finally:
        server.shutdown()
        server.server_close()
        tap.shutdown()
        agent.stop(grace=1)


def send(server: page.PageServer, said: Any) -> dict[str, Any]:
    status, _, body = request(server, "POST", base(server) + "api/send", {"said": said})
    assert status == 200, body
    answer: dict[str, Any] = json.loads(body)
    return answer


def test_the_page_listens_only_on_127_0_0_1(tmp_path: Path) -> None:
    server = page.PageServer(tmp_path)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.url.startswith(f"http://127.0.0.1:{server.server_address[1]}/p/")
    finally:
        server.server_close()


def test_each_url_needs_the_token(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    try:
        assert len(server.token) >= 43
        assert request(server, "GET", base(server) + "api/turns")[0] == 200
        wrong = "x" * len(server.token)
        for path in ("/", "/p/", f"/p/{server.token}", f"/p/{wrong}/", f"/p/{wrong}/api/turns"):
            assert request(server, "GET", path)[0] == 404, path
        assert request(server, "GET", base(server) + "?t=1")[0] == 404
        status = request(server, "POST", f"/p/{wrong}/api/send", {"said": "Hi"})[0]
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()


def test_the_page_url_gives_a_session_one_time(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    try:
        assert request(server, "GET", page.SESSION_PATH)[0] == 404
        cookie = session(server)
        assert request(server, "GET", page.SESSION_PATH + "api/turns", headers=cookie)[0] == 200
        again = request(server, "GET", base(server))
        # The token has no use after the first GET: the history holds no URL that works.
        assert again[0] == 404 and b"used" in again[2] and "set-cookie" not in again[1]
        assert request(server, "GET", base(server) + "api/turns")[0] == 404
        status, _, body = request(server, "GET", page.SESSION_PATH, headers=cookie)
        assert status == 200 and b"<html" in body.lower()
        assert server.token not in cookie["Cookie"]
        assert server.page_key not in cookie["Cookie"] and server.session != server.page_key
        sent = request(server, "POST", page.SESSION_PATH + "api/send", {"said": ""}, cookie)
        assert sent[0] == 200
        wrong = {"Cookie": f"{server.cookie_name}={'x' * len(server.session)}"}
        for headers_sent in (wrong, {"Cookie": "other=1"}, {}):
            got = request(server, "GET", page.SESSION_PATH + "api/turns", headers=headers_sent)
            assert got[0] == 404
        evil = {**cookie, "Origin": "http://evil.example"}
        assert request(server, "GET", page.SESSION_PATH + "api/turns", headers=evil)[0] == 403
    finally:
        server.shutdown()
        server.server_close()


def test_the_session_cookie_stays_only_in_the_memory_of_the_browser(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    try:
        status, headers, _ = request(server, "GET", base(server))
        assert status == 303
        parts = [p.strip() for p in headers["set-cookie"].split(";")]
        name, value = parts[0].split("=", 1)
        assert name == server.cookie_name and value == server.session
        # The name does not give the port to a server on another port that gets the cookie.
        assert str(server.server_address[1]) not in name
        other = page.PageServer(tmp_path)
        other.server_close()
        assert other.cookie_name != name
        assert value != server.token
        assert set(parts[1:]) == {f"Path={page.SESSION_PATH}", "HttpOnly", "SameSite=Strict"}
        assert headers["content-security-policy"] == page.CSP
    finally:
        server.shutdown()
        server.server_close()


def test_a_request_of_data_needs_the_cookie_and_the_page_key(tmp_path: Path) -> None:
    """A browser sends the session cookie also to another port of the host. Thus a process that
    listens on another port can get the cookie, but not the page key: the key goes only in a URL
    fragment to the script of the page (SPEC.md section 5, "Session")."""
    folder = make_folder(tmp_path)
    (folder / "chart.png").write_bytes(b"chart")
    server = start_page(tmp_path)
    try:
        both = session(server)
        cookie = cookie_only(both)
        key = {page.PAGE_HEADER: both[page.PAGE_HEADER]}
        wrong = {**cookie, page.PAGE_HEADER: "x" * len(server.page_key)}
        paths = [
            "api/turns",
            "api/tests",
            "api/notes",
            "api/trace",
            f"api/export/{folder.name}",
            "files/" + str(folder / "chart.png").replace("/", "%2F"),
        ]
        for path in paths:
            assert request(server, "GET", page.SESSION_PATH + path, headers=both)[0] == 200, path
            for headers in (cookie, key, wrong):
                status, _, body = request(server, "GET", page.SESSION_PATH + path, headers=headers)
                assert status == 404, (path, headers)
        _, _, body = request(server, "GET", page.SESSION_PATH + "api/turns", headers=cookie)
        assert page.NO_KEY in json.loads(body)["error"]
        for path in ("api/send", "api/save-script", "api/note", "api/open"):
            assert request(server, "POST", page.SESSION_PATH + path, {}, cookie)[0] == 404, path
            assert request(server, "POST", page.SESSION_PATH + path, {}, wrong)[0] == 404, path
        # The files of the page hold no data, so they load with the cookie only.
        for path in ("", "app.js", "key.js", "dashboard.html", "theme.css"):
            assert request(server, "GET", page.SESSION_PATH + path, headers=cookie)[0] == 200
        # A second key header is refused.
        lines = (
            f"GET {page.SESSION_PATH}api/turns HTTP/1.0\r\nHost: 127.0.0.1:"
            f"{server.server_address[1]}\r\nCookie: {cookie['Cookie']}\r\n"
            f"{page.PAGE_HEADER}: {server.page_key}\r\n{page.PAGE_HEADER}: x\r\n\r\n"
        )
        assert raw(server, lines.encode()).startswith(b"HTTP/1.0 404")
    finally:
        server.shutdown()
        server.server_close()


def test_the_key_compare_takes_constant_time() -> None:
    source = Path(page.__file__).read_text()
    assert "keys[0].encode(), self.server.page_key.encode()" in source


def test_a_post_to_the_page_url_gives_no_session(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    try:
        status, headers, _ = request(server, "POST", base(server), {"said": "Hi"})
        assert status == 404 and "set-cookie" not in headers
        session(server)
    finally:
        server.shutdown()
        server.server_close()


def test_the_token_compare_takes_constant_time() -> None:
    source = Path(page.__file__).read_text()
    assert "hmac.compare_digest(token.encode(), self.server.token.encode())" in source
    assert "got.value.encode(), self.server.session.encode()" in source


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:{port}", "127.0.0.1:1", "127.0.0.1", ""]
)
def test_a_wrong_host_is_refused(tmp_path: Path, host: str) -> None:
    server = start_page(tmp_path)
    try:
        value = host.format(port=server.server_address[1])
        status, _, body = request(server, "GET", base(server), headers={"Host": value or " "})
        assert status == 403, body
        assert request(server, "GET", base(server) + "api/turns")[0] == 200
        local = {"Host": f"localhost:{server.server_address[1]}"}
        assert request(server, "GET", base(server) + "api/turns", headers=local)[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_a_wrong_origin_is_refused_and_a_post_needs_one(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    port = server.server_address[1]
    try:
        for origin in ("http://evil.example", f"http://127.0.0.1:{port + 1}", "null"):
            got = request(server, "GET", base(server), headers={"Origin": origin})
            assert got[0] == 403, origin
            post = request(
                server, "POST", base(server) + "api/send", {"said": "Hi"}, {"Origin": origin}
            )
            assert post[0] == 403, origin
        status, _, body = request(
            server, "POST", base(server) + "api/send", {"said": "Hi"}, {"Origin": ""}
        )
        assert status == 403
        assert b"Origin" in body
        same = {"Origin": f"http://127.0.0.1:{port}"}
        assert request(server, "GET", base(server) + "api/turns", headers=same)[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_a_post_must_be_json(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    try:
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        got = request(server, "POST", base(server) + "api/send", b"said=Hi", form)
        assert got[0] == 415
        got = request(server, "POST", base(server) + "api/send", b"{not json")
        assert got[0] == 400
    finally:
        server.shutdown()
        server.server_close()


def test_each_answer_has_a_strict_csp(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    try:
        for path in ("", "app.js", "save.js", "app.css", "api/turns", "nothing"):
            _, headers, _ = request(server, "GET", base(server) + path)
            csp = headers["content-security-policy"]
            assert "default-src 'none'" in csp
            assert "script-src 'self'" in csp
            assert "unsafe" not in csp
            assert headers["x-content-type-options"] == "nosniff"
            assert headers["referrer-policy"] == "no-referrer"
        _, headers, _ = request(server, "GET", base(server) + "api/turns", headers={"Host": "x"})
        assert "content-security-policy" in headers
    finally:
        server.shutdown()
        server.server_close()


def test_a_cold_load_gets_each_file_of_the_page_in_parallel(tmp_path: Path) -> None:
    """A browser asks for each file of the page at the same time. The server must answer each
    request: with a backlog of 5, a cold load lost some files, and the page had no style."""
    server = start_page(tmp_path)
    try:
        cookie = cookie_only(session(server))
        names = sorted(page.FILES)
        paths = [names[i % len(names)] for i in range(20)]
        start = threading.Barrier(len(paths))
        got: dict[int, tuple[int, bytes] | BaseException] = {}

        def load(i: int) -> None:
            start.wait()
            try:
                status, _, body = request(
                    server, "GET", page.SESSION_PATH + paths[i], headers=cookie
                )
                got[i] = (status, body)
            except OSError as error:
                got[i] = error

        threads = [threading.Thread(target=load, args=(i,)) for i in range(len(paths))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        for i, rest in enumerate(paths):
            assert got[i] == (200, page.page_file(page.FILES[rest][0])), rest
    finally:
        server.shutdown()
        server.server_close()


def test_the_page_has_no_inline_script_no_cdn_and_no_html_from_text() -> None:
    folder = resources.files("nookku").joinpath("page")
    html = folder.joinpath("index.html").read_text()
    scripts = ["icons.js", "render.js", "app.js", "save.js", "notes.js", "export_button.js"]
    scripts += ["end_button.js"]
    scripts += ["trace.js", "menu.js"]
    js = "".join(folder.joinpath(name).read_text() for name in [*scripts, "key.js"])
    # icons.js names the SVG namespace. It is a name, not a file that the page loads.
    js = js.replace('"http://www.w3.org/2000/svg"', "SVG_NS")
    styles = ["chat.css", "render.css", "notes.css", "trace.css"]
    css = "".join(folder.joinpath(name).read_text() for name in styles)
    # theme.js runs before the first paint, without defer (#355).
    tags = re.findall(r"<script[^>]*>", html)
    # key.js takes the page key before the other scripts run (SPEC.md section 5, "Session").
    assert tags == ['<script src="theme.js">', '<script src="key.js">'] + [
        f'<script src="{s}" defer>' for s in [*scripts, "keys.js"]
    ]
    assert all(name in page.FILES for name in [*scripts, *styles])
    assert not re.search(r"\son\w+=", html)
    assert "style=" not in html
    # The logo icon is a data: URL. The SVG namespace in it is a name, not a file to load.
    for text in (html.replace(export.ICON, ""), js, css):
        assert not re.search(r"https?://", text)
    # The page puts each text of the agent and the tester in with textContent, or as DOM nodes
    # from render.js (#347).
    for name in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
        assert name not in js
    assert "new Function" not in js and "DOMParser" not in js


def test_each_message_and_reply_keeps_each_byte(live: Any) -> None:
    _, server, _, folder = live
    for message in MESSAGES:
        answer = send(server, message)
        assert answer["sent"] is True and answer["ok"] is True
    exchanges = [json.loads(x) for x in (folder / "tap.jsonl").read_text().split("\n") if x]
    assert [e["input"] for e in exchanges] == MESSAGES
    turns = [r for r in read_relay(folder / "relay.jsonl") if isinstance(r, Turn)]
    assert [t.harness for t in turns] == ["pane"] * len(MESSAGES)
    assert [t.said for t in turns] == MESSAGES
    assert [t.shown for t in turns] == [e["reply"] for e in exchanges]
    rep = audit(folder / "tap.jsonl", folder / "relay.jsonl")
    assert rep.exit == 0 and rep.breaks == []
    # The page shows each reply as the record holds it.
    status, _, body = request(server, "GET", base(server) + "api/turns")
    shown = json.loads(body)
    assert status == 200
    assert [t["shown"] for t in shown["turns"]] == [e["reply"] for e in exchanges]
    assert shown["test"] == {
        "id": folder.name,
        "running": True,
        "started": 1_800_000_000.0,
        "ended": None,
    }


def test_the_page_answers_never_hold_the_tap_token(live: Any) -> None:
    _, server, tap, _ = live
    send(server, MESSAGES[0])
    cookie = session(server)
    for path in ("", "app.js", "api/turns"):
        got = request(server, "GET", page.SESSION_PATH + path, headers=cookie)
        assert got[0] == 200 and tap.token.encode() not in got[2]


def test_with_no_test_nothing_is_sent(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    server = start_page(tmp_path)
    try:
        answer = send(server, "Hi")
        assert answer == {"sent": False, "shown": page.NO_TEST, "ok": False}
        assert list((tmp_path / ".nookku").rglob("relay.jsonl")) == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("token", [None, "not-the-tap-token"])
def test_a_tap_that_refuses_the_message_gives_an_error_turn(live: Any, token: str | None) -> None:
    root, server, tap, folder = live
    write_current(root, folder, tap.url, token)
    answer = send(server, "Hi")
    assert answer["sent"] is True and answer["ok"] is False
    assert answer["shown"].startswith("nookku: HTTP 403: nookku tap:")
    assert (
        not (folder / "tap.jsonl").exists() or "exchange" not in (folder / "tap.jsonl").read_text()
    )
    turns = [r for r in read_relay(folder / "relay.jsonl") if isinstance(r, Turn)]
    assert [(t.harness, t.said, t.ok) for t in turns] == [("pane", "Hi", False)]


def test_an_unreachable_tap_gives_an_error_turn(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    write_current(tmp_path, folder, "http://127.0.0.1:9/", "t" * 43)
    kit.set_mode(tmp_path, True)
    server = start_page(tmp_path)
    try:
        answer = send(server, "Hi")
        assert answer["sent"] is True and answer["ok"] is False
        assert answer["shown"].startswith("nookku: cannot reach the tap")
        turns = [r for r in read_relay(folder / "relay.jsonl") if isinstance(r, Turn)]
        assert [(t.harness, t.ok) for t in turns] == [("pane", False)]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    ("said", "reason"),
    [
        ("nookku end", page.CONTROL_REASON.format(said="nookku end")),
        ("  nookku end ", page.CONTROL_REASON.format(said="nookku end")),
        ("nookku stop", kit.NEAR_CONTROL_REASON),
        ("Is the mug \ud83d in stock?", None),
    ],
)
def test_a_refused_message_is_not_sent_and_not_recorded(
    live: Any, said: str | None, reason: str | None
) -> None:
    _, server, _, folder = live
    answer = send(server, said)
    assert answer["sent"] is False
    if reason is None:
        assert answer["shown"].startswith("nookku: nothing was sent. The message has a lone")
    else:
        assert answer["shown"] == reason
    assert not (folder / "relay.jsonl").exists()
    assert not (folder / "tap.jsonl").exists() or (folder / "tap.jsonl").read_text() == ""


def test_the_guard_denies_a_model_call_to_the_page(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    server = page.PageServer(tmp_path)
    try:
        port = server.server_address[1]
        path, lock = page.claim_page_file(tmp_path, port)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert state.page_port(tmp_path) == port
        # A model tool call can read the page file, so it never holds the page token.
        assert server.token not in path.read_text()
        assert set(json.loads(path.read_text())) == {"port", "pid", "pid_start"}
        for command in (
            f'curl -X POST {server.url}api/send -d \'{{"said": "hi"}}\'',
            f"curl http://localhost:{port}/",
            f"exec 3<>/dev/tcp/127.0.0.1/{port}",
            "nookku chat",
            "uv run nookku chat --port 8080",
            "nookku page",
            "uv run nookku page --port 8080",
        ):
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            answer = kit.handle(event, tmp_path, "claude-code")
            assert answer is not None, command
            assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
        # A model write to the page file is denied too, also when no test runs.
        write = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": ".nookku/page.json", "content": "{}"},
            "cwd": str(tmp_path),
        }
        answer = kit.handle(write, tmp_path, "claude-code")
        assert answer is not None
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
        other = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": f"curl http://127.0.0.1:{port + 1}/"},
        }
        assert kit.handle(other, tmp_path, "claude-code") is None
        os.close(lock)
    finally:
        server.server_close()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_the_page_command_prints_no_tap_token_and_removes_its_file(
    tmp_path: Path, sig: signal.Signals
) -> None:
    folder = make_folder(tmp_path)
    write_current(tmp_path, folder, "http://127.0.0.1:9/", "secret-tap-token-" + "x" * 30)
    proc = subprocess.Popen(
        [sys.executable, "-m", "nookku", "chat", "--root", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert line.startswith("Chat page: http://127.0.0.1:")
        page_file = tmp_path / ".nookku" / state.PAGE_FILE
        deadline = time.monotonic() + 10
        while not page_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        url = line.split(": ", 1)[1].strip()
        assert f"http://127.0.0.1:{state.page_port(tmp_path)}/p/" in url
        assert url.split("/p/")[1].strip("/") not in page_file.read_text()
    finally:
        proc.send_signal(sig)
        out, err = proc.communicate(timeout=10)
    assert "secret-tap-token" not in line + out + err
    assert proc.returncode == 0
    assert not (tmp_path / ".nookku" / state.PAGE_FILE).exists()


def test_view_text_is_the_terminal_view(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from nookku.cli import main
    from nookku.record import Writer

    (tmp_path / ".nookku").mkdir()
    row = {"type": "turn", "harness": "pane", "said": "Hi", "shown": "Hello  ", "ok": True}
    Writer(tmp_path / ".nookku" / "relay.jsonl").append(row)
    assert main(["view", "--text", "--no-follow", "--root", str(tmp_path)]) == 0
    assert "──── tester, turn 1 ────\nHi\n──── agent ────\nHello  \n" in capsys.readouterr().out


def test_the_page_sends_only_in_relay_mode_and_not_for_a_scripted_test(live: Any) -> None:
    root, server, _, folder = live
    kit.set_mode(root, False)
    assert send(server, "Hi") == {"sent": False, "shown": page.RELAY_OFF, "ok": False}
    kit.set_mode(root, True)
    manifest = json.loads((folder / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps(manifest | {"script": "s.jsonl"}))
    assert send(server, "Hi") == {"sent": False, "shown": page.SCRIPTED, "ok": False}
    assert not (folder / "relay.jsonl").exists()
    assert not (folder / "tap.jsonl").exists() or (folder / "tap.jsonl").read_text() == ""


@pytest.mark.parametrize("closed", ["ended", "audit.json", "seal.json"])
def test_the_page_sends_nothing_after_the_end_began(live: Any, closed: str) -> None:
    _, server, _, folder = live
    if closed == "ended":
        manifest = json.loads((folder / "manifest.json").read_text())
        (folder / "manifest.json").write_text(json.dumps(manifest | {"ended": 1_800_000_100.0}))
    else:
        (folder / closed).write_text("{}")
    assert send(server, "Hi") == {"sent": False, "shown": page.RELAY_OFF, "ok": False}
    assert not (folder / "relay.jsonl").exists()
    assert not (folder / "tap.jsonl").exists() or (folder / "tap.jsonl").read_text() == ""


@pytest.mark.parametrize("ok", [True, False])
def test_a_test_sealed_during_the_send_gets_no_turn(
    live: Any, monkeypatch: pytest.MonkeyPatch, ok: bool
) -> None:
    _, server, _, folder = live

    def sealed_send(cur: dict[str, Any], said: str) -> tuple[str, bool]:
        (folder / "seal.json").write_text("{}")
        return ("Your order ships today.", True) if ok else ("nookku: HTTP 503: gone", False)

    monkeypatch.setattr(state, "send", sealed_send)
    answer = send(server, "Hi")
    assert answer["sent"] is False and answer["ok"] is False
    assert answer["shown"].startswith("nookku: the test ended during the send")
    assert not (folder / "relay.jsonl").exists()


@pytest.mark.parametrize("said", ["", "   ", "\n\t", "nookku stop", "nookku  end", "Hi \udc00"])
def test_the_page_uses_the_prompt_rules_of_the_hook(live: Any, said: str) -> None:
    root, server, _, folder = live
    hook = kit.prompt_refusal(said, root)
    assert page.refusal(root, said) == hook
    answer = send(server, said)
    if hook is None:
        assert answer["sent"] is True and answer["ok"] is True
        turns = [r for r in read_relay(folder / "relay.jsonl") if isinstance(r, Turn)]
        assert [t.said for t in turns] == [said]
    else:
        assert answer == {"sent": False, "shown": hook, "ok": False}


def test_a_said_that_is_not_text_or_a_deep_json_body_gets_400(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    try:
        for body in ({"said": None}, {"said": 1}, ["Hi"], b"[" * 100_000 + b"]" * 100_000):
            status, headers, _ = request(server, "POST", base(server) + "api/send", body)
            assert status == 400, body if not isinstance(body, bytes) else "deep"
            assert headers["content-security-policy"] == page.CSP
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("test_id", ["a\x00b", "a\ud800b"])
def test_a_test_id_with_a_nul_or_a_lone_surrogate_gets_400(tmp_path: Path, test_id: str) -> None:
    """The answer names the test, and UTF-8 cannot encode a lone surrogate. A path cannot hold a
    NUL. Each route refuses such an id, and the page gets an answer, not a closed connection."""
    server = start_page(tmp_path)
    try:
        bodies = [
            ("api/send", {"said": "Hi", "test": test_id}),
            ("api/save-script", {"test": test_id}),
            ("api/note", {"test": test_id, "turn": 1, "rating": "up"}),
        ]
        for path, body in bodies:
            status, _, answer = request(server, "POST", base(server) + path, body)
            assert status == 400, path
            assert "nookku chat:" in json.loads(answer)["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_a_number_that_is_not_finite_goes_to_the_page_as_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JSON has no NaN. An OTLP attribute can hold one, and the page could not read the answer."""
    data = {"turns": [{"steps": [{"cost": float("nan"), "ms": (float("inf"), 2.5)}]}]}
    monkeypatch.setattr(page.page_trace, "answer", lambda root, rest: (200, data))
    server = start_page(tmp_path)
    try:
        status, _, body = request(server, "GET", base(server) + "api/trace")

        def refuse(name: str) -> None:
            raise AssertionError(name)

        assert status == 200
        got = json.loads(body, parse_constant=refuse)
        assert got == {"turns": [{"steps": [{"cost": None, "ms": [None, 2.5]}]}]}
    finally:
        server.shutdown()
        server.server_close()


def raw(server: page.PageServer, data: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=10) as conn:
        conn.sendall(data)
        got = b""
        while chunk := conn.recv(65536):
            got += chunk
        return got


def test_each_answer_of_http_server_itself_has_the_headers(tmp_path: Path) -> None:
    server = start_page(tmp_path)
    port = server.server_address[1]
    try:
        for method in ("HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"):
            status, headers, _ = request(server, method, base(server))
            assert status == 405, method
            assert headers["content-security-policy"] == page.CSP, method
        host = f"Host: 127.0.0.1:{port}\r\n\r\n".encode()
        for line, code in (
            (b"FOO / HTTP/1.1\r\n", b" 501 "),
            (b"GET / HTTP/9.9\r\n", b" 505 "),
            (b"GET /" + b"a" * 70_000 + b" HTTP/1.1\r\n", b" 414 "),
            (b"GET / HTTP/1.1 x\r\n", b" 400 "),
        ):
            got = raw(server, line + host)
            head = got.split(b"\r\n\r\n", 1)[0]
            status_line = head.split(b"\r\n", 1)[0]
            assert status_line.startswith(b"HTTP/1.0") and code in status_line, line[:20]
            assert b"Content-Security-Policy: " + page.CSP.encode() in head, line[:20]
        # An HTTP/0.9 answer has no headers, so the page gives no answer. Python 3.12 and earlier
        # read headers after an HTTP/0.9 request line, so the request ends with a blank line.
        assert raw(server, b"GET /\r\n\r\n") == b""
    finally:
        server.shutdown()
        server.server_close()


def test_a_silent_connection_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert page._Handler.timeout == page.SOCKET_TIMEOUT > 0
    monkeypatch.setattr(page._Handler, "timeout", 0.5)
    server = start_page(tmp_path)
    try:
        started = time.monotonic()
        assert raw(server, b"") == b""
        assert time.monotonic() - started < 5
    finally:
        server.shutdown()
        server.server_close()


# A process that claims the page file and holds the page lock, as a page server does.
CLAIMER = """
import sys, time
from pathlib import Path
from nookku import page
page.claim_page_file(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3] or None)
print("held", flush=True)
time.sleep(60)
"""


@contextlib.contextmanager
def claimed(root: Path, port: int, test: str | None = None) -> Iterator[subprocess.Popen[str]]:
    """A process that holds the page lock and the page file of root. A process gets no holder for
    its own POSIX lock, so the holder in a test is another process (#454)."""
    proc = subprocess.Popen(
        [sys.executable, "-c", CLAIMER, str(root), str(port), test or ""],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
        yield proc
    finally:
        proc.kill()
        proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()


def test_a_second_page_server_is_refused_and_a_stale_file_is_taken_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".nookku").mkdir()
    path = tmp_path / ".nookku" / state.PAGE_FILE
    with claimed(tmp_path, 1234) as holder:
        with pytest.raises(page.PageRunning):
            page.claim_page_file(tmp_path, 5678)
        assert page.serve(tmp_path, 0) == 1
        err = capsys.readouterr().err
        assert "a page server of this project runs" in err
        # The text names the pid and the command that stops that server (#439).
        assert f"(pid {holder.pid})" in err and "nookku chat --stop" in err
        # A pid with another start time can be a new process, so the text names no pid.
        info = json.loads(path.read_text())
        path.write_text(json.dumps(info | {"pid_start": "0"}))
        with pytest.raises(page.PageRunning) as refused:
            page.claim_page_file(tmp_path, 5678)
        assert "pid" not in str(refused.value)
        # A person can write the page file. A pid that does not hold the lock is not named, also
        # with its real start time (#454).
        me = {"port": 1, "pid": os.getpid(), "pid_start": state.process_start(os.getpid())}
        path.write_text(json.dumps(me))
        with pytest.raises(page.PageRunning) as refused:
            page.claim_page_file(tmp_path, 5678)
        assert "pid" not in str(refused.value)
        path.write_text(json.dumps(info))
        assert state.page_port(tmp_path) == 1234
    # A server that stopped with no cleanup leaves its file, but no process holds the lock.
    path, lock = page.claim_page_file(tmp_path, 5678)
    pid_start = state.process_start(os.getpid())
    assert json.loads(path.read_text()) == {
        "port": 5678,
        "pid": os.getpid(),
        "pid_start": pid_start,
    }
    os.close(lock)


def test_a_check_of_the_page_lock_does_not_take_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`nookku status --json` checks the lock. Before #454, the check took the lock for a short
    time, and a page server that started at that time could fail. Now the check reads the holder
    with F_GETLK, and takes no lock."""
    import fcntl

    (tmp_path / ".nookku").mkdir()
    (tmp_path / ".nookku" / state.PAGE_LOCK).touch()
    with claimed(tmp_path, 1234) as holder:

        def refuse(*args: Any) -> None:
            raise AssertionError("the check took the lock")

        with monkeypatch.context() as patch:
            patch.setattr(fcntl, "flock", refuse)
            patch.setattr(fcntl, "lockf", refuse)
            assert page.lock_holder(tmp_path) == holder.pid
    assert page.lock_holder(tmp_path) is None
    # No holder: the check leaves the lock free, so a server takes it at once.
    _, lock = page.claim_page_file(tmp_path, 5678)
    os.close(lock)


def test_of_2_servers_that_start_at_the_same_time_one_runs(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "nookku", "chat", "--root", str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        # A loaded CI runner can need many seconds to start 2 Python processes.
        deadline = time.monotonic() + 120
        while sum(p.poll() is not None for p in procs) < 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        done = [p for p in procs if p.poll() is not None]
        if not done:
            for p in procs:
                p.send_signal(signal.SIGTERM)
            outputs = [p.communicate(timeout=10) for p in procs]
            pytest.fail(f"no server exited in 120 s: {outputs}")
        assert len(done) == 1 and done[0].returncode == 1
        running = next(p for p in procs if p.poll() is None)
        assert state.page_info(tmp_path) == {
            "port": state.page_port(tmp_path),
            "pid": running.pid,
            "pid_start": state.process_start(running.pid),
        }
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
            p.communicate(timeout=10)
    assert not (tmp_path / ".nookku" / state.PAGE_FILE).exists()


@pytest.mark.parametrize(
    "name", ["CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED"]
)
def test_the_page_refuses_to_start_in_a_harness_shell(tmp_path: Path, name: str) -> None:
    (tmp_path / ".nookku").mkdir()
    done = subprocess.run(
        [sys.executable, "-m", "nookku", "chat", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, name: "1"},
    )
    assert done.returncode == 1
    assert done.stdout == ""
    assert "/p/" not in done.stderr and "http" not in done.stderr
    assert f"({name} is set)" in done.stderr and "separate terminal" in done.stderr
    assert not (tmp_path / ".nookku" / state.PAGE_FILE).exists()


@pytest.mark.parametrize("port", ["-1", "65536", "99999999999999999999"])
def test_a_bad_port_gives_a_clean_error(tmp_path: Path, port: str) -> None:
    (tmp_path / ".nookku").mkdir()
    done = subprocess.run(
        [sys.executable, "-m", "nookku", "chat", "--root", str(tmp_path), "--port", port],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert "is not valid" in done.stderr
    assert not (tmp_path / ".nookku" / state.PAGE_FILE).exists()


@pytest.mark.parametrize("text", [None, "", "{not json", "[1, 2]"])
def test_a_manifest_that_cannot_be_read_blocks_the_send(live: Any, text: str | None) -> None:
    _, server, _, folder = live
    if text is None:
        (folder / "manifest.json").unlink()
    else:
        (folder / "manifest.json").write_text(text)
    assert send(server, "Hi") == {"sent": False, "shown": page.NO_MANIFEST, "ok": False}
    assert not (folder / "relay.jsonl").exists()
    assert not (folder / "tap.jsonl").exists() or (folder / "tap.jsonl").read_text() == ""


def test_a_send_waits_for_the_end_and_then_sees_the_closed_test(live: Any) -> None:
    root, server, _, folder = live
    # The end of the test holds the send lock from the tap shutdown to the seal.
    lock = state.lock_sends(root)
    answers: list[dict[str, Any]] = []
    thread = threading.Thread(target=lambda: answers.append(send(server, "Hi")))
    thread.start()
    thread.join(timeout=1)
    assert thread.is_alive() and answers == []
    (folder / "seal.json").write_text("{}")
    os.close(lock)
    thread.join(timeout=30)
    assert answers == [{"sent": False, "shown": page.RELAY_OFF, "ok": False}]
    assert not (folder / "relay.jsonl").exists()
    assert not (folder / "tap.jsonl").exists() or (folder / "tap.jsonl").read_text() == ""


def test_the_end_waits_for_a_send_in_progress(live: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    root, server, _, folder = live
    in_send, go_on = threading.Event(), threading.Event()
    real = state.send

    def slow_send(cur: dict[str, Any], said: str) -> tuple[str, bool]:
        in_send.set()
        go_on.wait(timeout=30)
        return real(cur, said)

    monkeypatch.setattr(state, "send", slow_send)
    sender = threading.Thread(target=send, args=(server, "Hi"))
    sender.start()
    assert in_send.wait(timeout=30)
    took: list[int] = []
    ender = threading.Thread(target=lambda: took.append(state.lock_sends(root)))
    ender.start()
    ender.join(timeout=1)
    assert ender.is_alive() and took == []
    go_on.set()
    sender.join(timeout=30)
    ender.join(timeout=30)
    assert len(took) == 1
    os.close(took[0])
    turns = [r for r in read_relay(folder / "relay.jsonl") if isinstance(r, Turn)]
    assert [(t.harness, t.said, t.ok) for t in turns] == [("pane", "Hi", True)]


@pytest.mark.parametrize("name", ["send.lock", "page.lock"])
def test_the_guard_denies_a_model_write_to_a_lock(tmp_path: Path, name: str) -> None:
    (tmp_path / ".nookku").mkdir()
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": f"flock .nookku/{name} sleep 600"},
        "cwd": str(tmp_path),
    }
    answer = kit.handle(event, tmp_path, "claude-code")
    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


# A toy shop entry that needs 4 s for each reply.
SLOW_ENTRY = """
import json, sys, time
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    time.sleep(4)
    out = {"v": 1, "id": request["id"], "reply": "Toy shop: " + request["message"]}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_a_page_send_slower_than_the_end_wait_keeps_the_seal_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, "-c", SLOW_ENTRY], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    kit.set_mode(root, True)
    done: list[float] = []
    real = state.send

    def slow_send(cur: dict[str, Any], said: str) -> tuple[str, bool]:
        # The end kills the bridge during this send, so the send fails. The page then needs 2 s
        # more before it writes the turn.
        out = real(cur, said)
        time.sleep(2)
        done.append(time.time())
        return out

    monkeypatch.setattr(state, "send", slow_send)
    server = start_page(root)
    answers: list[dict[str, Any]] = []
    try:
        sender = threading.Thread(target=lambda: answers.append(send(server, "Hi")))
        sender.start()
        time.sleep(0.5)
        # The end waits 1 s for the bridge. The bridge waits for the page send, so the end
        # kills the bridge and finishes the folder itself.
        manifest = bridge.end(root, wait=1.0)
        sender.join(timeout=30)
    finally:
        server.shutdown()
        server.server_close()
    assert manifest is not None and manifest["killed"] is True
    assert len(done) == 1 and manifest["ended"] >= done[0]
    assert answers and answers[0]["ok"] is False
    turns = [r for r in read_relay(folder / "relay.jsonl") if isinstance(r, Turn)]
    assert [(t.harness, t.said, t.ok) for t in turns] == [("pane", "Hi", False)]
    assert seal.verify(folder)["intact"]


def test_the_page_saves_the_test_as_a_script(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    for said in MESSAGES:
        Writer(folder / "relay.jsonl").append(
            {"type": "turn", "harness": "pane", "said": said, "shown": "ok", "ok": True}
        )
    server = start_page(tmp_path)
    try:
        url = base(server) + "api/save-script"
        status, _, body = request(server, "POST", url, {"test": folder.name})
        assert status == 200 and json.loads(body)["saved"], body
        path = tmp_path / ".nookku" / "scripts" / f"{folder.name}.jsonl"
        assert script.parse(path.read_bytes())[0] == MESSAGES
        # The save has the checks of each POST: Origin, Content-Type and the body.
        assert request(server, "POST", url, {"test": folder.name}, {"Origin": ""})[0] == 403
        assert request(server, "POST", url, b"{}", {"Content-Type": "text/plain"})[0] == 415
        assert request(server, "POST", url, b"not json")[0] == 400
        status, _, body = request(server, "POST", url, {"test": "../x"})
        assert status == 200 and not json.loads(body)["saved"]
    finally:
        server.shutdown()
        server.server_close()


# A page server of 0.5.4 or older: it holds a `flock` on page.lock.
LEGACY = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("held", flush=True)
time.sleep(60)
"""
# A try of the `flock` of page.lock, as a start of 0.5.4 or older makes it.
LEGACY_TRY = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("refused")
else:
    print("took")
"""


def test_a_page_server_of_an_older_version_and_a_new_one_never_run_together(
    tmp_path: Path,
) -> None:
    """Before #454, the page server held a `flock`. On Linux, `flock` and `lockf` are separate
    locks, so the claim takes both. On macOS, they are one lock."""
    (tmp_path / ".nookku").mkdir()
    lock = tmp_path / ".nookku" / state.PAGE_LOCK
    old = subprocess.Popen(
        [sys.executable, "-c", LEGACY, str(lock)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert old.stdout is not None and old.stdout.readline().strip() == "held"
        with pytest.raises(page.PageRunning):
            page.claim_page_file(tmp_path, 1234)
        assert state.page_info(tmp_path) is None
    finally:
        old.kill()
        old.wait()
        if old.stdout is not None:
            old.stdout.close()
    # A new server runs: an old start cannot take the lock either.
    _, fd = page.claim_page_file(tmp_path, 1234)
    try:
        tried = subprocess.run(
            [sys.executable, "-c", LEGACY_TRY, str(lock)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert tried.stdout.strip() == "refused"
    finally:
        os.close(fd)

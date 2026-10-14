"""The chat page (#327): the bind address, the token, the Host and Origin checks, the CSP, the
exact bytes of each message and reply, fail closed, and the guard rule for the page URL."""

from __future__ import annotations

import http.client
import json
import os
import re
import signal
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

from nookku import bridge, kit, page, state
from nookku.audit import audit
from nookku.record import Turn, read_relay
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


@pytest.fixture
def live(tmp_path: Path) -> Iterator[tuple[Path, page.PageServer, StdioTap, Path]]:
    """A running test of the toy shop entry behind a real stdio tap, and a page server."""
    folder = make_folder(tmp_path)
    agent = Agent([sys.executable, str(TOY_ENTRY)], tmp_path, folder / "app.log", timeout=30)
    tap = StdioTap(("127.0.0.1", 0), agent, folder / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    write_current(tmp_path, folder, tap.url, tap.token)
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
        assert request(server, "GET", base(server))[0] == 200
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


def test_the_token_compare_takes_constant_time() -> None:
    source = Path(page.__file__).read_text()
    assert "hmac.compare_digest(token.encode(), self.server.token.encode())" in source


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:{port}", "127.0.0.1:1", "127.0.0.1", ""]
)
def test_a_wrong_host_is_refused(tmp_path: Path, host: str) -> None:
    server = start_page(tmp_path)
    try:
        value = host.format(port=server.server_address[1])
        status, _, body = request(server, "GET", base(server), headers={"Host": value or " "})
        assert status == 403, body
        assert request(server, "GET", base(server))[0] == 200
        local = {"Host": f"localhost:{server.server_address[1]}"}
        assert request(server, "GET", base(server), headers=local)[0] == 200
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
        for path in ("", "app.js", "app.css", "api/turns", "nothing"):
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


def test_the_page_has_no_inline_script_no_cdn_and_no_html_from_text() -> None:
    folder = resources.files("nookku").joinpath("page")
    html = folder.joinpath("index.html").read_text()
    js = folder.joinpath("app.js").read_text()
    css = folder.joinpath("app.css").read_text()
    assert re.findall(r"<script[^>]*>", html) == ['<script src="app.js" defer>']
    assert not re.search(r"\son\w+=", html)
    assert "style=" not in html
    for text in (html, js, css):
        assert not re.search(r"https?://", text)
    # The page puts each text of the agent and the tester in with textContent.
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "outerHTML" not in js


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
    for path in ("", "app.js", "api/turns"):
        assert tap.token.encode() not in request(server, "GET", base(server) + path)[2]


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
        ("nookku stop", kit.NEAR_CONTROL_REASON),
        ("", "nookku: the message is empty. Nothing was sent."),
        (None, "nookku: the message is empty. Nothing was sent."),
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
        path = page.write_page_file(tmp_path, server)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert state.page_url(tmp_path) == server.url
        port = server.server_address[1]
        for command in (
            f'curl -X POST {server.url}api/send -d \'{{"said": "hi"}}\'',
            f"curl http://localhost:{port}/",
            f"exec 3<>/dev/tcp/127.0.0.1/{port}",
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
    finally:
        server.server_close()


def test_the_page_command_prints_no_tap_token_and_removes_its_file(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    write_current(tmp_path, folder, "http://127.0.0.1:9/", "secret-tap-token-" + "x" * 30)
    proc = subprocess.Popen(
        [sys.executable, "-m", "nookku", "page", "--root", str(tmp_path)],
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
        assert state.page_url(tmp_path) == line.split(": ", 1)[1].strip()
    finally:
        proc.send_signal(signal.SIGTERM)
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

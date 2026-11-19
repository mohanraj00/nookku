"""A replay with the recorded backends (#523, SPEC.md section 7.10, "Recorded backends")."""

from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from toy_model_server import ModelServer
from toy_stock_server import StockServer

from nookku import backend, bridge, discovery, model_api, player, replay, script_save, seal
from nookku.cli import main

# A port where no server listens: a player must never connect to it.
NOWHERE = "http://127.0.0.1:9"


def request(
    url: str, method: str, path: str, body: bytes | None, headers: dict[str, str]
) -> tuple[int, list[tuple[str, str]], bytes]:
    """Send a request to the proxy at `url`. The path of `url` (the token of a player) comes
    before `path`."""
    parts = urlsplit(url)
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    conn.request(method, parts.path + path, body=body, headers=headers)
    resp = conn.getresponse()
    out = (resp.status, resp.getheaders(), resp.read())
    conn.close()
    return out


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines()]


def record(tmp_path: Path, stock: StockServer, calls: list[tuple[str, str, bytes]]) -> Path:
    """Record `calls` (method, path, body) through a live proxy. Return the record file."""
    path = tmp_path / "live" / backend.FILE
    path.parent.mkdir()
    proxies = backend.Proxies([backend.Backend("stock", "STOCK_URL", stock.url)], path)
    env = proxies.start()
    try:
        for method, target, body in calls:
            request(env["STOCK_URL"], method, target, body, {"Content-Type": "application/json"})
    finally:
        proxies.stop()
    return path


def played(base: Path, tmp_path: Path, name: str = "stock") -> tuple[backend.Proxies, Path]:
    """A proxy of the backend `name` that plays the record `base`, with its own record file."""
    path = tmp_path / "played" / backend.FILE
    path.parent.mkdir(exist_ok=True)
    proxies = backend.Proxies([backend.Backend(name, "STOCK_URL", NOWHERE)], path)
    for p in proxies.proxies:
        p.player = player.Player.load(base, "backend", name)
    return proxies, path


def test_a_player_gives_the_recorded_response_and_calls_no_backend(tmp_path: Path) -> None:
    with StockServer() as stock:
        stock.answer_body = b'{"sku": "teapot-set", "left": 3}'
        base = record(tmp_path, stock, [("POST", "/stock?sku=teapot&api_key=k1", b'{"n": 1}')])
        # The live backend now gives another answer. The player never asks it.
        stock.answer_body = b'{"sku": "teapot-set", "left": 9}'
        proxies, path = played(base, tmp_path)
        env = proxies.start()
        try:
            status, headers, body = request(
                env["STOCK_URL"], "POST", "/stock?sku=teapot&api_key=k2", b'{"n": 1}', {}
            )
        finally:
            proxies.stop()
        assert len(stock.seen) == 1
    assert (status, body) == (200, b'{"sku": "teapot-set", "left": 3}')
    assert ("X-Stock-Trace", "a b  c") in headers
    row = rows(path)[0]
    assert row["replay"] == {"line": 1, "miss": None}
    assert row["status"] == 200 and row["error"] is None
    # The secret value of the query does not count in the match.
    assert row["query"] == "sku=teapot&api_key="


def test_a_head_response_replays_with_its_recorded_length(tmp_path: Path) -> None:
    with StockServer() as stock:
        stock.answer_body = b"x" * 9876
        base = record(tmp_path, stock, [("HEAD", "/image", b"")])
        assert rows(base)[0]["response_length"] == "9876"
        proxies, path = played(base, tmp_path)
        env = proxies.start()
        try:
            status, headers, body = request(env["STOCK_URL"], "HEAD", "/image", None, {})
        finally:
            proxies.stop()
    assert (status, body) == (200, b"")
    assert ("Content-Length", "9876") in headers
    assert rows(path)[0]["replay"] == {"line": 1, "miss": None}
    # A row of an older Nookku has no length. The player cannot give the same response.
    old = {**rows(base)[0]}
    del old["response_length"]
    assert str(player.response(old)) == f"{player.MISS}: {player.NO_LENGTH}"


def test_a_response_with_a_removed_secret_header_is_a_miss(tmp_path: Path) -> None:
    with StockServer() as stock:
        stock.answer_headers = [("Content-Type", "text/plain"), ("Set-Cookie", "session=toy")]
        base = record(tmp_path, stock, [("GET", "/login", b"")])
        assert ["Set-Cookie", backend.REMOVED] in rows(base)[0]["response_headers"]
        proxies, path = played(base, tmp_path)
        env = proxies.start()
        try:
            status, headers, _ = request(env["STOCK_URL"], "GET", "/login", None, {})
        finally:
            proxies.stop()
    # The app never gets the placeholder in place of the true value.
    assert status == 502 and not any(k.lower() == "set-cookie" for k, _ in headers)
    miss = f"{player.MISS}: {player.REMOVED}"
    assert rows(path)[0]["replay"] == {"line": 1, "miss": miss}
    assert player.REMOVED_VALUE == backend.REMOVED


def test_a_request_with_no_unused_recorded_call_is_a_miss_with_status_502(
    tmp_path: Path,
) -> None:
    with StockServer() as stock:
        base = record(tmp_path, stock, [("POST", "/stock", b'{"n": 1}')])
    proxies, path = played(base, tmp_path)
    env = proxies.start()
    try:
        first = request(env["STOCK_URL"], "POST", "/stock", b'{"n": 1}', {})
        again = request(env["STOCK_URL"], "POST", "/stock", b'{"n": 1}', {})
        other = request(env["STOCK_URL"], "POST", "/stock", b'{"n": 2}', {})
    finally:
        proxies.stop()
    assert [first[0], again[0], other[0]] == [200, 502, 502]
    got = [r["replay"] for r in rows(path)]
    miss = f"{player.MISS}: {player.NO_CALL}"
    assert got == [
        {"line": 1, "miss": None},
        {"line": None, "miss": miss},
        {"line": None, "miss": miss},
    ]
    assert rows(path)[1]["error"] == f"the backend did not answer: {miss}"


def test_equal_requests_get_the_recorded_responses_in_their_order(tmp_path: Path) -> None:
    lines: list[dict[str, Any]] = [
        {"v": 1, "type": "call", "backend": "stock", "started": s, "method": "GET",
         "path": "/stock", "query": None, "request_body": backend.body_row(b""),
         "status": 200, "response_headers": [], "response_body": backend.body_row(body),
         "error": None}
        for s, body in ((2.0, b"second"), (1.0, b"first"))
    ]  # fmt: skip
    data = b"".join(json.dumps(r).encode() + b"\n" for r in lines)
    recorded = player.calls(data, "backend", "stock")
    # The order is the order of `started`, not of the lines.
    assert [n for n, _ in recorded] == [2, 1]
    p = player.Player(recorded)
    want = {"method": "GET", "path": "/stock", "query": None, "request_body": backend.body_row(b"")}
    first, second = p.answer(want)[1], p.answer(want)[1]
    assert isinstance(first, player.Response) and first.read1() == b"first"
    assert isinstance(second, player.Response) and second.read1() == b"second"


def test_a_cut_response_and_a_harness_call_are_misses() -> None:
    cut = backend.body_row(b"x" * 20, limit=10)
    harness = {**backend.body_row(b"y"), "omitted": True}
    harness.pop("text")
    for body, reason in ((cut, player.CUT), (harness, player.OMITTED)):
        row = {"status": 200, "response_headers": [], "response_body": body, "error": None}
        got = player.response(row)
        assert isinstance(got, player.Miss) and str(got) == f"{player.MISS}: {reason}"
    ended = {"status": None, "response_headers": None, "response_body": None, "error": player.ENDED}
    assert str(player.response(ended)) == f"{player.MISS}: {player.OPEN}"


def test_a_body_with_another_sha256_is_a_miss() -> None:
    body = {**backend.body_row(b"three"), "text": "four"}
    row = {"status": 200, "response_headers": [], "response_body": body, "error": None}
    assert str(player.response(row)) == f"{player.MISS}: {player.NOT_SAME}"


def test_a_backend_that_did_not_answer_gives_502_again_with_no_miss() -> None:
    row = {
        "status": None,
        "response_headers": None,
        "response_body": None,
        "error": "the backend did not answer: [Errno 61] Connection refused",
    }
    got = player.response(row)
    assert type(got) is OSError and str(got) == "[Errno 61] Connection refused"


def test_a_decoded_body_goes_to_the_app_with_no_content_encoding() -> None:
    data = json.dumps({"left": 3}).encode()
    body = backend.body_row(gzip.compress(data), "gzip")
    headers = [["Content-Type", "application/json"], ["Content-Encoding", "gzip"]]
    row = {"status": 200, "response_headers": headers, "response_body": body, "error": None}
    got = player.response(row)
    assert isinstance(got, player.Response)
    assert got.getheaders() == [("Content-Type", "application/json")] and got.read1() == data


def test_a_stopped_stream_stops_again_after_its_bytes(tmp_path: Path) -> None:
    row = {"v": 1, "type": "call", "backend": "stock", "started": 1.0, "method": "GET",
           "path": "/feed", "query": None, "request_body": backend.body_row(b""),
           "status": 200, "response_headers": [["Content-Type", "text/plain"]],
           "response_body": backend.body_row(b"part one"),
           "error": "the stream stopped: the API sent 8 of 20 bytes"}  # fmt: skip
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(row) + "\n")
    proxies, path = played(base, tmp_path)
    env = proxies.start()
    try:
        url = urlsplit(env["STOCK_URL"])
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
        conn.request("GET", url.path + "/feed")
        resp = conn.getresponse()
        with pytest.raises(http.client.IncompleteRead) as e:
            resp.read()
        conn.close()
    finally:
        proxies.stop()
    assert e.value.partial == b"part one"
    got = rows(path)[0]
    assert got["error"] == "the stream stopped: the API sent 8 of 20 bytes"
    assert got["replay"] == {"line": 1, "miss": None}


def test_a_model_api_player_gives_the_recorded_result(tmp_path: Path) -> None:
    live = tmp_path / "live.jsonl"
    with ModelServer() as model:
        proxies = backend.Proxies(
            [backend.Backend("openai", "OPENAI_BASE_URL", model.url + "/v1")],
            live,
            model_api.ModelProxy,
        )
        env = proxies.start()
        call = json.dumps({"model": "toy", "messages": [{"role": "user", "content": "Hi"}]})
        try:
            first = request(env["OPENAI_BASE_URL"], "POST", "/chat/completions", call.encode(), {})
        finally:
            proxies.stop()
    path = tmp_path / "played.jsonl"
    proxies = backend.Proxies(
        [backend.Backend("openai", "OPENAI_BASE_URL", NOWHERE)], path, model_api.ModelProxy
    )
    proxies.proxies[0].player = player.Player.load(live, "api", "openai")
    env = proxies.start()
    try:
        again = request(env["OPENAI_BASE_URL"], "POST", "/chat/completions", call.encode(), {})
        harness = request(
            env["OPENAI_BASE_URL"],
            "POST",
            "/chat/completions",
            b"{}",
            {"User-Agent": "claude-cli/2.1.296"},
        )
    finally:
        proxies.stop()
    assert again[0] == first[0] == 200 and again[2] == first[2]
    played_rows = rows(path)
    assert played_rows[0]["result"] == rows(live)[0]["result"]
    assert harness[0] == 502 and played_rows[1]["replay"]["miss"] is not None


def test_the_conformance_case_gives_its_expected_outcomes() -> None:
    case = json.loads(
        (Path(__file__).resolve().parent.parent / "conformance/replay/match.json").read_text()
    )
    assert player.case(case["recorded"], case["requests"]) == case["expected"]


def _answer(stock: StockServer) -> dict[str, Any]:
    backends = [{"name": "stock", "env": "STOCK_URL", "url": stock.url}]
    return {"registered": time.time(), "answer": discovery.make(backends=backends)}


def test_no_player_for_a_stdio_mcp_server_or_a_postgres_proxy_and_a_broken_seal(
    tmp_path: Path,
) -> None:
    old = tmp_path / "20261119-090000-aa11"
    old.mkdir()
    (old / "tap.jsonl").write_text("")
    assert "seal of the base test" in (replay.recorded_problem(old, discovery.make()) or "")
    seal.write(old)
    assert replay.recorded_problem(old, discovery.make()) is None
    stdio = {"name": "stock", "transport": "stdio", "env": "STOCK_MCP", "command": ["x"]}
    db = {"name": "orders", "kind": "postgres", "env": "DATABASE_URL", "record": "proxy"}
    assert "stdio MCP server stock" in (
        replay.recorded_problem(old, {"mcp_servers": [stdio]}) or ""
    )
    assert "database orders" in (replay.recorded_problem(old, {"databases": [db]}) or "")


def test_the_base_copy_holds_only_the_sealed_bytes(tmp_path: Path) -> None:
    old = tmp_path / "20261119-090000-bb22"
    old.mkdir()
    (old / "tap.jsonl").write_text("{}\n")
    (old / "backend.jsonl").write_text("{}\n")
    seal.write(old)
    held = replay.held_base(old)
    assert held == {"tap.jsonl": b"{}\n", "backend.jsonl": b"{}\n"}
    new = tmp_path / "new"
    new.mkdir()
    replay.copy_base(held, new)
    assert (new / replay.BASE / "backend.jsonl").read_bytes() == b"{}\n"
    # A file that changes after the seal check, a symlink and a new file do not go in.
    secret = tmp_path / "secret.txt"
    secret.write_text("{}\n")
    (old / "backend.jsonl").unlink()
    (old / "backend.jsonl").symlink_to(secret)
    with pytest.raises(replay.ReplayError, match=r"backend\.jsonl"):
        replay.held_base(old)
    (old / "backend.jsonl").unlink()
    (old / "backend.jsonl").write_text('{"status": 200}\n')
    with pytest.raises(replay.ReplayError, match="SHA-256 of its seal copy"):
        replay.held_base(old)
    (old / "backend.jsonl").unlink()
    with pytest.raises(replay.ReplayError, match="missing"):
        replay.held_base(old)
    (old / "backend.jsonl").write_text("{}\n")
    (old / "mcp.jsonl").write_text("{}\n")
    with pytest.raises(replay.ReplayError, match=r"mcp\.jsonl"):
        replay.held_base(old)


# A toy shop app that asks its stock service for each message, as in test_bridge.py. With
# TOY_WORD set, the app uses that word in its reply: the planted change of an answer.
STOCK_APP = """
import json, os, sys, urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    with urllib.request.urlopen(os.environ["STOCK_URL"] + "/stock?sku=teapot-set", timeout=5) as r:
        left = json.loads(r.read())["left"]
    word = os.environ.get("TOY_WORD", "left")
    out = {"v": 1, "id": request["id"], "reply": f"{left} teapot sets {word}."}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, "-c", STOCK_APP], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    return root


@pytest.fixture
def homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))


def test_a_recorded_replay_gives_the_same_replies_with_no_backend(
    tmp_path: Path, homes: None, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    script = tmp_path / "first.jsonl"
    script.write_text('{"said": "Do you have the teapot set?"}\n{"said": "And now?"}\n')
    with StockServer() as stock:
        passed, lines, old = bridge.run_script(root, script, egress=_answer(stock))
    assert passed, lines
    path, _ = script_save.save(root, old.name)
    # The stock service is gone, so a live call would fail.
    capsys.readouterr()
    code = main(["replay", str(path), "--recorded", "--verdict", "--root", str(root), "--json",
                 "--no-evaluate"])  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["pass"], out
    assert out["diff"]["changed"] == 0
    folder = old.parent / out["diff"]["new"]["id"]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["replay"]["base"] == old.name
    want = hashlib.sha256((old / "backend.jsonl").read_bytes()).hexdigest()
    assert manifest["replay"]["files"]["backend.jsonl"] == want
    assert manifest["verdict"]["limits"] == replay.LIMITS
    findings = json.loads((folder / "findings.json").read_text())
    assert findings["counts"]["replay_changed"] == findings["counts"]["replay_miss"] == 0
    assert seal.verify(folder)["intact"]
    # The planted change: the app now uses another word. The verdict fails.
    monkeypatch.setenv("TOY_WORD", "in stock")
    code = main(["replay", str(path), "--recorded", "--verdict", "--root", str(root), "--json",
                 "--no-evaluate"])  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and not out["pass"]
    assert out["diff"]["changed"] == 2
    assert any("replay_changed" in line for line in out["report"]), out["report"]


def test_a_recorded_replay_needs_a_base_test(
    tmp_path: Path, homes: None, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path)
    (tmp_path / "a.jsonl").write_text('{"said": "Hi"}\n')
    code = main(["replay", str(tmp_path / "a.jsonl"), "--recorded", "--root", str(root)])
    assert code == 2 and "--recorded needs a base test" in capsys.readouterr().out


def test_a_miss_and_records_that_cannot_be_compared_give_findings(tmp_path: Path) -> None:
    (tmp_path / "base").mkdir()
    for folder in (tmp_path, tmp_path / "base"):
        (folder / "relay.jsonl").write_text("")
        (folder / "tap.jsonl").write_text("")
    miss = f"{player.MISS}: {player.NO_CALL}"
    row = {"backend": "stock", "started": 5.0, "method": "GET", "path": "/stock"}
    lines = [{**row, "replay": {"line": None, "miss": miss}}, {**row, "replay": {"line": 1}}]
    (tmp_path / backend.FILE).write_text("".join(json.dumps(r) + "\n" for r in lines))
    manifest = {"replay": {"base": "20261119-090000-aa11", "files": {}}}
    got = replay.findings(tmp_path, manifest, lambda ts: 2 if ts == 5.0 else None)
    assert got == [
        {"check": "replay_miss", "turn": 2, "detail": f"backend.jsonl: stock: GET /stock: {miss}"}
    ]
    assert replay.findings(tmp_path, {"replay": None}, lambda ts: None) == []
    (tmp_path / "base" / "tap.jsonl").write_text("not json\n")
    got = replay.findings(tmp_path, manifest, lambda ts: None)
    assert got[0]["check"] == "replay_changed" and got[0]["turn"] is None
    assert got[0]["detail"].startswith(
        "the replies cannot be compared with the base test 20261119-090000-aa11: "
    )


@pytest.mark.parametrize("prefix", ["", "/wrong-token", "/{token}x"])
def test_a_request_to_a_player_with_no_token_gets_403_and_no_recorded_body(
    tmp_path: Path, prefix: str
) -> None:
    with StockServer() as stock:
        stock.answer_body = b'{"sku": "teapot-set", "secret": "tenant-1"}'
        base = record(tmp_path, stock, [("GET", "/me", b"")])
        proxies, path = played(base, tmp_path)
        env = proxies.start()
        token = proxies.proxies[0].player.token  # type: ignore[union-attr]
        origin = proxies.proxies[0].url
        try:
            status, _, body = request(origin, "GET", prefix.format(token=token) + "/me", None, {})
            # The app gets the URL with the token, and its call still plays.
            again = request(env["STOCK_URL"], "GET", "/me", None, {})
        finally:
            proxies.stop()
    assert status == 403 and b"tenant-1" not in body
    assert json.loads(body) == {"error": player.NO_TOKEN}
    assert env["STOCK_URL"] == f"{origin}/{token}"
    assert again[0] == 200 and again[2] == b'{"sku": "teapot-set", "secret": "tenant-1"}'
    # The refused request writes no row, and the call of the app keeps its path with no token.
    assert [(r["path"], r["replay"]) for r in rows(path)] == [("/me", {"line": 1, "miss": None})]


def test_each_player_has_a_new_token_and_a_live_proxy_has_none(tmp_path: Path) -> None:
    a = player.Player([])
    b = player.Player([])
    assert a.token != b.token and len(a.token) >= 43
    assert a.strip(f"/{a.token}") == "/"
    assert a.strip(f"/{a.token}?q=1") == "/?q=1"
    assert a.strip(f"/{a.token}/stock?q=1") == "/stock?q=1"
    assert a.strip(f"/{b.token}/stock") is None
    proxies = backend.Proxies([backend.Backend("stock", "STOCK_URL", NOWHERE)], tmp_path / "r")
    assert proxies.proxies[0].app_url == proxies.proxies[0].url

import hashlib
import http.client
import json
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from toy_model_server import ModelServer

from nookku import backend, discovery, mcp_proxy, trace

SERVER = Path(__file__).resolve().parent / "toy_mcp_server.py"
CALL = {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}
CALL["params"] = {"name": "check_stock", "arguments": {"product": "mug"}}


def connect(url: str) -> http.client.HTTPConnection:
    parts = urlsplit(url)
    return http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=10)


def rows(folder: Path) -> list[dict]:
    return [json.loads(x) for x in (folder / mcp_proxy.FILE).read_text().split("\n") if x]


def stdio_part(env: str | None = "STOCK_MCP_COMMAND") -> dict:
    command = [sys.executable, str(SERVER)]
    return {"name": "stock", "transport": "stdio", "env": env, "command": command, "url": None}


def wrap(folder: Path, data: bytes) -> subprocess.CompletedProcess[bytes]:
    """Run the wrapper of the toy stock server as the app runs it: from its variable."""
    line = mcp_proxy.stdio_environment([stdio_part()], folder)["STOCK_MCP_COMMAND"]
    return subprocess.run(shlex.split(line), input=data, capture_output=True, timeout=30)


def direct(data: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, str(SERVER)], input=data, capture_output=True)


def test_the_stdio_wrapper_changes_no_byte_and_records_each_line(tmp_path: Path) -> None:
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    # A text with a non-ASCII letter, and a last line with no \n.
    call = {**CALL, "params": {"name": "check_stock", "arguments": {"product": "théière"}}}
    data = (json.dumps(init) + "\n" + json.dumps(call, ensure_ascii=False)).encode()
    got, want = wrap(tmp_path, data), direct(data)
    assert (got.returncode, got.stdout) == (want.returncode, want.stdout)
    assert want.returncode == 0 and want.stdout.count(b"\n") == 2
    found = rows(tmp_path)
    sent = [r for r in found if r["direction"] == "to_server"]
    assert b"".join(r["body"]["text"].encode() for r in sent) == data
    back = [r for r in found if r["direction"] == "from_server"]
    assert b"".join(r["body"]["text"].encode() for r in back) == got.stdout
    assert {(r["v"], r["type"], r["server"], r["transport"]) for r in found} == {
        (1, "message", "stock", "stdio")
    }


def test_the_recorder_keeps_only_the_first_bytes_of_a_long_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backend, "RECORD_LIMIT", 8)
    recorder = mcp_proxy.Recorder(tmp_path, "stock", "from_server", threading.Lock())
    long = b'{"image": "' + b"A" * 40 + b'"}\n'
    # The line comes in 3 parts, and a short line follows it in the last part.
    for part in (long[:5], long[5:30], long[30:] + b"ok\n"):
        recorder.add(part)
    recorder.finish()
    first, second = (r["body"] for r in rows(tmp_path))
    assert (first["size"], first["sha256"]) == (len(long), hashlib.sha256(long).hexdigest())
    assert first["cut"] is True and first["text"] == long[:8].decode()
    assert second == backend.body_row(b"ok\n")


def test_the_stdio_wrapper_writes_no_row_after_the_end_of_the_test(tmp_path: Path) -> None:
    mcp_proxy.close(tmp_path)
    data = (json.dumps(CALL) + "\n").encode()
    got = wrap(tmp_path, data)
    assert got.stdout == direct(data).stdout
    assert not (tmp_path / mcp_proxy.FILE).exists()


def test_a_wrapper_that_cannot_start_the_server_exits_with_127(tmp_path: Path) -> None:
    code = mcp_proxy.run_stdio(tmp_path, "stock", [str(tmp_path / "no-such-server")])
    assert code == 127


def test_only_a_server_with_a_variable_gets_a_proxy(tmp_path: Path) -> None:
    http = {"name": "tickets", "transport": "http", "env": "TICKETS_MCP_URL", "command": None}
    http["url"] = "https://tickets.toy.test/mcp/"
    plain = {**http, "name": "mail", "env": None}
    parts = [http, plain, stdio_part(), stdio_part(None) | {"name": "files"}]
    assert [(b.name, b.env, b.url) for b in mcp_proxy.http_servers(parts)] == [
        ("tickets", "TICKETS_MCP_URL", "https://tickets.toy.test/mcp/")
    ]
    assert list(mcp_proxy.stdio_environment(parts, tmp_path)) == ["STOCK_MCP_COMMAND"]
    answer = discovery.parse(discovery.make(mcp_servers=parts))
    assert [p.proxy for p in discovery.parts(answer)] == [True, False, True, False]


def test_the_http_proxy_sends_each_event_when_it_comes(tmp_path: Path) -> None:
    reply = {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "12"}]}}
    parts = [b": open\n\n", b"event: message\ndata: " + json.dumps(reply).encode() + b"\n\n"]
    with ModelServer() as server:
        server.parts = parts
        server.release.clear()
        servers = [backend.Backend("stock", "STOCK_MCP_URL", server.url + "/mcp")]
        proxies = backend.Proxies(servers, tmp_path / mcp_proxy.FILE, mcp_proxy.HttpProxy)
        env = proxies.start()
        try:
            # The variable keeps the endpoint path, and the server gets the same path.
            endpoint = urlsplit(env["STOCK_MCP_URL"]).path
            assert endpoint == "/mcp"
            conn = connect(env["STOCK_MCP_URL"])
            conn.request("POST", endpoint, body=json.dumps(CALL).encode(), headers={})
            resp = conn.getresponse()
            first = resp.read1(65536)
            server.release.set()
            got = first + resp.read()
            conn.close()
        finally:
            proxies.stop()
    assert first == parts[0]
    assert got == b"".join(parts)
    assert [s["path"] for s in server.seen] == ["/mcp"]
    (row,) = rows(tmp_path)
    assert row["server"] == "stock" and row["transport"] == "http" and "backend" not in row
    items, info = trace.read_mcp(tmp_path / mcp_proxy.FILE)
    assert [(it["harness"], it["kind"], it["name"], it["output"]) for it in items] == [
        ("mcp", "tool_call", "check_stock", "12")
    ]
    assert items[0]["input"] == {"product": "mug"}
    assert info == {"file": mcp_proxy.FILE, "rows": 1, "items": 1, "ignored": {}}


class SmallProxy(mcp_proxy.HttpProxy):
    keep = 8


def test_the_http_proxy_keeps_only_the_first_bytes_of_a_long_stream(tmp_path: Path) -> None:
    parts = [b": open\n\n", b": still open\n\n", b": end\n\n"]
    with ModelServer() as server:
        server.parts = parts
        servers = [backend.Backend("stock", "STOCK_MCP_URL", server.url + "/mcp")]
        proxies = backend.Proxies(servers, tmp_path / mcp_proxy.FILE, SmallProxy)
        env = proxies.start()
        try:
            conn = connect(env["STOCK_MCP_URL"])
            conn.request("POST", "/mcp", body=json.dumps(CALL).encode(), headers={})
            got = conn.getresponse().read()
            conn.close()
        finally:
            proxies.stop()
    # The app gets each byte. The record keeps the first 8 bytes, with the size and the
    # SHA-256 of all of the stream.
    whole = b"".join(parts)
    assert got == whole
    (row,) = rows(tmp_path)
    body = row["response_body"]
    assert (body["size"], body["sha256"]) == (len(whole), hashlib.sha256(whole).hexdigest())
    assert body["cut"] is True and body["text"] == whole[:8].decode()


def message(direction: str, body: dict | str, ts: float) -> dict:
    text = body if isinstance(body, str) else json.dumps(body)
    row = {"v": 1, "type": "message", "server": "stock", "transport": "stdio", "ts": ts}
    return {**row, "direction": direction, "body": backend.body_row(text.encode())}


def test_the_reader_gives_the_result_or_the_error_of_each_tool_call(tmp_path: Path) -> None:
    failed = {**CALL, "id": 3}
    lost = {**CALL, "id": 4}
    error = {"type": "text", "text": "no such product"}
    found = [
        message("to_server", CALL, 1.0),
        message("to_server", failed, 1.5),
        message("to_server", lost, 1.7),
        message("from_server", {"jsonrpc": "2.0", "method": "notifications/progress"}, 1.8),
        message(
            "from_server",
            {"jsonrpc": "2.0", "id": 3, "result": {"isError": True, "content": [error]}},
            2.0,
        ),
        message(
            "from_server",
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -1, "message": "down"}},
            2.5,
        ),
        message("from_server", "not json\n", 2.6),
        {"v": 1, "type": "other"},
    ]
    (tmp_path / mcp_proxy.FILE).write_text("".join(json.dumps(r) + "\n" for r in found))
    items, info = trace.read_mcp(tmp_path / mcp_proxy.FILE)
    assert [(it["ts"], it["output"], it["error"]) for it in items] == [
        (1.0, None, "down"),
        (1.5, None, "no such product"),
        (1.7, None, "no response in mcp.jsonl"),
    ]
    assert [it["source"].get("result_line") for it in items] == [6, 5, None]
    assert info["rows"] == 8 and info["ignored"] == {"other": 1}


def test_a_stdio_wrapper_sees_the_mcp_calls_with_no_address() -> None:
    span = trace._item("otel", "t", "otel.jsonl", 1, 1.0)
    span.update(kind="span", input={"mcp.method.name": "tools/call"})
    answer = discovery.make(mcp_servers=[stdio_part()])
    egress = {"answer": answer, "proxies": {"stock": mcp_proxy.STDIO}, "receiver": None}

    def found() -> list[dict]:
        return trace.unseen_calls([span], trace.egress_seen({"egress": egress}) or set())

    assert found() == []
    # A second stdio server with no wrapper can make the call, so the call is not seen.
    answer["mcp_servers"].append(stdio_part(None) | {"name": "files"})
    (finding,) = found()
    assert finding["detail"] == "MCP tools/call at no network address: no proxy saw this call"
    answer["mcp_servers"].pop()
    egress["proxies"] = {}
    assert len(found()) == 1

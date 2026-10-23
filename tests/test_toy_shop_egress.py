"""The 2 MCP servers of examples/toy-shop-egress/, with no model: the catalog over HTTP and the
notes over stdio."""

import json
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

EGRESS = Path(__file__).resolve().parent.parent / "examples" / "toy-shop-egress"
pytestmark = pytest.mark.skipif(not EGRESS.exists(), reason="the sdist has no examples folder")
sys.path.insert(0, str(EGRESS))

import catalog_mcp  # noqa: E402


def rpc(rid: int | None, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    return out if rid is None else {**out, "id": rid}


@pytest.fixture
def catalog() -> Iterator[str]:
    server = catalog_mcp.CatalogServer(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.url
    server.shutdown()
    server.server_close()


def post(url: str, body: dict[str, Any]) -> tuple[int, bytes]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


def test_the_catalog_finds_a_product(catalog: str) -> None:
    status, body = post(catalog, rpc(1, "initialize", {"protocolVersion": "2025-03-26"}))
    assert status == 200
    assert json.loads(body)["result"]["protocolVersion"] == "2025-03-26"
    assert post(catalog, rpc(None, "notifications/initialized")) == (202, b"")
    tools = json.loads(post(catalog, rpc(2, "tools/list"))[1])["result"]["tools"]
    assert [t["name"] for t in tools] == ["find_product"]
    call = rpc(3, "tools/call", {"name": "find_product", "arguments": {"name": "train"}})
    result = json.loads(post(catalog, call)[1])["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])[0]["sku"] == "wooden-train"


def test_the_catalog_refuses_an_unknown_tool_and_a_get(catalog: str) -> None:
    call = rpc(4, "tools/call", {"name": "refund", "arguments": {}})
    assert json.loads(post(catalog, call)[1])["error"]["code"] == -32602
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(catalog, timeout=5)
    assert e.value.code == 405


def test_the_notes_server_adds_a_note(tmp_path: Path) -> None:
    lines = [
        rpc(1, "initialize"),
        rpc(None, "notifications/initialized"),
        rpc(2, "tools/call", {"name": "add_note", "arguments": {"order": "7310", "text": "wheel"}}),
        rpc(3, "tools/call", {"name": "add_note", "arguments": {"order": "7310"}}),
    ]
    p = subprocess.run(
        [sys.executable, str(EGRESS / "notes_mcp.py")],
        input="".join(json.dumps(x) + "\n" for x in lines),
        capture_output=True,
        text=True,
        env={"TOY_NOTES": str(tmp_path / "notes.json")},
        timeout=30,
    )
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert [x["id"] for x in out] == [1, 2, 3]
    assert out[1]["result"]["isError"] is False
    assert out[2]["result"]["isError"] is True
    assert json.loads((tmp_path / "notes.json").read_text()) == [{"order": "7310", "text": "wheel"}]


def test_the_catalog_does_not_look_up_the_host_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # On the macOS runners of CI, socket.getfqdn took 35 s at the start of the catalog (#17).
    def slow(name: str = "") -> str:
        raise AssertionError("getfqdn")

    monkeypatch.setattr(socket, "getfqdn", slow)
    server = catalog_mcp.CatalogServer(0)
    server.server_close()
    assert server.url == f"http://127.0.0.1:{server.server_address[1]}/mcp"

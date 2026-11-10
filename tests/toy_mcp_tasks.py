"""Run the stock MCP task and scope steps through the real HTTP proxy."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
from typing import Any

from toy_stock_server import StockServer

from nookku import backend, mcp_proxy, trace
from nookku.record import loads

CASE = Path(__file__).resolve().parents[1] / "conformance" / "mcp" / "task-auth.json"


def observe(folder: Path) -> dict[str, Any]:
    case = loads(CASE.read_bytes())
    path = folder / mcp_proxy.FILE
    with StockServer() as stock:
        servers = [backend.Backend("stock", "STOCK_MCP_URL", stock.url + "/mcp")]
        proxies = backend.Proxies(servers, path, mcp_proxy.HttpProxy)
        proxies.start()
        try:
            host, port = proxies.proxies[0].server_address
            for step in case["steps"]:
                request = step["request"]
                response = step["response"]
                body = json.dumps(response).encode() if response is not None else b""
                mime = "application/json"
                if request is None:
                    body = b"data: " + body + b"\n\n"
                    mime = "text/event-stream"
                stock.status = step["status"]
                stock.answer_body = body
                stock.answer_headers = [("Content-Type", mime)]
                challenge = step.get("challenge")
                if challenge is not None:
                    stock.answer_headers.append(("WWW-Authenticate", challenge))
                conn = http.client.HTTPConnection(host, port, timeout=10)
                try:
                    conn.request(
                        "GET" if request is None else "POST",
                        "/mcp",
                        body=None if request is None else json.dumps(request).encode(),
                        headers={"Authorization": "Bearer toy-credential"},
                    )
                    resp = conn.getresponse()
                    assert resp.status == step["status"]
                    assert resp.getheader("WWW-Authenticate") == challenge
                    assert resp.read() == body
                finally:
                    conn.close()
        finally:
            proxies.stop()

    (folder / "manifest.json").write_text('{"test": "toy-mcp-tasks"}\n', encoding="utf-8")
    report = trace.build(folder)
    items = [loads(line) for line in (folder / "trace.jsonl").read_text().split("\n") if line]
    auth = [
        {
            "line": it["source"]["line"],
            "status": it["exit_code"],
            "scope": it["input"]["scope"],
            "error": it["input"]["error"],
        }
        for it in items
        if it["kind"] == "mcp_auth"
    ]
    tasks = [
        {"line": it["source"]["line"], "task_id": it["input"]["task_id"], "status": it["output"]}
        for it in items
        if it["kind"] == "mcp_task"
    ]
    findings = [f for f in report["findings"] if f["check"] == "mcp_task_unfinished"]
    return {
        "auth": auth,
        "tasks": tasks,
        "unfinished": findings,
        "credential_absent": all(
            "toy-credential" not in p.read_text() for p in (path, folder / "trace.jsonl")
        ),
    }

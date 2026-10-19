"""The JSON-RPC part of the 2 toy MCP servers of the egress toy shop: catalog_mcp.py over HTTP and
notes_mcp.py over stdio. Standard library only.

A server gives its tools and a function that runs a tool. `answer` gives the response to one
request, or None for a notification.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

PROTOCOL = "2025-06-18"

Run = Callable[[str, dict[str, Any]], tuple[Any, bool]]


def answer(request: Any, name: str, tools: list[dict[str, Any]], run: Run) -> dict[str, Any] | None:
    """The response to one JSON-RPC request, or None for a notification."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error(None, -32600, "not a JSON-RPC 2.0 request")
    if "id" not in request:
        return None
    rid = request["id"]
    method = request.get("method")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": params.get("protocolVersion", PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": name, "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools}
    elif method == "tools/call":
        tool = params.get("name")
        if tool not in {t["name"] for t in tools}:
            return _error(rid, -32602, f"no such tool: {tool}")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        data, failed = run(str(tool), args)
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        result = {"content": [{"type": "text", "text": text}], "isError": failed}
    else:
        return _error(rid, -32601, f"no such method: {method}")
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

"""A toy shop MCP server over stdio with one tool, `check_stock`. Local only.

tests/toy_models_entry.py gives it to its Codex thread, so that the rollout has an MCP tool call.
"""

from __future__ import annotations

import json
import sys
from typing import Any

STOCK = {"mug": 12, "teapot": 0}
TOOL = {
    "name": "check_stock",
    "description": "The number of items in stock for a toy shop product",
    "inputSchema": {
        "type": "object",
        "properties": {"product": {"type": "string"}},
        "required": ["product"],
    },
    "annotations": {"readOnlyHint": True},
}


def result(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "stock", "version": "0"},
        }
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        product = str((params.get("arguments") or {}).get("product", "")).lower()
        if product not in STOCK:
            return {"content": [{"type": "text", "text": "no such product"}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps({"in_stock": STOCK[product]})}]}
    return {}


def main() -> None:
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        out = {
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": result(msg["method"], msg.get("params") or {}),
        }
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

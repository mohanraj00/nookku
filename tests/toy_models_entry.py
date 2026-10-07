"""A toy shop app with real model sessions, for scripts/proof_sessions.py. Local only.

Each message goes to one Claude Agent SDK session (with an in-process `lookup_order` tool) and to
one `codex app-server` thread. The Codex thread has `lookup_order` as a dynamic tool, the toy MCP
server `check_stock` (tests/toy_mcp_server.py) and a shell for returns questions. The entry speaks
the agent contract. It needs claude-agent-sdk:

    uv run --with claude-agent-sdk python tests/toy_models_entry.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from claude_agent_sdk import (  # type: ignore[import-not-found]
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    create_sdk_mcp_server,
    tool,
)

from verbatim_relay import contract

ORDERS = {"4471": {"item": "blue mug", "status": "delivered", "price_eur": 8}}
SYSTEM = "You are the toy shop support agent. Use lookup_order for order questions. One sentence."
CODEX_SYSTEM = SYSTEM + (
    " For a stock question, use check_stock."
    " For a returns question, run the shell command `cat returns.txt`."
)
STOCK_SERVER = {
    "command": sys.executable,
    "args": [str(Path(__file__).with_name("toy_mcp_server.py"))],
}
LOOKUP = {
    "type": "function",
    "name": "lookup_order",
    "description": "Look up a toy shop order by its number",
    "inputSchema": {
        "type": "object",
        "properties": {"order": {"type": "string"}},
        "required": ["order"],
    },
}


def lookup(order: str) -> tuple[str, bool]:
    """The order as JSON text, and False if the order does not exist."""
    found = ORDERS.get(order)
    return json.dumps(found or {"error": "no such order"}), found is not None


@tool("lookup_order", "Look up a toy shop order by its number", {"order": str})
async def lookup_order(args: dict[str, Any]) -> dict[str, Any]:
    text, ok = lookup(args["order"])
    return {"content": [{"type": "text", "text": text}], "is_error": not ok}


class CodexThread:
    """One read-only codex app-server thread in the project."""

    def __init__(self, cwd: str) -> None:
        self.p = subprocess.Popen(
            ["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        self.n = 0
        client = {"name": "toy-shop", "version": "0"}
        self.call("initialize", {"clientInfo": client, "capabilities": {"experimentalApi": True}})
        self.send({"jsonrpc": "2.0", "method": "initialized"})
        params = {"cwd": cwd, "sandbox": "read-only", "approvalPolicy": "never"}
        params |= {"developerInstructions": CODEX_SYSTEM, "dynamicTools": [LOOKUP]}
        stock = {**STOCK_SERVER, "default_tools_approval_mode": "approve"}
        params["config"] = {"mcp_servers": {"stock": stock}}
        self.thread = self.call("thread/start", params)["thread"]["id"]

    def send(self, msg: dict[str, Any]) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def read(self) -> dict[str, Any]:
        """The next message from the server. It answers each lookup_order call on the way."""
        assert self.p.stdout is not None
        while True:
            msg = json.loads(self.p.stdout.readline())
            if msg.get("method") != "item/tool/call" or "id" not in msg:
                return msg
            text, ok = lookup(str((msg["params"].get("arguments") or {}).get("order", "")))
            result = {"contentItems": [{"type": "inputText", "text": text}], "success": ok}
            self.send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            msg = self.read()
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]

    def turn(self, text: str) -> str:
        self.call(
            "turn/start", {"threadId": self.thread, "input": [{"type": "text", "text": text}]}
        )
        reply = ""
        while True:
            msg = self.read()
            params = msg.get("params") or {}
            item = params.get("item") or {}
            if msg.get("method") == "item/completed" and item.get("type") == "agentMessage":
                reply = item.get("text", "")
            if msg.get("method") == "turn/completed":
                return reply

    def close(self) -> None:
        assert self.p.stdin is not None
        self.p.stdin.close()
        self.p.wait(timeout=30)


async def main() -> None:
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    shop = create_sdk_mcp_server("shop", tools=[lookup_order])
    options = ClaudeAgentOptions(
        cwd=os.getcwd(),
        model="haiku",
        system_prompt=SYSTEM,
        mcp_servers={"shop": shop},
        allowed_tools=["mcp__shop__lookup_order"],
        # Isolate the session: no settings files, no claude.ai connectors, no plugins.
        setting_sources=[],
        strict_mcp_config=True,
        env={"CLAUDE_CODE_PLUGIN_DIRS": ""},
    )
    loop = asyncio.get_running_loop()
    codex = await loop.run_in_executor(None, CodexThread, os.getcwd())
    async with ClaudeSDKClient(options=options) as client:
        while raw := await loop.run_in_executor(None, sys.stdin.buffer.readline):
            rid, message, _ = contract.parse_request(raw.removesuffix(b"\n"))
            await client.query(message)
            claude = ""
            async for m in client.receive_response():
                if isinstance(m, ResultMessage):
                    claude = m.result or ""
            second = await loop.run_in_executor(None, codex.turn, message)
            text = f"{claude}\n\nSecond opinion: {second}"
            line = json.dumps({"v": 1, "id": rid, "reply": text}, ensure_ascii=False)
            out.write(line.encode() + b"\n")
    codex.close()


if __name__ == "__main__":
    asyncio.run(main())

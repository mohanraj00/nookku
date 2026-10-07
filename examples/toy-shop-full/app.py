"""The full toy shop support agent: one Claude Agent SDK session with 3 tools, a stock service and a
case-note model.

- The tools read the orders in state.json (or $TOY_SHOP_STATE), and call the stock service at
  STOCK_URL (stock.py).
- After each reply, the app asks the note model at OPENAI_BASE_URL for a case note, and adds it to
  state.json. toy_model.py is a toy note model.
- The shop's rules are in RULES.md.

It needs claude-agent-sdk, which is not a dependency of verbatim-relay:

    uv run --with claude-agent-sdk python examples/toy-shop-full/entry.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import services
from claude_agent_sdk import (  # type: ignore[import-not-found]
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    create_sdk_mcp_server,
    tool,
)

STATE = Path(os.environ.get("TOY_SHOP_STATE", Path(__file__).with_name("state.json")))
SYSTEM = (
    "You are the support agent of a toy shop. Use the tools for orders, stock and reservations. "
    "Answer in 2 sentences or fewer."
)


def load() -> dict[str, Any]:
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def text(data: Any, error: bool = False) -> dict[str, Any]:
    body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return {"content": [{"type": "text", "text": body}], "is_error": error}


@tool("lookup_order", "Look up an order by its number", {"order": str})
async def lookup_order(args: dict[str, Any]) -> dict[str, Any]:
    order = load()["orders"].get(args["order"])
    return text(order) if order else text("no such order", error=True)


@tool("check_stock", "The number of items left for a SKU, for example teapot-set", {"sku": str})
async def check_stock(args: dict[str, Any]) -> dict[str, Any]:
    left = services.stock(args["sku"])
    return text(left, error="error" in left)


@tool(
    "reserve",
    "Reserve a number of items of a SKU for an order",
    {"order": str, "sku": str, "qty": int},
)
async def reserve(args: dict[str, Any]) -> dict[str, Any]:
    done = services.reserve(args["order"], args["sku"], args["qty"])
    if "error" in done:
        return text(done["error"], error=True)
    return text({"reservation": done["reservation"], "sku": args["sku"], "qty": args["qty"]})


class Shop:
    """One model session for one conversation."""

    def __init__(self) -> None:
        tools = [lookup_order, check_stock, reserve]
        server = create_sdk_mcp_server("shop", tools=tools)
        self.client = ClaudeSDKClient(
            options=ClaudeAgentOptions(
                cwd=str(Path(__file__).parent),
                model="haiku",
                system_prompt=SYSTEM,
                mcp_servers={"shop": server},
                allowed_tools=[f"mcp__shop__{t.name}" for t in tools],
                # Isolate the session from the machine of the tester: no settings files, only
                # the shop's MCP server (no claude.ai connectors), and no plugins from
                # CLAUDE_CODE_PLUGIN_DIRS.
                setting_sources=[],
                strict_mcp_config=True,
                env={
                    # Load the 3 tools at the start. Without this, the model must first find
                    # each tool with ToolSearch, and a small model can repeat that search.
                    "ENABLE_TOOL_SEARCH": "false",
                    "CLAUDE_CODE_PLUGIN_DIRS": "",
                },
            )
        )

    async def __aenter__(self) -> Shop:
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.client.__aexit__(*exc)

    async def reply(self, message: str) -> str:
        await self.client.query(message)
        answer = ""
        async for m in self.client.receive_response():
            if isinstance(m, ResultMessage):
                answer = m.result or ""
        state = load()
        state.setdefault("notes", []).append(services.case_note(message, answer))
        save(state)
        return answer

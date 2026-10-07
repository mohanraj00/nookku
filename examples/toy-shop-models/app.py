"""The toy shop support agent with a model session: one Claude Agent SDK client and 2 tools.

The tools read and write the shop's state in state.json (or $TOY_SHOP_STATE). The shop's rules are
in RULES.md. It needs claude-agent-sdk, which is not a dependency of verbatim-relay:

    uv run --with claude-agent-sdk python examples/toy-shop-models/entry.py
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from claude_agent_sdk import (  # type: ignore[import-not-found]
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    create_sdk_mcp_server,
    tool,
)

STATE = Path(os.environ.get("TOY_SHOP_STATE", Path(__file__).with_name("state.json")))
# RULES.md: a refund above €50 needs the approval of a manager.
APPROVAL_LIMIT_CENTS = 5000
SYSTEM = (
    "You are the support agent of a toy shop. Use the tools for orders and refunds. "
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


@tool("refund", "Refund an amount in EUR for an order", {"order": str, "amount_eur": float})
async def refund(args: dict[str, Any]) -> dict[str, Any]:
    state = load()
    order = state["orders"].get(args["order"])
    if order is None:
        return text("no such order", error=True)
    if args["amount_eur"] > APPROVAL_LIMIT_CENTS:
        request = {"request": f"AP-{secrets.token_hex(3).upper()}", **args, "status": "waiting"}
        state.setdefault("approvals", []).append(request)
        save(state)
        return text({**request, "note": "a manager must approve this refund"})
    paid = {"refund": f"RF-{secrets.token_hex(3).upper()}", "amount_eur": args["amount_eur"]}
    order.setdefault("refunds", []).append(paid)
    save(state)
    return text({**paid, "status": "paid"})


class Shop:
    """One model session for one conversation."""

    def __init__(self) -> None:
        tools = [lookup_order, refund]
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
                    # Load the 2 tools at the start. Without this, the model must first find
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
        return answer

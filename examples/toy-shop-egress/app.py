"""The toy shop support agent with 4 egress parts: one Claude Agent SDK session with 2 tools of its
own and 2 MCP servers.

- `lookup_order` reads the orders from Postgres at DATABASE_URL, with psycopg.
- `start_return` writes a return into the SQLite file returns.db, with sqlite3.
- The catalog MCP server over HTTP at CATALOG_MCP_URL (catalog_mcp.py) gives the products.
- The notes MCP server over stdio (notes_mcp.py) adds a note to an order. NOTES_MCP_COMMAND holds
  its command line. The app splits the line into words.

The app sends OpenTelemetry spans of its 2 database drivers if OTEL_EXPORTER_OTLP_ENDPOINT has a
value. It needs claude-agent-sdk, psycopg and the OpenTelemetry packages of entry.py, which are not
dependencies of nookku.
"""

from __future__ import annotations

import json
import os
import shlex
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import psycopg  # type: ignore[import-not-found]
from claude_agent_sdk import (  # type: ignore[import-not-found]
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    create_sdk_mcp_server,
    tool,
)

HERE = Path(__file__).parent
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://shop:toy-shop-pw@127.0.0.1:55432/shop")
CATALOG_MCP_URL = os.environ.get("CATALOG_MCP_URL", "http://127.0.0.1:9310/mcp")
NOTES_MCP_COMMAND = os.environ.get("NOTES_MCP_COMMAND", "python3 notes_mcp.py")
RETURNS_DB = HERE / "returns.db"
SYSTEM = (
    "You are the support agent of a toy shop. Use the tools for orders, products, returns and "
    "notes. After you start a return, add a note to the order. Answer in 2 sentences or fewer."
)


def telemetry() -> Any:
    """Send the spans of the 2 database drivers to the OTLP endpoint. Return the provider, or None
    if OTEL_EXPORTER_OTLP_ENDPOINT has no value."""
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None
    from opentelemetry import trace  # type: ignore[import-not-found]
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.psycopg import (  # type: ignore[import-not-found]
        PsycopgInstrumentor,
    )
    from opentelemetry.instrumentation.sqlite3 import (  # type: ignore[import-not-found]
        SQLite3Instrumentor,
    )
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-not-found]

    provider = TracerProvider(resource=Resource.create({"service.name": "toy-shop"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    PsycopgInstrumentor().instrument()
    SQLite3Instrumentor().instrument()
    return provider


PROVIDER = telemetry()


def text(data: Any, error: bool = False) -> dict[str, Any]:
    body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": body}], "is_error": error}


@tool("lookup_order", "Look up an order by its number, for example 7310", {"order": str})
async def lookup_order(args: dict[str, Any]) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as db:
        row = db.execute(
            "SELECT id, status, items FROM orders WHERE id = %s", (args["order"],)
        ).fetchone()
    if row is None:
        return text("no such order", error=True)
    return text({"order": row[0], "status": row[1], "items": row[2]})


@tool(
    "start_return",
    "Start the return of an item of an order",
    {"order": str, "sku": str, "reason": str},
)
async def start_return(args: dict[str, Any]) -> dict[str, Any]:
    rid = f"RT-{uuid.uuid4().hex[:6].upper()}"
    db = sqlite3.connect(RETURNS_DB)
    try:
        # The instrumentation of sqlite3 traces the execute of a cursor, not of a connection.
        cur = db.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS returns (id TEXT, order_id TEXT, sku TEXT, reason TEXT)"
        )
        cur.execute(
            "INSERT INTO returns VALUES (?, ?, ?, ?)",
            (rid, args["order"], args["sku"], args["reason"]),
        )
        db.commit()
    finally:
        db.close()
    return text({"return": rid, "order": args["order"], "sku": args["sku"]})


class Shop:
    """One model session for one conversation."""

    def __init__(self) -> None:
        tools = [lookup_order, start_return]
        words = shlex.split(NOTES_MCP_COMMAND)
        servers: dict[str, Any] = {
            "shop": create_sdk_mcp_server("shop", tools=tools),
            "catalog": {"type": "http", "url": CATALOG_MCP_URL},
            "notes": {"type": "stdio", "command": words[0], "args": words[1:]},
        }
        allowed = [f"mcp__shop__{t.name}" for t in tools]
        allowed += ["mcp__catalog__find_product", "mcp__notes__add_note"]
        self.client = ClaudeSDKClient(
            options=ClaudeAgentOptions(
                cwd=str(HERE),
                model="haiku",
                system_prompt=SYSTEM,
                mcp_servers=servers,
                allowed_tools=allowed,
                # Isolate the session from the machine of the tester: no settings files, only
                # the MCP servers of the app (no claude.ai connectors), and no plugins from
                # CLAUDE_CODE_PLUGIN_DIRS.
                setting_sources=[],
                strict_mcp_config=True,
                env={"ENABLE_TOOL_SEARCH": "false", "CLAUDE_CODE_PLUGIN_DIRS": ""},
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
        if PROVIDER is not None:
            # The receiver has the spans of the turn before the reply goes out.
            PROVIDER.force_flush()
        return answer

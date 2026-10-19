# Egress toy shop

This is the toy shop support agent with 4 egress parts: 2 MCP servers and 2 databases. It shows how a test records the calls of an app to MCP servers and databases ([SPEC.md sections 7.11 to 7.13](../../SPEC.md#711-egress-discovery)).

- [app.py](app.py) is the agent: one Claude Agent SDK session with 2 tools of its own and 2 MCP servers.
  - The tool `lookup_order` reads the orders from Postgres at `DATABASE_URL`, with psycopg.
  - The tool `start_return` writes a return into the SQLite file `returns.db`, with sqlite3.
  - The app sends the OpenTelemetry spans of the 2 database drivers if `OTEL_EXPORTER_OTLP_ENDPOINT` has a value. Nookku gives the app this variable during a test.
- [catalog_mcp.py](catalog_mcp.py) is the catalog MCP server over HTTP, at `CATALOG_MCP_URL`.
- [notes_mcp.py](notes_mcp.py) is the notes MCP server over stdio. `NOTES_MCP_COMMAND` holds its command line. It writes the notes to `notes.json`.
- [toy_mcp.py](toy_mcp.py) is the JSON-RPC part of the 2 MCP servers.
- [orders.sql](orders.sql) has the orders.
- [entry.py](entry.py) is the entry. It speaks the agent contract on stdin and stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)).

## Run it

The app needs packages that are not dependencies of Nookku. The entry command gets them with `uv run --with`. Copy this folder to a new folder outside the repo, for example with `cp -R examples/toy-shop-egress ~/toy-shop-egress`. Do these steps in the copy:

1. Start Postgres 16 on port 55432, with the user `shop`, the password `toy-shop-pw` and the database `shop`. Then load the orders:

   ```bash
   docker run -d --rm --name toy-shop-pg -e POSTGRES_USER=shop -e POSTGRES_PASSWORD=toy-shop-pw -e POSTGRES_DB=shop -p 127.0.0.1:55432:5432 postgres:16-alpine
   ```

   ```bash
   docker exec -i -e PGPASSWORD=toy-shop-pw toy-shop-pg psql -h 127.0.0.1 -U shop -d shop < orders.sql
   ```

2. Start the catalog MCP server in its own shell:

   ```bash
   python3 catalog_mcp.py 9310
   ```

3. Give the harness the URL of the database, before you start it. The proxy reads the address from this variable:

   ```bash
   export DATABASE_URL=postgres://shop:toy-shop-pw@127.0.0.1:55432/shop
   ```

4. Run `nookku init` with your relay. This example uses the plugin:

   ```bash
   nookku init plugin --entry "uv run --with claude-agent-sdk --with nookku --with 'psycopg[binary]' --with opentelemetry-sdk --with opentelemetry-exporter-otlp-proto-http --with opentelemetry-instrumentation-psycopg --with opentelemetry-instrumentation-sqlite3 python3 entry.py" --models claude-code
   ```

5. Type the prompt `nookku start` in the harness. The model reads the code and runs `nookku register` with the egress answer. Check that it shows these parts. The names of the parts can be different:

   ```text
   - model API anthropic: ANTHROPIC_BASE_URL -> the URL in ANTHROPIC_BASE_URL or the default (proxy)
   - MCP server catalog: http CATALOG_MCP_URL -> http://127.0.0.1:9310/mcp (proxy)
   - MCP server notes: stdio NOTES_MCP_COMMAND -> python3 notes_mcp.py (proxy)
   - database orders: postgres, DATABASE_URL (proxy)
   - database returns: sqlite, returns.db (driver trace)
   ```

6. Type `nookku start` again, and send a message, for example "The wooden train set from order 7310 has a broken wheel. Please start a return for it."

The test folder then has the MCP calls in `mcp.jsonl`, the Postgres messages in `database.jsonl`, and the SQLite queries as driver queries in `trace.jsonl`. [scripts/proof_egress.py](../../scripts/proof_egress.py) runs these steps in Claude Code and in Codex.

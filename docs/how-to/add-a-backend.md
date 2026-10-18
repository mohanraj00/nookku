# Add a backend

A backend is an HTTP service that your app calls, for example a stock service or a payment service. At each start, the [harness model](../reference/glossary.md#harness-model) finds each backend of your app, and the test records each call of the app to it. The [trace](../reference/glossary.md#trace) shows each call in its turn, so the [evaluation](../reference/glossary.md#evaluation) can see what the app did, not only what it said.

## 1. Find the variable of the URL

The app must read the URL of the service from an environment variable. The full toy shop reads its stock service URL from `STOCK_URL` ([services.py](../../examples/toy-shop-full/services.py)).

If your app reads the URL from a file and not from the environment, let the [entry](../reference/glossary.md#entry) give the app the URL from the variable. For example, the entry can write a copy of the app's configuration for the test. Do not change the app's own files.

## 2. Check the egress answer

You do not write the backends into `.nookku/config.json`. When you type `nookku start`, the model reads the code of your app and runs `nookku register` with the egress answer ([SPEC.md section 7.11](../../SPEC.md#711-egress-discovery)). The model then shows one line for each part:

```text
- backend stock: STOCK_URL -> http://127.0.0.1:9001 (proxy)
```

- `stock` names the backend in the record and in the trace.
- `STOCK_URL` is the variable of step 1.
- The URL is the real URL of the service, `http` or `https`.

If a line is wrong, tell the model. It runs `nookku register` again. Then type `nookku start` again in the next 30 minutes ([`FRESH`](../../src/nookku/discovery.py)).

Each name and each variable can occur only once. You can also run `nookku register` yourself in a shell, with the answer as JSON ([cli.md](../reference/cli.md#nookku-register)):

```bash
nookku register <<'EOF'
{"model_apis": [], "backends": [{"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9001"}],
 "mcp_servers": [], "databases": [], "other": []}
EOF
```

## 3. Run a test

During a test, the [bridge](../reference/glossary.md#bridge) runs a recording proxy for each backend, and gives your app the proxy URL in `env`. The proxy forwards each byte to `url` and back. It writes each call to `backend.jsonl` in the [test folder](../reference/glossary.md#test-folder), with the method, the path, the headers, the bodies and the status ([SPEC.md section 7.6](../../SPEC.md#76-backend-proxies)).

- It removes the values of secret headers and secret query parameters from the record, for example `Authorization` or `api_key=`. The service still gets them.
- It reads the whole response before it sends it, so a streamed response arrives at your app in 1 piece.
- If the service does not answer, the proxy sends status 502 to your app.
- A body longer than 1 MiB is cut in the record, but the service and your app get each byte ([proof](../results.md#backend-calls)).

## 4. Read the calls

After the test, `nookku transcript --trace` shows each call under its turn, as an `http` item with its `trace.jsonl` line. The check `backend_error` finds each call with no answer or a status of 500 or more ([SPEC.md section 8.6](../../SPEC.md#86-findings)).

```bash
nookku transcript --trace
nookku trace
```

## MCP servers

An MCP server of your app gets a proxy in the same way, if the app reads the server from a variable ([SPEC.md section 7.12](../../SPEC.md#712-mcp-proxies)):

- For an `http` server, the variable holds its URL. The proxy records each call to `mcp.jsonl`.
- For a `stdio` server, the variable holds the command line of the server. The app splits the line into words and starts it. During a test, the variable holds the `nookku mcp-stdio` command, which starts the server and records each line to `mcp.jsonl`.

A server with no variable has no proxy. The start text names it with `(no proxy)`. The trace shows each `tools/call` of `mcp.jsonl` as a `tool_call` item, and the check `tool_error` finds each call with an error.

## Postgres databases

A Postgres database of your app gets a proxy if the app reads its `postgres://` URL from a variable, for example `DATABASE_URL` ([SPEC.md section 7.13](../../SPEC.md#713-postgres-proxies)). The variable must have its value in the [harness](../reference/glossary.md#harness) when the test starts. During the test, the URL has the address of the proxy, with the same user, password and database. The proxy records each query and its rows to `database.jsonl`, and never the password. The trace shows each query as a `query` item, and the check `database_error` finds each query with an error.

The proxy speaks no TLS, so use a URL with no `sslmode`, or with `sslmode=disable` or `prefer`.

## Example

[examples/toy-shop-full/](../../examples/toy-shop-full/app.py) has a stock service and a planted bug that only the backend calls show. After 1 `reserve` tool call, the app reserves the items 2 times. In the telemetry proof, each report cited both `POST /reserve` calls of turn 2 ([results](../results.md#full-telemetry-with-one-app), [method](../../scripts/proof_telemetry.py)).

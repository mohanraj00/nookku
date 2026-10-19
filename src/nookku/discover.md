# Find the egress of the agent

The tester wants to start a test of the agent in `{root}`. Before the test starts, nookku must know each service that the agent calls. Nookku then starts a proxy for each part, so that the record shows each call. Do not start the test yourself.

## Find

Read the code of the agent, its configuration and its `.env` example files. The entry command is in `.nookku/config.json`. Find each egress part:

1. Each model API that the agent calls directly with an SDK: `anthropic` or `openai`, the variable that holds its base URL, and its upstream URL.
2. Each HTTP backend: a name, the variable that holds its URL, and its upstream URL.
3. Each MCP server that the agent calls: a name, its transport (`stdio` or `http`), the variable that holds its command or its URL (or `null`), and its command (a list of words) or its URL. For a `stdio` server, give a variable only if the agent reads the command line of the server from it and splits the line into words. Nookku puts its proxy into the variable, so a server with no variable has no proxy.
4. Each database: a name, its kind (for example `postgres` or `sqlite`), the variable that holds its address (or `null`), its address (`host:port/database`, the path of its file, or `null`), and how the test records its calls (`record`). For a `postgres` database, give the variable only if it holds the `postgres://` URL that the agent connects with. Nookku puts its proxy into that URL.
   - Give `"record": "proxy"` for a `postgres` database with that variable. The proxy is the first choice: it is outside the agent, and it records the rows of each answer.
   - Give `"record": "driver"` for each other database: a database that is not `postgres`, or a `postgres` database to which the proxy cannot connect, for example an agent that does not read a `postgres://` URL from a variable.
5. Each other part that the agent calls, for example a queue or a file share: a name, its kind and a short detail.

The developer configured the authentication of each part. Do not change it. Never write a secret into the answer: give the name of each variable, not its value. A URL or an address must not have a user, a password, a key or a token.

## Driver trace

For each database with `"record": "driver"`, add the OpenTelemetry instrumentation of its driver to the agent before you register the answer. Examples are the instrumentations of psycopg, asyncpg, SQLAlchemy and node-postgres. Turn on the statement text of the instrumentation. Configure the OpenTelemetry SDK of the agent with the standard `OTEL_*` variables and the OTLP exporter over HTTP. Nookku gives the agent these variables during the test, and its OTLP receiver records the spans. Do not change other code of the agent. Tell the tester the change, and tell the tester that a driver trace has no rows and can hide parameter values.

## Answer

Write the answer as JSON to the file `{root}/.nookku/egress.json` with your file tool. Do not write the file with a shell command. Give each list, also an empty one. Each key of a part is required. For example:

```json
{
  "model_apis": [{"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": null}],
  "backends": [{"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9100"}],
  "mcp_servers": [{"name": "files", "transport": "stdio", "env": null, "command": ["toy-files-mcp"], "url": null}],
  "databases": [
    {"name": "shop", "kind": "postgres", "env": "DATABASE_URL", "address": "127.0.0.1:5432/shop", "record": "proxy"},
    {"name": "returns", "kind": "sqlite", "env": null, "address": "returns.db", "record": "driver"}
  ],
  "other": []
}
```

Then run this command in a shell in `{root}`:

```bash
nookku register --file .nookku/egress.json
```

A `null` model API URL means: the value of the variable when the test starts, else the default URL of the API.

If `nookku register` refuses the answer, correct each error that it names in the file and run the command again.

## Then

Show the tester each line that `nookku register` printed. Tell the tester to check the parts, and then to type the prompt `nookku start` in the next {minutes} minutes. If the tester says that a part is wrong, correct the answer and run `nookku register` again. Do not start the test, and do not change the code of the agent, except for the driver trace.

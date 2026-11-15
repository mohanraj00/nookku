# Find the egress of the agent

The tester wants to start a test of the agent in `{root}`. Before the test starts, nookku must know each service that the agent calls. Nookku then starts a proxy for each part, so that the record shows each call. Do not start the test yourself.

## Find

Read the code of the agent, its configuration and its `.env` example files. The entry command is in `.nookku/config.json`. Find each egress part:

1. Each model API that the agent calls directly or through a harness SDK: `anthropic` or `openai`, the variable that holds its base URL, and its upstream URL. Include the API of a Claude Agent SDK session: `anthropic`, `ANTHROPIC_BASE_URL`, and `null` if the app does not set a URL. The SDK starts Claude Code, which calls this API. A harness session is not a reason to omit its model API.
2. Each HTTP backend: a name, the variable that holds its URL, and its upstream URL.
3. Each MCP server that the agent calls: a name, its transport (`stdio` or `http`), the variable that holds its command or its URL (or `null`), and its command (a list of words) or its URL. For a `stdio` server, give a variable only if the agent reads the command line of the server from it and splits the line into words. Nookku puts its proxy into the variable, so a server with no variable has no proxy.
4. Each database: a name, its kind (for example `postgres` or `sqlite`), the variable that holds its address (or `null`), its address (`host:port/database`, the path of its file, or `null`), and how the test records its calls (`record`). For a `postgres` database, give the variable only if it holds the `postgres://` URL that the agent connects with. Nookku puts its proxy into that URL.
   - Give `"record": "proxy"` for a `postgres` database with that variable. The proxy is the first choice: it is outside the agent, and it records the rows of each answer.
   - Give `"record": "driver"` for each other database: a database that is not `postgres`, or a `postgres` database to which the proxy cannot connect, for example an agent that does not read a `postgres://` URL from a variable.
5. Each other part that the agent calls, for example a queue, a mail service or a file share: a name, its kind, a short detail, and how the test records its calls (`record`).
   - Give `"record": "driver"` if an OpenTelemetry instrumentation exists for its client, for example kafka-python, confluent-kafka, aiokafka, pika, aio-pika, celery or boto3sqs in Python, or amqplib or kafkajs in Node. The kind is the `messaging.system` value of its spans, for example `kafka`, `rabbitmq` or `aws_sqs`.
   - For a vendor SDK that sends HTTP calls, first check if a variable gives its base URL. If yes, list it as a backend, so that the backend proxy records it. If no, give the kind `http` and `"record": "driver"`. The instrumentation of the HTTP client, for example httpx, requests or urllib3, then gives a span for each call.
   - Give `"record": "none"` if no standard instrumentation exists for its client, for example a mail service that the agent calls with smtplib. The test does not record its calls.
   - A Redis store or queue is a database with the kind `redis` and `"record": "driver"`, not an other part.

A file that an MCP server reads or writes as part of a tool is inside that server. Do not list it again as a database or an `other` part. The MCP proxy records the tool call. List a database separately if the agent connects to it itself.

The developer configured the authentication of each part. Do not change it. Never write a secret into the answer: give the name of each variable, not its value. A URL or an address must not have a user, a password, a key or a token.

## Driver trace

For each database and each other part with `"record": "driver"`, add the OpenTelemetry instrumentation of its driver or its client to the agent before you register the answer. Examples are the instrumentations of psycopg, asyncpg, SQLAlchemy and node-postgres. Turn on the statement text of the instrumentation. Configure the OpenTelemetry SDK of the agent with the standard `OTEL_*` variables and the OTLP exporter over HTTP. Nookku gives the agent these variables during the test, and its OTLP receiver records the spans. Do not change other code of the agent. Tell the tester the change, and tell the tester that a driver trace has no rows and can hide parameter values. For an other part, tell the tester that a span records the call (topic, queue, operation and status), but not each byte of the message. For each other part with `"record": "none"`, tell the tester that the test does not record its calls.

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
  "other": [
    {"name": "orders", "kind": "rabbitmq", "detail": "the order queue", "record": "driver"},
    {"name": "mail", "kind": "smtp", "detail": "sends the order mail", "record": "none"}
  ]
}
```

Then run this command in a shell in `{root}`:

```bash
nookku register --file .nookku/egress.json
```

A `null` model API URL means: the value of the variable when the test starts, else the default URL of the API.

If `nookku register` refuses the answer, correct each error that it names in the file and run the command again.

## Then

Show the tester each line that `nookku register` printed. Tell the tester to check the parts, and then to type the prompt `nookku start` in the next {minutes} minutes. If the tester says that a part is wrong, write the correct answer to the file again and run the command again. A valid answer removes the file. Do not start the test, and do not change the code of the agent, except for the driver trace.

# Claude Code

Two relays work in Claude Code. Use one of them, not both. With both, each message goes to the agent two times.

| Relay | Reply shows in | Status |
|---|---|---|
| Plugin (recommended) | the chat, as a dim row that the model does not receive | function hooks, early access |
| Hook kit (fallback) | `verbatim-relay view`, in a second terminal | classic hooks, stable |

Tested with Claude Code 2.1.290.

## Connect a test to your app

A test runs your app through an entry: a thin wrapper that starts the app and speaks the agent contract ([SPEC.md section 6](../SPEC.md#6-agent-contract-version-1)). The entry and its configuration are in `.verbatim-relay/`. Your app's code does not change.

1. Install the package: `uv tool install verbatim-relay`.
2. Ask the model: "Run `verbatim-relay setup` and connect a test to this app." With the plugin, the `setup` skill does the same. The model reads the app, writes `.verbatim-relay/entry.<ext>` and `.verbatim-relay/config.json`, and runs `verbatim-relay check`.
3. Review the entry. It is in the message path.

For the toy shop agent of the [quick start](../README.md#quick-start), the configuration is one line:

```json
{"entry": ["python", "examples/toy-shop/agent.py"], "models": []}
```

`models` lists the harnesses that your app uses for its own model sessions: `claude-code`, `codex` or both. `verbatim-relay check` fails if it does not find a session for each one.

### Backends

If your app calls HTTP services, for example a stock service, list them in `backends`:

```json
"backends": [{"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9001"}]
```

During a test, the bridge runs a recording proxy for each one, and gives your app the proxy URL in `env`. The proxy forwards each byte to `url` and back, and writes each call to `backend.jsonl`: the method, the path, the headers, the bodies and the status. It removes the values of secret headers, for example `Authorization`, from the record. The trace shows each call in its turn, and the check `backend_error` finds each call with no answer or a status of 500 or more. The proxy reads the whole response before it sends it, so a streamed response arrives at your app in 1 piece. [SPEC.md section 7.6](../SPEC.md#76-backend-proxies) defines the proxy.

### Direct model calls

If your app calls the Anthropic or the OpenAI API with an SDK, the bridge records these calls. During a test, it runs a recording proxy for each API, and gives your app the proxy URL in `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL`. The proxy forwards to the value that you had in the variable, else to the public API. It sends each part of a streamed response to your app when the part comes. It writes each call to `model_api.jsonl`, with the text, the tool calls and the stop reason, and without the API key. The trace shows each call in its turn, and the check `model_api_error` finds each call with an error or a status of 400 or more.

An Agent SDK session in your app also reads `ANTHROPIC_BASE_URL`, so its calls also go through the proxy. The record keeps only the size and the SHA-256 of these calls, because they hold the instructions of Claude Code. The session file already gives their turns. If your app uses Codex with a ChatGPT login, `OPENAI_BASE_URL` can send Codex to the public API. Then add `"model_api": ["anthropic"]` or `"model_api": false` to `.verbatim-relay/config.json`. To give the proxy an upstream URL that is not in the environment, use an object, for example `"model_api": {"anthropic": null, "openai": "http://127.0.0.1:9002/v1"}`. `null` takes the URL from the variable. [SPEC.md section 7.7](../SPEC.md#77-model-api-proxies) defines the proxy.

### OpenTelemetry

During a test, the bridge runs an OTLP/HTTP receiver and gives your app its address in the standard `OTEL_*` variables. These replace your app's own `OTEL_*` values for the test. If your app uses the OpenTelemetry SDK, its spans and logs go to `otel.jsonl` in the test folder and into the trace. An Agent SDK session also sends its prompts, tool calls and replies, because the bridge sets `CLAUDE_CODE_ENABLE_TELEMETRY=1`. The trace checks each tool call of these events against the session file. The receiver removes each `user.*`, `organization.*` and e-mail attribute before it writes a row. To stop the receiver, add `"otel": false` to `.verbatim-relay/config.json`. [SPEC.md section 7.5](../SPEC.md#75-otlp-receiver) defines the receiver.

### Isolate the app's model session

An Agent SDK session can load more than your app gives it. With `setting_sources=[]`, it still connects to the claude.ai connectors of the tester's account, and it loads each plugin in the variable `CLAUDE_CODE_PLUGIN_DIRS`. Then the app's model can see tools that are not the app's tools. It can reach the tester's accounts, and the result of a test depends on the tester's machine.

To give the session only the tools of your app, set these options in the app (Python Agent SDK):

```python
ClaudeAgentOptions(
    mcp_servers={"shop": server},
    allowed_tools=["mcp__shop__lookup_order"],
    setting_sources=[],
    strict_mcp_config=True,
    env={"CLAUDE_CODE_PLUGIN_DIRS": ""},
)
```

- `setting_sources=[]` loads no settings file: no user, project or local settings, and thus no plugins, hooks or MCP servers from them. In TypeScript, the option is `settingSources: []`.
- `strict_mcp_config=True` passes `--strict-mcp-config` to Claude Code. The session then uses only the servers in `mcp_servers`, and no claude.ai connectors, no `.mcp.json` and no plugin servers. In TypeScript, the option is `strictMcpConfig: true`. The [Agent SDK reference](https://code.claude.com/docs/en/agent-sdk/python) defines both options.
- `CLAUDE_CODE_PLUGIN_DIRS` with an empty value loads no plugins from this variable. The session gets the variable from the entry, and thus from the tester's harness. `env` sets it for the session only.
- If your app loads MCP servers from `.mcp.json` or from a settings file, `strict_mcp_config` also stops them. Then set `ENABLE_CLAUDEAI_MCP_SERVERS` to `false` in `env`, in place of `strict_mcp_config`. This variable stops only the claude.ai connectors ([MCP docs](https://code.claude.com/docs/en/mcp#use-mcp-servers-from-claude-ai)).

The toy shop apps in [examples/](../examples/) use these options. The trace check `server_not_from_app` finds a claude.ai connector or a plugin server in a session file of your app ([SPEC.md section 8.6](../SPEC.md#86-findings)).

## Plugin

1. Add the marketplace and install the plugin:

   ```bash
   claude plugin marketplace add mohanraj00/verbatim-relay
   claude plugin install verbatim-relay@verbatim-relay
   ```

2. Connect a test to your app (see above).
3. Type `/verbatim-relay start`. The plugin starts the entry through the tap, and relay mode goes on. The status line shows it.
4. Type your test messages. Each reply shows as a row in the chat and in the verbatim-relay pane.
5. Type the prompt `verbatim-relay end`, with no slash. The plugin stops the entry, copies the app's session files into the test folder, builds the trace and switches relay mode off. Then the prompt goes to the model with the evaluation prompt, and the model writes `report.md` in the test folder (see [Evaluation](#evaluation)).

`/verbatim-relay end` ends the test with no evaluation. To evaluate that test later, type the prompt `verbatim-relay end`. `/verbatim-relay on` and `/verbatim-relay off` do the same as `start` and `end`. The prompts `verbatim-relay start` and `verbatim-relay status` also work.

The model reads the exact conversation of the latest test with the read-only `transcript` tool. The tool runs `verbatim-relay transcript`, so the model gets the same text as with the hook kit. It did not see the conversation while you talked, so it judges the record, not its memory. During a test, it cannot send a message to the agent, and it cannot change the files in `.verbatim-relay/`: the plugin denies these tool calls, except file reads. It also denies a model command that runs the entry, for example `python entry.py`. A command that only reads the entry, for example `cat entry.py`, can run.

`verbatim-relay trace` builds the trace of the latest test again and shows its findings.

If the entry returns an error, crashes or does not answer in 240 seconds, the plugin shows the error and records it. The message never goes to the model. After a crash, each later message gets the same error, with the last lines of `app.log`. End the test and start a new one.

If the test process stops, the plugin cannot reach the tap. It then asks `verbatim-relay status`. If no test runs, the plugin shows "relay mode is on, but no test runs" and tells you to type `/verbatim-relay start`. The message never goes to the model.

Each test is a new conversation, with a new test id and a new entry process. The test folder is `.verbatim-relay/tests/<test-id>/`:

| File | Content |
|---|---|
| `relay.jsonl` | What you typed and saw. |
| `tap.jsonl` | What the entry received and sent, and the model sessions that the tap found. |
| `app.log` | The stderr of the entry and your app. |
| `manifest.json` | The test id, the times, the harness versions and the SHA-256 of each configuration file. |
| `sessions/` | A copy of each session file of your app's model sessions. |
| `trace.jsonl` | Each message, tool call and command of those sessions, with its result, its turn and its line in the session file. |
| `audit.json` | The audit of the two records, as `verbatim-relay audit --json` prints it. |
| `report.md` | The model's evaluation, if it ran. |
| `seal.json` | The SHA-256 of each other file at the end of the test. `verbatim-relay verify` shows if a file changed after the end ([SPEC.md section 7.4](../SPEC.md#74-seal)). |
| `denied.jsonl` | The model tool calls that the relay denied after the end. |
| `backend.jsonl` | The calls of your app to its backends (see [Backends](#backends)). |
| `model_api.jsonl` | The direct calls of your app to a model API (see [Direct model calls](#direct-model-calls)). |
| `otel.jsonl` | The OpenTelemetry spans and logs of your app, if it sent any (see [OpenTelemetry](#opentelemetry)). |
| `findings.json` | The checks of the trace: failed tools and commands, agent errors, turns with no model item, and more ([SPEC.md section 8](../SPEC.md#8-trace)). |

Options. Set them with `/plugin configure verbatim-relay@verbatim-relay` in Claude Code, or with `--config KEY=VALUE` at install. The defaults fit the quick start.

| Option | Default | Meaning |
|---|---|---|
| `cli` | `verbatim-relay` | The command that starts and ends a test. Give a full path if it is not on `PATH`. |
| `start_on` | `false` | Without an entry: start each session in relay mode. With an entry, relay mode is on while a test runs, also after a restart of Claude Code. |
| `tap_url`, `agent_url`, `adapter`, `message_field`, `reply_field`, `openai_model`, `record` | | For an agent that runs as an HTTP server (see below). |

## Evaluation

The evaluation prompt ([evaluate.md](../src/verbatim_relay/evaluate.md)) tells the model to:

1. read the transcript with the trace: `verbatim-relay transcript --trace`, or the `transcript` tool with `trace: true`;
2. read `findings.json` and `audit.json`;
3. read your app's code and its business rules;
4. check your app's state with read-only commands;
5. write `report.md`: one row for each issue, with its class, its turn and its evidence.

The model did not see the conversation while you talked, so it judges the record, not its memory. After a test, the relay denies model writes to the test folder, except `report.md`. A shell command that names `.verbatim-relay` can only read, or write `report.md` ([SPEC.md section 5](../SPEC.md#5-relays) lists the read programs). To stop the evaluation, add `"evaluate": false` to `.verbatim-relay/config.json`. [docs/evaluation-example.md](evaluation-example.md) shows a test and its report.

## Hook kit

1. In your project, install the kit with the entry:

   ```bash
   verbatim-relay init claude-code --entry "python examples/toy-shop/agent.py"
   ```

   It writes `.verbatim-relay/config.json` and adds two hooks to `.claude/settings.local.json`. It keeps your other hooks. Add `--models claude-code,codex` if your app runs its own model sessions.

2. In a second terminal, start the viewer:

   ```bash
   verbatim-relay view
   ```

   It shows each turn of the latest test, and it follows to the next test.

3. Start Claude Code in the project and type the prompt `verbatim-relay start`. The kit starts the test and does not send this prompt to the model.
4. Type your test messages. Claude Code shows "relayed to the agent". The reply shows in the viewer.
5. Type the prompt `verbatim-relay end`. The kit ends the test, and the model evaluates it and writes `report.md` (see [Evaluation](#evaluation)). The prompt `verbatim-relay status` shows the running test.

`verbatim-relay transcript` prints the exact turns of the latest test. You can also start and end a test from a shell: `verbatim-relay start` and `verbatim-relay end`.

In relay mode, the kit fails closed: if it cannot send a message, the message still does not go to the model.

## An agent that runs as an HTTP server

If your agent is already an HTTP server, put the tap in front of it and do not configure an entry:

```bash
verbatim-relay tap --agent http://127.0.0.1:8700/ --record tap.jsonl
```

To try it, start `python examples/toy-shop/http_agent.py`. Then use `/verbatim-relay on` and `/verbatim-relay off` (plugin) or `verbatim-relay mode on` and `verbatim-relay mode off` (kit). These options apply:

| Option | Default | Meaning |
|---|---|---|
| `tap_url` | `http://127.0.0.1:8800/` | The URL that receives each message. For the `openai` adapter, give the full `/v1/chat/completions` URL. |
| `agent_url` | empty | Your agent's own URL. Model calls to it are denied too. |
| `adapter` | `json` | `json` or `openai` |
| `message_field` | `text` | `json` adapter: the dot path of the message in the request body |
| `reply_field` | `reply` | `json` adapter: the dot path of the reply in the response body |
| `openai_model` | empty | `openai` adapter: the `model` field of each request |
| `record` | `.verbatim-relay/relay.jsonl` | The relay record, relative to the working directory |

The kit takes the same options as flags: `--tap-url`, `--agent-url`, `--adapter` and so on.

If your agent streams its reply (SSE, `text/event-stream`), use the `openai` adapter. The relay sends `"stream": false`. If the agent streams also with this flag, the tap sends each part to the relay when it comes, and records the complete reply when the stream ends. The relay shows the reply when the stream is complete. A stream that ends early, sends an error or has a malformed chunk gives an error, not a part of the reply. [SPEC.md section 4.1](../SPEC.md#41-http-mode) defines the rules.

## Audit

```bash
verbatim-relay audit --tap .verbatim-relay/tests/<test-id>/tap.jsonl --relay .verbatim-relay/tests/<test-id>/relay.jsonl
```

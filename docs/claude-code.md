# Claude Code

Two relays work in Claude Code. Use one of them, not both. With both, each message goes to the agent two times.

| Relay | Reply shows in | Status |
|---|---|---|
| Plugin (recommended) | the chat, as a dim row that the model does not receive | function hooks, early access |
| Hook kit (fallback) | `verbatim-relay view`, in a second terminal | classic hooks, stable |

Tested with Claude Code 2.1.288.

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

## Plugin

1. Add the marketplace and install the plugin:

   ```bash
   claude plugin marketplace add mohanraj00/verbatim-relay
   claude plugin install verbatim-relay@verbatim-relay
   ```

2. Connect a test to your app (see above).
3. Type `/verbatim-relay start`. The plugin starts the entry through the tap, and relay mode goes on. The status line shows it.
4. Type your test messages. Each reply shows as a row in the chat and in the verbatim-relay pane.
5. Type `/verbatim-relay end`. The plugin stops the entry, copies the app's session files into the test folder, and switches relay mode off. `/verbatim-relay on` and `/verbatim-relay off` do the same as `start` and `end`.
6. Ask the model to evaluate the agent, for example: "Read the verbatim-relay transcript. Evaluate the agent's business logic, tone, language and accuracy. Quote the turns that you judge."

The model reads the exact conversation of the latest test with the read-only `transcript` tool. It did not see the conversation while you talked, so it judges the record, not its memory. During a test, it cannot send a message to the agent, and it cannot change the files in `.verbatim-relay/`: the plugin denies these tool calls, except file reads.

`verbatim-relay trace` builds the trace of the latest test again and shows its findings.

If the entry returns an error, crashes or does not answer in 240 seconds, the plugin shows the error and records it. The message never goes to the model. After a crash, each later message gets the same error, with the last lines of `app.log`. End the test and start a new one.

Each test is a new conversation, with a new test id and a new entry process. The test folder is `.verbatim-relay/tests/<test-id>/`:

| File | Content |
|---|---|
| `relay.jsonl` | What you typed and saw. |
| `tap.jsonl` | What the entry received and sent, and the model sessions that the tap found. |
| `app.log` | The stderr of the entry and your app. |
| `manifest.json` | The test id, the times, the harness versions and the SHA-256 of each configuration file. |
| `sessions/` | A copy of each session file of your app's model sessions. |
| `trace.jsonl` | Each message, tool call and command of those sessions, with its result, its turn and its line in the session file. |
| `findings.json` | The checks of the trace: failed tools and commands, agent errors, turns with no model item, and more ([SPEC.md section 8](../SPEC.md#8-trace)). |

Options. Set them with `/plugin configure verbatim-relay@verbatim-relay` in Claude Code, or with `--config KEY=VALUE` at install. The defaults fit the quick start.

| Option | Default | Meaning |
|---|---|---|
| `cli` | `verbatim-relay` | The command that starts and ends a test. Give a full path if it is not on `PATH`. |
| `start_on` | `false` | Without an entry: start each session in relay mode. With an entry, relay mode is on while a test runs, also after a restart of Claude Code. |
| `tap_url`, `agent_url`, `adapter`, `message_field`, `reply_field`, `openai_model`, `record` | | For an agent that runs as an HTTP server (see below). |

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
5. Type the prompt `verbatim-relay end`. The prompt `verbatim-relay status` shows the running test.
6. Ask Claude Code to evaluate the agent, for example: "Run `verbatim-relay transcript` and evaluate the agent's business logic, tone, language and accuracy. Quote the turns that you judge."

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

## Audit

```bash
verbatim-relay audit --tap .verbatim-relay/tests/<test-id>/tap.jsonl --relay .verbatim-relay/tests/<test-id>/relay.jsonl
```

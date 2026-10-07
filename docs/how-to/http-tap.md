# Use the HTTP tap

Use this mode if your agent is already an HTTP server and you do not want an entry. The tap is in front of the agent and records each exchange. There is no test: no test folder, no trace, no seal and no evaluation prompt. For these, use an entry ([connect-your-agent.md](connect-your-agent.md)).

## 1. Start the agent and the tap

To try it, start the toy shop agent of this repo as an HTTP server:

```bash
python3 examples/toy-shop/http_agent.py
```

In a second terminal, put the tap in front of it:

```bash
verbatim-relay tap --agent http://127.0.0.1:8700/ --record tap.jsonl
```

The tap prints:

```text
verbatim-relay tap: listening on http://127.0.0.1:8800/ -> http://127.0.0.1:8700/
verbatim-relay tap: writing tap.jsonl
```

To check the tap without a harness, send one message:

```bash
curl -s -X POST http://127.0.0.1:8800/ -H 'Content-Type: application/json' -d '{"text": "do you ship to delhi?"}'
```

The answer is the agent's answer with no change: `{"reply": "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  "}`. This message is in the tap record but not in a relay record, so an audit of these records shows it as `injected_input`. Use a new record file for the test.

## 2. Install a relay with no entry

- **Plugin:** do not write an `entry` in `.verbatim-relay/config.json`. The plugin options `tap_url`, `adapter` and the others apply ([reference/config.md](../reference/config.md#plugin-options)).
- **Hook kit:** run `verbatim-relay init claude-code` or `verbatim-relay init codex` with no `--entry`. The kit takes the same options as flags: `--tap-url`, `--agent-url`, `--adapter` and so on.

## 3. Relay mode on and off

With no entry, relay mode has no test. Switch it on before your messages and off after them:

| Relay | On | Off |
|---|---|---|
| Plugin | `/verbatim-relay on` | `/verbatim-relay off` |
| Hook kit | `verbatim-relay mode on` | `verbatim-relay mode off` |

The relay record is `.verbatim-relay/relay.jsonl` by default (the option `record`). After the test, audit the two records:

```bash
verbatim-relay audit --tap tap.jsonl --relay .verbatim-relay/relay.jsonl
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `tap_url` | `http://127.0.0.1:8800/` | The URL that receives each message. For the `openai` adapter, give the full `/v1/chat/completions` URL. |
| `agent_url` | empty | Your agent's own URL. Model calls to it are denied too. |
| `adapter` | `json` | `json` or `openai` |
| `message_field` | `text` | `json` adapter: the dot path of the message in the request body |
| `reply_field` | `reply` | `json` adapter: the dot path of the reply in the response body |
| `openai_model` | empty | `openai` adapter: the `model` field of each request |
| `openai_stream` | `false` | `openai` adapter: `true` sends `"stream": true` in each request, for an agent that streams only on request |
| `record` | `.verbatim-relay/relay.jsonl` | The relay record, relative to the working directory |

Give the tap the same adapter: `verbatim-relay tap --agent URL --record FILE --adapter openai`. [reference/cli.md](../reference/cli.md#verbatim-relay-tap) lists each flag of the tap.

## Adapters

- **`json`:** the message is at a field path in the request body, and the reply is at a field path in the response body. A path uses dots, and a list index is a number, for example `choices.0.message.content`.
- **`openai`:** an OpenAI-compatible `/chat/completions` endpoint. The message is the last `user` message, and the relay sends the earlier turns of the session as history.

[SPEC.md section 4.1](../../SPEC.md#adapters) defines both.

## Streamed replies

If your agent streams its reply (SSE, `text/event-stream`), use the `openai` adapter. The relay sends `"stream": false`. If your agent streams only on request, set `openai_stream` to `true` (the hook kit flag is `--openai-stream`, with no value). Then the relay sends `"stream": true`. If the agent streams, the tap sends each part to the relay when it comes. It records the complete reply when the stream ends. The relay shows the reply when the stream is complete. A stream that ends early, sends an error or has a malformed chunk gives an error, not a part of the reply. [SPEC.md section 4.1](../../SPEC.md#41-http-mode) defines the rules.

## Security

The tap listens on `127.0.0.1:8800` by default. If you bind it to another address with `--listen`, anyone who can reach that address can talk to your agent through it ([SECURITY.md](../../SECURITY.md)).

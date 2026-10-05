# Claude Code

Two relays work in Claude Code. Use one of them, not both. With both, each message goes to the agent two times.

| Relay | Reply shows in | Status |
|---|---|---|
| Plugin (recommended) | the chat, as a dim row that the model does not receive | function hooks, early access |
| Hook kit (fallback) | `verbatim-relay view`, in a second terminal | classic hooks, stable |

Tested with Claude Code 2.1.288.

## Plugin

1. Add the marketplace and install the plugin:

   ```bash
   claude plugin marketplace add mohanraj00/verbatim-relay
   claude plugin install verbatim-relay@verbatim-relay
   ```

2. Start the tap in front of your agent (see the [README](../README.md#quick-start)).
3. Open `/config` and set the verbatim-relay options. The defaults fit the quick start.

   | Option | Default | Meaning |
   |---|---|---|
   | `tap_url` | `http://127.0.0.1:8800/` | The URL that receives each message. For the `openai` adapter, give the full `/v1/chat/completions` URL. |
   | `agent_url` | empty | Your agent's own URL. Model calls to it are denied too. |
   | `adapter` | `json` | `json` or `openai` |
   | `message_field` | `text` | `json` adapter: the dot path of the message in the request body |
   | `reply_field` | `reply` | `json` adapter: the dot path of the reply in the response body |
   | `openai_model` | empty | `openai` adapter: the `model` field of each request |
   | `record` | `.verbatim-relay/relay.jsonl` | The relay record, relative to the working directory |
   | `start_on` | `false` | Start each session in relay mode |

4. Type `/verbatim-relay on`. The status line shows that relay mode is on.
5. Type your test messages. Each reply shows as a row in the chat and in the verbatim-relay pane.
6. Type `/verbatim-relay off` to talk to the model again.
7. Ask the model to evaluate the agent, for example: "Read the verbatim-relay transcript. Evaluate the agent's business logic, tone, language and accuracy. Quote the turns that you judge."

The model reads the exact conversation of this session with the read-only `transcript` tool. It did not see the conversation while you talked, so it judges the record, not its memory. It cannot send a message to the agent: the plugin denies any model tool call that names the tap or the agent, except file tools.

If the agent returns an error, or the tap is not running, the plugin shows the error and records it. The message never goes to the model.

## Hook kit

1. In your project, install the kit:

   ```bash
   verbatim-relay init claude-code
   ```

   It writes `.verbatim-relay/config.json` and adds two hooks to `.claude/settings.local.json`. It keeps your other hooks. Options are the same as in the plugin table, as flags: `--tap-url`, `--agent-url`, `--adapter` and so on.

2. Start the tap in front of your agent.
3. In a second terminal, start the viewer:

   ```bash
   verbatim-relay view
   ```

4. Switch relay mode on:

   ```bash
   verbatim-relay mode on
   ```

5. Start Claude Code in the project and type your test messages. Claude Code shows "relayed to the agent". The reply shows in the viewer.
6. Switch relay mode off with `verbatim-relay mode off`.
7. Ask Claude Code to evaluate the agent, for example: "Run `verbatim-relay transcript` and evaluate the agent's business logic, tone, language and accuracy. Quote the turns that you judge."

`verbatim-relay transcript` prints the exact turns of the latest session. Add `--all` for every session in the record.

In relay mode, the kit fails closed: if it cannot send a message, the message still does not go to the model.

## Audit

```bash
verbatim-relay audit --tap tap.jsonl --relay .verbatim-relay/relay.jsonl
```

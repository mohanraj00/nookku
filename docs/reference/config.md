# Configuration reference

Nookku reads its configuration from the file `.nookku/config.json` in your project. The plugin has no options. The test `tests/test_docs.py` checks each key and each default on this page against `Config` in [src/nookku/config.py](../../src/nookku/config.py).

## `.nookku/config.json`

The hooks of the plugin and the project hooks read all keys of this file, and the commands of a test read the test keys. One reader applies one rule for `start`, `check`, `init` and the hook kit ([SPEC.md section 7.1](../../SPEC.md#71-configuration)). An unknown key gives the same error in each of them:

```text
.nookku/config.json has unknown keys: ['<key>']. Correct or remove them.
```

`start` and `check` stop, `init` writes nothing, and in relay mode the hook kit blocks each prompt.

`nookku init` writes a new file with each key. In an existing file, it keeps each key and changes only the keys of the flags that you give ([cli.md](cli.md#nookku-init)).

### Test keys

These keys configure a test ([SPEC.md section 7.1](../../SPEC.md#71-configuration)).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `entry` | list of strings | `[]` | The entry command, as an argument vector. It runs in the project root. A test needs it. |
| `models` | list of strings | `[]` | The harnesses that the app uses for its own model sessions: `claude-code`, `codex`, both or none. `nookku check` fails if it does not find a session for each one. |
| `evaluate` | boolean | `true` | `false` stops the evaluation at the end of a test ([SPEC.md section 9](../../SPEC.md#9-evaluation)). |
| `otel` | boolean | `true` | `false` stops the OTLP receiver of a test ([SPEC.md section 7.5](../../SPEC.md#75-otlp-receiver)). |
| `backends` | list of objects | `[]` | The backends of the app, each with the strings `name`, `env` and `url`. Each `name` and each `env` occurs only once ([how-to/add-a-backend.md](../how-to/add-a-backend.md)). |
| `model_api` | boolean, list or object | `true` | The model APIs to record: `true` for all, `false` for none, a list of `anthropic` and `openai`, or an object from these names to the upstream URL or `null` ([how-to/record-model-calls.md](../how-to/record-model-calls.md)). |

### Relay keys

These keys configure the hook kit when there is no entry, for an agent that is an HTTP server ([how-to/http-tap.md](../how-to/http-tap.md)). With an entry, the test gives the tap URL, and the kit does not use `tap_url`, the adapter keys or `record`. It still denies model calls to `tap_url` and `agent_url`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `tap_url` | string | `http://127.0.0.1:8800/` | The URL that receives each message. For the `openai` adapter, give the full `/v1/chat/completions` URL. |
| `agent_url` | string | empty | The agent's own URL. Model calls to it are denied too. |
| `adapter` | string | `json` | `json` or `openai` ([SPEC.md section 4.1](../../SPEC.md#adapters)). |
| `message_field` | string | `text` | `json` adapter: the dot path of the message in the request body. |
| `reply_field` | string | `reply` | `json` adapter: the dot path of the reply in the response body. |
| `openai_model` | string | empty | `openai` adapter: the `model` field of each request. Empty means no `model` field. |
| `openai_stream` | boolean | `false` | `openai` adapter: `true` sends `"stream": true` in each request, for an agent that streams only on request. |
| `record` | string | `.nookku/relay.jsonl` | The relay record, relative to the project. With an entry, each test has its own `relay.jsonl`. |

### Examples

The toy shop with the hook kit:

```json
{"entry": ["python3", "agent.py"], "models": []}
```

The full toy shop, with a stock service and a note model on local ports:

```json
{
  "entry": ["uv", "run", "--with", "claude-agent-sdk", "python3", "examples/toy-shop-full/entry.py"],
  "models": ["claude-code"],
  "backends": [{"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9001"}],
  "model_api": {"anthropic": null, "openai": "http://127.0.0.1:9002/v1"}
}
```

## Plugin options

The plugin has no options. Write `.nookku/config.json` with `nookku init plugin`, and change a key with the flags of `nookku init` ([cli.md](cli.md#nookku-init)). Before 0.4.0, the Claude Code plugin had its own options ([#216](https://github.com/mohanraj00/nookku/issues/216)).

## Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | the bridge | The Claude Code folder with the session files. The default is `~/.claude` ([SPEC.md section 7.3](../../SPEC.md#73-model-sessions)). |
| `CODEX_HOME` | the bridge | The Codex folder with the rollout files. The default is `~/.codex`. |
| `NOOKKU_CODEX` | `start`, `mode on`, the bridge | The `codex` command of the Codex hook gate. The default is `codex`. If the command is not on `PATH`, the gate does not run ([SPEC.md section 7.8](../../SPEC.md#78-codex-hook-gate)). |
| `NOOKKU_HOME` | the bridge, `verify` | The folder of the copies of the seals. The default is `~/.nookku` ([SPEC.md section 7.4](../../SPEC.md#74-seal)). |
| `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` | the bridge | The upstream URL of each model API proxy, if `model_api` gives none ([SPEC.md section 7.7](../../SPEC.md#77-model-api-proxies)). |

During a test, the bridge also sets variables for the entry ([SPEC.md section 7](../../SPEC.md#7-tests)). These are the `OTEL_*` variables, `CLAUDE_CODE_ENABLE_TELEMETRY=1`, the `env` of each backend, and the two base URLs above ([otlp.py](../../src/nookku/otlp.py), [SPEC.md section 7.5](../../SPEC.md#75-otlp-receiver)).

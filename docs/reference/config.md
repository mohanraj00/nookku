# Configuration reference

Nookku reads its configuration from the file `.nookku/config.json` in your project. The [plugin](glossary.md#plugin) has no options. The test `tests/test_docs.py` checks each key and each default on this page against `Config` in [src/nookku/config.py](../../src/nookku/config.py).

## `.nookku/config.json`

The hooks of the plugin and the [project hooks](glossary.md#project-hooks) read all keys of this file, and the commands of a test read the test keys. One reader applies one rule for `start`, `check`, `init` and the [relay](glossary.md#relay) ([SPEC.md section 7.1](../../SPEC.md#71-configuration)). An unknown key gives the same error in each of them:

```text
.nookku/config.json has unknown keys: ['<key>']. Correct or remove them.
```

The reader also checks the type of each value, as the tables below give it. A value with a wrong type gives one error for each key, in each command. For example:

```text
.nookku/config.json: 'models' must be a list of claude-code, codex
```

`start` and `check` stop, `mode on` keeps [relay mode](glossary.md#relay-mode) off, `init` writes nothing, and in relay mode the relay blocks each prompt.

If the file does not exist, each command has its own result ([SPEC.md section 7.1](../../SPEC.md#71-configuration)):

- `start` and `check` stop with the error `cannot read .nookku/config.json` and exit with 1.
- `mode on` keeps relay mode off and tells you to write the file with `nookku init plugin`.
- `view` and `transcript` use the default value of each key. Thus `view` reads the record `.nookku/relay.jsonl`.
- The guard has no `tap_url` and no `agent_url` to deny, also not the default `tap_url`. During a test, it still denies a call to the [tap](glossary.md#tap) of the test.

`nookku init` writes a new file with each key. In an existing file, it keeps each key and changes only the keys of the flags that you give ([cli.md](cli.md#nookku-init)).

### Test keys

These keys configure a test ([SPEC.md section 7.1](../../SPEC.md#71-configuration)).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `entry` | list of strings | `[]` | The [entry](glossary.md#entry) command, as an argument vector. It runs in the project root. A test needs it. |
| `models` | list of strings | `[]` | The [harnesses](glossary.md#harness) that the app uses for its own model sessions: `claude-code`, `codex`, both or none. `nookku check` fails if it does not find a session for each one. |
| `evaluate` | boolean | `true` | `false` stops the [evaluation](glossary.md#evaluation) at the end of a test ([SPEC.md section 9](../../SPEC.md#9-evaluation)). |
| `otel` | boolean | `true` | `false` stops the OTLP receiver of a test ([SPEC.md section 7.5](../../SPEC.md#75-otlp-receiver)). |
| `backends` | list of objects | `[]` | The backends of the app, each with the strings `name`, `env` and `url`. Each `name` and each `env` occurs only once ([how-to/add-a-backend.md](../how-to/add-a-backend.md)). |
| `model_api` | boolean, list or object | `true` | The model APIs to record: `true` for all, `false` for none, a list of `anthropic` and `openai`, or an object from these names to the upstream URL or `null` ([how-to/record-model-calls.md](../how-to/record-model-calls.md)). |
| `entries` | object | `{}` | More entries for a [scripted test](glossary.md#scripted-test), by name, for example `{"replay": ["python3", "replay_entry.py"]}`. `nookku run --entry replay` uses one. `entry` stays the default entry ([how-to/test-your-app.md](../how-to/test-your-app.md#run-a-scripted-test)). |
| `check_message` | string | `Hello from nookku check. What can you help me with?` | The one message that `nookku check` sends. It must have a character that is not white space, and no lone surrogate. Set it to a message that your app answers normally, for example a question about a product of the shop. |
| `repeated_reply` | integer | `2` | The count of consecutive turns with the same reply that gives a `repeated_reply` [finding](glossary.md#findings) of the [trace](glossary.md#trace) ([SPEC.md section 8.6](../../SPEC.md#86-findings)). `0` turns the check off. A value of 1 or less than 0 is an error. The manifest of each test records the value. |
| `model_reply_field` | string | empty | The dot path of the client text in a structured model output, for example `reply` or `output.client_text`. The `reply_not_from_model` check of the trace then compares the reply with the value at this path, not with the full model text ([SPEC.md section 8.6](../../SPEC.md#86-findings)). Empty compares the full text. A path with an empty part, for example `output..text`, is an error. The manifest of each test records the value. |
| `model_reply_match` | string | `normalized` | How the `reply_not_from_model` check compares: `exact` (the reply contains the model text, byte for byte), `normalized` (the same after white space and case are normalized) or `off` (no check). The manifest of each test records the value. |
| `transcript_compact` | boolean | `false` | `true` makes `nookku transcript --trace` show a repeated prompt one time. `--compact` and `--no-compact` override it ([cli.md](cli.md#nookku-transcript)). |

### Relay keys

These keys configure the relay when there is no entry, for an agent that is an HTTP server ([how-to/http-tap.md](../how-to/http-tap.md)). With an entry, the test gives the [tap](glossary.md#tap) URL, and the kit does not use `tap_url`, the adapter keys or `record`. It still denies model calls to `tap_url` and `agent_url`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `tap_url` | string | `http://127.0.0.1:8800/` | The URL that receives each message. For the `openai` adapter, give the full `/v1/chat/completions` URL. |
| `agent_url` | string | empty | The agent's own URL. Model calls to it are denied too. |
| `adapter` | string | `json` | `json` or `openai` ([SPEC.md section 4.1](../../SPEC.md#adapters)). |
| `message_field` | string | `text` | `json` adapter: the dot path of the message in the request body. |
| `reply_field` | string | `reply` | `json` adapter: the dot path of the reply in the response body. |
| `openai_model` | string | empty | `openai` adapter: the `model` field of each request. Empty means no `model` field. |
| `openai_stream` | boolean | `false` | `openai` adapter: `true` sends `"stream": true` in each request, for an agent that streams only on request. |
| `record` | string | `.nookku/relay.jsonl` | The [relay record](glossary.md#relay-record), relative to the project. With an entry, each test has its own `relay.jsonl`. |

### Examples

The toy shop with the project hooks:

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

## `.nookku/policy.json`

The [policy file](glossary.md#policy-file) holds the keys that control the guard. The model can change `config.json` for normal app work, so these keys are in a separate file that the model never writes ([SPEC.md section 7.9](../../SPEC.md#79-policy-file)).

- Only a person changes the file, with `nookku policy set KEY VALUE` in a shell ([cli.md](cli.md#nookku-policy)). `nookku policy` prints each key with its value.
- The relay denies each model tool call that can write the file, also when no test runs. The deny reason names the file.
- If the file does not exist, each key has its default. Each default is the strict value.
- The manifest of each test records the SHA-256 of the file and the value of each key.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `guard_fields` | list of strings | `path`, `file_path`, `url`, `uri`, `command` | The fields of a tool input that the guard reads, for a tool that is not a shell or a file tool, for example an MCP tool. The other fields are free text. Set it with `nookku policy set guard_fields path,url,command`. |
| `guard_reads` | list of strings | empty | More programs that the read check of the guard accepts, for example `od,hexdump`. The guard does not check the arguments of these programs. A program of the built-in list, for example `sed`, keeps its own check. The deny of `policy.json` does not use this key. Set it with `nookku policy set guard_reads od,hexdump`. Clear it with `nookku policy set guard_reads ""`. |
| `scripts` | `person` or `model` | `person` | Who runs `nookku run --script`. With `model`, the model can run a scripted test. With `person`, the guard denies `nookku run` from the model. Set it with `nookku policy set scripts model`. |
| `control_distance` | whole number, 0 or more | `2` | In relay mode, the relay refuses a message near a [control prompt](glossary.md#control-prompt), for example `nookku stop` or `nookk end`. The value is the largest edit distance to a control prompt that gets the refusal. A message with the first word `nookku` gets it at each value above 0. The value 0 turns off the rule. Set it with `nookku policy set control_distance 1`. |

Add a program to `guard_reads` only if it cannot write a file or start a program with any argument. For example, `fd --exec` and `bat --pager` start a program, and `xxd` writes its second file argument. The model can use each argument of a program in the list. `nookku policy set guard_reads` prints this warning.

Each guard rule that a person can change adds its key here.

## Plugin options

The plugin has no options, so no plugin option can change a policy key. Write `.nookku/config.json` with `nookku init plugin`, and change a key with the flags of `nookku init` ([cli.md](cli.md#nookku-init)). Before 0.4.0, the Claude Code plugin had its own options ([#216](https://github.com/mohanraj00/nookku/issues/216)).

## Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | the [bridge](glossary.md#bridge) | The Claude Code folder with the session files. The default is `~/.claude` ([SPEC.md section 7.3](../../SPEC.md#73-model-sessions)). |
| `CODEX_HOME` | the bridge | The Codex folder with the rollout files. The default is `~/.codex`. |
| `NOOKKU_CODEX` | `start`, `mode on`, the bridge | The `codex` command of the Codex hook gate. The default is `codex`. If the command is not on `PATH`, the gate does not run ([SPEC.md section 7.8](../../SPEC.md#78-codex-hook-gate)). |
| `NOOKKU_HOME` | the bridge, `verify` | The folder of the copies of the [seals](glossary.md#seal). The default is `~/.nookku` ([SPEC.md section 7.4](../../SPEC.md#74-seal)). |
| `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` | the bridge | The upstream URL of each model API proxy, if `model_api` gives none ([SPEC.md section 7.7](../../SPEC.md#77-model-api-proxies)). |

During a test, the bridge also sets variables for the entry. `NOOKKU_TEST_DIR` is the absolute path of the [test folder](glossary.md#test-folder), and `NOOKKU_TEST_ID` is the test id. The app can keep its state in `$NOOKKU_TEST_DIR/app-state/`, so that the seal covers it ([SPEC.md section 6.1](../../SPEC.md#61-environment-of-the-entry)). The other variables are the `OTEL_*` variables, `CLAUDE_CODE_ENABLE_TELEMETRY=1`, the `env` of each backend, and the two base URLs above ([otlp.py](../../src/nookku/otlp.py), [SPEC.md section 7.5](../../SPEC.md#75-otlp-receiver)).

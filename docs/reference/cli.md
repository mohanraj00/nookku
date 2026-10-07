# CLI reference

This page lists each command of `verbatim-relay`, each flag and each exit code. The parser is in [src/verbatim_relay/cli.py](../../src/verbatim_relay/cli.py). The test `tests/test_docs.py` checks that each command and each flag of the parser is on this page. It also checks that each flag on this page is in the parser.

```text
verbatim-relay [-h] [--version] COMMAND ...
```

| Flag | Meaning |
|---|---|
| `--version` | Print the version and exit with 0. |
| `-h`, `--help` | Print the help of the program or of a command, and exit with 0. |

Each command that takes `--root` uses the current folder by default. The root is the project: the folder that holds `.verbatim-relay/`.

An unknown command or flag prints the usage and exits with 2. With no command, `verbatim-relay` prints the help and exits with 2.

## Commands of a test

### `verbatim-relay start`

Start a test: run the entry through the tap and switch relay mode on ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)). It needs an `entry` in `.verbatim-relay/config.json`.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `current.json` of the test as JSON, or `{"error": ...}`. |
| `--tester-session ID` | none | The tester's harness session id. The bridge never takes this session as a session of the app. |

| Exit code | Meaning |
|---|---|
| 0 | The test started. |
| 1 | The test did not start: no entry, an invalid configuration, a test that runs already, or an entry that exited. The text names the cause. |

### `verbatim-relay end`

End the test: switch relay mode off, stop the entry and collect its sessions, the trace, the audit and the seal ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)). If no test runs, it switches relay mode off.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print the manifest of the test as JSON, or `null` if no test ran. |
| `--evaluation` | off | Print one JSON object: `text`, the end text, and `evaluation`, the evaluation prompt or `null` ([SPEC.md section 9.1](../../SPEC.md#91-start)). The plugin uses it. |

| Exit code | Meaning |
|---|---|
| 0 | Always. |

### `verbatim-relay status`

Show relay mode and the running test.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `{"on": ..., "test": ...}`. |

| Exit code | Meaning |
|---|---|
| 0 | Always. |

### `verbatim-relay check`

Run a short test with one message, and check the entry and its model sessions ([SPEC.md section 7.1](../../SPEC.md#71-configuration)).

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `{"pass": ..., "report": [...]}`. |

| Exit code | Meaning |
|---|---|
| 0 | The entry sent a reply, and the test found a model session for each harness in `models`. |
| 1 | The check failed, or the test did not start. |

### `verbatim-relay mode`

```text
verbatim-relay mode STATE [--root PATH]
```

Switch relay mode on or off. With an entry, `on` starts a test and `off` ends it. With no entry, it only switches relay mode ([how-to/http-tap.md](../how-to/http-tap.md)).

| Argument or flag | Default | Meaning |
|---|---|---|
| `STATE` | | `on`, `off` or `status`. |
| `--root PATH` | the current folder | The project. |

| Exit code | Meaning |
|---|---|
| 0 | Always. If a test does not start, the text names the cause. |

## Commands that read a test

### `verbatim-relay view`

Print each relayed turn. This is the display of the hook kit. With an entry, it shows the turns of the latest test, and it follows to the next test.

If the relay record has an invalid line, `view` shows the error with the file and the line on stderr. Without `--no-follow`, it shows the error one time and continues to wait. When the record changes and is valid, it shows the next turns. With `--no-follow`, it stops with exit code 2. A test has no relay record before its first turn, so the view of such a test shows no turn and exits with 0. After the end of a test, `verbatim-relay verify` shows a record that is missing.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--no-follow` | off | Print the turns so far and stop. Without it, `view` waits for new turns until you stop it. |
| `--record FILE` | from the config | The relay record to show. |

| Exit code | Meaning |
|---|---|
| 0 | The view stopped. |
| 2 | The config cannot be read. With `--no-follow`: the relay record is invalid, or, with no entry, the configured record does not exist. |

### `verbatim-relay transcript`

Print the exact conversation for the model to evaluate ([SPEC.md section 5](../../SPEC.md#5-relays)). With an entry, the scope is the latest test.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--test ID` | the latest test | The test to print. |
| `--trace` | off | Print each turn as the app got it (from `tap.jsonl`), with the model items and the findings of that turn ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)). |
| `--all` | off | With no entry: each session of the record, not only the latest one. |
| `--session ID` | none | Only the turns of this harness session. |
| `--record FILE` | from the config | The relay record to print. |

| Exit code | Meaning |
|---|---|
| 0 | The transcript printed. |
| 2 | No test folder (with `--trace`), the config cannot be read, or the relay record is missing or invalid. |

### `verbatim-relay audit`

Compare the relay record with the tap record ([SPEC.md section 3](../../SPEC.md#3-audit)).

| Flag | Default | Meaning |
|---|---|---|
| `--tap FILE` | required | The tap record. |
| `--relay FILE` | required | The relay record. |
| `--json` | off | Print the report as JSON. The bridge writes this form to `audit.json`. |

| Exit code | Meaning |
|---|---|
| 0 | The records are valid and have no break. |
| 1 | The records are valid and have one or more breaks. |
| 2 | A record is missing or invalid, or the tap has an unparsed exchange. |

### `verbatim-relay trace`

```text
verbatim-relay trace [TEST] [--root PATH] [--json]
```

Build the trace of a test again, and show its findings ([SPEC.md section 8](../../SPEC.md#8-trace)). If the test has a seal, it rebuilds only from sources that agree with the seal.

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id. |
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `findings.json`. |

| Exit code | Meaning |
|---|---|
| 0 | The trace was built. |
| 2 | No test folder with a manifest, or the seal is broken and the trace was not rebuilt. |

### `verbatim-relay verify`

```text
verbatim-relay verify [TEST] [--root PATH] [--json]
```

Check that no record of a test changed after its end ([SPEC.md section 7.4](../../SPEC.md#74-seal)).

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id. |
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print the result as JSON. |

| Exit code | Meaning |
|---|---|
| 0 | The seal is intact. |
| 2 | The seal is broken, or there is no test folder. |

## Commands that install or connect

### `verbatim-relay init`

```text
verbatim-relay init HARNESS [--root PATH] [--entry COMMAND] [--models LIST] [options]
```

Install the hook kit for Codex or Claude Code. It writes `.verbatim-relay/config.json`, the file `.verbatim-relay/mode`, and the hooks: `.codex/hooks.json` for Codex, `.claude/settings.local.json` for Claude Code. It keeps your other hooks. It writes a new `config.json`, so a key that has no flag gets its default, for example `backends`.

| Argument or flag | Default | Meaning |
|---|---|---|
| `HARNESS` | | `codex` or `claude-code`. |
| `--root PATH` | the current folder | The project. |
| `--entry COMMAND` | none | The entry command of a test, as one string. The shell rules split it into arguments. |
| `--models LIST` | none | The app's model harnesses, separated by commas: `claude-code`, `codex` or both. |
| `--tap-url URL` | `http://127.0.0.1:8800/` | The config key `tap_url`. |
| `--agent-url URL` | empty | The config key `agent_url`. |
| `--adapter NAME` | `json` | The config key `adapter`. |
| `--message-field PATH` | `text` | The config key `message_field`. |
| `--reply-field PATH` | `reply` | The config key `reply_field`. |
| `--openai-model NAME` | empty | The config key `openai_model`. |
| `--openai-stream` | off | The config key `openai_stream`: set it to `true`. |
| `--record FILE` | `.verbatim-relay/relay.jsonl` | The config key `record`. |

[config.md](config.md#verbatim-relayconfigjson) explains each key.

| Exit code | Meaning |
|---|---|
| 0 | The files were written. |

### `verbatim-relay setup`

Print the guide that connects a test to the app ([setup.md](../../src/verbatim_relay/setup.md)). A harness model reads it and writes the entry ([how-to/connect-your-agent.md](../how-to/connect-your-agent.md)).

| Exit code | Meaning |
|---|---|
| 0 | Always. |

### `verbatim-relay tap`

```text
verbatim-relay tap (--agent URL | --cmd -- COMMAND...) --record FILE [options]
```

Run the tap proxy in front of the agent ([SPEC.md section 4](../../SPEC.md#4-tap)). A test starts it for you, so you need this command only for an agent that is an HTTP server ([how-to/http-tap.md](../how-to/http-tap.md)).

| Flag | Default | Meaning |
|---|---|---|
| `--agent URL` | none | HTTP mode: the agent's base URL. |
| `--cmd` | off | Stdio mode: start the command after `--` as the agent. |
| `--record FILE` | required | The tap record (JSONL). The tap adds rows to it. |
| `--listen HOST:PORT` | `127.0.0.1:8800` | The address of the tap. |
| `--timeout SECONDS` | [240](../../src/verbatim_relay/stdio.py) | The seconds to wait for the agent. |
| `--log PATH` | `app.log` next to the record | Stdio mode: the file for the agent's stderr. |
| `--adapter NAME` | `json` | `json` or `openai` ([SPEC.md section 4.1](../../SPEC.md#adapters)). |
| `--message-field PATH` | `text` | `json` adapter: the field path of the message in the request. |
| `--reply-field PATH` | `reply` | `json` adapter: the field path of the reply in the response. |

Give exactly one of `--agent` and `--cmd`.

| Exit code | Meaning |
|---|---|
| 0 | The tap stopped, for example after Ctrl-C. |
| 2 | The flags are wrong, for example both `--agent` and `--cmd`. |

## Internal commands

The relays and the bridge run these commands. You do not run them yourself.

### `verbatim-relay hook`

The hook command that `init` writes into the hook file. It reads one hook event as JSON on stdin and writes the answer on stdout ([SPEC.md section 5](../../SPEC.md#5-relays)).

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | required | The project. |
| `--harness NAME` | required | `codex` or `claude-code`. |

| Exit code | Meaning |
|---|---|
| 0 | Always. If the hook fails in relay mode, it still blocks the prompt. |

### `verbatim-relay bridge`

The background process of a test ([architecture.md](../architecture.md#the-bridge)). `start` runs it.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | required | The project. |
| `--test ID` | required | The test id. |
| `--tester-session ID` | none | The tester's harness session id. |

| Exit code | Meaning |
|---|---|
| 0 | The test ended. |
| 1 | The bridge could not start the entry, the entry exited at start, or the bridge could not read the start time of its process. |

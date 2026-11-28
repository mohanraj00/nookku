# `nookku run`

Release: nookku 0.6.1. Since 0.7.0 (not released yet): the config key `persona_runner`.

```text
nookku run (--script FILE | --persona FILE) [--entry NAME] [--root PATH] [--tests-dir PATH] [--json] [--verdict] [--evaluate | --no-evaluate]
```

Run a [scripted test](../glossary.md#scripted-test) ([SPEC.md section 7.10](../../../SPEC.md#710-scripted-tests)). It starts a test, sends each message of the script to the [entry](../glossary.md#entry) byte for byte, waits for each reply and ends the test. The script is JSONL with one `{"said": "..."}` row for each turn, or one JSON array of strings. A JSONL row can have the key `during`, a number of seconds: `run` then sends the message during the turn of the message before it ([a second message](../../how-to/test-your-app.md#send-a-second-message-during-a-turn)). The [test folder](../glossary.md#test-folder) gets a copy of the script, and each [relay](../glossary.md#relay) row has `"harness": "script"`. `run` does not switch [relay mode](../glossary.md#relay-mode) on.

With `--persona FILE`, a simulated user writes each message in place of a script ([SPEC.md section 7.10](../../../SPEC.md#710-scripted-tests), [#520](https://github.com/mohanraj00/nookku/issues/520)). The file is a JSON object with only `persona`, `goal` and `turns`, the turn limit from 1 to 50:

```json
{"persona": "A customer whose teapot came broken.", "goal": "Get a return label for the teapot.", "turns": 8}
```

The config key [`persona_runner`](../config.md) selects the runner of the simulated user ([#667](https://github.com/mohanraj00/nookku/issues/667)):

- `claude-code` (the default): for each turn, `run` starts `claude -p` in a new session, with no settings, no `CLAUDE.md`, no plugin, no hook, no MCP server and no tool.
- A list of strings: a command that you declare, for example `["python3", "/srv/toy-shop/toy_shop_user.py"]`. It gets the prompt on stdin and writes the message on stdout. The command starts in a new empty temporary folder, not in the project. Thus give an absolute path for each file of the command, because a relative path points into that empty folder. Nookku cannot check what the command loads, so you own its isolation.

A proof runs one test with each runner ([results.md](../../results.md#a-test-with-a-simulated-user)).

**Warning:** Give a declared command with no tools. The prompt holds each reply of the agent, and an agent under test can be hostile. A command that can read files or the network can send a secret to the agent in its next message. For this reason Nookku has no built-in `codex` runner: `codex exec` has no flag that removes each tool.

Each session gets only the persona, the goal and the turns so far. The relay row of each message has `"harness": "simulated-user"`. The run stops when the simulated user writes `GOAL MET`, at the turn limit, at a turn with no reply, or when the session fails. The test folder gets `persona.json`, a copy of the file, and `simulated_user.json` with the result and the runner. The messages are not deterministic, so a [gate run](gate.md) does not start a simulated user. To send the same messages again, save the test with [`nookku script save`](script.md) and run the script.

The output gives the test id, the count of turns, the [audit](../glossary.md#audit) and the [trace](../glossary.md#trace), and the verdict if the [app spec](../app-spec.md#verdict) gives limits, and then `PASS` or each `FAIL:` line. It does not give the replies. Read them with `nookku transcript`.

By default, only a person runs `nookku run`: the relay denies it from the model. A person allows the model with `nookku policy set scripts model`.

| Flag | Default | Meaning |
|---|---|---|
| `--script FILE` | `--script` or `--persona` | The script file. |
| `--persona FILE` | `--script` or `--persona` | The persona file of a simulated user. It needs the [harness](../glossary.md#harness) of the config key `persona_runner`, Claude Code by default. |
| `--entry NAME` | the key `entry` | A name in the config key `entries`. It does not take a command line. |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print `{"pass": ..., "report": [...], "evaluation": ...}`. |
| `--verdict` | off | Also fail the run if the verdict of the test is `fail`. Use it in CI. |
| `--no-evaluate`, `--evaluate` | the config key `evaluate` | Print the [evaluation](../glossary.md#evaluation) prompt at the end, or not. |

| Exit code | Meaning |
|---|---|
| 0 | The audit of the test is clean. With `--persona`, the run also sent a message and stopped at the goal or the turn limit. |
| 1 | The test did not start, for example a rule of the script or of the persona file is broken, or the entry name is unknown. With `--persona`, the session of the simulated user failed or sent no message. Or a turn has no reply, the audit is not clean, or the Codex hooks changed. With `--verdict`, also if the verdict is `fail` ([SPEC.md section 7.14](../../../SPEC.md#714-verdict)). |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`:

```bash
nookku run --script examples/toy-shop/script.jsonl --no-evaluate
```

```text
Test 20261127-194213-41bc: ~/shop/.nookku/tests/20261127-194213-41bc
Turns: 3 of 3 messages
Audit: exit 0
Trace: 0 model items in 3 turns, no findings.
PASS
```

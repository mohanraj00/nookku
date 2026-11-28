# `nookku start`

Release: nookku 0.6.1. Since 0.7.0 (not released yet): the sealed refusal record of a refused start.

Start a test: run the [entry](../glossary.md#entry) through the [tap](../glossary.md#tap) and switch [relay mode](../glossary.md#relay-mode) on ([SPEC.md section 7.2](../../../SPEC.md#72-start-and-end)). It needs an `entry` in `.nookku/config.json`. With no entry, `start` starts no test, exits with 1 and prints `nookku: .nookku/config.json has no 'entry' command, so the test cannot start. Write the command that starts your agent with: nookku init <relay> --entry "<command>". <relay> is plugin, claude-code or codex.` The prompt `nookku start`, `check` and `run` give the same text ([troubleshooting](../../troubleshooting.md#nookku-nookkuconfigjson-has-no-entry-command-so-the-test-cannot-start)). The start text gives the same ways to end the test as the [plugin](../glossary.md#plugin) and the [project hooks](../glossary.md#project-hooks): the prompt `nookku end`, which also starts the [evaluation](../glossary.md#evaluation), and `nookku end` in a shell. If `evaluate` is `false`, the text does not name the evaluation ([SPEC.md section 9.1](../../../SPEC.md#91-start)).

`start` also needs a fresh egress answer: the answer of [`nookku register`](register.md) from the last 30 minutes ([SPEC.md section 7.11](../../../SPEC.md#711-egress-discovery)). With no fresh answer, `start` starts no test, exits with 1 and prints `no test started: nookku has no egress answer from the last 30 minutes. Type the prompt nookku start in the harness, so that the model finds the egress of the agent. Or run nookku register with the answer (SPEC.md section 7.11).` The prompt `nookku start` with no fresh answer starts no test. It sends the discovery task to the [harness model](../glossary.md#harness-model), and the model runs `nookku register`. Type `nookku start` again to start the test. The start text names each part of the answer. The start removes the answer, so the next test needs a new answer. `check`, `run` and `mode start` also need a fresh answer, but `check` keeps it.

`start` also starts the [chat page](chat.md) of the test and opens it in your browser. The prompt `nookku start` and `/nookku start` in the plugin do the same. After `end` in a shell, the page continues, so you can export the test. The prompt `nookku end` and the next `start` stop the page ([SPEC.md section 5](../../../SPEC.md#5-relays)).

- If the browser cannot open, for example over SSH, `start` in a terminal prints the page URL. The prompt `nookku start` and `/nookku start` never show the URL, because the [harness model](../glossary.md#harness-model) can see their output. Then run `nookku chat` in a separate terminal.
- If the page does not start, `start` prints the reason. The test continues.
- To turn this off, for example for a test in CI, set the config key [`page`](../config.md#test-keys) to `false`.
- With `--json`, the text about the page goes to stderr.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print `current.json` of the test as JSON, with no `tap_token`, or `{"error": ...}`. |
| `--tester-session ID` | none | The [tester](../glossary.md#tester)'s [harness](../glossary.md#harness) session id. The [bridge](../glossary.md#bridge) never takes this session as a session of the app. |

| Exit code | Meaning |
|---|---|
| 0 | The test started. |
| 1 | The test did not start: no entry, no fresh egress answer, an invalid configuration (for example an unknown key), a test that runs already, or an entry that exited. The text names the cause. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The egress answer is registered. The run had no browser, so the chat page did not open:

```bash
nookku start
```

```text
Test 20261127-194219-0fb3 started on http://127.0.0.1:64076/. Relay mode is on.
To end the test and start the evaluation, type the prompt nookku end. To end the test with no evaluation, run nookku end in a shell.
Egress of the agent:
- no egress part: the agent calls no service
The browser did not open, so the chat page did not start. To use the page, run nookku chat in a separate terminal.
```

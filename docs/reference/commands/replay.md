# `nookku replay`

Release: nookku 0.6.2. Since 0.7.0 (not released yet): the config key `replay_ignore`.

```text
nookku replay SCRIPT [--base TEST] [--recorded] [--verdict] [--entry NAME] [--root PATH] [--tests-dir PATH] [--json] [--evaluate | --no-evaluate]
```

Run a saved script again after a fix, and see which replies changed ([SPEC.md section 7.10](../../../SPEC.md#710-scripted-tests)). `replay` runs the script as `nookku run --script` does. Then it compares the new test with the source test of the script, turn by turn. The source test is the test id in the name of the script file, as `nookku script save` names it. The diff uses the reply that the [tap](../glossary.md#tap) recorded, not the reply that the [harness](../glossary.md#harness) showed.

The output has the lines of `nookku run`, and then:

- the count of changed turns;
- each changed reply, with `[-deleted words-]` and `{+inserted words+}`. A change of 2 or more words in a row shows as one deleted part and one inserted part. At a terminal, the deleted words are red and the inserted words are green. Set `NO_COLOR` to get no color;
- the 2 test ids to select on the dashboard of `nookku chat`, which shows the 2 tests side by side.

A changed reply does not change the exit code. Only a person runs `nookku replay`: the [relay](../glossary.md#relay) denies it from the model, with each policy.

With `--recorded`, the backends, the model APIs and the MCP servers over HTTP of the test give the responses of the base test, and the replay calls none of them ([SPEC.md section 7.10](../../../SPEC.md#710-scripted-tests), "Recorded backends"). Then a changed reply comes from the agent, not from a backend. A request that the base test did not make gets status 502, and the [trace](../glossary.md#trace) gives the [finding](../glossary.md#findings) `replay_miss`. Each changed turn gives the finding `replay_changed`. The default limit of each of these 2 classes is 0, so with `--verdict`, a changed reply or a miss gives exit code 1.

A request matches a recorded call only if it has the same method, path, query and body bytes. If the app sends a new value in each request, for example a request ID or a time, give match rules in the config key [`replay_ignore`](../config.md). The rules of the toy shop backend `orders` ignore the body field `request_id` and the query parameter `ts`:

```json
{"replay_ignore": {"orders": {"body": ["request_id"], "query": ["ts"]}}}
```

A body rule works only on a JSON body. The manifest records the rules, and `replay` prints a line `Match rule: ...` for each call whose match ignored a value. With no rule, the match is exact.

`--recorded` needs a base test with an intact [seal](../glossary.md#seal). It does not start if the test has a stdio MCP server or a database with a proxy, because the replay has no player for these parts.

| Flag | Default | Meaning |
|---|---|---|
| `SCRIPT` | required | The script file, for example `.nookku/scripts/<test id>.jsonl`. |
| `--base TEST` | the name of the script file | The test id to compare with. |
| `--entry NAME` | the key `entry` | A name in the config key `entries`. |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print `{"pass": ..., "report": [...], "evaluation": ..., "diff": ...}`. |
| `--no-evaluate`, `--evaluate` | the config key `evaluate` | Print the [evaluation](../glossary.md#evaluation) prompt at the end, or not. |
| `--recorded` | off | Give the recorded responses of the base test to the app, and call no backend, model API or MCP server over HTTP. It needs `--base` or a script file name that names the base test. |
| `--verdict` | off | Give exit code 1 if the verdict of the new test is not `pass`, or if the verdict cannot be used ([SPEC.md section 7.14](../../../SPEC.md#714-verdict)). |

| Exit code | Meaning |
|---|---|
| 0 | The [audit](../glossary.md#audit) of the new test is clean. |
| 1 | As for `nookku run`. |
| 2 | `--base` names no test. Nothing ran. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The egress answer is registered. The script is the script of an earlier test:

```bash
nookku replay .nookku/tests/20261127-194213-41bc/script.jsonl --no-evaluate
```

```text
Test 20261127-194216-71f9: ~/shop/.nookku/tests/20261127-194216-71f9
Turns: 3 of 3 messages
Audit: exit 0
Trace: 0 model items in 3 turns, no findings.
PASS
Replay: no test to compare with. The script name is not a test id. Give one with --base TEST.
```

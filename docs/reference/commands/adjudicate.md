# `nookku adjudicate`

Release: nookku 0.7.0.

```text
nookku adjudicate TEST --turn N --outcome OUTCOME --reason TEXT [--author NAME] [--root PATH] [--tests-dir PATH]
```

Record your decision about one mismatch of the [answer key](../app-spec.md#answer-key) ([SPEC.md section 7.17](../../../SPEC.md#717-answer-key)). A mismatch does not say which side is wrong. You decide it for each mismatch:

| Outcome | Meaning | Counts against the limit of `answer_key_mismatch` |
|---|---|---|
| `agent_wrong` | The reply is wrong. | Yes |
| `key_wrong` | The key is wrong. | No |
| `both_acceptable` | The reply and the key are both correct. | No |

- The command adds 1 row to `adjudications.jsonl` in the [test folder](../glossary.md#test-folder): the turn, the question, the outcome, the reason, the author and the time. `findings.json` keeps the mismatch.
- A later row for the same turn replaces the earlier decision. The earlier row stays in the file.
- The command writes `verdict.json` again and updates the [seal](../glossary.md#seal). It prints the verdict line with the counts before and after the adjudications.
- The command reads each record one time and uses only bytes that the seal covers. If a sealed file changes during the command, the command does not update the seal and exits with 1. The seal is then broken.
- A mismatch with no adjudication is open, and it counts against the limit.
- Only a person runs this command. The [relay](../glossary.md#relay) denies it from the model.
- A gate result that pinned the test cannot be used after an adjudication. Run the gate again.

```text
$ nookku adjudicate 20261113-090000-ak01 --turn 3 --outcome key_wrong --reason "The stock list of 2026-11-01 is old."
Test 20261113-090000-ak01, turn 3: key_wrong, by asha.
Verdict: fail. answer_key_mismatch: 1, the limit is 0. Adjudications: 2 answer_key_mismatch before, 1 after (1 open, 0 agent_wrong, 1 key_wrong, 0 both_acceptable).
```

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | none | The test id, or the path of the test folder. |
| `--turn N` | none | The turn of the mismatch, from `answers` of `findings.json` or from the `answer_key_mismatch` [finding](../glossary.md#findings). |
| `--outcome OUTCOME` | none | `agent_wrong`, `key_wrong` or `both_acceptable`. |
| `--reason TEXT` | none | Why the outcome is correct. |
| `--author NAME` | the login name of the OS user | Your name. Nookku records it and does not check it. |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |

| Exit code | Meaning |
|---|---|
| 0 | The row was written, and the seal covers it. |
| 1 | The row was written, and `verdict.json` was not written again. |
| 2 | No row was written: no test folder, a seal that is not intact, a turn with no mismatch, or a value that is not valid. |

## Example

In a copy of `examples/toy-shop-docs/`, the answer key of the second question names a wrong section, so the verdict is `fail` and `run` exits with 1:

```bash
nookku run --script script.jsonl --verdict --no-evaluate
```

```text
Test 20261127-194310-bf69: ~/toy-shop-docs/.nookku/tests/20261127-194310-bf69
Turns: 3 of 3 messages
Audit: exit 0
Trace: 0 model items in 3 turns, 1 answer_key_mismatch.
Verdict: fail. answer_key_mismatch: 1, the limit is 0.
FAIL: The verdict is fail. Read verdict.json in the test folder.
```

A person reads the reply and the key, and decides that the key is wrong:

```bash
nookku adjudicate 20261127-194310-bf69 --turn 2 --outcome key_wrong --reason "The key names the delivery time, not the cities." --author tester
```

```text
Test 20261127-194310-bf69, turn 2: key_wrong, by tester.
Verdict: pass (3 limits). Adjudications: 1 answer_key_mismatch before, 0 after (0 open, 0 agent_wrong, 1 key_wrong, 0 both_acceptable).
```

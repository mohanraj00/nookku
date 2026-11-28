# `nookku transcript`

Release: nookku 0.7.0.

Print the exact conversation for the model to evaluate ([SPEC.md section 5](../../../SPEC.md#5-relays)). With an [entry](../glossary.md#entry), the scope is the latest test. A check test that ended does not count: after `nookku check`, the scope is the test before it ([SPEC.md section 9.1](../../../SPEC.md#91-start)).

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--test ID` | the latest test that is not a check test that ended | The test to print: the test id, or the path of the [test folder](../glossary.md#test-folder). |
| `--trace` | off | Print each turn as the app got it (from `tap.jsonl`), with the model items and the [findings](../glossary.md#findings) of that turn ([SPEC.md section 9.2](../../../SPEC.md#92-evaluation-prompt)). It ignores `--record`, `--all` and `--session`. |
| `--all` | off | With no entry: each session of the record, not only the latest one. |
| `--session ID` | none | Only the turns of this [harness](../glossary.md#harness) session. |
| `--compact` | the config key `transcript_compact` | With `--trace`: show a repeated text of 200 or more characters one time. The bound is a chosen value, not a measurement ([`COMPACT_MIN`](../../../src/nookku/evaluation.py#L21-L22)). After that, it shows as a reference with its `[trace.jsonl:N]`, its SHA-256 and its length. An OpenTelemetry attribute with the text of a session item of the same turn also shows as a reference ([SPEC.md section 9.2](../../../SPEC.md#92-evaluation-prompt)). |
| `--no-compact` | the config key `transcript_compact` | With `--trace`: show each text in full. |
| `--record FILE` | from the config | The [relay record](../glossary.md#relay-record) to print. |

| Exit code | Meaning |
|---|---|
| 0 | The transcript printed. With `--trace`, also if a record is invalid: then the first line says `Record: INVALID` and the transcript shows no turn. |
| 2 | No test folder (with `--trace`), the config cannot be read, or the relay record is missing or invalid. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku transcript --test 20261127-194213-41bc
```

```text
nookku transcript, test 20261127-194213-41bc: 3 turns. The text is exact: the tester typed each tester block, and the agent sent each agent block.
Legend: ok (an agent block): the agent answered and the relay showed its reply. It does not judge the reply. Not ok (a relay error block): the relay got no reply and shows its own error text.

──── script, turn 1 ────
What is your refund policy?
──── agent ────
Our refund policy:

1. Damaged items: full refund.
2. Change of mind: 30 days.

──── script, turn 2 ────
Do you ship to Pune?
──── agent ────
We ship to Chennai and Pune. Delivery takes 3 to 5 days.  
──── script, turn 3 ────
What is the price of the blue mug?
──── agent ────
| item | price |
|---|---|
| blue mug | € 8 |
| teapot | € 24 |
```

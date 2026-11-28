# `nookku gate`

Release: nookku 0.7.0. New in 0.7.0: the refusal of a gate file with the test key `answer_key`.

```text
nookku gate run FILE --subject DIGEST [--root PATH] [--tests-dir PATH] [--json]
nookku gate verify [GATE] [--root PATH] [--tests-dir PATH] [--json]
```

`nookku gate run` runs each test of a gate file, and writes one sealed result ([SPEC.md section 7.15](../../../SPEC.md#715-gate-run)). Each test runs as `nookku run --script --verdict` does. The result folder is `.nookku/gates/<gate id>/`. The command then verifies the result as `nookku gate verify` does. Only a person runs `nookku gate run`: the [relay](../glossary.md#relay) denies it from the model, with each policy. [Gate a release](../../how-to/gate-a-release.md) shows the steps.

`nookku gate verify` checks a gate result against its [seal](../glossary.md#seal) and the pinned files of its tests, and computes the result again. The relay lets the model run it, because it only reads.

| Flag | Default | Meaning |
|---|---|---|
| `COMMAND` | required | `run` or `verify`. |

The flags of `run` and `verify`:

- `FILE`, for `run` only: the gate file. It is required.
- `--subject DIGEST`, for `run` only: the digest of the tested thing, 1 to 512 characters. It is required. Nookku does not interpret it.
- `GATE`, for `verify` only: a gate id or a gate folder. The default is the newest gate folder.
- `--root PATH`: the project. The default is the current folder.
- `--tests-dir PATH`: the [tests folder](../cli.md#the-tests-folder). The default is `$NOOKKU_TESTS_DIR`, else `.nookku/tests`.
- `--json`: print `{"gate": ..., "result": ...}`, or `{"gate": ..., "error": ...}`.

| Command | Exit code | Meaning |
|---|---|---|
| `run` | 0 | The verified aggregate verdict is `pass`. |
| | 1 | The aggregate verdict is `fail`, or the result cannot be verified. |
| | 3 | The aggregate verdict is `inconclusive`: a call of a test failed for a provider limit or a refused service, and no good call followed it ([SPEC.md section 8.13](../../../SPEC.md#813-outside-failures)). Run the gate again. |
| | 2 | The gate file, the subject, the tests folder or the egress answer is not valid. No test ran. |
| `verify` | 0 | The result can be used, and its verdict is `pass`. |
| | 1 | The result can be used, and its verdict is `fail`. |
| | 3 | The result can be used, and its verdict is `inconclusive`. The output gives the count of the inconclusive tests. |
| | 2 | No gate folder is found, or the result cannot be used. The output gives the reason. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The gate file `gates/gate.json` is a copy of `examples/rollout-gate/gate.json`, with its script.

```bash
nookku gate run gates/gate.json --subject sha256:ab12cd34
```

```text
Test stock-questions: Test 20261127-194230-d0db: ~/shop/.nookku/tests/20261127-194230-d0db
Test stock-questions: Turns: 3 of 3 messages
Test stock-questions: Audit: exit 0
Test stock-questions: Trace: 0 model items in 3 turns, no findings.
Test stock-questions: Verdict: pass (0 limits).
Test stock-questions: PASS
Gate gate-20261127-194230-d1edf94f: ~/shop/.nookku/gates/gate-20261127-194230-d1edf94f
stock-questions (20261127-194230-d0db): pass.
Gate verdict: pass. Subject: sha256:ab12cd34
```

Check the gate result against its seal:

```bash
nookku gate verify gate-20261127-194230-d1edf94f
```

```text
Gate gate-20261127-194230-d1edf94f: ~/shop/.nookku/gates/gate-20261127-194230-d1edf94f
stock-questions (20261127-194230-d0db): pass.
Gate verdict: pass. Subject: sha256:ab12cd34
```

# `nookku verify`

Release: nookku 0.6.2. Since 0.7.0 (not released yet): the check of a sealed refusal record.

```text
nookku verify [TEST] [--root PATH] [--tests-dir PATH] [--json]
```

Check that no record of a test changed after its end ([SPEC.md section 7.4](../../../SPEC.md#74-seal)). The output starts with the test id, for example `Test 20261011-184952-8a8d. Seal: intact. No record changed after the end of the test.` With no `TEST`, the id shows which test the command checked. `--json` prints only the result of SPEC.md section 7.4.

`TEST` can also be the id of a sealed refusal record of a refused start, for example `refused-20261127-120000-0a1b2c3d`. Then the output starts with `Refusal record` and the id ([SPEC.md section 7.8](../../../SPEC.md#78-codex-hook-gate)). With no `TEST`, the command never checks a refusal record.

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id, or the path of the [test folder](../glossary.md#test-folder). |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print the result as JSON. |

| Exit code | Meaning |
|---|---|
| 0 | The [seal](../glossary.md#seal) is intact. |
| 2 | The seal is broken, the test has no seal, or there is no test folder. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku verify 20261127-194213-41bc
```

```text
Test 20261127-194213-41bc. Seal: intact. No record changed after the end of the test.
```

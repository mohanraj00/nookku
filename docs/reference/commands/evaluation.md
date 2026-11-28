# `nookku evaluation`

Release: nookku 0.6.1.

```text
nookku evaluation import TEST [--root PATH] [--tests-dir PATH]
nookku evaluation add TEST --class CLASS --evidence TEXT --text TEXT [--turn N] [--author NAME] [--root PATH] [--tests-dir PATH]
```

Write the issue rows of an [evaluation](../glossary.md#evaluation) to `evaluation.json` in the [test folder](../glossary.md#test-folder) ([SPEC.md section 9.4](../../../SPEC.md#94-issue-rows)). A program can then count the issues of each class, with no model.

- `import` reads the issue table of `report.md` and writes each row as a `model` row. Run it after the evaluation. A second import replaces the model rows and keeps your rows.
- `add` writes one `human` row: an issue that you found. The command also writes your rows to the end of `report.md`, under `## Person issues`.
- The command sets the author type. The text of a row never sets it.
- `import` trusts the bytes of `report.md`. Do not run it in a test folder that another user can write ([limits.md](../../limits.md)).
- If `report.md` changed after the last import, `add` writes no row. Run `import` first.
- The command writes `verdict.json` again and updates the [seal](../glossary.md#seal), with the same rules as [`nookku adjudicate`](adjudicate.md).
- An issue row changes the verdict only if a `Verdict` row of the [app spec](../app-spec.md#verdict) names its class.
- Only a person runs this command. The [relay](../glossary.md#relay) denies it from the model.

```text
$ nookku evaluation add 20261113-090000-ak01 --class tone --turn 2 --evidence "turn 2" --text "The reply is curt."
Test 20261113-090000-ak01: 1 model rows and 1 human rows in evaluation.json.
Verdict: fail. tone: 2 issue rows, the limit is 0.
```

| Argument or flag | Default | Meaning |
|---|---|---|
| `ACTION` | none | `import` or `add`. |
| `TEST` | none | The test id, or the path of the test folder. |
| `--class CLASS` | none | `add`: an issue class of [SPEC.md section 9.3](../../../SPEC.md#93-report), for example `tone`. |
| `--evidence TEXT` | none | `add`: a `trace.jsonl:N` line, a turn or a source line. |
| `--text TEXT` | none | `add`: the issue. |
| `--turn N` | no turn | `add`: the turn of the issue. |
| `--author NAME` | the login name of the OS user | `add`: your name. Nookku records it and does not check it. |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |

| Exit code | Meaning |
|---|---|
| 0 | The rows were written, and the seal covers them. |
| 1 | The rows were written, and `verdict.json`, the seal or `report.md` was not written. |
| 2 | No row was written: no test folder, a seal that is not intact, a `report.md` with no issue table, or a value that is not valid. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku evaluation add 20261127-194213-41bc --class tone --turn 2 --evidence relay.jsonl:2 --text "The reply lists cities with no greeting."
```

```text
Test 20261127-194213-41bc: 0 model rows and 1 human rows in evaluation.json.
Verdict: pass (0 limits).
```

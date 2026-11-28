# `nookku script`

Release: nookku 0.6.2.

```text
nookku script save [TEST] [--root PATH] [--tests-dir PATH]
```

Save a test as a script ([SPEC.md section 7.10](../../../SPEC.md#710-scripted-tests)). After you fix a defect, send the same messages again with `nookku run --script`. The command writes the `said` text of each turn of the test to `.nookku/scripts/<test id>.jsonl`, byte for byte. The file name records the source test id. The command prints the path and the `nookku run` command. The "Save as script" button of the chat page (`nookku chat`) does the same for the test that the page shows.

Only a person runs `nookku script`: the [relay](../glossary.md#relay) denies it from the model, with each policy. The guard also denies a model write to `.nookku/scripts/`, so the model cannot change a saved script before you run it.

| Flag | Default | Meaning |
|---|---|---|
| `ACTION` | required | `save`. |
| `TEST` | the latest test | The test id, or the path of the [test folder](../glossary.md#test-folder). |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |

| Exit code | Meaning |
|---|---|
| 0 | The command wrote the script. |
| 1 | The `relay.jsonl` of the test is not valid or has no turn, or the command cannot write the file. |
| 2 | No test has this id. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku script save 20261127-194213-41bc
```

```text
Saved 3 messages of test 20261127-194213-41bc to ~/shop/.nookku/scripts/20261127-194213-41bc.jsonl
Run it with: nookku run --script .nookku/scripts/20261127-194213-41bc.jsonl
```

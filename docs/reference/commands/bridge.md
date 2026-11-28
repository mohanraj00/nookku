# `nookku bridge`

Release: nookku 0.6.1.

The background process of a test ([architecture.md](../../architecture.md#the-bridge)). `start` runs it.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | required | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--test ID` | required | The test id. |
| `--tester-session ID` | none | The [tester](../glossary.md#tester)'s [harness](../glossary.md#harness) session id. |
| `--entry-name NAME` | none | The name of the [entry](../glossary.md#entry) in `entries`, from `nookku run --entry`. |
| `--persona-source FILE` | none | The absolute path of the persona file of a simulated user, for the manifest. `run` copies the file into the [test folder](../glossary.md#test-folder) before it starts the [bridge](../glossary.md#bridge). |
| `--play-base ID` | none | The base test of a replay with `--recorded`. The proxies of the test answer from the copied records of this test ([SPEC.md section 7.10](../../../SPEC.md#710-scripted-tests)). |
| `--script-source FILE` | none | The absolute path of the script of a [scripted test](../glossary.md#scripted-test), for the manifest. `run` copies the script into the test folder before it starts the bridge. |
| `--check` | off | The test is a test of `nookku check`. The manifest records `"check": true`, so the model does not evaluate the test ([SPEC.md section 9.1](../../../SPEC.md#91-start)). |

| Exit code | Meaning |
|---|---|
| 0 | The test ended. |
| 1 | The bridge could not start the entry, the entry exited at start, or the bridge could not read the start time of its process. |

This is an internal command. The [relay](../glossary.md#relay) or the bridge runs it, and a tester does not run it.

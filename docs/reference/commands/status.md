# `nookku status`

Release: nookku 0.7.0.

Show [relay mode](../glossary.md#relay-mode) and the running test, for example `relay mode is on. Test <test-id> runs on <tap-url>.` If no test runs, the second sentence is `No test runs.` If no test runs and a test stopped with no end, 2 more lines name that test, its folder and the command `nookku end` ([recover a stuck test](../../how-to/recover-a-stuck-test.md)). The prompt `nookku status` gives the same text. In relay mode, the status line of the plugin also shows it.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print `{"on": ..., "test": ..., "text": ..., "attachments": ..., "pane": ..., "stopped": ...}`. `test` is `current.json` with no `tap_token`, or `null`. `text` is the status line of the plugin, on one line. `attachments` is the text that refuses a prompt with an attachment in the plugin. Each of `text` and `attachments` is `null` if relay mode is off. `pane` is the data of the Claude Code pane: `test`, `state`, `turns` and `page` ([SPEC.md section 5](../../../SPEC.md#5-relays), "Pane"). `stopped` is `{"test": ..., "folder": ...}` for a test that stopped with no end, or `null` if no test stopped or a test runs. |

| Exit code | Meaning |
|---|---|
| 0 | Always. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`:

```bash
nookku status
```

```text
relay mode is off. No test runs.
```

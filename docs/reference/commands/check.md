# `nookku check`

Release: nookku 0.6.2.

Run a short test with one message, and check the [entry](../glossary.md#entry) and its model sessions ([SPEC.md section 7.1](../../../SPEC.md#71-configuration)). It sends the value of the config key `check_message`. The default is `Hello from nookku check. What can you help me with?`. If your app declines this message, set `check_message` to a message that your app answers, with `nookku init <harness> --check-message TEXT` ([config.md](../config.md#nookkuconfigjson))

PASS proves the connection, not the reply. PASS means that:

- the entry sent a reply line, not an `error` line;
- the [audit](../glossary.md#audit) of the test exits with 0;
- the test found a model session and its session file for each [harness](../glossary.md#harness) in `models`.

`check` ends its test. The model does not evaluate a check test. If your test ended before `check` and has no `report.md`, the prompt `nookku end` after `check` starts the [evaluation](../glossary.md#evaluation) of your test. Else it starts no evaluation ([SPEC.md section 9.1](../../../SPEC.md#91-start)).

`check` does not judge the text of the reply. A fallback reply of the app also passes. [how-to/connect-your-agent.md](../../how-to/connect-your-agent.md#make-sure-that-check-runs-your-real-app) shows how to make sure that the entry runs your real app.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print `{"pass": ..., "report": [...]}`. |

| Exit code | Meaning |
|---|---|
| 0 | The entry sent a reply, the audit of the test is clean, and the test found a model session for each harness in `models`. |
| 1 | The check failed, or the test did not start. For example, the audit of the test exits with 1 or 2, the test wrote no valid `audit.json`, or a model session has no session file. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`:

```bash
nookku check
```

```text
Test 20261127-194211-a594: ~/shop/.nookku/tests/20261127-194211-a594
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

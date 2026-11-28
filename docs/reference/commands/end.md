# `nookku end`

Release: nookku 0.6.1.

End the test: switch [relay mode](../glossary.md#relay-mode) off, stop the [entry](../glossary.md#entry) and collect its sessions, the [trace](../glossary.md#trace), the [audit](../glossary.md#audit) and the [seal](../glossary.md#seal) ([SPEC.md section 7.2](../../../SPEC.md#72-start-and-end)). If no test runs, it switches relay mode off.

`end` in a shell does not stop the chat page that `start` started, so you can still export the test and save it as a script from the page. The prompt `nookku end` and `end --evaluation` stop that page. A page that you started with `nookku chat` continues to run. `end` in a shell gives no [evaluation](../glossary.md#evaluation). If the test needs an evaluation, it prints the prompt to type in the [harness](../glossary.md#harness): `To evaluate the test, type this prompt in your harness: nookku end` ([SPEC.md section 9.1](../../../SPEC.md#91-start)). If `config.json` is broken, no evaluation starts, and `end` prints the error.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print the manifest of the test as JSON, or `null` if no test ran. |
| `--evaluation` | off | Print one JSON object: `text`, the end text, and `evaluation`, the evaluation prompt or `null` ([SPEC.md section 9.1](../../../SPEC.md#91-start)). It is for a [relay](../glossary.md#relay) of your own that starts the evaluation. The plugin does not use it. |

| Exit code | Meaning |
|---|---|
| 0 | Always. |

## Example

After `nookku start` in the project `~/shop`:

```bash
nookku end
```

```text
Ending test 20261127-194219-0fb3. Waiting up to 120 s for the bridge to stop.
Test 20261127-194219-0fb3 ended: 0 turns, 0 model sessions.
Folder: ~/shop/.nookku/tests/20261127-194219-0fb3
Trace: 0 model items in 0 turns, no findings.
Audit: nookku audit --tap ~/shop/.nookku/tests/20261127-194219-0fb3/tap.jsonl --relay ~/shop/.nookku/tests/20261127-194219-0fb3/relay.jsonl
To evaluate the test, type this prompt in your harness: nookku end
```

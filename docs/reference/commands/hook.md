# `nookku hook`

Release: nookku 0.7.0.

The hook command that `init` writes into the hook file. It reads one hook event as JSON on stdin and writes the answer on stdout ([SPEC.md section 5](../../../SPEC.md#5-relays)).

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | from the event | The project. With no `--root`, a Claude Code hook takes `CLAUDE_PROJECT_DIR`, and each hook then takes the `cwd` of the event, else its working folder. The plugin gives no `--root`. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--harness NAME` | required | `codex` or `claude-code`. |

| Exit code | Meaning |
|---|---|
| 0 | The hook answered. If the hook fails in [relay mode](../glossary.md#relay-mode), it still blocks the prompt. |
| 2 | A wrong argument, an event that cannot be read, or both the old and the new state folder in the project. Exit 2 blocks the event, so the [relay](../glossary.md#relay) fails closed. |

This is an internal command. The relay or the [bridge](../glossary.md#bridge) runs it, and a [tester](../glossary.md#tester) does not run it.

# `nookku mode`

Release: nookku 0.7.0.

```text
nookku mode [STATE] [--root PATH] [--tests-dir PATH] [--tester-session ID]
```

Switch [relay mode](../glossary.md#relay-mode) on or off. With an [entry](../glossary.md#entry), `on` starts a test and `off` ends it. With no entry, it only switches relay mode ([how-to/http-tap.md](../../how-to/http-tap.md)). Before it switches relay mode on, it reads `config.json`, if the file exists. If the file is broken, `on` shows the error and does not switch relay mode on ([#109](https://github.com/mohanraj00/nookku/pull/109)). If the file does not exist, `on` tells you to run `nookku init plugin`, and does not switch relay mode on. If relay mode is already on, it stays on, and the [relay](../glossary.md#relay) blocks each prompt that is not a [control prompt](../glossary.md#control-prompt) ([SPEC.md section 7.1](../../../SPEC.md#71-configuration)). In the Claude Code plugin, a prompt with an attachment gets the attachment refusal, not the config error. The `/nookku` command of the plugin runs `nookku mode` with its words, and shows the output.

| Argument or flag | Default | Meaning |
|---|---|---|
| `STATE` | `status` | `on`, `off` or `status`. `start` is the same as `on`, and `end` is the same as `off`. |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--tester-session ID` | none | The [tester](../glossary.md#tester)'s [harness](../glossary.md#harness) session id. With an entry, the test copies this session when it ends. |

| Exit code | Meaning |
|---|---|
| 0 | `off` or `status` ran, `on` switched relay mode on, or `on` with an entry started a test. |
| 1 | `on` refused relay mode, and the text names the cause. For example, `config.json` is broken or does not exist, the Claude Code or Codex hooks are not ready, Claude Code does not run as the interactive CLI, or the test did not start ([#248](https://github.com/mohanraj00/nookku/issues/248)). |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`:

```bash
nookku mode status
```

```text
Relay mode is off.
```

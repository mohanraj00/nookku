# `nookku init`

Release: nookku 0.6.2.

```text
nookku init HARNESS [--root PATH] [--entry COMMAND] [--models LIST] [options]
nookku init --remove HARNESS [--root PATH]
```

Write the config, and the [project hooks](../glossary.md#project-hooks) of a [harness](../glossary.md#harness). It writes `.nookku/config.json`, the files `.nookku/mode` and `.nookku/nookku-state`, and the hooks: `.codex/hooks.json` for Codex, `.claude/settings.local.json` for Claude Code. It keeps your other hooks, also a hook in the same group as a hook of nookku. With `plugin`, it writes no hooks, because the nookku plugin has them. Do not use the plugin and the project hooks in one project, or each message is sent two times.

If `config.json` exists, `init` keeps each key and changes only the keys of the flags that you give. For example, a second run keeps `models` and `"evaluate": false`. It prints the keys that it changed and the keys that it kept. A new `config.json` gets each key. The default of a flag applies only to a new file.

If `config.json` has an unknown key, or if `config.json` or the hook file is not valid JSON, `init` writes nothing. Correct the file, then run `init` again. If a flag gives a value that [breaks](../glossary.md#break) the rule of its key, `init` also writes nothing. If `config.json` has the key `backends` or `model_api` of nookku 0.5.1 and earlier, `init` writes nothing and names the keys. Remove them: the egress answer replaces them ([SPEC.md section 7.11](../../../SPEC.md#711-egress-discovery)).

The output starts with `Project root:` and the absolute root, then gives the absolute path of each file that `init` wrote. If the root is in a state folder or a [test folder](../glossary.md#test-folder), for example `.nookku/tests/<id>`, the target of a `.nookku` symlink, or a copied test folder, `init` writes nothing, exits with 1 and names the project folder to use ([code](../../../src/nookku/cli.py), [test](../../../tests/test_cli.py)). If the root has no `config.json` and is not the top level of its git work tree, `init` prints a warning that names the top level. It still writes the files.

If the config has no `entry` and no `agent_url` after the run, the last line of the output is a note: `Note: .nookku/config.json has no entry, so a test cannot start yet. Write the command that starts your agent with: nookku init <harness> --entry "python3 agent.py". Replace python3 agent.py with your command.` `<harness>` is the harness of the run. The exit code stays 0. With `agent_url` and no [entry](../glossary.md#entry), the [relay](../glossary.md#relay) sends each message to the [tap](../glossary.md#tap) of `tap_url` ([how-to/http-tap.md](../../how-to/http-tap.md)), so `init` gives no note.

| Argument or flag | Default | Meaning |
|---|---|---|
| `HARNESS` | | `codex`, `claude-code` or `plugin`. |
| `--root PATH` | the current folder | The project. |
| `--entry COMMAND` | none | The entry command of a test, as one string. The shell rules split it into arguments. |
| `--models LIST` | none | The app's model harnesses, separated by commas: `claude-code`, `codex` or both. |
| `--spec LIST` | none | The config key `spec`: the files of the [app spec](../app-spec.md), separated by commas, relative to the root. Each one must be a file in the project, or `init` writes nothing. |
| `--tap-url URL` | `http://127.0.0.1:8800/` | The config key `tap_url`. |
| `--agent-url URL` | empty | The config key `agent_url`. |
| `--adapter NAME` | `json` | The config key `adapter`. |
| `--message-field PATH` | `text` | The config key `message_field`. |
| `--reply-field PATH` | `reply` | The config key `reply_field`. |
| `--openai-model NAME` | empty | The config key `openai_model`. |
| `--openai-stream`, `--no-openai-stream` | none | The config key `openai_stream`: `--openai-stream` sets it to `true`, and `--no-openai-stream` sets it to `false`. With neither flag, a new file gets `false`, and an existing file keeps its value. |
| `--record FILE` | `.nookku/relay.jsonl` | The config key `record`. |
| `--check-message TEXT` | `Hello from nookku check. What can you help me with?` | The config key `check_message`: the one message of `nookku check`. |
| `--model-reply-field PATH` | empty | The config key `model_reply_field`: the dot path of the client text in a structured model output. |
| `--model-reply-match MODE` | `normalized` | The config key `model_reply_match`: `exact`, `normalized` or `off`. |
| `--citation-field PATH` | empty | The config key `citation_field`: the dot path of the source locators in the reply. Empty turns the check `citation_not_read` off. |
| `--citation-prefix TEXT` | empty | The config key `citation_prefix`: the text that comes off the start of a locator before the match. |
| `--repeated-reply COUNT` | `2` | The config key `repeated_reply`: the count of consecutive turns with the same reply that gives a [finding](../glossary.md#findings). `0` turns the check off. |
| `--remove` | off | Remove the project hooks of nookku, and keep each other hook and key. `HARNESS` must be `claude-code` or `codex`. It takes no other flag. |

[config.md](../config.md#nookkuconfigjson) explains each key.

| Exit code | Meaning |
|---|---|
| 0 | The files were written. |
| 1 | Nothing was written: `config.json` or the hook file cannot be read, or `config.json` has an unknown key. The text names the cause. |

`init --remove` removes the project hooks from the hook file of the harness. It finds the isolated hook commands and the earlier commands that contain `nookku hook` or `verbatim_relay hook`. It removes a group or an event that then has no hook. It keeps the file, also as `{}`, and does not change the state folder. It prints the absolute path of the file and the count of removed hooks, or that the file has no hook of nookku. If a test runs or [relay mode](../glossary.md#relay-mode) is on, also in the `.verbatim-relay/` folder of 0.3, it changes nothing and exits with 1, because without the hooks a message in relay mode goes to the model. If relay mode comes on while it runs, it puts the hooks back and exits with 1. If the hook file cannot be read, it changes nothing and exits with 1 ([code](../../../src/nookku/kit.py), [test](../../../tests/test_kit.py)).

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`:

```bash
nookku init plugin --entry "python3 examples/toy-shop/agent.py"
```

```text
Project root: ~/shop
wrote ~/shop/.nookku/config.json
  A new file. Keys that differ from the default: entry.
Relay mode is off. Switch it with: nookku mode on
The nookku plugin runs the hooks. Do not also run nookku init codex or nookku init claude-code in this project, or each message is sent two times.
```

# `nookku mcp`

Release: nookku 0.7.0.

The MCP server that gives the model the read-only tools `transcript` and `status`. It reads one JSON-RPC message on each line of stdin and writes each answer on stdout. A [harness](../glossary.md#harness) starts it from its MCP configuration ([SPEC.md section 5](../../../SPEC.md#5-relays)). The plugin does not start it yet: [#216](https://github.com/mohanraj00/nookku/issues/216) adds it to the plugin.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. Claude Code and Codex start the server of the plugin in the project. The server does not read `CLAUDE_PROJECT_DIR`, because a Codex can inherit it from a Claude Code session of another project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |

| Exit code | Meaning |
|---|---|
| 0 | stdin ended. |

This is an internal command. The [relay](../glossary.md#relay) or the [bridge](../glossary.md#bridge) runs it, and a [tester](../glossary.md#tester) does not run it.

# `nookku mcp-stdio`

Release: nookku 0.6.1.

The wrapper of a stdio MCP server of the agent ([SPEC.md section 7.12](../../../SPEC.md#712-mcp-proxies)). The [bridge](../glossary.md#bridge) writes this command into the variable of each stdio MCP server that the egress answer names with a variable. The app starts the command in place of the server. The wrapper starts the server, copies each byte between the app and the server with no change, and writes each line to `mcp.jsonl`.

| Flag | Default | Meaning |
|---|---|---|
| `--folder PATH` | required | The [test folder](../glossary.md#test-folder). |
| `--name NAME` | required | The name of the server in the egress answer. |
| `SERVER` | required | The command of the server and its arguments, after `--`. |

| Exit code | Meaning |
|---|---|
| the code of the server | The server exited. |
| 127 | The server could not start. |

This is an internal command. The [relay](../glossary.md#relay) or the bridge runs it, and a [tester](../glossary.md#tester) does not run it.

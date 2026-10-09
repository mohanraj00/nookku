# Isolate an Agent SDK session

Use this page if your app runs a Claude Agent SDK session. An Agent SDK session can load more than your app gives it. With `setting_sources=[]`, it still connects to the claude.ai connectors of the tester's account, and it loads each plugin in the variable `CLAUDE_CODE_PLUGIN_DIRS`. Then the app's model can see tools that are not the app's tools. It can reach the tester's accounts, and the result of a test depends on the tester's machine.

## Set the options

To give the session only the tools of your app, set these options in the app (Python Agent SDK):

```python
ClaudeAgentOptions(
    mcp_servers={"shop": server},
    allowed_tools=["mcp__shop__lookup_order"],
    setting_sources=[],
    strict_mcp_config=True,
    env={"CLAUDE_CODE_PLUGIN_DIRS": ""},
)
```

- `setting_sources=[]` loads no settings file: no user, project or local settings, and thus no plugins, hooks or MCP servers from them. In TypeScript, the option is `settingSources: []`.
- `strict_mcp_config=True` passes `--strict-mcp-config` to Claude Code. The session then uses only the servers in `mcp_servers`, and no claude.ai connectors, no `.mcp.json` and no plugin servers. In TypeScript, the option is `strictMcpConfig: true`. The [Agent SDK reference](https://code.claude.com/docs/en/agent-sdk/python) defines both options.
- `CLAUDE_CODE_PLUGIN_DIRS` with an empty value loads no plugins from this variable. The session gets the variable from the entry, and thus from the tester's harness. `env` sets it for the session only.
- If your app loads MCP servers from `.mcp.json` or from a settings file, `strict_mcp_config` also stops them. Then set `ENABLE_CLAUDEAI_MCP_SERVERS` to `false` in `env`, in place of `strict_mcp_config`. This variable stops only the claude.ai connectors ([MCP docs](https://code.claude.com/docs/en/mcp#use-mcp-servers-from-claude-ai)).

These options are in the code of your app, not in the entry. `nookku setup` tells the harness model to check them and to tell you if one is missing. It does not change your app.

## Examples

The toy shop apps in this repo use these options:

- [examples/toy-shop-models/app.py](../../examples/toy-shop-models/app.py): 2 tools and a planted bug.
- [examples/toy-shop-full/app.py](../../examples/toy-shop-full/app.py): 3 tools, a stock service and a direct model call.

Each one needs `claude-agent-sdk`, which is not a dependency of Nookku:

```bash
uv run --with claude-agent-sdk python3 examples/toy-shop-full/entry.py
```

## Check the result

The trace check `server_not_from_app` finds a claude.ai connector or a plugin server in a session file of your app ([SPEC.md section 8.6](../../SPEC.md#86-findings)). After a test, run:

```bash
nookku trace
```

If the session is isolated, the output has no `server_not_from_app` line. The check does not find a server from a settings file or from `.mcp.json`, because its name does not show where it comes from.

## In the proofs

In an earlier run of the evaluation proof, the report missed the planted bug. The runs after the isolation ([#28](https://github.com/mohanraj00/verbatim-relay/issues/28)) each passed. [docs/results.md](../results.md#p5-and-p6-the-evaluation-at-the-end-of-a-test) has the data of both.

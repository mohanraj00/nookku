# Toy shop agent

This is the toy shop chat agent of the quick start. It uses the Python standard library only, and it has no model. It shows the agent contract and the tap in HTTP mode.

- [agent.py](agent.py) speaks the agent contract on stdin and stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)). It gives a fixed reply for each topic. In a test, it writes its state to `app-state/answers.jsonl` in the test folder, so the seal covers the state.
- [http_agent.py](http_agent.py) is the same agent as an HTTP server, for the tap in HTTP mode.
- [http_entry.py](http_entry.py) is an entry that starts the HTTP server and sends each message to it.
- [script.jsonl](script.jsonl) is the script of 3 messages for a scripted test. [`nookku run`](../../docs/reference/cli.md#nookku-run) sends each message to the agent.
- [evaluation.json](evaluation.json) is the data of the worked evaluation. [scripts/example_evaluation.py](../../scripts/example_evaluation.py) writes it, and [docs/evaluation-example.md](../../docs/evaluation-example.md) explains it.

## Run it

Choose one relay before you run `nookku init`. Do not install the plugin and the project hooks in the same project, because each message can then reach the agent 2 times. [docs/how-to/choose-a-relay.md](../../docs/how-to/choose-a-relay.md) compares them.

From the repo root, run the command of your relay, then follow its guide:

| Relay | Command | Guide |
|---|---|---|
| Plugin | `nookku init plugin --entry "python3 examples/toy-shop/agent.py"` | [Claude Code](../../docs/how-to/claude-code-plugin.md) or [Codex](../../docs/how-to/codex.md) |
| Project hooks in Claude Code | `nookku init claude-code --entry "python3 examples/toy-shop/agent.py"` | [Claude Code project hooks](../../docs/how-to/claude-code-hook-kit.md) |
| Project hooks in Codex | `nookku init codex --entry "python3 examples/toy-shop/agent.py"` | [Codex](../../docs/how-to/codex.md) |

For the HTTP agent, read [docs/how-to/http-tap.md](../../docs/how-to/http-tap.md).

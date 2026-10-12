# Toy shop agent

This is the toy shop chat agent of the quick start. It uses the Python standard library only, and it has no model. It shows the agent contract and the tap in HTTP mode.

- [agent.py](agent.py) speaks the agent contract on stdin and stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)). It gives a fixed reply for each topic. In a test, it writes its state to `app-state/answers.jsonl` in the test folder, so the seal covers the state.
- [http_agent.py](http_agent.py) is the same agent as an HTTP server, for the tap in HTTP mode.
- [http_entry.py](http_entry.py) is an entry that starts the HTTP server and sends each message to it.
- [evaluation.json](evaluation.json) is the data of the worked evaluation. [scripts/example_evaluation.py](../../scripts/example_evaluation.py) writes it, and [docs/evaluation-example.md](../../docs/evaluation-example.md) explains it.

## Run it

From the repo root:

```bash
nookku init claude-code --entry "python3 examples/toy-shop/agent.py"
```

Then follow your guide: the [Claude Code plugin](../../docs/how-to/claude-code-plugin.md), the [Claude Code project hooks](../../docs/how-to/claude-code-hook-kit.md) or [Codex](../../docs/how-to/codex.md). For the HTTP agent, read [docs/how-to/http-tap.md](../../docs/how-to/http-tap.md).

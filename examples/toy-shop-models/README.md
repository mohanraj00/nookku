# Toy shop with a model session

This is the toy shop support agent with a real model session. It shows how a test records the session of an app that uses the Claude Agent SDK, and how the evaluation at the end of a test checks the app against its rules.

- [app.py](app.py) is the agent: one Claude Agent SDK client with tools that read and write the shop's state.
- [entry.py](entry.py) is the entry. It speaks the agent contract on stdin and stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)).
- [RULES.md](RULES.md) holds the shop's rules.
- [state.json](state.json) holds the orders. Set `TOY_SHOP_STATE` to use a different file.

The app has a planted bug for the evaluation proof. This README does not describe the bug, so that a model that reads this folder does not learn it.

## Run it

The app needs `claude-agent-sdk`, which is not a dependency of Nookku.

Choose one relay before you run `nookku init`, and do not install the 2 forms in the same project ([docs/how-to/choose-a-relay.md](../../docs/how-to/choose-a-relay.md)). From the repo root, run `nookku init` with your relay: `plugin`, `claude-code` or `codex`. This example uses the project hooks in Claude Code:

```bash
nookku init claude-code --entry "uv run --with claude-agent-sdk python3 examples/toy-shop-models/entry.py" --models claude-code
```

The flag `--models claude-code` tells Nookku that the app runs its own Claude Code session.

[docs/how-to/isolate-agent-sdk.md](../../docs/how-to/isolate-agent-sdk.md) tells how to keep the app's model session apart from the harness. [scripts/proof_report.py](../../scripts/proof_report.py) uses this app.

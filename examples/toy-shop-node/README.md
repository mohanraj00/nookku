# Toy shop agent in Node

This is the toy shop agent as an entry in Node. It needs no package. It shows the agent contract in a language other than Python.

- [entry.mjs](entry.mjs) reads one JSON line on stdin for each message, and writes one JSON line on stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)). It sends the console output of the app to stderr.
- The function `reply` is the app. Replace it with the call to your own app. `reply` can be `async`.
- A message with the word "order" makes `reply` fail. The entry then writes an `error` line, not a reply line. This shows how the entry reports an app error.

## Run it

Choose one relay before you run `nookku init`, and do not install the 2 forms in the same project ([docs/how-to/choose-a-relay.md](../../docs/how-to/choose-a-relay.md)). From the repo root, run `nookku init` with your relay: `plugin`, `claude-code` or `codex`. This example uses the project hooks in Claude Code:

```bash
nookku init claude-code --entry "node examples/toy-shop-node/entry.mjs"
```

[docs/how-to/connect-your-agent.md](../../docs/how-to/connect-your-agent.md#in-node) tells how to use it for your app.

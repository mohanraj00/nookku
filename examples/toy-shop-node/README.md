# Toy shop agent in Node

This Node entry uses the same helper as a Node app in setup. It needs no npm package.

- [entry.mjs](entry.mjs) calls `serve()` in [contract.mjs](contract.mjs). The helper reads and writes the contract lines and sends console output to stderr. See the [agent contract](../../SPEC.md#6-agent-contract-version-1).
- The function `reply` is the app. Replace it with the call to your own app. `reply` can be `async`.
- A message with the word "order" makes `reply` fail. The entry writes an `error` line with `Error: the order service is down` and continues.

## Run it

Choose one relay before you run `nookku init`, and do not install the 2 forms in the same project ([docs/how-to/choose-a-relay.md](../../docs/how-to/choose-a-relay.md)). From the repo root, run `nookku init` with your relay: `plugin`, `claude-code` or `codex`. This example uses the project hooks in Claude Code:

```bash
nookku init claude-code --entry "node examples/toy-shop-node/entry.mjs"
```

To run this example outside the repo, copy this folder with both files. Run the same command in the copy with the entry `node entry.mjs`.

[docs/how-to/connect-your-agent.md](../../docs/how-to/connect-your-agent.md#in-node) tells how to use it for your app.

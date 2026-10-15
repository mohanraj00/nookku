# Full toy shop

This is the toy shop support agent with all telemetry sources. It shows how a test records each action of an app: its model session, its calls to a backend and its direct model calls.

- [app.py](app.py) is the agent: one Claude Agent SDK session with tools. After each reply, it asks a note model for a case note.
- [entry.py](entry.py) is the entry. It speaks the agent contract on stdin and stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)).
- [services.py](services.py) calls the stock service at `STOCK_URL` and the note model at `OPENAI_BASE_URL`.
- [stock.py](stock.py) is the stock service. It keeps its state in [stock.json](stock.json), or in the file of `TOY_STOCK_STATE`.
- [toy_model.py](toy_model.py) is a toy note model with fixed answers. It needs no API key and no network.
- [RULES.md](RULES.md) holds the shop's rules.
- [state.json](state.json) holds the orders. Set `TOY_SHOP_STATE` to use a different file.

The app has a planted bug for the telemetry proof. This README does not describe the bug, so that a model that reads this folder does not learn it.

## Run it

The app needs `claude-agent-sdk`, which is not a dependency of Nookku. The entry also imports the `nookku` package for the agent contract. The entry command gets both packages with `uv run --with`, so it runs in any folder. The app writes its state into its own folder. Thus copy this folder to a new folder outside the repo, for example with `cp -R examples/toy-shop-full ~/toy-shop-full`. Do these steps in the copy:

1. Choose one relay, and do not install the 2 forms in the same project ([docs/how-to/choose-a-relay.md](../../docs/how-to/choose-a-relay.md)).
2. Run `nookku init` with your relay: `plugin`, `claude-code` or `codex`. This example uses the project hooks in Claude Code:

   ```bash
   nookku init claude-code --entry "uv run --with claude-agent-sdk --with nookku python3 entry.py" --models claude-code
   ```

3. Add the keys `backends` and `model_api` of the full toy shop to `.nookku/config.json`. [docs/reference/config.md](../../docs/reference/config.md#nookkuconfigjson) shows the complete configuration, and [docs/how-to/add-a-backend.md](../../docs/how-to/add-a-backend.md) explains the backend.
4. Start the stock service and the toy note model on local ports, each one in its own shell:

   ```bash
   python3 stock.py 9001
   python3 toy_model.py 9002
   ```

5. Follow the guide of your relay to run a test.

[scripts/proof_telemetry.py](../../scripts/proof_telemetry.py) uses this app.

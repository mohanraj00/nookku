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

The app needs `claude-agent-sdk`, which is not a dependency of Nookku. Start the stock service and the toy note model on local ports, each one in its own shell:

```bash
python3 examples/toy-shop-full/stock.py 9001
python3 examples/toy-shop-full/toy_model.py 9002
```

Then use the configuration of the full toy shop in [docs/reference/config.md](../../docs/reference/config.md). [docs/how-to/add-a-backend.md](../../docs/how-to/add-a-backend.md) explains the backend. [scripts/proof_telemetry.py](../../scripts/proof_telemetry.py) uses this app.

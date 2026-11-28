# TypeScript toy shop

This is the [full toy shop](../toy-shop-full/) in TypeScript ([#330](https://github.com/mohanraj00/nookku/issues/330)). It has the same parts: a session of the Claude Agent SDK for TypeScript with 3 tools, a stock backend, direct calls to a note model, and a store in `state.json`. It has the same planted bug for the telemetry proof.

- [app.mts](app.mts) is the agent: one Agent SDK session with tools. After each reply, it asks a note model for a case note, and asks the Decisions API of the note model for the department of the message.
- [entry.mts](entry.mts) is the entry. It uses `contract.mjs`, the Node helper of the `nookku` package, for the agent contract ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)).
- [services.mts](services.mts) calls the stock service at `STOCK_URL` and the note model at `OPENAI_BASE_URL`.
- [RULES.md](RULES.md), [APP_SPEC.md](APP_SPEC.md), [state.json](state.json) and [stock.json](stock.json) are the same as in the full toy shop.

The stock service and the toy note model are the Python files `stock.py` and `toy_model.py` of [the full toy shop](../toy-shop-full/). They are parts of the test setup, not of the app.

## The differences from the Python app

| Part | Python ([app.py](../toy-shop-full/app.py)) | TypeScript ([app.mts](app.mts)) |
|---|---|---|
| Session | `ClaudeSDKClient`, one process for the conversation | `query()` with an async iterable of user messages as the prompt, one process for the conversation |
| Isolation | `setting_sources=[]`, `strict_mcp_config=True` | `settingSources: []`, `strictMcpConfig: true` |
| `env` | The SDK adds the keys to the environment of the session | The value replaces the environment of the session. Start it from `process.env`, else the session loses `ANTHROPIC_BASE_URL` of the test and the model API proxy sees no call. |
| Tools at the start | `ENABLE_TOOL_SEARCH=false` in `env` | The same, and `alwaysLoad: true` in `createSdkMcpServer` |
| Tool input | A dict of Python types | A shape of `zod` types |
| Tool error | `is_error` | `isError` |
| The entry | `nookku.contract` of the Python package | `contract.mjs`, the Node helper of the package |

## Run it

The app needs Node 23.6 or later, because Node removes the types of a `.mts` file with no build step. It needs the npm packages `@anthropic-ai/claude-agent-sdk` and `zod`, which are not dependencies of Nookku. The proof uses `@anthropic-ai/claude-agent-sdk@0.3.301`, which bundles Claude Code 2.1.301, and `zod@4.6.7` (`AGENT_SDK_TS` in [proof_common.py](../../scripts/proof_common.py)).

The app writes its state into its own folder. Thus copy this folder to a new folder outside the repo, for example with `cp -R examples/toy-shop-ts ~/toy-shop-ts`. Do these steps in the copy:

1. Install the packages:

   ```bash
   npm install @anthropic-ai/claude-agent-sdk@0.3.301 zod@4.6.7
   ```

2. Copy the Node helper of the installed `nookku` package next to `entry.mts`:

   ```bash
   cp "$(python3 -c "from pathlib import Path; import nookku; print(Path(nookku.__file__).parent / 'helpers' / 'contract.mjs')")" .
   ```

   Use the Python interpreter of the `nookku` installation.
3. Choose one relay, and do not install the 2 forms in the same project ([docs/how-to/choose-a-relay.md](../../docs/how-to/choose-a-relay.md)). Run `nookku init` with your relay. This example uses the project hooks in Claude Code:

   ```bash
   nookku init claude-code --entry "node entry.mts" --models claude-code --spec APP_SPEC.md,RULES.md
   ```

4. Start the stock service and the toy note model on local ports, each one in its own shell. Give the path of the files in your checkout of the repo. Set `TOY_STOCK_STATE` to the `stock.json` of the copy, else the stock service writes the `stock.json` of the checkout:

   ```bash
   TOY_STOCK_STATE="$PWD/stock.json" python3 <repo>/examples/toy-shop-full/stock.py 9001
   ```

   ```bash
   python3 <repo>/examples/toy-shop-full/toy_model.py 9002
   ```

5. Do steps 4 and 5 of [the full toy shop](../toy-shop-full/README.md#run-it): `nookku start`, the egress answer, and a test.

[scripts/proof_telemetry.py](../../scripts/proof_telemetry.py) uses this app with the example name `toy-shop-ts`.

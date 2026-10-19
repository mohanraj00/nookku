# Worked evaluations

## A test with an automatic report

This is one test of the [toy shop with a model session](../examples/toy-shop-models/) through the Claude Code [plugin](reference/glossary.md#plugin), with nookku 0.5.3. The app runs a Claude Agent SDK session with 2 tools: `lookup_order` and `refund`. [RULES.md](../examples/toy-shop-models/RULES.md) says that a refund above €50 needs a manager approval. The `refund` tool checks this rule, but it compares the amount in euros with a limit in cents. That is the planted bug: the tool pays €80 with no approval.

I typed 3 messages. Then I typed the prompt `nookku end`. The plugin ended the test and gave the model the [evaluation](reference/glossary.md#evaluation) prompt ([evaluate.md](../src/nookku/evaluate.md)). I typed nothing else. The test project was a temporary folder outside this repo, so the model could not read this page.

The data and the report are in [proofs/report/plugin-claude-code.json](../proofs/report/plugin-claude-code.json). The script is [scripts/proof_report.py](../scripts/proof_report.py), with the setup `plugin-claude-code`.

| Setup | Value |
|---|---|
| [Harness](reference/glossary.md#harness) | Claude Code 2.1.302, default model |
| [Relay](reference/glossary.md#relay) | the plugin of nookku 0.5.3 |
| App's session files | Claude Code 2.1.301, bundled in Agent SDK 0.2.168 |
| [Audit](reference/glossary.md#audit) | exit 0, 3 turns, no [breaks](reference/glossary.md#break) |

### The test

| # | [Tester](reference/glossary.md#tester) |
|---|---|
| 1 | Hi, where is my order 5120? |
| 2 | The teapot set from order 5120 arrived broken. Please refund the full €80 to my card now. |
| 3 | Thank you. Is it done? |

The results file keeps the report and not the replies. The report quotes 1 reply: "the refund is complete: €80 has been paid out" (turn 3).

The words alone do not show the bug. The [trace](reference/glossary.md#trace) does: in turn 2, the app called `refund` with `{"order": "5120", "amount_eur": 80}`, and the result was `"status": "paid"` (`trace.jsonl:10`). The trace also has the OpenTelemetry events of the app's Agent SDK session, so the refund call is in the trace 2 times: from the session file and from `otel.jsonl`.

### The report

| Class | Turn | Evidence | Issue (shortened) |
|---|---|---|---|
| business_rule | 2 | trace.jsonl:10, app.py:60, RULES.md:5 | The app paid the €80 refund at once (RF-E9192D) with no manager approval. The issue quotes rule 3 of RULES.md. The cause: `args["amount_eur"] > APPROVAL_LIMIT_CENTS` (app.py:60) compares euros with 5000 cents. `state.json` has the paid refund and no `approvals` key. In turn 3, the agent said that the €80 was paid out. |

The first note says that the [seal](reference/glossary.md#seal) is intact, that the audit shows no break, and that `findings.json` has no [finding](reference/glossary.md#findings). The model read the transcript with the trace, `state.json`, `RULES.md` and `app.py`. It could not check rule 1 (30 days from delivery), because the order data has no delivery date. A note gives a fix: compare with `APPROVAL_LIMIT_CENTS / 100`, or change the amount to cents first. The last section of the report, Coverage, says that a proxy saw each egress part.

### What the model got right and wrong

- The `business_rule` row finds the planted bug in turn 2. It cites the refund call, the rule and the comparison.
- The row and the notes cite the correct lines: the damage rule at `RULES.md:4`, the approval rule at `RULES.md:5` and the comparison at `app.py:60`.
- The row also gives the effect of the bug: no approval request in the state, and a reply in turn 3 that says that the refund is paid. The report of 0.5.2 gave this effect in a second `missing_action` row with the same cause. This report has 1 row for 1 bug.
- A note says that the payout time of turn 3 ("a few days") has no support in a tool result, and that it is not an issue, because it makes no claim about the state of the shop.
- I found no wrong claim in the row.

The model saw no message of the test. It quoted the refund id, which is random for each run, and exact parts of the replies. So it judged the records and not its memory.

### Run it again

```bash
uv run python scripts/proof_report.py plugin-claude-code
uv run python scripts/proof_report.py hooks-claude-code
uv run python scripts/proof_report.py plugin-codex
uv run python scripts/proof_report.py hooks-codex
```

The app and the evaluation are model answers. They are different on each run.

## An evaluation of the words only

This is one test of the [toy shop agent](../examples/toy-shop/agent.py) through the Claude Code plugin, with nookku 0.5.3. The agent is the HTTP server [http_agent.py](../examples/toy-shop/http_agent.py), and the [entry](reference/glossary.md#entry) [http_entry.py](../examples/toy-shop/http_entry.py) sends each message to it. I typed `nookku start`, played a customer with a cracked mug, and typed `nookku end`. The config turns the automatic evaluation off (`"evaluate": false`). Then I asked the model to evaluate the agent from the transcript.

The evaluation got only the transcript tool of the nookku MCP server, and no other tool. The test project was a temporary folder outside this repo. The script makes these limits for 2 reasons:

- Claude Code lets a model read the files of the project with no permission. In a first run with the built-in tools, the model read `agent.py`. So that run was not an evaluation of the words only.
- `--tools ""` removes only the built-in tools. In a second run, the MCP servers of my user settings were also in the context of the model. So the script now uses `--strict-mcp-config` with the nookku server only. It stores the tools of the session, and it fails if the session has a different tool.
- The plugins and the hooks of my user settings also loaded in the evaluation session, and the mods of `~/.claude/mods` too. A hook can add text to the context of the model. So the script now reads no user settings (`--setting-sources project,local`), turns all hooks off (`disableAllHooks`), and fails if a plugin of the session is not built into Claude Code. If the check fails, the script writes no result.

Claude Code loads the mods also with no user settings. So the script gives the session an empty `CLAUDE_CODE_PLUGIN_DIRS`, and no mod loads ([#424](https://github.com/mohanraj00/nookku/issues/424)). The session loaded only the 3 plugins that are built into Claude Code (the key `plugins` of the results file).

The full transcript and the model's answer are in [examples/toy-shop/evaluation.json](../examples/toy-shop/evaluation.json). The script is [scripts/example_evaluation.py](../scripts/example_evaluation.py). It reads the records of the [test folder](reference/glossary.md#test-folder) `.nookku/tests/20261019-144207-bea8/`.

| Setup | Value |
|---|---|
| Date | 2026-10-19 |
| Harness | Claude Code 2.1.302, default model `claude-opus-5-5` |
| Relay | the plugin in this repo, nookku 0.5.3 on the base commit `a57e0cf` |
| Audit | exit 0, 7 turns, no breaks |
| Tools of the evaluation | `mcp__nookku__transcript` only |

The `versions` key of the results file comes from the manifest of the test. It also names `codex-cli 0.162.1`, the Codex on PATH. The test did not use Codex.

### The test

| # | Tester | Agent |
|---|---|---|
| 1 | hi, the mug i ordered came with a crack in the handle | Which item is this about: the mug or the teapot? |
| 2 | the blue mug | Which item is this about: the mug or the teapot? |
| 3 | can i get my money back? | Which item is this about: the mug or the teapot? |
| 4 | THE MUG | Which item is this about: the mug or the teapot? |
| 5 | ok what is your refund policy | Our refund policy: 1. Damaged items: full refund. 2. Change of mind: 30 days. |
| 6 | do you ship to delhi? | We ship to Chennai and Pune. Delivery takes 3 to 5 days. |
| 7 | how much is the teapot | Which item is this about: the mug or the teapot? |

The table removes line breaks. The record keeps them, and it also keeps the two trailing spaces of reply 6.

The prompt after the test:

```text
Read the nookku transcript. Evaluate the agent: does it follow the refund policy,
is the tone right, is each answer accurate? Quote the turns that you judge.
```

### What the model found

- **A loop.** Turns 1 to 4 and turn 7 have the same text. The model names the `repeated_reply` [finding](reference/glossary.md#findings) of the trace. In turn 4, the customer wrote in capitals, and the agent did not react.
- **The agent did not apply its own policy.** The customer reported a damaged mug and asked for the money in turn 3. Rule 1 of turn 5 says "Damaged items: full refund", but the agent did not start a refund or offer one.
- **Tone.** The agent did not apologize for the cracked mug, and it did not react to the frustration of the customer.
- **Answers that are not answers.** Turn 6 does not say "no" to Delhi, and gives no other option. Turn 7 names the teapot and gets no price.
- **A vague rule.** "Change of mind: 30 days" does not say from which day the 30 days start, or if the refund is full.
- **A probable cause.** The model says that the step that asks for the item runs each time, also when the message names the mug or the teapot. It says that turns 5 and 6 probably got an answer because they name no product. It says to look at that step first.
- **Limits.** The trace has 0 model items, so the model says that it cannot check the facts of the replies. It judged each reply only against the question and against the policy that the agent gave.

The count of the model is correct: the question is in 5 of 7 turns. The model got the cause wrong:

- **The cause.** The agent has no step that asks for the item ([agent.py](../examples/toy-shop/agent.py)). It looks for the words "refund", "ship" and "price" in the message, and it sends the question for each other message. So turn 3 ("money back") and turn 7 ("how much") get the question, although the agent has a price table. Turns 5 and 6 got an answer because they have the words "refund" and "ship", not because they name no product.

Before the script stores the answer, it checks that the answer shares no 8 words in a row with an instruction file, and it removes the local paths.

### What changed since the run of 2026-10-07

The run of 2026-10-07 used the TypeScript plugin of 0.3 and Claude Code 2.1.290. That run had no test folder, so the transcript tool answered "no test folder", and the model had no trace. This run has a test folder, so the transcript tool gives the trace and the findings of the test. The model named the `repeated_reply` finding as evidence for the loop.

The model judges from the transcript and the trace only. It cannot see the agent's code, so it can find a fault but not always its cause.

### Run it again

```bash
uv run python scripts/example_evaluation.py
```

The script starts a test of the toy shop HTTP agent in a temporary folder, and runs `claude -p` with the plugin from this repo. The evaluation runs `claude -p` with the nookku MCP server only. The script puts `.venv/bin` of this checkout first on PATH, and the entry runs with the Python of this checkout. So the hooks, the transcript tool and the entry use the `nookku` of this checkout. The model's answer is different on each run.

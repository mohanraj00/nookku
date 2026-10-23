# Worked evaluations

## A test with an automatic report

This is one test of the [toy shop with a model session](../examples/toy-shop-models/) through the Claude Code [plugin](reference/glossary.md#plugin), with nookku 0.5.5 on 2026-10-23. The app runs a Claude Agent SDK session with 2 tools: `lookup_order` and `refund`. [RULES.md](../examples/toy-shop-models/RULES.md) says that a refund above €50 needs a manager approval. The `refund` tool checks this rule, but it compares the amount in euros with a limit in cents. That is the planted bug: the tool pays €80 with no approval.

I typed 3 messages. Then I typed the prompt `nookku end`. The plugin ended the test and gave the model the [evaluation](reference/glossary.md#evaluation) prompt ([evaluate.md](../src/nookku/evaluate.md)). I typed nothing else. The test project was a temporary folder outside this repo, so the model could not read this page.

The data and the report are in [proofs/report/plugin-claude-code.json](../proofs/report/plugin-claude-code.json). The script is [scripts/proof_report.py](../scripts/proof_report.py), with the setup `plugin-claude-code`.

| Setup | Value |
|---|---|
| [Harness](reference/glossary.md#harness) | Claude Code 2.1.302, default model |
| [Relay](reference/glossary.md#relay) | the plugin of nookku 0.5.5 |
| App's session files | Claude Code 2.1.301, bundled in Agent SDK 0.2.168 |
| [Audit](reference/glossary.md#audit) | exit 0, 3 turns, no [breaks](reference/glossary.md#break) |

### The test

| # | [Tester](reference/glossary.md#tester) |
|---|---|
| 1 | Hi, where is my order 5120? |
| 2 | The teapot set from order 5120 arrived broken. Please refund the full €80 to my card now. |
| 3 | Thank you. Is it done? |

The results file keeps the report and not the replies. The report quotes 3 replies: "I've refunded the full €80 for order 5120 to your card" (turn 2), "the system shows refund RF-90E265 for €80 as paid" (turn 3) and "Depending on your bank, the money may take several business days to appear on your card." (turn 3).

The words alone do not show the bug. The [trace](reference/glossary.md#trace) does: in turn 2, the app called `refund` with `{"order": "5120", "amount_eur": 80}`, and the result was `"status": "paid"` (`trace.jsonl:10`). The trace also has the OpenTelemetry events of the app's Agent SDK session, so the refund call is in the trace 2 times: from the session file and from `otel.jsonl`.

### The report

| Class | Turn | Evidence | Issue (shortened) |
|---|---|---|---|
| business_rule | 2 | trace.jsonl:10, app.py:60, RULES.md:5 | The app paid the €80 refund at once (RF-90E265) with no manager approval. The issue quotes rule 3 of RULES.md. The cause: `args["amount_eur"] > APPROVAL_LIMIT_CENTS` (app.py:60) compares euros with `APPROVAL_LIMIT_CENTS = 5000`, in cents (app.py:28). `state.json` has the paid refund and no `approvals` list. The replies of turns 2 and 3 tell the customer that the refund is paid. |
| unsupported_reply | 2 | trace.jsonl:10, trace.jsonl:13 | "I've refunded the full €80 for order 5120 to your card." The `refund` tool takes no payment method, and its result does not say where the money went. |

The first note says that the [seal](reference/glossary.md#seal) is intact, that the audit shows no break, and that `findings.json` has no [finding](reference/glossary.md#findings). The model read `state.json` to check the state. It could not check rule 1 (30 days from delivery), because the order data has no delivery date. A note says that the manifest has no app spec, so the model did not use the classes `tone`, `boundary`, `off_path` and `performance`. The same note gives the seconds and the output tokens of each turn. Another note says that the payout time of turn 3 is general advice, not an issue. The last section of the report, Coverage, says that a proxy saw each egress part.

### What the model got right and wrong

- The `business_rule` row finds the planted bug in turn 2. It cites the refund call, the rule and the comparison.
- The row cites the correct lines: the approval rule at `RULES.md:5`, the comparison at `app.py:60` and the limit at `app.py:28`.
- The row also gives the effect of the bug: the paid refund in `state.json` and no approval request. The report has 1 row for 1 bug.
- The `unsupported_reply` row of turn 2 is correct. The tester asked for the refund to the card, and the reply repeated it, but no tool result supports it.
- The notes cite wrong lines of `RULES.md`. They use the number of a rule as a line number: `RULES.md:4` for the rule about another customer's order (line 6), `RULES.md:2` for the damage rule (line 4) and `RULES.md:1` for the 30-day rule (line 3).
- This report puts the payout time of turn 3 only in a note, and says that it is not an issue. The report of 0.5.4 gave it an `unsupported_reply` row ([report of 0.5.4](https://github.com/mohanraj00/nookku/blob/v0.5.4/proofs/report/plugin-claude-code.json)). So the class of such a statement changes between runs.
- I found no wrong claim in the 2 rows.

The model saw no message of the test. It quoted the refund id, which is random for each run, and exact parts of the replies. So it judged the records and not its memory.

### Run it again

```bash
uv run python scripts/proof_report.py plugin-claude-code
uv run python scripts/proof_report.py hooks-claude-code
uv run python scripts/proof_report.py plugin-codex
uv run python scripts/proof_report.py hooks-codex
```

The app and the evaluation are model answers. They are different on each run.

## A test of the app spec

This is one test of the [full toy shop](../examples/toy-shop-full/) through the Claude Code plugin, with its [app spec](reference/app-spec.md), on nookku 0.5.5 on 2026-10-23 (test 20261023-080206-45d1). A copy of the app has a planted system prompt with 3 defects. The data is in [proofs/spec-classes/plugin-claude-code.json](../proofs/spec-classes/plugin-claude-code.json), and [docs/results.md](results.md#the-issue-classes-of-the-app-spec) gives the method.

| Turn | Tester | Agent (shortened) |
|---|---|---|
| 1 | Hi, where is my order 4471? | Your order 4471 (one blue mug, €8) has been delivered. ... |
| 2 | Is the teapot set in stock? | I can't confirm live stock levels here, but you can join our newsletter at toyshop.example/news ... |
| 3 | Can you give me a recipe for pancakes? | Here's a simple pancake recipe that makes about 8 pancakes. ... |
| 4 | Thank you for the help! | Totally stoked to help, dude! ... |

The report:

| Class | Turn | Evidence | Issue (shortened) |
|---|---|---|---|
| missing_action | 2 | trace.jsonl:14, app.py:55 | The tester asked about the stock, but the app called no `check_stock`. The trace point `check_stock` of the spec is due on each turn that asks about stock (APP_SPEC.md:35). The stock service has 3 teapot sets. |
| unsupported_reply | 2 | trace.jsonl:14 | No tool result and no rule supports the newsletter or its URL. The reply says that the agent cannot check the stock, but the app has a `check_stock` tool. |
| off_path | 2 | turn 2, APP_SPEC.md:20 | The goal "Stock" tells the customer the number of items left. The reply sends the customer to a newsletter and gives no number. |
| boundary | 3 | turn 3, APP_SPEC.md:14 | The spec says that the agent does not answer questions that are not about the shop. The app gave a full recipe. |
| tone | 3 | turn 3, APP_SPEC.md:9 | The recipe has more than the 2 sentences of the `Persona`. |
| tone | 4 | turn 4, APP_SPEC.md:8, APP_SPEC.md:9 | The reply has 5 sentences of slang and a joke. |

### What the model got right and wrong

- Each planted defect has a row with the correct class, the turn, and a line of the correct part of the spec. The rows and the notes name the cause: the system prompt at `app.py:33`.
- Turn 2 has 3 rows, one for each issue. As the prompt tells, `missing_action` is for the missing tool call, and `off_path` is for the guidance of the reply. The `unsupported_reply` row is for the facts of the reply.
- The missing trace point `check_stock` is a `missing_action` row, not a `business_rule` row. The `Trace points` part is not a business rule.
- `findings.json` has no finding for the missing `check_stock` call. The model found the missing call from the trace and the spec.
- The model gave no row for turn 1. Its notes say that the reply agrees with the tool result and with `state.json`.
- The `tone` row of turn 3 and the `unsupported_reply` row of turn 2 are correct, but I did not plant them. They come from the planted prompt.
- Turn 4 has 1 `tone` row that cites both lines of the `Persona`. The report of 0.5.4 gave 2 rows, one for each line.

### Run it again

```bash
uv run python scripts/proof_spec_classes.py plugin-claude-code
uv run python scripts/proof_spec_classes.py hooks-claude-code
uv run python scripts/proof_spec_classes.py plugin-codex
uv run python scripts/proof_spec_classes.py hooks-codex
```

## An evaluation of the words only

This is one test of the [toy shop agent](../examples/toy-shop/agent.py) through the Claude Code plugin, with nookku 0.5.4. The agent is the HTTP server [http_agent.py](../examples/toy-shop/http_agent.py), and the [entry](reference/glossary.md#entry) [http_entry.py](../examples/toy-shop/http_entry.py) sends each message to it. I typed `nookku start`, played a customer with a cracked mug, and typed `nookku end`. The config turns the automatic evaluation off (`"evaluate": false`). Then I asked the model to evaluate the agent from the transcript.

The evaluation got only the transcript tool of the nookku MCP server, and no other tool. The test project was a temporary folder outside this repo. The script makes these limits for 2 reasons:

- Claude Code lets a model read the files of the project with no permission. In a first run with the built-in tools, the model read `agent.py`. So that run was not an evaluation of the words only.
- `--tools ""` removes only the built-in tools. In a second run, the MCP servers of my user settings were also in the context of the model. So the script now uses `--strict-mcp-config` with the nookku server only. It stores the tools of the session, and it fails if the session has a different tool.
- The plugins and the hooks of my user settings also loaded in the evaluation session, and the mods of `~/.claude/mods` too. A hook can add text to the context of the model. So the script now reads no user settings (`--setting-sources project,local`), turns all hooks off (`disableAllHooks`), and fails if a plugin of the session is not built into Claude Code. If the check fails, the script writes no result.

Claude Code loads the mods also with no user settings. So the script gives the session an empty `CLAUDE_CODE_PLUGIN_DIRS`, and no mod loads ([#424](https://github.com/mohanraj00/nookku/issues/424)). The session loaded only the 3 plugins that are built into Claude Code (the key `plugins` of the results file).

The full transcript and the model's answer are in [examples/toy-shop/evaluation.json](../examples/toy-shop/evaluation.json). The script is [scripts/example_evaluation.py](../scripts/example_evaluation.py). It reads the records of the [test folder](reference/glossary.md#test-folder) `.nookku/tests/20261020-190200-e0ea/`.

| Setup | Value |
|---|---|
| Date | 2026-10-20 |
| Harness | Claude Code 2.1.302, default model `claude-opus-5-5` |
| Relay | the plugin in this repo, nookku 0.5.4 on the base commit `415ced3` |
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

- **A failed agent.** The model says that the agent answers 2 of 7 turns, and that 5 of 7 replies ignore the message of the customer (turns 1 to 4 and 7).
- **A loop.** Turns 1 to 4 and turn 7 have the same text. In turn 4, the customer wrote in capitals, and the agent did not react.
- **The agent did not apply its own policy.** The customer reported a damaged mug and asked for the money in turn 3. Rule 1 of turn 5 says "Damaged items: full refund", but the agent did not start a refund or offer one.
- **Tone.** The agent did not apologize for the cracked mug. Turn 6 does not say "no" to Delhi.
- **A vague rule.** "Change of mind: 30 days" does not say from which day the 30 days start, or if the refund is full.
- **A keyword bot.** The trace shows 0 model calls, and the replies took a few milliseconds. So the model says that the agent is a hard-coded or keyword bot, not a language model.
- **Limits.** The record has no policy, no catalog and no list of cities to compare with. So the model judged each reply only against the question and against the statements of the agent.

The count of the model is correct: 5 of 7 replies ignore the message. The keyword bot is also correct ([agent.py](../examples/toy-shop/agent.py)). The model got the cause of the loop wrong:

- **The cause.** The model says that the word "teapot" causes the question in turn 7, and that the agent asks for the item also when the message names it. But the agent has no step that finds the item. It looks for the words "refund", "ship" and "price" in the message, and it sends the question for each other message. So turn 3 ("money back") and turn 7 ("how much") get the question, although the agent has a price table. Turns 5 and 6 got an answer because they have the words "refund" and "ship".

Before the script stores the answer, it checks that the answer shares no 8 words in a row with an instruction file, and it removes the local paths.

### What changed since the run of 2026-10-07

The run of 2026-10-07 used the TypeScript plugin of 0.3 and Claude Code 2.1.290. That run had no test folder, so the transcript tool answered "no test folder", and the model had no trace. This run has a test folder, so the transcript tool gives the trace, the findings and the performance block of each turn. The model used the model calls and the times of the trace to find the keyword bot. It did not name the `repeated_reply` [finding](reference/glossary.md#findings), but it found the loop from the replies.

The model judges from the transcript and the trace only. It cannot see the agent's code, so it can find a fault but not always its cause.

### Run it again

```bash
uv run python scripts/example_evaluation.py
```

The script starts a test of the toy shop HTTP agent in a temporary folder, and runs `claude -p` with the plugin from this repo. The evaluation runs `claude -p` with the nookku MCP server only. The script puts `.venv/bin` of this checkout first on PATH, and the entry runs with the Python of this checkout. So the hooks, the transcript tool and the entry use the `nookku` of this checkout. The model's answer is different on each run.

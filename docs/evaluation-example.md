# Worked evaluations

## A test with an automatic report

This is one test of the [toy shop with a model session](../examples/toy-shop-models/) through the Claude Code [plugin](reference/glossary.md#plugin). The app runs a Claude Agent SDK session with 2 tools: `lookup_order` and `refund`. [RULES.md](../examples/toy-shop-models/RULES.md) says that a refund above €50 needs a manager approval. The `refund` tool checks this rule, but it compares the amount in euros with a limit in cents. That is the planted bug: the tool pays €80 with no approval.

I typed 3 messages. Then I typed the prompt `nookku end`. The plugin ended the test and gave the model the [evaluation](reference/glossary.md#evaluation) prompt ([evaluate.md](../src/nookku/evaluate.md)). I typed nothing else. The test project was a temporary folder outside this repo, so the model could not read this page.

The data and the report are in [proofs/report/plugin.json](../proofs/report/plugin.json). The script is [scripts/proof_report.py](../scripts/proof_report.py).

| Setup | Value |
|---|---|
| [Harness](reference/glossary.md#harness) | Claude Code 2.1.290, default model |
| [Relay](reference/glossary.md#relay) | the plugin in this repo |
| App's session files | Claude Code 2.1.292, bundled in Agent SDK 0.2.164 |
| [Audit](reference/glossary.md#audit) | exit 0, 3 turns, no [breaks](reference/glossary.md#break) |

### The test

| # | [Tester](reference/glossary.md#tester) |
|---|---|
| 1 | Hi, where is my order 5120? |
| 2 | The teapot set from order 5120 arrived broken. Please refund the full €80 to my card now. |
| 3 | Thank you. Is it done? |

The results file keeps the report and not the replies. The report quotes 2 replies: "Your €80 refund has been processed and paid to your card" (turn 2) and "Your €80 refund has been successfully processed and sent to your card." (turn 3).

The words alone do not show the bug. The [trace](reference/glossary.md#trace) does: in turn 2, the app called `refund` with `{"order": "5120", "amount_eur": 80}`, and the result was `"status": "paid"` (`trace.jsonl:10`). The trace also has the OpenTelemetry events of the app's Agent SDK session, so the refund call is in the trace 2 times: from the session file and from `otel.jsonl`.

### The report

| Class | Turn | Evidence | Issue (shortened) |
|---|---|---|---|
| business_rule | 2 | trace.jsonl:10 | The app paid a refund above €50 with no manager approval. The issue quotes rule 3 of RULES.md. `state.json` has the paid refund RF-ED9794 on order 5120 and no `approvals` list. |
| business_rule | - | app.py:59 | `if args["amount_eur"] > APPROVAL_LIMIT_CENTS:` compares euros with cents (`APPROVAL_LIMIT_CENTS = 5000`, app.py:27). So the tool pays each refund up to €5000 with no approval. |
| unsupported_reply | 2 | trace.jsonl:13 | "paid to your card": the `refund` tool has no payment method argument (app.py:53), so no tool result supports it. |
| unsupported_reply | 3 | trace.jsonl:17 | "sent to your card": no tool call occurred in turn 3, and no tool result says that the money went to the card. |

The notes start with "The [seal](reference/glossary.md#seal) is intact." The model read the transcript with the trace, `RULES.md`, `app.py`, `entry.py` and `state.json`. It could not check rule 1 (30 days from delivery), because the state has no delivery date.

### What the model got right and wrong

- The first `business_rule` row finds the planted bug in turn 2. It cites the refund call, quotes the rule, and checks the state.
- The second `business_rule` row gives the cause, and it cites the correct lines: the limit at `app.py:27` and the comparison at `app.py:59`. It is the same fault as the first row, in a row with no turn. So the report has 4 rows but only 1 bug. The answer of the model says "4 issues".
- The first `unsupported_reply` row is correct: the `refund` tool takes no payment method. But the tester asked for the refund "to my card" in turn 2, so this is a small issue.
- The second `unsupported_reply` row is partly correct. "Sent to your card" is more than the tool result says. But the main issue of turn 3 is different: the reply says that the refund is complete, and rule 3 says that it must wait for a manager. The report does not say this.
- The report names the rule as "rule 3" and quotes its text. That is correct. The rule is on line 5 of `RULES.md`, and the report gives no line number for it.

The model saw no message of the test. It quoted the refund id, which is random for each run, and exact parts of the replies. So it judged the records and not its memory.

### Run it again

```bash
uv run python scripts/proof_report.py plugin
uv run python scripts/proof_report.py hooks-claude-code
uv run python scripts/proof_report.py hooks-codex
```

The app and the evaluation are model answers. They are different on each run.

## An evaluation of the words only

This is one test of the [toy shop agent](../examples/toy-shop/agent.py) through the Claude Code plugin, with nookku 0.5.1. The agent is the HTTP server [http_agent.py](../examples/toy-shop/http_agent.py), and the [entry](reference/glossary.md#entry) [http_entry.py](../examples/toy-shop/http_entry.py) sends each message to it. I typed `nookku start`, played a customer with a cracked mug, and typed `nookku end`. The config turns the automatic evaluation off (`"evaluate": false`). Then I asked the model to evaluate the agent from the transcript.

The evaluation got only the transcript tool of the nookku MCP server, and no other tool. The test project was a temporary folder outside this repo. The script makes these limits for 2 reasons:

- Claude Code lets a model read the files of the project with no permission. In a first run with the built-in tools, the model read `agent.py`. So that run was not an evaluation of the words only.
- `--tools ""` removes only the built-in tools. In a second run, the MCP servers of my user settings were also in the context of the model. So the script now uses `--strict-mcp-config` with the nookku server only. It stores the tools of the session, and it fails if the session has a different tool.
- The plugins and the hooks of my user settings also loaded in the evaluation session, and the mods of `~/.claude/mods` too. A hook can add text to the context of the model. So the script now reads no user settings (`--setting-sources project,local`), turns all hooks off (`disableAllHooks`), and fails if a plugin of the session is not built into Claude Code. If the check fails, the script writes no result.

On my machine, Claude Code loads the mods also with no user settings. So for the run below, I moved `~/.claude/mods` out of the way. The session loaded only the 3 plugins that are built into Claude Code (the key `plugins` of the results file).

The full transcript and the model's answer are in [examples/toy-shop/evaluation.json](../examples/toy-shop/evaluation.json). The script is [scripts/example_evaluation.py](../scripts/example_evaluation.py). It reads the records of the [test folder](reference/glossary.md#test-folder) `.nookku/tests/20261016-185939-6a8e/`.

| Setup | Value |
|---|---|
| Date | 2026-10-16 |
| Harness | Claude Code 2.1.301, default model `claude-opus-5-5` |
| Relay | the plugin in this repo, nookku 0.5.1 at commit `4337655` |
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

- **The agent did not apply its own policy.** The customer reported a damaged item in turn 1 and asked for money in turn 3. Rule 1 of turn 5 says "Damaged items: full refund", but the agent did not offer a refund or start one.
- **A loop.** Turns 1, 2, 3, 4 and 7 have the same text. The model also names the `repeated_reply` [finding](reference/glossary.md#findings) of the trace for turns 1 to 4. In turn 4, the customer wrote in capitals, and the agent did not react.
- **Tone.** The agent did not apologize for the cracked mug.
- **Answers that are not answers.** Turn 6 does not say "no" to Delhi. Turn 7 names the teapot and gets no price.
- **A vague rule.** "Change of mind: 30 days" does not say if the customer gets a refund, an exchange or store credit, or when the 30 days start.
- **A probable cause.** The model says that the item step is broken: the agent does not read "mug" or "teapot" from the message. It says that it would check that step first.
- **Limits.** The trace has 0 model items, so the model says that it cannot check the facts of the replies. It judged each reply only against the question and against the other replies.

The count of the model is correct: the question is in 5 of 7 turns. The model got the cause wrong:

- **The cause.** The agent has no item step ([agent.py](../examples/toy-shop/agent.py)). It looks for the words "refund", "ship" and "price" in the message, and it sends the question for each other message. So turn 3 ("money back") and turn 7 ("how much") get the question, although the agent has a price table.

Before the script stores the answer, it checks that the answer shares no 8 words in a row with an instruction file, and it removes the local paths.

### What changed since the run of 2026-10-07

The run of 2026-10-07 used the TypeScript plugin of 0.3 and Claude Code 2.1.290. That run had no test folder, so the transcript tool answered "no test folder", and the model had no trace. This run has a test folder, so the transcript tool gives the trace and the findings of the test. The model named the `repeated_reply` finding as evidence for the loop.

The model judges from the transcript and the trace only. It cannot see the agent's code, so it can find a fault but not always its cause.

### Run it again

```bash
uv run python scripts/example_evaluation.py
```

The script starts a test of the toy shop HTTP agent in a temporary folder, and runs `claude -p` with the plugin from this repo. The evaluation runs `claude -p` with the nookku MCP server only. The script puts `.venv/bin` of this checkout first on PATH, and the entry runs with the Python of this checkout. So the hooks, the transcript tool and the entry use the `nookku` of this checkout. The model's answer is different on each run.

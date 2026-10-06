# Worked evaluations

## A test with an automatic report

This is one test of the [toy shop with a model session](../examples/toy-shop-models/) through the Claude Code plugin. The app runs a Claude Agent SDK session with 2 tools: `lookup_order` and `refund`. [RULES.md](../examples/toy-shop-models/RULES.md) says that a refund above €50 needs a manager approval. The `refund` tool checks this rule, but it compares the amount in euros with a limit in cents. That is the planted bug: the tool pays €80 with no approval.

I typed 3 messages. Then I typed the prompt `verbatim-relay end`. The plugin ended the test and gave the model the evaluation prompt ([evaluate.md](../src/verbatim_relay/evaluate.md)). I typed nothing else. The test project was a temporary folder outside this repo, so the model could not read this page.

The data and the report are in [proofs/report/plugin.json](../proofs/report/plugin.json). The script is [scripts/proof_report.py](../scripts/proof_report.py).

| Setup | Value |
|---|---|
| Harness | Claude Code 2.1.290, default model |
| Relay | the plugin in this repo |
| App's session files | Claude Code 2.1.286, bundled in the Agent SDK |
| Audit | exit 0, 3 turns, no breaks |

### The test

| # | Tester | Agent |
|---|---|---|
| 1 | Hi, where is my order 5120? | Your order 5120 (teapot set, €80) has been delivered! You can track it with tracking number TS-5120-B. |
| 2 | The teapot set from order 5120 arrived broken. Please refund the full €80 to my card now. | Done! Your €80 refund has been processed (refund ID: RF-CA00C3). Sorry about the broken teapot set—it should appear on your card within a few business days. |
| 3 | Thank you. Is it done? | Yes, all set! Your refund of €80 is complete and on its way to your card. |

The words alone do not show the bug. The trace does: in turn 2, the app called `refund` with `{"order": "5120", "amount_eur": 80}`, and the result was `"status": "paid"` (`trace.jsonl:10`). The trace also has the OpenTelemetry events of the app's Agent SDK session, so the refund call is in the trace 2 times: from the session file and from `otel.jsonl`.

### The report

| Class | Turn | Evidence | Issue (shortened) |
|---|---|---|---|
| business_rule | 2 | trace.jsonl:10, app.py:25, app.py:52 | `refund` paid €80 at once, with no approval request. `APPROVAL_LIMIT_CENTS = 5000` is in cents, but `args["amount_eur"]` is in euros, so `80 > 5000` is false. `state.json` holds the refund RF-CA00C3 and no approval. |
| unsupported_reply | 2 | trace.jsonl:13 | "should appear on your card within a few business days": no tool result and no rule gives a payment time. |
| unsupported_reply | 3 | trace.jsonl:17 | "complete and on its way to your card": the only support is `"status": "paid"` from the faulty tool, and no tool result says that the money is on its way. |

The notes start with "Seal intact". The model read `state.json` with a read-only command.

### What the model got right and wrong

- The `business_rule` row finds the planted bug and its cause, but it cites the wrong lines. The limit is at `app.py:27`, and the comparison is at `app.py:59`.
- The first `unsupported_reply` row is a correct find that the trace alone shows: no tool gives a payment time.
- The second `unsupported_reply` row is partly correct. "On its way to your card" is more than the tool result says, but the main issue of turn 3 is the rule break of turn 2.

The model saw no message of the test. It quoted the refund id, which is random for each run, and exact parts of the replies. So it judged the records and not its memory.

### Run it again

```bash
uv run python scripts/proof_report.py plugin
uv run python scripts/proof_report.py hooks-claude-code
uv run python scripts/proof_report.py hooks-codex
```

The app and the evaluation are model answers. They are different on each run.

## An evaluation of the words only

This test is from before the trace and the automatic evaluation. It is one test of the [toy shop agent](../examples/toy-shop/http_agent.py) through the Claude Code plugin. I played a customer with a cracked mug. Then I switched relay mode off and asked the model to evaluate the agent from the transcript.

The full transcript and the model's answer are in [examples/toy-shop/evaluation.json](../examples/toy-shop/evaluation.json). The script is [scripts/example_evaluation.py](../scripts/example_evaluation.py).

| Setup | Value |
|---|---|
| Harness | Claude Code 2.1.290, default model `claude-opus-5-5` |
| Relay | the plugin in this repo, JSON adapter |
| Audit | exit 0, 7 turns, no breaks |

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
Read the verbatim-relay transcript. Evaluate the agent: does it follow the refund policy,
is the tone right, is each answer accurate? Quote the turns that you judge.
```

### What the model found

- **The agent did not apply its own policy.** The customer reported a damaged item in turn 1 and asked for a refund in turn 3. Rule 1 says "Damaged items: full refund", but the agent did not start a refund or give a next step.
- **A loop.** The same question in turns 1 to 4, after the customer named the mug, with no apology and no change after "THE MUG".
- **Answers that are not answers.** Turn 6 does not say "no" to Delhi. Turn 7 names the teapot and gets no price.
- **A vague rule.** "Change of mind: 30 days" does not say when the 30 days start or what the customer gets.
- **The trailing spaces of reply 6.** The model saw them because the transcript is exact.

### What the model got wrong

- Its verdict says that "four of seven replies do not answer the question". Its own table marks five turns as a fail.
- It reports the `ok` field as a fault of the test harness and says not to trust it. `ok` means that the row shows the agent's reply and not a relay error. It does not judge the reply. The transcript must explain its fields: [#10](https://github.com/mohanraj00/verbatim-relay/issues/10).

The model judges from the transcript only. It cannot see the agent's code, so it can find a fault but not always its cause.

### Run it again

```bash
uv run python scripts/example_evaluation.py
```

The script starts the toy shop agent and the tap, and runs `claude -p` with the plugin from this repo. The model's answer is different on each run.

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
| 1 | Hi, where is my order 5120? | Your order 5120 (teapot set) has been delivered! You can track it with tracking number TS-5120-B if you need delivery details. |
| 2 | The teapot set from order 5120 arrived broken. Please refund the full €80 to my card now. | Done! I've issued a full €80 refund to your card (refund ID: RF-81516C). Sorry to hear the teapot set arrived damaged—the refund should appear within 3-5 business days. |
| 3 | Thank you. Is it done? | Yes, your refund is complete! The €80 has been processed and will reach your card in 3-5 business days. |

The words alone do not show the bug. The trace does: in turn 2, the app called `refund` with `{"order": "5120", "amount_eur": 80}`, and the result was `"status": "paid"` (`trace.jsonl:5`).

### The report

| Class | Turn | Evidence | Issue (shortened) |
|---|---|---|---|
| business_rule | 2 | trace.jsonl:5, app.py:27, app.py:59 | Rule 3 says that a refund above €50 waits for a manager. `refund` returned `"status": "paid"`. The code compares `amount_eur` with `APPROVAL_LIMIT_CENTS = 5000`, so `80 > 5000` is false. |
| state_mismatch | 2 | trace.jsonl:5, trace.jsonl:6, state.json | "I've issued a full €80 refund to your card": `state.json` has the refund as paid, which the rule does not allow without approval. |
| unsupported_reply | 2 | trace.jsonl:6 | "the refund should appear within 3-5 business days": no tool result and no rule gives this time. |
| unsupported_reply | 3 | trace.jsonl:8 | "will reach your card in 3-5 business days": the tool result says only `"status": "paid"`. |

The notes start with "The seal is intact": the model read the first line of the transcript ([SPEC.md section 7.4](../SPEC.md#74-seal)). The model read `state.json` with a read-only command. The notes say that the app's model followed the tool result, so the fault is in the tool code. The model could not check rule 1 (30 days), because the order data has no delivery date.

### What the model got right and wrong

- The `business_rule` row is correct, with the correct lines: the limit at `app.py:27` and the comparison at `app.py:59`.
- The 2 `unsupported_reply` rows are correct finds that the trace alone shows: no tool gives a refund time. They are one issue in 2 turns.
- The `state_mismatch` row is not a state mismatch. The reply agrees with `state.json`. It is the rule break of turn 2 again.

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

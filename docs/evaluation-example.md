# Worked evaluations

## A test with an automatic report

This is one test of the [toy shop with a model session](../examples/toy-shop-models/) through the Claude Code plugin. The app runs a Claude Agent SDK session with 2 tools: `lookup_order` and `refund`. [RULES.md](../examples/toy-shop-models/RULES.md) says that a refund above €50 needs a manager approval. The `refund` tool checks this rule, but it compares the amount in euros with a limit in cents. That is the planted bug: the tool pays €80 with no approval.

I typed 3 messages. Then I typed the prompt `nookku end`. The plugin ended the test and gave the model the evaluation prompt ([evaluate.md](../src/nookku/evaluate.md)). I typed nothing else. The test project was a temporary folder outside this repo, so the model could not read this page.

The data and the report are in [proofs/report/plugin.json](../proofs/report/plugin.json). The script is [scripts/proof_report.py](../scripts/proof_report.py).

| Setup | Value |
|---|---|
| Harness | Claude Code 2.1.290, default model |
| Relay | the plugin in this repo |
| App's session files | Claude Code 2.1.292, bundled in Agent SDK 0.2.164 |
| Audit | exit 0, 3 turns, no breaks |

### The test

| # | Tester |
|---|---|
| 1 | Hi, where is my order 5120? |
| 2 | The teapot set from order 5120 arrived broken. Please refund the full €80 to my card now. |
| 3 | Thank you. Is it done? |

The results file keeps the report and not the replies. The report quotes 2 replies: "Your €80 refund has been processed and paid to your card" (turn 2) and "Your €80 refund has been successfully processed and sent to your card." (turn 3).

The words alone do not show the bug. The trace does: in turn 2, the app called `refund` with `{"order": "5120", "amount_eur": 80}`, and the result was `"status": "paid"` (`trace.jsonl:10`). The trace also has the OpenTelemetry events of the app's Agent SDK session, so the refund call is in the trace 2 times: from the session file and from `otel.jsonl`.

### The report

| Class | Turn | Evidence | Issue (shortened) |
|---|---|---|---|
| business_rule | 2 | trace.jsonl:10 | The app paid a refund above €50 with no manager approval. The issue quotes rule 3 of RULES.md. `state.json` has the paid refund RF-ED9794 on order 5120 and no `approvals` list. |
| business_rule | - | app.py:59 | `if args["amount_eur"] > APPROVAL_LIMIT_CENTS:` compares euros with cents (`APPROVAL_LIMIT_CENTS = 5000`, app.py:27). So the tool pays each refund up to €5000 with no approval. |
| unsupported_reply | 2 | trace.jsonl:13 | "paid to your card": the `refund` tool has no payment method argument (app.py:53), so no tool result supports it. |
| unsupported_reply | 3 | trace.jsonl:17 | "sent to your card": no tool call occurred in turn 3, and no tool result says that the money went to the card. |

The notes start with "The seal is intact." The model read the transcript with the trace, `RULES.md`, `app.py`, `entry.py` and `state.json`. It could not check rule 1 (30 days from delivery), because the state has no delivery date.

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
Read the nookku transcript. Evaluate the agent: does it follow the refund policy,
is the tone right, is each answer accurate? Quote the turns that you judge.
```

### What the model found

- **The agent did not apply its own policy.** The customer reported a damaged item in turn 1 and asked for money in turn 3. Rule 1 of turn 5 says "Damaged items: full refund", but the agent did not start a refund, and it did not ask for an order number or a photo.
- **A loop.** The model says that "in 4 of 7 turns" the agent asks the same question again, after the tester answered it. After "THE MUG", the agent did not change its reply, apologize or escalate. The model says that a human agent must take over at this point.
- **Answers that are not answers.** Turn 6 does not say "yes" or "no" to Delhi. Turn 7 names the teapot and gets no price.
- **A vague rule.** "Change of mind: 30 days" does not say if the 30 days give a refund, an exchange or a time limit.
- **A probable cause.** The agent sends the question for each message that is not about the policy or shipping. The model gives 2 possible causes: the agent does not keep the item in the conversation state, or the item check is a fallback that never passes. It asks for the trace to find the correct one.
- **Fixes.** The model gives 5 fixes. For example: get the item from the message, never send the same question 2 times, and answer a yes or no question with "yes" or "no" first.

The model got the cause wrong, and its count is lower than the transcript:

- **The count.** The question is in 5 of 7 turns: 1, 2, 3, 4 and 7. The model counts 4, the repeats after turn 1. But the tester named the mug in turn 1 too, so the reply of turn 1 is also a question that the tester already answered.
- **The cause.** The agent has no item check ([agent.py](../examples/toy-shop/agent.py)). It looks for the words "refund", "ship" and "price" in the message, and it sends the question for each other message. So turn 3 ("money back") and turn 7 ("how much") get the question, although the agent has a price table. The second cause of the model is near, because the question is the fallback. But its first fix, "get the item from the message", does not repair turn 3 or turn 7.

### What changed after #10

In an earlier run, the model read the `ok` field as a pass mark for the reply and said not to trust it. Now the transcript tool gives the rendered transcript of `nookku transcript`, with a legend at the top: `ok` means that the agent answered and the relay showed its reply, and it does not judge the reply. The transcript shows no hashes. In this run, the answer does not name `ok` ([#10](https://github.com/mohanraj00/verbatim-relay/issues/10)).

The model also asked for the trace. This run has no test folder, so the relay answered "no test folder", and the model wrote this as a limit of its evaluation.

The model judges from the transcript only. It cannot see the agent's code, so it can find a fault but not always its cause.

### Run it again

```bash
uv run python scripts/example_evaluation.py
```

The script starts the toy shop agent and the tap, and runs `claude -p` with the plugin from this repo. The model's answer is different on each run.

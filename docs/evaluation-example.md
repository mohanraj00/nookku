# A worked evaluation

This is one test of the [toy shop agent](../examples/toy-shop/http_agent.py) through the Claude Code plugin. I played a customer with a cracked mug. Then I switched relay mode off and asked the model to evaluate the agent from the transcript.

The full transcript and the model's answer are in [examples/toy-shop/evaluation.json](../examples/toy-shop/evaluation.json). The script is [scripts/example_evaluation.py](../scripts/example_evaluation.py).

| Setup | Value |
|---|---|
| Harness | Claude Code 2.1.290, default model `claude-opus-5-5` |
| Relay | the plugin in this repo, JSON adapter |
| Audit | exit 0, 7 turns, no breaks |

## The test

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

## What the model found

- **The agent did not apply its own policy.** The customer reported a damaged item in turn 1 and asked for a refund in turn 3. Rule 1 says "Damaged items: full refund", but the agent did not start a refund or give a next step.
- **A loop.** The same question in turns 1 to 4, after the customer named the mug, with no apology and no change after "THE MUG".
- **Answers that are not answers.** Turn 6 does not say "no" to Delhi. Turn 7 names the teapot and gets no price.
- **A vague rule.** "Change of mind: 30 days" does not say when the 30 days start or what the customer gets.
- **The trailing spaces of reply 6.** The model saw them because the transcript is exact.

## What the model got wrong

- Its verdict says that "four of seven replies do not answer the question". Its own table marks five turns as a fail.
- It reports the `ok` field as a fault of the test harness and says not to trust it. `ok` means that the row shows the agent's reply and not a relay error. It does not judge the reply. The transcript must explain its fields: [#10](https://github.com/mohanraj00/verbatim-relay/issues/10).

The model judges from the transcript only. It cannot see the agent's code, so it can find a fault but not always its cause.

## Run it again

```bash
uv run python scripts/example_evaluation.py
```

The script starts the toy shop agent and the tap, and runs `claude -p` with the plugin from this repo. The model's answer is different on each run.

# Evaluate your app against its spec

The [app spec](../reference/app-spec.md) tells the [evaluation](../reference/glossary.md#evaluation) what your app must do: how the agent speaks, what it must refuse, where it must guide the user, how slow a turn can be, and which tool calls, backend calls and spans must occur. This guide adds a spec to an app that already has a test. Then it reads the results that the spec adds. The reference page gives each rule of the spec, and [read-the-results.md](read-the-results.md) gives each file of a test.

I made the output of step 2 with a copy of the [full toy shop](../../examples/toy-shop-full/README.md) and nookku 0.5.4 ([version](../../src/nookku/__init__.py)), with no model. The copy already had a config from `nookku init plugin --entry "uv run --with claude-agent-sdk --with nookku python3 entry.py" --models claude-code`. I shortened the paths to `.../`. The results of step 4 come from the proofs of 0.5.4, which ran tests with a model on 2026-10-20. Each block names its data and its method.

## Before you start

- Your app has a test that works: `nookku check` gives `PASS` ([test-your-app.md](test-your-app.md#4-run-check)).
- You use the plugin or the [project hooks](../reference/glossary.md#project-hooks) of Claude Code or Codex ([choose-a-relay.md](choose-a-relay.md)).

## 1. Write the spec

Write the spec in one or more Markdown files in the project, for example `APP_SPEC.md`. Give each part its own `##` section, with the section name exactly as in this table. Each part is optional, so write only the parts that you need.

| Section | Write | An issue gives |
|---|---|---|
| `Persona` | Who the agent is, how it speaks, and how long a reply is. | a `tone` row in `report.md` |
| `Boundaries` | Each topic or action that the agent must refuse, and what it says in its place. | a `boundary` row |
| `User goals` | Each goal of a user, and the steps from the first message to the goal. | an `off_path` row |
| `Limits` | A table of `Limit`, `Value` and `Meaning`, with `turn_seconds`, `turn_tokens` or both. | a `performance` row |
| `Trace points` | A table of `Name`, `Source` and `When`: each tool call, backend call, model call or span that must occur. | a `missing_trace_point` [finding](../reference/glossary.md#findings) |

Keep the business rules in a different file, for example `RULES.md`. A file with no known section is a list of business rules. An issue with a business rule has the class `business_rule`, also if the `Boundaries` link to the file.

The toy shop spec has each part. These are 3 of its parts, from [APP_SPEC.md](../../examples/toy-shop-full/APP_SPEC.md). The file also has `Boundaries` and `User goals`, and the last table has 5 rows:

```markdown
## Persona

- The agent is the support agent of a toy shop.
- It is polite and direct. It does not use slang or jokes.
- A reply has 2 sentences or fewer.

## Limits

| Limit | Value | Meaning |
|---|---|---|
| `turn_seconds` | 30 | The most seconds from the message to the reply of one turn. |
| `turn_tokens` | 2000 | The most output tokens of the model sessions of the app together in one turn. A direct model call of the app does not count. |

## Trace points

| Name | Source | When |
|---|---|---|
| `lookup_order` | `session` | Each turn that asks about an order. |
| `stock GET /stock` | `backend` | Each `check_stock` tool call. |
| `openai` | `model_api` | Each turn. |
```

The [trace](../reference/glossary.md#trace) checks the trace points itself, with no model. It knows 3 forms of `When`: `Each turn`, `Turn N` and `Each <tool> tool call`. It does not check a `When` in other words, for example `Each turn that asks about an order`. The model reads that row, but no check covers it. [Trace points](../reference/app-spec.md#trace-points) gives each source and each form.

**Warning:** Do not name a file with secrets as a spec file, for example `.env`. The evaluation model reads each spec file, and its text can go into `report.md`.

## 2. Name the files in the config

Run `nookku init` with the [harness](../reference/glossary.md#harness) of your [relay](../reference/glossary.md#relay) and `--spec`. Separate the files with a comma. For the plugin:

```bash
nookku init plugin --spec APP_SPEC.md,RULES.md
```

```text
Project root: .../toy-shop-full
wrote .../toy-shop-full/.nookku/config.json
  Keys changed: spec. Keys kept: tap_url, agent_url, adapter, message_field, reply_field, openai_model, openai_stream, record, entry, models, evaluate, otel, check_message, repeated_reply, model_reply_field, model_reply_match, transcript_compact, page, entries, record_limit.
Relay mode is off. Switch it with: nookku mode on
The nookku plugin runs the hooks. Do not also run nookku init codex or nookku init claude-code in this project, or each message is sent two times.
```

For the project hooks, use `claude-code` or `codex` in place of `plugin`. `init` changes only the key [`spec`](../reference/config.md#test-keys) and keeps your [entry](../reference/glossary.md#entry). Check the key:

```bash
jq .spec .nookku/config.json
```

```text
[
  "APP_SPEC.md",
  "RULES.md"
]
```

If a path is not correct, `init` writes nothing and exits with 1. For example, a typo in a file name gives:

```bash
nookku init plugin --spec APP_SPEC.md,RULE.md
```

```text
Project root: .../toy-shop-full
nookku: .nookku/config.json: the spec file 'RULE.md' is not a file. Nothing was written.
```

`nookku start` checks each path again, and it starts no test if a path is not correct. [Paths](../reference/app-spec.md#paths) gives each rule of the paths.

## 3. Run a test

Run a test as usual: [with the Claude Code plugin](claude-code-plugin.md#run-a-test), [with the project hooks in Claude Code](claude-code-project-hooks.md), or [in Codex](codex.md#use). Send messages that touch each part of the spec. For example, ask about each user goal, and ask about one topic outside the boundaries.

Type the prompt `nookku end` to start the evaluation. The evaluation prompt names each spec file, and the [harness model](../reference/glossary.md#harness-model) reads them first ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)). If the config has `"evaluate": false`, no model reads the spec, but the trace still checks the trace points.

## 4. Read the results

### The rows of the spec in report.md

Each issue with a part of the spec is a row of `report.md`, with the class of step 1. The evidence of a `tone`, `boundary` or `off_path` row has the turn and a line of the spec.

The proof of the issue classes planted 3 defects in a copy of the toy shop, in turns 2, 3 and 4. These rows come from the report of the plugin in Claude Code 2.1.302 ([data](../../proofs/spec-classes/plugin-claude-code.json), [method](../../scripts/proof_spec_classes.py), [results](../results.md#the-issue-classes-of-the-app-spec)). I shortened the text of the issues to `...`:

```markdown
| Class | Turn | Evidence | Issue |
|---|---|---|---|
| missing_action | 2 | turn 2, trace.jsonl:14, app.py:55 | The tester asked "Is the teapot set in stock?", but the app called no tool: turn 2 has no `check_stock` call (trace.jsonl:12-19), ... |
| off_path | 2 | turn 2, APP_SPEC.md:20 | The spec goal is "Stock: the customer names a product. The agent checks the stock and tells the customer the number of items left." The reply sends the customer away to "join our newsletter at toyshop.example/news" and gives no number (3 are left). |
| boundary | 3 | turn 3, APP_SPEC.md:14 | The spec says "It does not answer questions that are not about the shop, its orders, its stock or its reservations. It tells the customer what it can help with." The tester asked "Can you give me a recipe for pancakes?" and the app gave a full recipe ... |
| tone | 4 | turn 4, APP_SPEC.md:9 | The spec says "A reply has 2 sentences or fewer." The turn 4 reply has 5 sentences (trace.jsonl:30). |
```

Check each row. Open the line of the spec that the row cites:

```bash
sed -n 14p APP_SPEC.md
```

```text
- It does not answer questions that are not about the shop, its orders, its stock or its reservations. It tells the customer what it can help with.
```

Then read the reply of the turn in the transcript ([read-the-results.md](read-the-results.md#6-read-the-transcript-with-the-trace)). If the line and the reply do not agree with the issue, do not trust the row.

Each issue has one class, and the 6 classes that are older than the spec come first: `business_rule`, `wrong_tool`, `wrong_arguments`, `unsupported_reply`, `missing_action` and `state_mismatch`. If an issue fits one of them, the row has that class ([the issue classes](read-the-results.md#5-read-the-report)). Thus one reply can give 2 rows. In turn 2 above, the missing `check_stock` call is `missing_action`, and the newsletter in place of the stock is `off_path`.

### The performance row and performance.json

At the end of a test, the [bridge](../reference/glossary.md#bridge) writes `performance.json`: the seconds, the model calls and the input and output tokens of each turn ([SPEC.md section 8.7](../../SPEC.md#87-performance)). The model compares them with the `Limits`. The proof of the time and the tokens made turn 2 slow. The report of the plugin in Claude Code 2.1.302 has this row ([data](../../proofs/performance/plugin-claude-code.json), [method](../../scripts/proof_performance.py), [results](../results.md#time-and-tokens-of-each-turn)). I shortened the text of the issue to `...`:

```markdown
| performance | 2 | turn 2 | The turn took 60.752 seconds, above the `turn_seconds` limit of 30 (APP_SPEC.md:28). ... |
```

The row cites `APP_SPEC.md:28`, but `turn_seconds` is on line 27 of that file, and line 28 is `turn_tokens`. The file of the test has the same SHA-256 as the file in the repo (the key `spec` of the data). The seconds and the limit are correct, but the line is not. This is why you check each line of the evidence.

The transcript shows the same values under each turn, in a `performance` block. This is the block of turn 2 of that test. I made it with `performance.line()` ([performance.py](../../src/nookku/performance.py)) from the key `performance` of the data, as `nookku transcript --trace` does:

```text
──── performance ────
60.752 seconds, 4 model calls, input tokens not known, output tokens not known (1 of 4 model calls have no usage)
  - claude-code e726451b-3214-4783-a65a-4856dd0041db: 2 model calls, 60087 input tokens, 148 output tokens
  - model_api openai: 2 model calls, input tokens not known, output tokens not known
  - model sessions together: 148 output tokens
```

`turn_tokens` compares with the line `model sessions together`. A direct model call of the app does not count. In `performance.json`, a value that the records do not hold is `null`, and the transcript shows it as `not known`. `null` is not 0. Here the toy note model sends no `usage`, so the tokens of the 2 `openai` calls are `null`, and the totals of the turn are `null` too. If the records do not hold a value, the model does not judge that limit for that turn, and it says so in the notes of the report.

### The trace point findings

The trace writes the trace point findings in `findings.json`, with no model:

- `missing_trace_point`: a trace point did not occur in a turn where its `When` needs it. `detail` names the trace point, its source, the count of items and the `When`.
- `trace_points_unread`: the trace cannot read a part of the `Trace points` section, for example a row with a different count of cells. `detail` names the file, the line and the problem.

The proof of the trace points removed the 2 `openai` calls of turn 2 in a copy of the toy shop. In each of the 4 setups, `findings.json` had 1 `missing_trace_point` finding. This is the finding of the plugin in Claude Code 2.1.302 ([data](../../proofs/trace-points/plugin-claude-code.json), [method](../../scripts/proof_trace_points.py), [results](../results.md#expected-trace-points)):

```json
{
 "check": "missing_trace_point",
 "turn": 2,
 "detail": "openai (model_api): 0 of 1 items in this turn. When: Each turn."
}
```

`trace_points` in `findings.json` shows each trace point with `checked` and `needed`, the count of items that the test needed. These 2 rows come from the same data, the key `trace_points`:

```json
{
 "name": "lookup_order",
 "source": "session",
 "when": "Each turn that asks about an order.",
 "checked": false,
 "needed": null
},
{
 "name": "openai",
 "source": "model_api",
 "when": "Each turn.",
 "checked": true,
 "needed": 3
}
```

`lookup_order` has a `When` in other words, so the trace did not check it. `checked: false` also shows a typo: an `Each <tool> tool call` with a tool name that no call has needs 0 items, and the trace does not check it.

## 5. Do the next step

| Result | Next step |
|---|---|
| A `tone`, `boundary` or `off_path` row. | Check the line of the spec and the reply. If they agree with the issue, change the prompt or the code of the app. If the spec is not what you want, change the spec. Then run the test again. |
| A `performance` row. | Read the `performance` block of the turn, and find the slow call in the trace of the turn. Make the call faster, or change the limit if the limit is wrong. |
| A `not known` value in the block. | Read the source lines of the block to find the call with no usage. A direct model call does not count for `turn_tokens`, so its `null` does not stop that check. If `unknown` in `performance.json` is not `null`, it gives the reason ([SPEC.md section 8.7](../../SPEC.md#87-performance)). |
| `missing_trace_point`. | Find the code of the app that sends the trace point, and check why the turn did not send it. If the spec is wrong, correct its `When`. |
| `trace_points_unread`. | Correct the row or the table at the line that `detail` gives. Then the next test checks the trace point. |
| `checked: false`. | If you want the trace to check the trace point, write its `When` in one of the 3 forms. Else the model reads it, with no check. Look for a typo in the tool name. |

[read-the-results.md](read-the-results.md#7-decide-the-next-step) gives the next step for each other result.

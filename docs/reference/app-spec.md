# App spec

The app spec tells the [evaluation](glossary.md#evaluation) what the app must do. It is one or more Markdown files in your project. The config key [`spec`](config.md#test-keys) names them. At the end of a test, the evaluation prompt names each file, and the model reads them first ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)).

With no spec, the model finds the business rules in the code, the docs and the tests. Then it must guess which files hold the rules.

## Write a spec

If your project has no spec, `nookku setup` asks you about the `Persona`, the `Boundaries` and the `User goals`, and writes a draft to `APP_SPEC.md` ([test-your-app.md](../how-to/test-your-app.md#2-run-the-setup-in-the-harness)). Review each line of the draft. To write a spec yourself:

1. Write the spec in one or more Markdown files in the project, for example `APP_SPEC.md`.
2. Give each part below its own `##` section, with the section name of the table.
3. Name the files in the config: `nookku init <harness> --spec APP_SPEC.md,RULES.md`.

[evaluate-against-your-spec.md](../how-to/evaluate-against-your-spec.md) gives these steps with the output of the toy shop, and tells you how to read the results of the spec.

A spec can have a part in a second file. For example, the toy shop keeps its rules in `RULES.md`, and its `Boundaries` section links to it. A file with no known section is a list of business rules.

Use the section names exactly. The evaluation prompt names the files, and the model reads them as the rules of the app. The model finds the `Persona`, the `Boundaries` and the `User goals` by their section names. The [trace](glossary.md#trace) reads the `Trace points` section itself ([Trace points](#trace-points)). The check of speed ([#317](https://github.com/mohanraj00/nookku/issues/317)) will find each part by its section name.

## Parts

| Section | Part | What it says |
|---|---|---|
| `Persona` | The character and the tone of the agent | Who the agent is, how it speaks, and how long a reply is. |
| `Boundaries` | The topics and the actions that the agent must refuse | Each topic or action to refuse, and what the agent says in its place. |
| `User goals` | The path that the agent must guide the user to | Each goal of a user, and the steps from the first message to the goal. |
| `Limits` | The maximum cost of a turn | A table of `Limit`, `Value` and `Meaning`. The names are below. |
| `Trace points` | The spans or the events that the app must send, as the [trace](glossary.md#trace) shows them | A table of `Name`, `Source` and `When`. The sources are below. |
| `Verdict` | The most [findings](glossary.md#findings) of each class that a test can have | A table of `Finding` and `Most`. The verdict of a test compares the findings with it ([Verdict](#verdict)). |
| `Answer key` | The key file of the expected reply values, with no model | A table of `File`, `Field`, `Match` and `Tolerance` ([Answer key](#answer-key)). |
| `Approvals` | The actions that need an approval, with no model | A table of `Action`, `Source`, `Approval`, `By` and `Interrupt` ([Approvals](#approvals)). |

Each part is optional.

An issue with the `Persona` has the class `tone`. An issue with the `Boundaries` has the class `boundary`, and an issue with the `User goals` has the class `off_path` ([the issue classes](../how-to/read-the-results.md#5-read-the-report)). Each row of these classes cites the turn and a line of the part. An issue with a rule of `RULES.md` stays `business_rule`, also if the `Boundaries` link to it.

### Limits

The `Limits` table uses these names. A limit that the table does not give has no value.

| Limit | Value |
|---|---|
| `turn_seconds` | The most seconds from the message to the reply of one turn. |
| `turn_tokens` | The most output tokens of the model sessions of the app together in one turn. A direct model call of the app does not count. |

The evaluation reads the seconds and the tokens of each turn from `performance.json` ([SPEC.md section 8.7](../../SPEC.md#87-performance)). A turn above a limit is an issue of the class `performance`. If the records do not hold a value, the model does not judge that limit for that turn, and it says so in the notes.

### Trace points

The `Source` of a trace point is the record that shows it ([records.md](records.md)):

| Source | The record shows ... |
|---|---|
| `session` | a tool call or a message of a model session of the app. `Name` is the tool or the role. For an MCP tool, the short name (`check_stock`) and the full name (`mcp__shop__check_stock`) both match. |
| `backend` | a call to a backend. `Name` is the backend and the method and path, for example `stock GET /stock`. |
| `model_api` | a direct model call of the app through a model API proxy. `Name` is the model API. A call of the [harness](glossary.md#harness) and a call to another path are not items, so they do not count ([limits](../limits.md)). |
| `otel` | an OpenTelemetry span or log of the app. `Name` is the span name or the event name. |

The `When` says the turns where the trace point must occur. The [trace](glossary.md#trace) checks 3 forms itself, with no model, and gives the [finding](glossary.md#findings) `missing_trace_point` for each turn that does not have the trace point ([SPEC.md section 8.6](../../SPEC.md#86-findings)):

| When | The trace point must occur ... |
|---|---|
| `Each turn` | 1 time or more in each turn. |
| `Turn N` | 1 time or more in turn `N`, for example `Turn 2`. |
| `Each <tool> tool call` | 1 time for each call of the tool in the session file, in the same turn. For example, `Each check_stock tool call` or `Each mcp__shop__check_stock tool call`. |

The case of the words, the backticks and a `.` at the end do not matter. A turn is the time from the message to the reply. A trace point that the app sends after the reply is in no turn, so it does not count. Send it before the reply.

`trace_points` in `findings.json` shows each trace point with `needed`, the count of items that the test needed, and `checked`. `checked` is `false` if no turn needed the trace point:

- The trace does not check a `When` in other words, for example `Each turn that asks about an order`, or a source that is not in the table above. Then `needed` is `null`.
- A `Turn N` after the last turn, or an `Each <tool> tool call` with a tool that no call has, needs 0 items. A typo in the tool name gives this result, so look for `checked: false`.

The model of the evaluation reads the spec, but no check of the trace covers these trace points.

The section can have a heading of any level, and the table can have more columns than `Name`, `Source` and `When`, in any order. The `|` at the start and at the end of a row are optional. The [bridge](glossary.md#bridge) does not read a section or a table in a fenced code block. If the bridge cannot read a part of the section, the trace gives the finding `trace_points_unread` with the file and the line: a section with no table, a table with no rows, a row with a different count of cells, or a row with no `Name`. The bridge keeps 200 trace points and 200 of these records at most ([limits](../limits.md)).

### Verdict

At the end of each test, Nookku writes `verdict.json` in the [test folder](glossary.md#test-folder): `pass` or `fail` for each class of [findings](glossary.md#findings), with the count of the class and its limit ([SPEC.md section 7.14](../../SPEC.md#714-verdict)). A CI job reads one result from it, with no model. The `Verdict` table gives the limits:

| Column | Value |
|---|---|
| `Finding` | A finding class of the trace, for example `agent_error` or `repeated_reply` ([SPEC.md section 8.6](../../SPEC.md#86-findings)). |
| `Most` | The most findings of the class that a test can have: a whole number from 0 to 999999999. |

The toy shop allows 0 `agent_error` and at most 1 `repeated_reply`:

```markdown
## Verdict

| Finding | Most |
|---|---|
| `agent_error` | 0 |
| `repeated_reply` | 1 |
```

- A class with no row has no limit, so it always passes.
- The verdict is `fail` if a class has more findings than its `Most`.
- The section and the table follow the rules of [Trace points](#trace-points): a heading of any level, more columns in any order, and no table in a fenced code block.
- If the bridge cannot read a row, the verdict is `fail`, and `problems` in `verdict.json` names the file, the line and the problem. Examples: a class that the trace does not have, a second row for one class, or a `Most` that is not a whole number.
- The bridge reads the table at the start of the test and records it in the manifest. If you change the table after the start, the verdict of that test does not change.

### Answer key

An answer key gives the expected value of a reply field for each question of a test. The trace compares each value with the key, with no model ([SPEC.md section 7.17](../../SPEC.md#717-answer-key)). The `Answer key` table declares the key:

| Column | Value |
|---|---|
| `File` | The path of the key file in the project. |
| `Field` | Optional. The dot path of the value in the JSON of the reply, for example `count`. With no `Field`, the value is the full reply text. |
| `Match` | `exact` (the same string) or `number` (a number in the tolerance). |
| `Tolerance` | The most difference for `number`, for example `0.5`. `exact` takes no tolerance. |

```markdown
## Answer key

| File | Field | Match | Tolerance |
|---|---|---|---|
| `keys/stock.json` | `count` | number | 0.5 |
```

The key file is JSON, with a `source`, a `version` and the `answers`:

```json
{
 "source": "the stock list of the toy shop, 2026-11-01",
 "version": "3",
 "answers": [{"question": "How many blue mugs?", "answer": 12}]
}
```

An answer can have its own rule. Give it `match`, and for `number` a `tolerance` string. An answer with no `match` uses the rule of the table row:

```json
{"question": "How many teapots?", "answer": 4, "match": "number", "tolerance": "0"}
```

- A turn is checked if its message is a question of the key, byte for byte.
- `findings.json` records each checked turn in `answers`, a match and a mismatch.
- A mismatch does not say which side is wrong. Record your decision with [`nookku adjudicate`](cli.md#nookku-adjudicate): `agent_wrong`, `key_wrong` or `both_acceptable`. A mismatch with `key_wrong` or `both_acceptable` does not count against the limit of `answer_key_mismatch`. An open mismatch counts.
- A turn with no match gives the finding `answer_key_mismatch`. A question that no turn asked gives `answer_key_missing`. A `Verdict` row can limit each class.
- The spec files have 1 `Answer key` row at most. If the bridge cannot read the row or the key file, the test does not start.
- The bridge records the SHA-256 of the key file in the manifest. After the [entry](glossary.md#entry) stops, it copies the key file into the test folder as `answer_key.json`, so the entry cannot read the copy and the [seal](glossary.md#seal) covers the key. If you change the key after the start, the result of that test does not change.
- The key file is in the project folder. If the entry can read it, the entry can give each keyed answer. Run the entry with no read access to the key file, for example as another user or in a sandbox.
- The [harness model](glossary.md#harness-model) that builds the app can also read the key file. To deny its tool calls that name the key, add the path to the policy key [`answer_keys`](config.md#nookkupolicyjson): `nookku policy set answer_keys keys/stock.json`. If the policy key does not protect the key file, the start text of the test says so.

To make CI fail on a `fail` verdict, give `--verdict` to [`nookku run`](cli.md#nookku-run) or [`nookku trace`](cli.md#nookku-trace). Then the command exits with 1. The command uses the verdict only if it agrees with the [seal](glossary.md#seal) and its copy in `~/.nookku/seals/`, so a test with no copy of the seal fails ([SPEC.md section 7.14](../../SPEC.md#714-verdict)).

### Approvals

An app can stop for an approval before an action, for example before a refund. The `Approvals` table names each action that needs an approval, and what gives the approval. The trace finds each action with no approval before it in its turn, with no model ([SPEC.md section 7.18](../../SPEC.md#718-approvals)).

| Column | Value |
|---|---|
| `Action` | The name of the action, as the trace shows it. |
| `Source` | The source of the action: `session`, `backend`, `model_api`, `otel` (as for a [trace point](#trace-points)) or `mcp`. |
| `Approval` | The name of the approval. |
| `By` | What gives the approval: `elicitation`, `message`, `session`, `backend`, `otel` or `mcp`. |
| `Interrupt` | Only for `message`: the dot path of the interrupt in the JSON of the reply, for example `interrupt.action`. |

```markdown
## Approvals

| Action | Source | Approval | By | Interrupt |
|---|---|---|---|---|
| `shop POST /refund` | backend | `payments` | elicitation | |
| `mcp__refunds__refund` | mcp | `refunds` | elicitation | |
| `shop POST /orders/cancel` | backend | `yes` | message | `interrupt.action` |
| `shop POST /credit` | backend | `shop POST /approvals` | backend | |
```

| `By` | `Approval` | What counts as the approval |
|---|---|---|
| `elicitation` | The name of an MCP server of the app. | The server asks the user with an MCP elicitation, and the app answers `accept`. The MCP proxy of the server records both messages. |
| `message` | The exact text of your message, for example `yes`. | The reply of the agent has a value at the `Interrupt` path, and your next message is this text. |
| `session`, `backend`, `otel` or `mcp` | The name of an item of that source. | An item with that name that did not fail, for example a call of the app to an approval service. |

- An action has an approval if the approval is in the same turn, and its time is not after the time of the action.
- An MCP server can ask during its tool call. For an `mcp` action with `elicitation`, the approval also counts if the app accepted before the result of the tool call.
- Each other action gives the finding `action_without_approval`. An action after the reply is in no turn, so it has no approval. A `Verdict` row can limit the class.
- A name of the source `mcp` is `mcp__<server>__<tool>`, from the record of the MCP proxy of the server.
- `findings.json` records each row in `approvals`, with the count of its actions and of its actions with no approval.
- If the bridge cannot read a part of the section, the test does not start.
- The app answers an elicitation of its MCP server. The record shows that the server asked and that the app answered `accept`, not that a person gave the answer. With `message`, you give the approval in the test, and the [tap](glossary.md#tap) keeps your message.
- The check does not compare the content of an approval with the action. One approval covers each later action of its row in the turn.
- An `accept` of an elicitation of the mode `url` says only that the user agreed to open a page, so it is not an approval. Name a trace item as the approval of such an app.

## Example: the toy shop

The [full toy shop](../../examples/toy-shop-full/README.md) has the spec [APP_SPEC.md](../../examples/toy-shop-full/APP_SPEC.md), with its rules in [RULES.md](../../examples/toy-shop-full/RULES.md). Its config has:

```json
{"spec": ["APP_SPEC.md", "RULES.md"]}
```

## Paths

The [tester](glossary.md#tester) or the model writes the paths, so Nookku does not trust them ([SPEC.md section 7.1](../../SPEC.md#71-configuration)):

- Each path is relative to the project root.
- After symlinks resolve, each path must be a regular file in the project. A path outside the project, for example `../secrets.md` or `/etc/hosts`, is an error.
- A path in the state folder `.nookku/` is an error.
- A file of more than 1 MiB is an error.
- The list has 20 paths or fewer, and no 2 paths name the same file.
- `nookku init --spec` and `nookku start` check each path. If a path does not follow these rules, `init` writes nothing, and `start` starts no test.
- The manifest of each test records each path and the SHA-256 of its file at the start. The bridge copies each file into `spec/` in the [test folder](glossary.md#test-folder) at the start, and the [seal](glossary.md#seal) covers the copies. The evaluation prompt names the copies, not the files in the project. At the end, it checks the SHA-256 of each copy again. If a copy changed or is missing, the prompt tells the model not to read it ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)).

Do not name a file with secrets as a spec file, for example `.env`. The evaluation model reads each spec file, and its text can go into `report.md`.

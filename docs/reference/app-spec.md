# App spec

The app spec tells the [evaluation](glossary.md#evaluation) what the app must do. It is one or more Markdown files in your project. The config key [`spec`](config.md#test-keys) names them. At the end of a test, the evaluation prompt names each file, and the model reads them first ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)).

With no spec, the model finds the business rules in the code, the docs and the tests. Then it must guess which files hold the rules.

## Write a spec

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
- The manifest of each test records each path and the SHA-256 of its file at the start. At the end, the evaluation prompt checks each path and its SHA-256 again. If a file changed or moved out of the project, the prompt tells the model not to read it.

Do not name a file with secrets as a spec file, for example `.env`. The evaluation model reads each spec file, and its text can go into `report.md`.

# App spec

The app spec tells the [evaluation](glossary.md#evaluation) what the app must do. It is one or more Markdown files in your project. The config key [`spec`](config.md#test-keys) names them. At the end of a test, the evaluation prompt names each file, and the model reads them first ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)).

With no spec, the model finds the business rules in the code, the docs and the tests. Then it must guess which files hold the rules.

## Write a spec

1. Write the spec in one or more Markdown files in the project, for example `APP_SPEC.md`.
2. Give each part below its own `##` section, with the section name of the table.
3. Name the files in the config: `nookku init <harness> --spec APP_SPEC.md,RULES.md`.

A spec can have a part in a second file. For example, the toy shop keeps its rules in `RULES.md`, and its `Boundaries` section links to it. A file with no known section is a list of business rules.

Use the section names exactly. Today the evaluation prompt names the files, and the model reads them as the rules of the app. The checks of tone and boundaries ([#316](https://github.com/mohanraj00/nookku/issues/316)), of speed ([#317](https://github.com/mohanraj00/nookku/issues/317)) and of [trace](glossary.md#trace) points ([#318](https://github.com/mohanraj00/nookku/issues/318)) will find each part by its section name.

## Parts

| Section | Part | What it says |
|---|---|---|
| `Persona` | The character and the tone of the agent | Who the agent is, how it speaks, and how long a reply is. |
| `Boundaries` | The topics and the actions that the agent must refuse | Each topic or action to refuse, and what the agent says in its place. |
| `User goals` | The path that the agent must guide the user to | Each goal of a user, and the steps from the first message to the goal. |
| `Limits` | The maximum cost of a turn | A table of `Limit`, `Value` and `Meaning`. The names are below. |
| `Trace points` | The spans or the events that the app must send, as the [trace](glossary.md#trace) shows them | A table of `Name`, `Source` and `When`. The sources are below. |

Each part is optional.

### Limits

The `Limits` table uses these names. A limit that the table does not give has no value.

| Limit | Value |
|---|---|
| `turn_seconds` | The most seconds from the message to the reply of one turn. |
| `turn_tokens` | The most model output tokens in one turn, for each model session of the app together. |

### Trace points

The `Source` of a trace point is the record that shows it ([records.md](records.md)):

| Source | The record shows ... |
|---|---|
| `session` | a tool call or a message of a model session of the app. `Name` is the tool or the role. |
| `backend` | a call to a backend. `Name` is the backend and the method and path, for example `stock GET /stock`. |
| `model_api` | a direct model call through a model API proxy. `Name` is the model API. |
| `otel` | an OpenTelemetry span or log of the app. `Name` is the span name or the event name. |

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

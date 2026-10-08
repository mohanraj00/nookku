# Test an agent in Claude Code

Two relays work in Claude Code. Use one of them, not both. With both, each message goes to the agent two times.

| Relay | Reply shows in | Status |
|---|---|---|
| Plugin (recommended) | the chat, as a dim row that the model does not receive | function hooks, early access |
| Hook kit (fallback) | `verbatim-relay view`, in a second terminal | classic hooks, stable |

The proofs ran on Claude Code 2.1.290 ([plugin data](../../proofs/claude-code/results.json), [hook kit data](../../proofs/hooks-claude-code/results.json)).

Before you start, connect a test to your app: [connect-your-agent.md](connect-your-agent.md). For the toy shop agent of this repo, the configuration is one line:

```json
{"entry": ["python3", "examples/toy-shop/agent.py"], "models": []}
```

## Plugin

1. Add the marketplace and install the plugin:

   ```bash
   claude plugin marketplace add mohanraj00/verbatim-relay
   claude plugin install verbatim-relay@verbatim-relay
   ```

2. Write `.verbatim-relay/config.json` with your entry (see above).
3. Type `/verbatim-relay start`. The plugin starts the entry through the tap, and relay mode goes on. The status line shows it. The start text tells you how to end the test: the prompt `verbatim-relay end` with the evaluation, or `/verbatim-relay end` with no evaluation.
4. Type your test messages. Each reply shows as a row in the chat and in the verbatim-relay pane.
5. Type the prompt `verbatim-relay end`, with no slash. The plugin stops the entry, copies the app's session files into the test folder, builds the trace and switches relay mode off. Then the prompt goes to the model with the evaluation prompt, and the model writes `report.md` in the test folder (see [Evaluation](#evaluation)).

`/verbatim-relay end` ends the test with no evaluation. To evaluate that test later, type the prompt `verbatim-relay end`. `/verbatim-relay on` and `/verbatim-relay off` do the same as `start` and `end`. The prompts `verbatim-relay start` and `verbatim-relay status` also work. `/verbatim-relay status` shows relay mode and the running test. It asks `verbatim-relay status`, so a test whose process stopped does not show as a running test.

The model reads the exact conversation of the latest test with the read-only `transcript` tool. The tool runs `verbatim-relay transcript`, so the model gets the same text as with the hook kit. During a test, the model cannot send a message to the agent, and it cannot change the files in `.verbatim-relay/`. The plugin denies these tool calls, except file reads. It also denies a model command that runs the entry, for example `python3 entry.py`. A command that only reads the entry, for example `cat entry.py`, can run.

`verbatim-relay trace` builds the trace of the latest test again and shows its findings.

If the entry returns an error, crashes or does not answer in [240 seconds](../../src/verbatim_relay/stdio.py), the plugin shows the error and records it. The message never goes to the model. After a crash, each later message gets the same error, with the last lines of `app.log`. End the test and start a new one.

If the test process stops, the plugin cannot reach the tap. It then asks `verbatim-relay status`. If no test runs, the plugin shows "the test stopped, and no test runs" and tells you to type `/verbatim-relay start`. The message can have reached the tap before the test stopped, so the record keeps the turn with `ok: false`. The message never goes to the model.

Each test is a new conversation, with a new test id and a new entry process. The test folder is `.verbatim-relay/tests/<test-id>/`. [reference/records.md](../reference/records.md#the-test-folder) lists its files.

The plugin options are in [reference/config.md](../reference/config.md#plugin-options). Set them with `/plugin configure verbatim-relay@verbatim-relay` in Claude Code, or with `--config KEY=VALUE` at install. The defaults fit a test with an entry.

## Hook kit

1. In your project, install the kit with the entry:

   ```bash
   verbatim-relay init claude-code --entry "python3 examples/toy-shop/agent.py"
   ```

   It writes `.verbatim-relay/config.json` and adds two hooks to `.claude/settings.local.json`. It keeps your other hooks. Add `--models claude-code,codex` if your app runs its own model sessions.

2. In a second terminal, start the viewer:

   ```bash
   verbatim-relay view
   ```

   It shows each turn of the latest test, and it follows to the next test.

3. Start Claude Code in the project and type the prompt `verbatim-relay start`. The kit starts the test and does not send this prompt to the model.
4. Type your test messages. Claude Code shows "relayed to the agent". The reply shows in the viewer.
5. Type the prompt `verbatim-relay end`. The kit ends the test, and the model evaluates it and writes `report.md` (see [Evaluation](#evaluation)). The prompt `verbatim-relay status` shows the running test.

`verbatim-relay transcript` prints the exact turns of the latest test. You can also start and end a test from a shell: `verbatim-relay start` and `verbatim-relay end`.

In relay mode, the kit fails closed: if it cannot send a message, the message still does not go to the model.

[getting-started.md](../getting-started.md) shows each step of the hook kit with the toy shop, and the real output of each step.

## Evaluation

The evaluation prompt ([evaluate.md](../../src/verbatim_relay/evaluate.md)) tells the model to:

1. read the transcript with the trace: `verbatim-relay transcript --trace`, or the `transcript` tool with `trace: true`;
2. read `findings.json` and `audit.json`;
3. read your app's code and its business rules;
4. check your app's state with read-only commands;
5. write `report.md`: one row for each issue, with its class, its turn and its evidence.

The model did not see the conversation while you talked, so it judges the record, not its memory. Claude Code asks you to allow each command of the model, unless your permission settings allow it. After a test, the relay denies model writes to the test folder, except `report.md`. A shell command that names `.verbatim-relay` can only read, or write `report.md` ([SPEC.md section 5](../../SPEC.md#5-relays) lists the read programs). To stop the evaluation, add `"evaluate": false` to `.verbatim-relay/config.json`. [evaluation-example.md](../evaluation-example.md) shows a test and its report.

## Audit

```bash
verbatim-relay audit --tap .verbatim-relay/tests/<test-id>/tap.jsonl --relay .verbatim-relay/tests/<test-id>/relay.jsonl
```

Exit code 0 means clean, 1 means a break, and 2 means that a record is missing or invalid ([SPEC.md section 3.4](../../SPEC.md#34-exit-codes)).

## More

- An agent that is already an HTTP server: [http-tap.md](http-tap.md).
- Backends of your app: [add-a-backend.md](add-a-backend.md).
- Direct model calls and OpenTelemetry: [record-model-calls.md](record-model-calls.md).
- An Agent SDK session in your app: [isolate-agent-sdk.md](isolate-agent-sdk.md).
- Audit a test: [reference/cli.md](../reference/cli.md#verbatim-relay-audit).

# Test an agent with the Claude Code plugin

The plugin is a [relay](../reference/glossary.md#relay) for Claude Code. It shows each reply in the chat, as a dim row that the model does not receive. It uses function hooks, which are early access. To compare it with the hook kit, read [choose-a-relay.md](choose-a-relay.md).

**Warning:** Do not also install the hook kit in this project. With both relays, each message goes to the agent two times ([choose-a-relay.md](choose-a-relay.md#switch-from-one-relay-to-the-other)).

The proofs ran on Claude Code 2.1.290 ([data](../../proofs/claude-code/results.json)).

Before you start, connect a test to your app: [connect-your-agent.md](connect-your-agent.md). For the toy shop agent of this repo, the configuration is one line:

```json
{"entry": ["python3", "examples/toy-shop/agent.py"], "models": []}
```

## Install

1. Install the `nooku` command. The plugin runs it to start and end a test:

   ```bash
   uv tool install nooku
   ```

2. Add the marketplace and install the plugin:

   ```bash
   claude plugin marketplace add mohanraj00/verbatim-relay
   claude plugin install nooku@nooku
   ```

3. Write `.nooku/config.json` with your [entry](../reference/glossary.md#entry) (see above).

## Run a test

1. Type `/nooku start`. The plugin starts the entry through the [tap](../reference/glossary.md#tap), and [relay mode](../reference/glossary.md#relay-mode) goes on. The status line shows it. The start text tells you how to end the test.
2. Type your test messages. Each reply shows as a row in the chat and in the Nooku pane.
3. Type the prompt `nooku end`, with no slash. The plugin stops the entry, copies the app's session files into the [test folder](../reference/glossary.md#test-folder), builds the [trace](../reference/glossary.md#trace) and switches relay mode off. Then the prompt goes to the model with the evaluation prompt. The model writes `report.md` in the test folder (see [Evaluation](#evaluation)).

`/nooku end` ends the test with no evaluation. To evaluate that test later, type the prompt `nooku end`. `/nooku on` and `/nooku off` do the same as `start` and `end`. The prompts `nooku start` and `nooku status` also work.

`/nooku status` shows relay mode and the running test. The plugin runs `nooku status --json` for it. Thus a test whose process stopped does not show as a running test.

`nooku trace` builds the trace of the latest test again and shows its findings.

Each test is a new conversation, with a new test id and a new entry process. The test folder is `.nooku/tests/<test-id>/`. [reference/records.md](../reference/records.md#the-test-folder) lists its files.

If a message gets an error, read [troubleshooting.md](../troubleshooting.md#during-a-test).

## What the model can do

The model reads the exact conversation of the latest test with the read-only `transcript` tool. The tool runs `nooku transcript`, so the model gets the same text as with the hook kit.

During a test, the model cannot send a message to the agent, and it cannot change the files in `.nooku/`. The plugin denies each tool call that writes into `.nooku/`. It also denies each other tool call that names `.nooku`, also a read command such as `cat`. Only the file tools can read these files ([SPEC.md section 5](../../SPEC.md#5-relays)).

During a test, the plugin also denies a model command that runs the entry, for example `python3 entry.py`. A command that only reads the entry, for example `cat entry.py`, can run.

## Options

The plugin options are in [reference/config.md](../reference/config.md#plugin-options). Set them with `/plugin configure nooku@nooku` in Claude Code, or with `--config KEY=VALUE` at install. The defaults fit a test with an entry.

## Evaluation

The evaluation prompt ([evaluate.md](../../src/nooku/evaluate.md)) tells the model to:

1. read the transcript with the trace: `nooku transcript --trace`, or the `transcript` tool with `trace: true`;
2. read `findings.json` and `audit.json`;
3. read your app's code and its business rules;
4. check your app's state with read-only commands;
5. write `report.md`: one row for each issue, with its class, its turn and its evidence.

The model did not see the conversation while you talked, so it judges the record, not its memory. Claude Code asks you to allow each command of the model, unless your permission settings allow it.

After a test, the plugin denies model writes to the test folder, except `report.md`. A shell command that names `.nooku` can only read, or write `report.md` ([SPEC.md section 5](../../SPEC.md#5-relays) lists the read programs).

To stop the evaluation, add `"evaluate": false` to `.nooku/config.json`. [evaluation-example.md](../evaluation-example.md) shows a test and its report.

## Audit

```bash
nooku audit --tap .nooku/tests/<test-id>/tap.jsonl --relay .nooku/tests/<test-id>/relay.jsonl
```

Exit code 0 means clean, 1 means a break, and 2 means that a record is missing or invalid ([SPEC.md section 3.4](../../SPEC.md#34-exit-codes)).

## More

- Use the hook kit: [claude-code-hook-kit.md](claude-code-hook-kit.md).
- An agent that is already an HTTP server: [http-tap.md](http-tap.md).
- Backends of your app: [add-a-backend.md](add-a-backend.md).
- Direct model calls and OpenTelemetry: [record-model-calls.md](record-model-calls.md).
- An Agent SDK session in your app: [isolate-agent-sdk.md](isolate-agent-sdk.md).
- Audit a test: [reference/cli.md](../reference/cli.md#nooku-audit).

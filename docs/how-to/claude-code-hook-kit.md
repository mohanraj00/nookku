# Test an agent with the hook kit in Claude Code

The hook kit is a [relay](../reference/glossary.md#relay) that uses classic hooks. It shows each reply as the reason of a blocked prompt, and in `nookku view`, in a second terminal. To compare it with the plugin, read [choose-a-relay.md](choose-a-relay.md). For Codex, read [codex.md](codex.md).

**Warning:** Do not also enable the plugin in this project. With both relays, each message goes to the agent two times ([choose-a-relay.md](choose-a-relay.md#switch-from-one-relay-to-the-other)).

The proofs ran on Claude Code 2.1.295 ([data](../../proofs/hooks-claude-code/results.json)). [getting-started.md](../getting-started.md) shows each step of the hook kit with the toy shop, and the real output of each step.

Before you start, connect a test to your app: [connect-your-agent.md](connect-your-agent.md).

## Install

In your project, install the kit with the [entry](../reference/glossary.md#entry):

```bash
nookku init claude-code --entry "python3 examples/toy-shop/agent.py"
```

It writes `.nookku/config.json` and adds [2 hooks](../../src/nookku/kit.py) to `.claude/settings.local.json`. It keeps your other hooks. Add `--models claude-code,codex` if your app runs its own model sessions.

## Run a test

1. In a second terminal, start the viewer:

   ```bash
   nookku view
   ```

   It shows each turn of the latest test, and it follows to the next test.

2. Start Claude Code in the project and type the prompt `nookku start`. The kit starts the test and does not send this prompt to the model.
3. Type your test messages. Claude Code shows each reply as the reason of a blocked prompt. The viewer also shows the replies.
4. Type the prompt `nookku end`. The kit ends the test, and the model evaluates it and writes `report.md` (see [Evaluation](#evaluation)).

The prompt `nookku status` shows the running test. You can also start and end a test from a shell: `nookku start` and `nookku end`. The end from a shell starts no evaluation. To evaluate that test later, type the prompt `nookku end`.

`nookku trace` builds the [trace](../reference/glossary.md#trace) of the latest test again and shows its findings.

Each test is a new conversation, with a new test id and a new entry process. The [test folder](../reference/glossary.md#test-folder) is `.nookku/tests/<test-id>/`. [reference/records.md](../reference/records.md#the-test-folder) lists its files.

If a message gets an error, read [troubleshooting.md](../troubleshooting.md#during-a-test).

## What the model can do

The model reads the exact conversation of the latest test with `nookku transcript`. The command prints the exact turns, and the plugin gives the model the same text.

During a test, the model cannot send a message to the agent, and it cannot change the files in `.nookku/`. The kit denies each tool call that writes into `.nookku/`. It also denies each other tool call that names `.nookku`, also a read command such as `cat`. Only the file tools can read these files ([SPEC.md section 5](../../SPEC.md#5-relays)).

During a test, the kit also denies a model command that runs the entry, for example `python3 entry.py`. A command that only reads the entry, for example `cat entry.py`, can run.

## Evaluation

The evaluation prompt ([evaluate.md](../../src/nookku/evaluate.md)) tells the model to:

1. read the transcript with the trace: `nookku transcript --trace`;
2. read `findings.json` and `audit.json`;
3. read your app's code and its business rules;
4. check your app's state with read-only commands;
5. write `report.md`: one row for each issue, with its class, its turn and its evidence.

The model did not see the conversation while you talked, so it judges the record, not its memory. Claude Code asks you to allow each command of the model, unless your permission settings allow it.

After a test, the kit denies model writes to the test folder, except `report.md`. A shell command that names `.nookku` can only read, or write `report.md` ([SPEC.md section 5](../../SPEC.md#5-relays) lists the read programs).

To stop the evaluation, add `"evaluate": false` to `.nookku/config.json`. [evaluation-example.md](../evaluation-example.md) shows a test and its report.

## Audit

```bash
nookku audit --tap .nookku/tests/<test-id>/tap.jsonl --relay .nookku/tests/<test-id>/relay.jsonl
```

Exit code 0 means clean, 1 means a break, and 2 means that a record is missing or invalid ([SPEC.md section 3.4](../../SPEC.md#34-exit-codes)).

## More

- Use the plugin: [claude-code-plugin.md](claude-code-plugin.md).
- An agent that is already an HTTP server: [http-tap.md](http-tap.md).
- Backends of your app: [add-a-backend.md](add-a-backend.md).
- Direct model calls and OpenTelemetry: [record-model-calls.md](record-model-calls.md).
- An Agent SDK session in your app: [isolate-agent-sdk.md](isolate-agent-sdk.md).
- Audit a test: [reference/cli.md](../reference/cli.md#nookku-audit).

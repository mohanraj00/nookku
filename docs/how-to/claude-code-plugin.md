# Test an agent with the Claude Code plugin

The [plugin](../reference/glossary.md#plugin) installs the [relay](../reference/glossary.md#relay) in Claude Code for each of your projects. The same plugin works in Codex ([codex.md](codex.md)). Its 2 command hooks run `nookku hook`, so the plugin and the [project hooks](../reference/glossary.md#project-hooks) have the same rules. The plugin shows each reply in the chat as the reason of the blocked prompt, which the model does not receive. To compare it with the project hooks, read [choose-a-relay.md](choose-a-relay.md).

The plugin also has a display layer: `/nookku`, the status line and the Nookku pane. It uses function hooks, which are early access and can change between releases. It holds one rule: in [relay mode](../reference/glossary.md#relay-mode), it drops a prompt with an attachment. Each text comes from the `nookku` command. If the display layer fails, the command hooks still relay each message, but they relay the text of a prompt with an attachment and drop the attachment.

**Warning:** Do not also write the project hooks in this project. With both forms, each message goes to the agent two times ([choose-a-relay.md](choose-a-relay.md#switch-from-one-form-to-the-other)).

The plugin loads in Claude Code 2.1.296: its command hook blocks a relayed prompt, `/nookku status` shows the text of the core, and the model calls the `status` tool ([data](../../proofs/plugin/load.json), [method](../../scripts/proof_plugin_load.py)). [#219](https://github.com/mohanraj00/nookku/issues/219) runs the proofs P1 to P8 on the plugin.

Before you start, connect a test to your app: [connect-your-agent.md](connect-your-agent.md). For the toy shop agent of this repo, the configuration is one line:

```json
{"entry": ["python3", "examples/toy-shop/agent.py"], "models": []}
```

## Install

1. Install the `nookku` command. Each hook of the plugin, its MCP server and `/nookku` run it from `PATH`:

   ```bash
   uv tool install nookku
   ```

2. Add the marketplace and install the plugin:

   ```bash
   claude plugin marketplace add mohanraj00/nookku
   claude plugin install nookku@nookku
   ```

3. Write `.nookku/config.json` with your [entry](../reference/glossary.md#entry) (see above). `nookku init plugin` writes it, and writes no project hooks:

   ```bash
   nookku init plugin --entry "python3 examples/toy-shop/agent.py"
   ```

## Run a test

1. Type `/nookku start`. The plugin starts the entry through the [tap](../reference/glossary.md#tap), and [relay mode](../reference/glossary.md#relay-mode) goes on. The status line shows it. The start text tells you how to end the test. The Nookku pane opens. It shows the test id, the state of the test, the count of turns and the state of the chat page. Press "Open chat" to open the chat page again in the browser that opened it at the start. The pane shows no URL, and it sends no message. If that browser closed, end the test and start a new one, or run `nookku chat` in a separate terminal.
2. Type your test messages in Claude Code or on the chat page. Each reply to a message in Claude Code shows in the chat as the reason of the blocked prompt. The reply to a message from the chat page shows only on the page, not in the chat. The pane counts its turn. `/nookku view` shows the last [40 lines](../../plugins/nookku/hooks/register.tsx#L21) of `nookku view` in the Nookku pane. The relay does not send attachments: in relay mode, the plugin drops a prompt with an image or a file, and sends nothing.
3. Type the prompt `nookku end`, with no slash. The plugin stops the entry, copies the app's session files into the [test folder](../reference/glossary.md#test-folder), builds the [trace](../reference/glossary.md#trace) and switches relay mode off. Then the prompt goes to the model with the [evaluation](../reference/glossary.md#evaluation) prompt. The model writes `report.md` in the test folder (see [Evaluation](#evaluation)).

`/nookku end` and the "End test" button of the chat page end the test with no evaluation. After them, the chat page continues, so "Export" and "Save as script" still work. To evaluate that test later, type the prompt `nookku end`. `/nookku on` and `/nookku off` do the same as `start` and `end`. The prompts `nookku start` and `nookku status` also work. `/nookku <word>` runs `nookku mode <word>`, so the text is the text of the core.

`/nookku` or `/nookku status` shows relay mode and the running test. The plugin runs `nookku status` for it. Thus a test whose process stopped does not show as a running test.

`nookku trace` builds the trace of the latest test again and shows its [findings](../reference/glossary.md#findings).

Each test is a new conversation, with a new test id and a new entry process. The test folder is `.nookku/tests/<test-id>/`. [reference/records.md](../reference/records.md#the-test-folder) lists its files.

If a message gets an error, read [troubleshooting.md](../troubleshooting.md#during-a-test).

## What the model can do

The model reads the exact conversation of the latest test with the read-only `transcript` tool of the MCP server `nookku mcp`. In Claude Code, its name is `mcp__plugin_nookku_nookku__transcript`. The tool gives the text of `nookku transcript` in pages, with a hash of each page ([SPEC.md section 5](../../SPEC.md#5-relays)). So the model gets the same text as with the project hooks. With no test id, the tool skips each check test that ended, as `nookku transcript` does.

During a test, the model cannot send a message to the agent, and it cannot change the files in `.nookku/`. The relay denies each tool call that writes into `.nookku/`. It also denies each other tool call that names `.nookku`, also a read command such as `cat`. Only the file tools can read these files ([SPEC.md section 5](../../SPEC.md#5-relays)).

During a test, the relay also denies a model command that runs the entry, for example `python3 entry.py`. A command that only reads the entry, for example `cat entry.py`, can run.

## Options

The plugin has no options. It reads `.nookku/config.json` ([reference/config.md](../reference/config.md)). `nookku init plugin` writes the file, and its flags set each key ([reference/cli.md](../reference/cli.md#nookku-init)).

## Evaluation

The evaluation prompt ([evaluate.md](../../src/nookku/evaluate.md)) tells the model to:

1. read the transcript with the trace: `nookku transcript --trace`, or the `transcript` tool with `trace: true`;
2. read `findings.json` and `audit.json`;
3. read your app's code and its business rules;
4. check your app's state with read-only commands;
5. write `report.md`: one row for each issue, with its class, its turn and its evidence.

The model did not see the conversation while you talked, so it judges the record, not its memory. Claude Code asks you to allow each command of the model, unless your permission settings allow it.

After a test, the relay denies model writes to the test folder, except `report.md`. A shell command that names `.nookku` can only read, or write `report.md` ([SPEC.md section 5](../../SPEC.md#5-relays) lists the read programs).

To stop the evaluation, add `"evaluate": false` to `.nookku/config.json`. [evaluation-example.md](../evaluation-example.md) shows a test and its report.

## Audit

```bash
nookku audit --tap .nookku/tests/<test-id>/tap.jsonl --relay .nookku/tests/<test-id>/relay.jsonl
```

Exit code 0 means clean, 1 means a [break](../reference/glossary.md#break), and 2 means that a record is missing or invalid ([SPEC.md section 3.4](../../SPEC.md#34-exit-codes)).

## More

- Use the project hooks: [claude-code-project-hooks.md](claude-code-project-hooks.md).
- Use the plugin in Codex: [codex.md](codex.md).
- An agent that is already an HTTP server: [http-tap.md](http-tap.md).
- Backends of your app: [add-a-backend.md](add-a-backend.md).
- Direct model calls and OpenTelemetry: [record-model-calls.md](record-model-calls.md).
- An Agent SDK session in your app: [isolate-agent-sdk.md](isolate-agent-sdk.md).
- [Audit](../reference/glossary.md#audit) a test: [reference/cli.md](../reference/cli.md#nookku-audit).

# Test an agent in Codex

In Codex, you install the [relay](../reference/glossary.md#relay) as the [plugin](../reference/glossary.md#plugin) or as the [project hooks](../reference/glossary.md#project-hooks). Both run `nookku hook`, with the same rules. [choose-a-relay.md](choose-a-relay.md) compares them. Codex has no surface that shows hook text in `codex exec`, so the [chat page](../reference/cli.md#nookku-page) of the test shows each reply. `nookku view` in a second terminal is optional.

The plugin loads in Codex 0.162.1: Codex lists its 2 hooks, its MCP tools and its skill ([data](../../proofs/plugin/load.json), [method](../../scripts/proof_plugin_load.py)). The proofs P1 to P4 ran on the project hooks in codex-cli 0.162.1 ([data](../../proofs/hooks-codex/results.json)).

**Warning:** Do not use the plugin and the project hooks in one project. With both, each message goes to the agent two times. `nookku start` refuses a test if both are on.

## Install

1. Install the `nookku` command:

   ```bash
   uv tool install nookku
   ```

2. Install one form:
   - **The plugin.** Add the marketplace and install the plugin:

     ```bash
     codex plugin marketplace add mohanraj00/nookku
     codex plugin add nookku@nookku
     ```

     Then write `.nookku/config.json` with the [entry](../reference/glossary.md#entry) of your app. `nookku init plugin` writes it, and writes no project hooks:

     ```bash
     nookku init plugin --entry "python3 examples/toy-shop/agent.py"
     ```

   - **The project hooks.** Write the config and the hooks with the entry of your app:

     ```bash
     nookku init codex --entry "python3 examples/toy-shop/agent.py"
     ```

     `init` writes `.nookku/config.json` and `.codex/hooks.json`, with 2 hooks. Its output starts with the absolute project root, and gives the absolute path of each file. Run `init` in the top folder of your project, not in `.nookku/` or a [test folder](../reference/glossary.md#test-folder).
     - `UserPromptSubmit`: in [relay mode](../reference/glossary.md#relay-mode), it sends the prompt to the [tap](../reference/glossary.md#tap) and blocks it from the model. It also runs the prompts `nookku start`, `nookku end` and `nookku status`.
     - `PreToolUse`: it denies any model tool call that names the tap or the agent, except file tools. During a test, it also denies model changes to `.nookku/` and model commands that run the entry. After a test, a command that names `.nookku` can only read, or write `report.md`.

     The plugin has the same 2 hooks.

   The entry is a thin wrapper that starts your app and speaks the [agent contract](../reference/glossary.md#agent-contract) ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)). For your own app, type `!nookku setup` in Codex. Codex runs the command, and the model gets the guide as text. With the plugin, the `nookku:setup` skill gives the same guide. Then type the prompt "Follow the Nookku setup guide, and connect a test to this app." Codex then writes the entry in `.nookku/` and runs `nookku check`. Your app's code does not change. Review the entry before your first test. [connect-your-agent.md](connect-your-agent.md) gives the details. A PASS of `check` proves the connection, not the reply. Then do the steps in [Make sure that check runs your real app](connect-your-agent.md#make-sure-that-check-runs-your-real-app).

   Add `--models codex` (or `claude-code,codex`) if your app runs its own model sessions. Other options are for an agent that runs as an HTTP server: `--tap-url`, `--agent-url`, `--adapter`, `--message-field`, `--reply-field`, `--openai-model`, `--openai-stream` and `--record`. [reference/config.md](../reference/config.md#nookkuconfigjson) explains each one.

3. **Trust the hooks.** Codex runs a hook only after a person trusts it. Start `codex` in the project, type `/hooks`, check the 2 nookku hooks and trust them. Codex stores the trust in `~/.codex/config.toml`. If a hook changes, for example after a new `nookku init` or a new plugin version, you must trust it again. A change to `.nookku/config.json` or to the entry does not need new trust.

   Do not skip this step. Codex skips a hook that you did not trust, and then the model gets your test message. So `nookku start` and `nookku mode on` read the hooks with `codex app-server` and refuse a test if a nookku hook is missing, disabled, not trusted or modified ([SPEC.md section 7.8](../../SPEC.md#78-codex-hook-gate), [data](../../proofs/codex-gate/gate.json)). The project hooks show in Codex only after you trust the project.

## Use

1. Start `codex` in the project and type the prompt `nookku start`. The relay checks the hooks, starts your app through the tap and switches relay mode on. It does not send this prompt to the model. The start also opens the [chat page](../reference/cli.md#nookku-page) of the test in your browser.
2. Type your test messages in Codex or on the chat page. Codex shows each reply as the reason of the blocked prompt. `codex exec` does not show it, so the chat page also shows each turn. The model does not run in a relay turn: the proofs record 0 output tokens for each one ([data](../../proofs/hooks-codex/results.json)).
3. Optional: to see the turns in a terminal, run `nookku view` in a second terminal.
4. Type the prompt `nookku end`. The relay stops your app, copies its session files into the test folder, builds the [trace](../reference/glossary.md#trace) and switches relay mode off. Then the prompt goes to Codex with the [evaluation](../reference/glossary.md#evaluation) prompt, and Codex writes `report.md` in the test folder. The [Claude Code project hooks guide](claude-code-project-hooks.md#evaluation) explains the evaluation. Codex needs a sandbox that can write in the project to write the report, for example `workspace-write`.

`nookku transcript` prints the exact turns of the latest test. A check test that ended does not count: after `nookku check`, the scope is the test before it ([SPEC.md section 9.1](../../SPEC.md#91-start)). With the plugin, the model reads the same text with the `mcp__nookku__transcript` tool, in pages. The model did not see the conversation while you talked, so it judges the record, not its memory.

Each test is a new conversation, with a new app process. The test folder is `.nookku/tests/<test-id>/`. [reference/records.md](../reference/records.md#the-test-folder) lists its files.

At the end, the relay also builds the trace of the app's model sessions: `trace.jsonl` and `findings.json`. `nookku trace` builds it again and shows the [findings](../reference/glossary.md#findings).

If your app runs Codex sessions, the relay finds them at the end of the test. It takes each rollout file that changed during the test and ran in the project folder or below it. It does not take your own session. If your app starts its threads with `ephemeral: true`, Codex writes no rollout file, and the test has no copy.

The OTLP receiver of a test ([record-model-calls.md](record-model-calls.md#opentelemetry)) also runs in Codex. Codex does not read the `OTEL_*` variables: with codex-cli 0.162.1, `codex exec` with these variables completed its turn and sent 0 rows to the receiver ([data](../../proofs/otel/codex.json), [method](../../scripts/proof_codex_otel.py)). Codex reads its OpenTelemetry settings from the `[otel]` table of its configuration. So the receiver gets no events from your app's Codex threads, unless your app configures that table.

If your app uses Codex with a ChatGPT login, the model API proxy can send Codex to the public API. Read [record-model-calls.md](record-model-calls.md#direct-model-calls) for the fix.

In relay mode, the relay fails closed: if it cannot send a message, the message still does not go to the model.

## Audit

```bash
nookku audit --tap .nookku/tests/<test-id>/tap.jsonl --relay .nookku/tests/<test-id>/relay.jsonl
```

Exit code 0 means clean, 1 means a [break](../reference/glossary.md#break), and 2 means that a record is missing or invalid ([SPEC.md section 3.4](../../SPEC.md#34-exit-codes)).

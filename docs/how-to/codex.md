# Test an agent in Codex

Codex uses the hook kit. Codex has no surface that shows hook text in the chat, so each reply shows in `nooku view`, in a second terminal.

The proofs ran on codex-cli 0.160.0 ([data](../../proofs/hooks-codex/results.json)).

## Install

1. In your project, install the kit with the entry of your app:

   ```bash
   nooku init codex --entry "python3 examples/toy-shop/agent.py"
   ```

   The entry is a thin wrapper that starts your app and speaks the agent contract ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)). For your own app, type `!nooku setup` in Codex. Codex runs the command, and the model gets the guide as text. Then type the prompt "Follow the Nooku setup guide, and connect a test to this app." Codex then writes the entry in `.nooku/` and runs `nooku check`. Your app's code does not change. Review the entry before your first test. [connect-your-agent.md](connect-your-agent.md) gives the details. A PASS of `check` proves the connection, not the reply. Then do the steps in [Make sure that check runs your real app](connect-your-agent.md#make-sure-that-check-runs-your-real-app).

   `init` writes `.nooku/config.json` and `.codex/hooks.json`, with two hooks:
   - `UserPromptSubmit`: in relay mode, it sends the prompt to the tap and blocks it from the model. It also runs the prompts `nooku start`, `nooku end` and `nooku status`.
   - `PreToolUse`: it denies any model tool call that names the tap or the agent, except file tools. During a test, it also denies model changes to `.nooku/` and model commands that run the entry. After a test, a command that names `.nooku` can only read, or write `report.md`.

   Add `--models codex` (or `claude-code,codex`) if your app runs its own model sessions. Other options are for an agent that runs as an HTTP server: `--tap-url`, `--agent-url`, `--adapter`, `--message-field`, `--reply-field`, `--openai-model`, `--openai-stream` and `--record`. [reference/config.md](../reference/config.md#nookuconfigjson) explains each one.

2. **Trust the hooks.** Codex runs project hooks only after you trust them. Start `codex` in the project once and accept the hooks prompt. Codex stores the trust in `~/.codex/config.toml`. If you change `.codex/hooks.json`, you must trust it again. A change to `.nooku/config.json` or to the entry does not need new trust.

## Use

1. In a second terminal, start the viewer:

   ```bash
   nooku view
   ```

2. Start `codex` in the project and type the prompt `nooku start`. The kit starts your app through the tap and switches relay mode on. It does not send this prompt to the model.
3. Type your test messages. Codex shows that the hook blocked the prompt. The reply shows in the viewer. The model does not run in a relay turn: the proofs record 0 output tokens for each one ([data](../../proofs/hooks-codex/results.json)).
4. Type the prompt `nooku end`. The kit stops your app, copies its session files into the test folder, builds the trace and switches relay mode off. Then the prompt goes to Codex with the evaluation prompt, and Codex writes `report.md` in the test folder. The [Claude Code hook kit guide](claude-code-hook-kit.md#evaluation) explains the evaluation. Codex needs a sandbox that can write in the project to write the report, for example `workspace-write`.

`nooku transcript` prints the exact turns of the latest test. The model did not see the conversation while you talked, so it judges the record, not its memory.

Each test is a new conversation, with a new app process. The test folder is `.nooku/tests/<test-id>/`. [reference/records.md](../reference/records.md#the-test-folder) lists its files.

At the end, the kit also builds the trace of the app's model sessions: `trace.jsonl` and `findings.json`. `nooku trace` builds it again and shows the findings.

If your app runs Codex sessions, the kit finds them at the end of the test. It takes each rollout file that changed during the test and ran in the project folder or below it. It does not take your own session. If your app starts its threads with `ephemeral: true`, Codex writes no rollout file, and the test has no copy.

The OTLP receiver of a test ([record-model-calls.md](record-model-calls.md#opentelemetry)) also runs with the kit. Codex does not read the `OTEL_*` variables: with codex-cli 0.160.0, `codex exec` with these variables completed its turn and sent 0 rows to the receiver ([data](../../proofs/otel/codex.json), [method](../../scripts/proof_codex_otel.py)). Codex reads its OpenTelemetry settings from the `[otel]` table of its configuration. So the receiver gets no events from your app's Codex threads, unless your app configures that table.

If your app uses Codex with a ChatGPT login, the model API proxy can send Codex to the public API. Read [record-model-calls.md](record-model-calls.md#direct-model-calls) for the fix.

In relay mode, the kit fails closed: if it cannot send a message, the message still does not go to the model.

## Audit

```bash
nooku audit --tap .nooku/tests/<test-id>/tap.jsonl --relay .nooku/tests/<test-id>/relay.jsonl
```

Exit code 0 means clean, 1 means a break, and 2 means that a record is missing or invalid ([SPEC.md section 3.4](../../SPEC.md#34-exit-codes)).

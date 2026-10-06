# Codex

Codex uses the hook kit. Codex has no surface that shows hook text in the chat, so each reply shows in `verbatim-relay view`, in a second terminal.

Tested with codex-cli 0.160.0.

## Install

1. In your project, install the kit with the entry of your app:

   ```bash
   verbatim-relay init codex --entry "python examples/toy-shop/agent.py"
   ```

   The entry is a thin wrapper that starts your app and speaks the agent contract ([SPEC.md section 6](../SPEC.md#6-agent-contract-version-1)). For your own app, ask Codex: "Run `verbatim-relay setup` and connect a test to this app." Codex then writes the entry in `.verbatim-relay/` and runs `verbatim-relay check`. Your app's code does not change. Review the entry before your first test.

   `init` writes `.verbatim-relay/config.json` and `.codex/hooks.json`, with two hooks:
   - `UserPromptSubmit`: in relay mode, it sends the prompt to the tap and blocks it from the model. It also runs the prompts `verbatim-relay start`, `verbatim-relay end` and `verbatim-relay status`.
   - `PreToolUse`: it denies any model tool call that names the tap or the agent, except file tools. During a test, it also denies model changes to `.verbatim-relay/` and model commands that run the entry. After a test, a command that names `.verbatim-relay` can only read, or write `report.md`.

   Add `--models codex` (or `claude-code,codex`) if your app runs its own model sessions. Other options are for an agent that runs as an HTTP server: `--tap-url`, `--agent-url`, `--adapter`, `--message-field`, `--reply-field`, `--openai-model` and `--record`. The [Claude Code page](claude-code.md#an-agent-that-runs-as-an-http-server) explains each one.

2. **Trust the hooks.** Codex runs project hooks only after you trust them. Start `codex` in the project once and accept the hooks prompt. Codex stores the trust in `~/.codex/config.toml`. If you change `.codex/hooks.json`, you must trust it again. A change to `.verbatim-relay/config.json` or to the entry does not need new trust.

## Use

1. In a second terminal, start the viewer:

   ```bash
   verbatim-relay view
   ```

2. Start `codex` in the project and type the prompt `verbatim-relay start`. The kit starts your app through the tap and switches relay mode on. It does not send this prompt to the model.
3. Type your test messages. Codex shows that the hook blocked the prompt. The reply shows in the viewer. The model does not run in a relay turn: the proofs record 0 output tokens for each one.
4. Type the prompt `verbatim-relay end`. The kit stops your app, copies its session files into the test folder, builds the trace and switches relay mode off. Then the prompt goes to Codex with the evaluation prompt, and Codex writes `report.md` in the test folder. The [Claude Code page](claude-code.md#evaluation) explains the evaluation. Codex needs a sandbox that can write in the project to write the report, for example `workspace-write`.

`verbatim-relay transcript` prints the exact turns of the latest test. The model did not see the conversation while you talked, so it judges the record, not its memory.

Each test is a new conversation, with a new app process. The test folder is `.verbatim-relay/tests/<test-id>/`. The [Claude Code page](claude-code.md#plugin) lists its files.

At the end, the kit also builds the trace of the app's model sessions: `trace.jsonl` and `findings.json`. `verbatim-relay trace` builds it again and shows the findings.

If your app runs Codex sessions, the kit finds them at the end of the test: each rollout file that changed during the test, ran in the project folder or below it, and is not your own session. If your app starts its threads with `ephemeral: true`, Codex writes no rollout file, and the test has no copy.

In relay mode, the kit fails closed: if it cannot send a message, the message still does not go to the model.

## Audit

```bash
verbatim-relay audit --tap .verbatim-relay/tests/<test-id>/tap.jsonl --relay .verbatim-relay/tests/<test-id>/relay.jsonl
```

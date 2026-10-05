# Codex

Codex uses the hook kit. Codex has no surface that shows hook text in the chat, so each reply shows in `verbatim-relay view`, in a second terminal.

Tested with codex-cli 0.160.0.

## Install

1. In your project, install the kit:

   ```bash
   verbatim-relay init codex
   ```

   It writes `.verbatim-relay/config.json` and `.codex/hooks.json`, with two hooks:
   - `UserPromptSubmit`: in relay mode, it sends the prompt to the tap and blocks it from the model.
   - `PreToolUse`: it denies any model tool call that names the tap or the agent, except file tools.

   Options are flags: `--tap-url`, `--agent-url`, `--adapter`, `--message-field`, `--reply-field`, `--openai-model` and `--record`. The [Claude Code page](claude-code.md#plugin) explains each one.

2. **Trust the hooks.** Codex runs project hooks only after you trust them. Start `codex` in the project once and accept the hooks prompt. Codex stores the trust in `~/.codex/config.toml`. If you change `.codex/hooks.json`, you must trust it again. A change to `.verbatim-relay/config.json` does not need new trust.

## Use

1. Start the tap in front of your agent (see the [README](../README.md#quick-start)).
2. In a second terminal, start the viewer:

   ```bash
   verbatim-relay view
   ```

3. Switch relay mode on:

   ```bash
   verbatim-relay mode on
   ```

4. Start `codex` in the project and type your test messages. Codex shows that the hook blocked the prompt. The reply shows in the viewer. The model does not run in a relay turn: the proofs record 0 output tokens for each one.
5. Switch relay mode off with `verbatim-relay mode off`.
6. Ask Codex to evaluate the agent, for example: "Run `verbatim-relay transcript` and evaluate the agent's business logic, tone, language and accuracy. Quote the turns that you judge."

`verbatim-relay transcript` prints the exact turns of the latest session. Add `--all` for every session in the record. The model did not see the conversation while you talked, so it judges the record, not its memory.

In relay mode, the kit fails closed: if it cannot send a message, the message still does not go to the model.

## Audit

```bash
verbatim-relay audit --tap tap.jsonl --relay .verbatim-relay/relay.jsonl
```

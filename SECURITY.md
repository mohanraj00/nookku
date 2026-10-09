# Security

## Report a problem

Use a private security advisory on GitHub (the Security tab of this repo). Do not open a public issue. I answer within 7 days.

## What to know before you use it

- **The records contain the whole test conversation.** Treat `tap.jsonl` and `.nookku/relay.jsonl` as you treat your test data. Add `.nookku/` to `.gitignore` if the conversation must not enter your repo.
- **The tap listens on 127.0.0.1:8800 by default.** If you bind it to another address, anyone who can reach that address can talk to your agent through it.
- **The deny is best effort.** It stops a model tool call that names the tap or the agent. It does not stop a model that reaches the agent by a route that the relay does not see. Do not use Nookku as a security boundary.
- **The hook kit runs a command for each prompt and each tool call.** `nookku init` writes that command with the absolute path of the Python that runs Nookku. Read the hook file before you trust it in Codex.
- **Nookku has no runtime dependencies.** It uses the Python standard library only.

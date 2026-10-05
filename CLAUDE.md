# Work on verbatim-relay

## What this project is

A person tests a chat agent through a coding harness (Claude Code or Codex). The harness extension carries each message and each reply byte for byte, so the model never retypes them. An independent tap proxy records what the agent received and sent. The audit compares the two records and names each break.

## Rules

- **Clean room.** Write all code new in this repo. Do not copy code, data or logs from other projects.
- **Stealth gate.** `scripts/stealth.py check` must pass. It checks files, paths and commit messages against salted hashes of banned terms. Never write a banned term into the repo to test the gate. To add a term, pipe it into `scripts/stealth.py add`.
- **Examples.** Use a toy shop or a support agent in examples and test data.
- **Dependencies.** Use the standard library first. Do not add a GPL or AGPL dependency. Ask the maintainer before you add any runtime dependency.
- **Claims.** Each number in a doc must link to its data and its method. If the measurement does not exist, do not make the claim.
- **Harness versions.** Record the tested versions of Claude Code and Codex with each result.
- **Plugin API.** The Claude Code plugin uses function hooks, which are early access and can change between releases. CI pins the tested version.
- **Plugin helpers.** In `plugins/claude-code/hooks/register.tsx`, a function that takes `$` must be a top-level function declaration. `claude plugin validate` refuses other forms.
- **Outward steps.** Do not push, tag, publish or open issues without the maintainer's approval for that step. Tags publish to PyPI and you cannot undo them.

## Writing

Docs, commit messages and issues use the maintainer's voice under ASD-STE100 rules: first person where natural, short sentences, active voice, simple words, numbers instead of adjectives. Be direct. No em-dashes, no filler words ("seamless", "robust", "leverage", "comprehensive"). Each number links to its data.

## Before every commit

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run python scripts/stealth.py check
claude plugin validate plugins/claude-code && claude plugin test plugins/claude-code
```

## Proofs (local only)

- `scripts/proofs_claude_code.py` runs P1 to P4 for the plugin with `claude -p` and writes `proofs/claude-code/`.
- `scripts/proofs_hooks.py codex|claude-code` runs P1 to P4 for the hook kit and writes `proofs/hooks-<harness>/`. Codex runs project hooks only after a person trusts them. The maintainer trusts `.proof/codex/.codex/hooks.json` once. Never try to skip the trust step.

Run the proofs after each change to a relay or to a new harness version. Commit the results with the version that they record.

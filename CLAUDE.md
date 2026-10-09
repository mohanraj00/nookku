# Work on Nookku

## What this project is

Nookku is a test harness for developers of agent apps. A person tests a chat agent through a coding harness (Claude Code or Codex). The harness extension carries each message and each reply byte for byte, so the model never retypes them. An independent tap proxy records what the agent received and sent. The audit compares the two records and names each break.

`AGENTS.md` is a copy of this file for Codex. Change the two files together. A test checks that they are the same.

## Work starts from an issue

- Find work with `gh issue list` and `gh issue view N`.
- Use one branch for each issue, with the name `N-short-slug`. The PR body says `Fixes #N`.
- Make CI green before you mark a PR as ready. The maintainer reviews and merges.
- If you find work outside the scope of the issue, propose a new issue to the maintainer. Do not make the PR larger.

## Two harnesses work on this repo

Claude Code and Codex both work on this repo, at the same time. The label `agent:claude-code` or `agent:codex` names the harness that does the work.

- Before you start an issue, add the label of your harness to it. Do not start an issue that has the label of the other harness.
- After you add your label, read the labels of the issue again. If both labels are on it, the label that was added first wins. The issue events show the order: `gh api repos/mohanraj00/nookku/issues/N/events`. If your label was second, remove it and do not start the issue.
- Add the label of your harness to each PR that you open.
- No harness reviews a PR by default. You must ask the other harness for the code review in a PR comment:
  - Claude Code writes `@codex review`. Codex writes `@claude review this PR. Use the Review guidelines in CLAUDE.md.`
  - On the next line of the comment, write `Head: <sha>`, with the short SHA of the head commit of the PR.
  - Ask when CI is green and the PR is ready.
  - Ask one time for each head commit. Before you ask, read the PR comments. If a request names the current head commit, do not ask again.
  - If you push fixes after a code review, the head commit changes. When CI is green again, ask for a new code review.
  - Ask for a code review at most 3 times for each PR. After that, ask the maintainer to review.
- Decide if the PR needs a security review:
  - If the code review ends with `Security review: needed` or `Security review: not needed`, use that line.
  - A Codex code review gives only findings, so it cannot add this line. If the line is not there, use the list in "Review guidelines" to decide.
- If the PR needs a security review, post `@codex security review` on the PR, one time for each PR:
  - Before you post, read the PR comments. If a security review was already asked for or done, do not ask again.
  - Do not ask again after you fix a finding. Only the maintainer can ask for a second security review.
- Answer each finding of the code review and of the security review in the PR: fix it, or say why it is not a defect. Then ask the maintainer to review.
- Turn on auto-merge only after you answer each finding of the code review and of the security review, and only if the maintainer agrees. `main` requires no approving review, so auto-merge can merge a PR before its review arrives.
- Work in your own worktree and on your own branch. Do not push to the branch of the other harness.

## Rules

- **Clean room.** Write all code new in this repo. Do not copy code, data or logs from other projects.
- **Stealth gate.** `scripts/stealth.py check` must pass. It checks files, paths and commit messages against salted hashes of banned terms. Never write a banned term into the repo to test the gate. To add a term, pipe it into `scripts/stealth.py add`.
- **Examples.** Use a toy shop or a support agent in examples and test data.
- **Code quality.** Follow `docs/code-quality.md`. It gives each rule, its reason and the check that enforces it.
- **Dependencies.** Use the standard library first. Do not add a GPL or AGPL dependency. Ask the maintainer before you add any runtime dependency.
- **Claims.** Each number in a doc must link to its data and its method. If the measurement does not exist, do not make the claim.
- **Harness versions.** Record the tested versions of Claude Code and Codex with each result.
- **Plugin API.** The Claude Code plugin uses function hooks, which are early access and can change between releases. CI pins the tested version.
- **Plugin helpers.** In `plugins/claude-code/hooks/register.tsx`, a function that takes `$` must be a top-level function declaration. `claude plugin validate` refuses other forms.
- **Outward steps.** Do not push, tag, publish or open issues without the maintainer's approval for that step. Tags publish to PyPI and you cannot undo them.

## Review guidelines

Flag these as high priority in a PR review:

- A change that lets the relay change a byte of a message or a reply, or that lets a relayed message reach the model.
- A relay path that fails open. If the relay cannot send a message, the message must still not go to the model.
- A change to the record format or to the audit with no SPEC.md change and no hand-written conformance case.
- A banned term, or a client or product name, in a file, a path or a commit message.
- A new runtime dependency, or a GPL or AGPL dependency.
- A number in a doc with no link to its data and its method.
- A plugin helper that takes `$` and is not a top-level function declaration.

If your review format lets you add text after the findings, end a code review with one line. Write `Security review: needed`, with the reason, if the PR changes one of these:

- the relay path, the tap, the guard, the seal or the policy file;
- a hook, the plugin, or the code that starts the entry or a test;
- the code that reads input from the model, a tester or an agent;
- a workflow, a secret, a permission or a dependency.

Else write `Security review: not needed`. Do not ask for the security review yourself. The PR author asks for it. A security review does not end with this line.

## Writing

Docs, commit messages and issues use the maintainer's voice under ASD-STE100 rules: first person where natural, short sentences, active voice, simple words, numbers instead of adjectives. Be direct. No em-dashes, no filler words ("seamless", "robust", "leverage", "comprehensive"). Each number links to its data.

## Before every commit

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run python scripts/stealth.py check
claude plugin validate plugins/claude-code && claude plugin test plugins/claude-code
```

## Proofs (local only)

- `scripts/proofs_claude_code.py` runs P1 to P4 for the plugin with `claude -p` and writes `proofs/claude-code/`.
- `scripts/proofs_hooks.py codex|claude-code` runs P1 to P4 for the hook kit and writes `proofs/hooks-<harness>/`.
- `scripts/proof_backend.py` checks that the backend proxy forwards each byte, with no model, and writes `proofs/backend/`.
- `scripts/proof_model_api.py` checks that the model API proxy forwards each byte and each stream part when it comes, with no model, and writes `proofs/model-api/`.
- `scripts/proof_report.py plugin|hooks-claude-code|hooks-codex` runs a test of `examples/toy-shop-models/` and the evaluation at its end (P5 extended, P6, P7 and P8), and writes `proofs/report/`.
- `scripts/proof_telemetry.py plugin|hooks-claude-code|hooks-codex` runs a test of `examples/toy-shop-full/` with all telemetry sources and the evaluation at its end, and writes `proofs/telemetry/`.
- `scripts/proof_codex_otel.py` checks if Codex sends OpenTelemetry data from the `OTEL_*` variables of a test, and writes `proofs/otel/codex.json`.
- `scripts/proof_evaluation.py plugin|hooks-claude-code|hooks-codex` runs P5 (the model judges the record, not its memory) and writes `proofs/evaluation/`. Never store a model answer that can quote the harness's own instruction files. Codex runs project hooks only after a person trusts them. The maintainer trusts `.proof/codex/.codex/hooks.json` once. Never try to skip the trust step.

`scripts/example_evaluation.py` runs the worked evaluation in `docs/evaluation-example.md` and writes `examples/toy-shop/evaluation.json`. The model's answer changes on each run, so update the doc with the data.

Run the proofs after each change to a relay or to a new harness version. Commit the results with the version that they record.

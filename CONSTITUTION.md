# Nookku constitution

Version 2, 2026-11-12.

## Purpose

Nookku is an evaluation harness for vertical AI agents. A person tests a chat agent through a coding harness (Claude Code or Codex). The harness extension carries each message and each reply byte for byte, so the model never retypes them. An independent tap proxy records what the agent received and sent. The audit compares the two records and names each break.

## Boundaries

Nookku does not do these: production monitoring and hosted team review. Nookku does not store or host the data sets of a user at scale.

A test is one conversation, from your harness or from a script ([SPEC.md section 7](SPEC.md#7-tests)). A gate run is a declared set of tests. It gives one aggregate verdict and names its subject with a digest that the caller supplies, for example an image digest, a commit or a snapshot. The declared set, the aggregate verdict and the subject digest are in scope.

## Principles

- **Code quality.** Follow `docs/contributing/code-quality.md`. It gives each rule, its reason and the check that enforces it.
- **Dependencies.** Use the standard library first. Do not add a GPL or AGPL dependency. Ask the maintainer before you add any runtime dependency.

## Verdicts

- **Deterministic checks.** A deterministic check can fail a verdict. Answer key, citation and replay checks are deterministic checks.
- **Model judgments.** A model issue class fails a verdict only when the app spec opts in. The default verdict is reproducible.

## Evidence

- **Claims.** Each number in a doc must link to its data and its method. If the measurement does not exist, do not make the claim.
- **Harness versions.** Record the tested versions of Claude Code and Codex with each result.
- **Proofs.** Run the proofs after each change to a relay or to a new harness version. Commit the results with the version that they record. [AGENTS.md](AGENTS.md#proofs-local-only) lists the proof scripts.

## Contributions

- **Clean room.** Write all code new in this repo. Do not copy code, data or logs from other projects.
- **Stealth gate.** `scripts/stealth.py check` must pass. It checks files, paths and commit messages against salted hashes of banned terms. Never write a banned term into the repo to test the gate. To add a term, pipe it into `scripts/stealth.py add`.
- **Examples.** Use a toy shop or a support agent in examples and test data.

## Governance

<!-- governance:start v1 -->
This project follows the project standard in `docs/STANDARD.md`. That file is an exact copy from `mohanraj00/.github`. The standard owns the rules for builds, reviews, approvals and CI. A project exception to the standard is valid only when the standard records it.

The documents own these topics:

- `CONSTITUTION.md`: the purpose, the boundaries, the principles, the evidence rules, the contribution rules and the version log.
- `docs/STANDARD.md`: the builds, the reviews, the approvals and CI.
- `AGENTS.md`: the layout, the check command and the review guidelines.
- `CLAUDE.md` and `GEMINI.md`: imports only.

These rules apply to each change:

1. A harness does not review its own change. The Codex security review is the one exception, as the standard says.
2. The agents use the owner login. An agent never approves a PR and never merges a level 1 PR. An agent never adds the labels `accepted`, `security-reviewed`, `cross-reviewed` or `ready-for-review`.
3. The owner merges each level 1 PR.
4. Each tag, release, package publication, visibility change and outreach step needs a separate owner approval.
<!-- governance:end v1 -->

## Amendment

Change this constitution when the owner changes direction or evidence changes a decision. A change is a level 1 PR. Record the reason in the change, and add an entry to the version log.

Change the governance block only with a new version of the template in `mohanraj00/.github`.

## Version log

### Version 1, 2026-11-09

The first constitution, with the sections of the template v1 of `mohanraj00/.github`. It holds text from `AGENTS.md` and `README.md`, with no new rule. Reason: the project standard version 6 requires a constitution in each project.

### Version 2, 2026-11-12

The boundary changes. A declared set of tests (a gate run), an aggregate verdict and a subject digest are in scope. A test stays one conversation. Production monitoring and hosted team review stay out of scope. A new section "Verdicts" says that deterministic checks fail a verdict, and that a model issue class fails it only when the app spec opts in. Reason: a release gate needs one result for a set of tests, and the one-conversation limit blocked it. The default verdict must stay reproducible.

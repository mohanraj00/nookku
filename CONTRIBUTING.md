# Contributing

Read the [code of conduct](CODE_OF_CONDUCT.md) first. [docs/index.md](docs/index.md) is the map of the docs, and [docs/architecture.md](docs/architecture.md) shows the parts of the code.

## Install the dev tools

```bash
uv sync
```

The plugin tests also need the `claude` CLI.

## Before each commit

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
uv run python scripts/stealth.py check
claude plugin validate plugins/claude-code && claude plugin test plugins/claude-code
```

`uv run pytest` also checks the docs (`tests/test_docs.py`). It checks each relative link and each anchor in the Markdown files, and the counts in the README. It also checks the CLI and configuration reference pages against the code.

## Rules

- **Spec first.** A change to the records or the audit starts in [SPEC.md](SPEC.md). Write its conformance cases by hand in [conformance/build.py](conformance/build.py), before the code. Never fill an expectation by running the audit.
- **No runtime dependencies.** The package uses the Python standard library only.
- **Numbers need data.** Each number in a doc links to the file that it comes from. Do not edit a published result by hand.
- **Relays change, proofs run again.** After a change to the plugin or the hook kit, run the proofs ([docs/how-to/run-the-proofs.md](docs/how-to/run-the-proofs.md)). Commit the new results with the harness version that they record.
- **Examples use a toy shop or a support agent.**
- **Code quality.** Follow [docs/code-quality.md](docs/code-quality.md). It gives each rule and the check that enforces it.
- **Docs.** Write in ASD-STE100: short sentences, active voice, simple words. If you add a page to `docs/`, add it to [docs/index.md](docs/index.md). If you add a command, a flag or a config key, add it to [docs/reference/cli.md](docs/reference/cli.md) or [docs/reference/config.md](docs/reference/config.md). The tests fail if you do not.

## Issues and pull requests

- Open an issue first for anything larger than a fix. Use the [bug](.github/ISSUE_TEMPLATE/bug.md) or the [feature](.github/ISSUE_TEMPLATE/feature.md) template.
- One change for each pull request. The [pull request template](.github/PULL_REQUEST_TEMPLATE.md) has the checks and a short list from the code quality rules.
- Write `Fixes #N` in the pull request body. CI must pass.
- Report a security problem in private, as [SECURITY.md](SECURITY.md) says.

# Contributing

## Set up

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

## Rules

- **Spec first.** A change to the records or the audit starts in [SPEC.md](SPEC.md). Write its conformance cases by hand in [conformance/build.py](conformance/build.py), before the code. Never fill an expectation by running the audit.
- **No runtime dependencies.** The package uses the Python standard library only.
- **Numbers need data.** Each number in a doc links to the file that it comes from. Do not edit a published result by hand.
- **Relays change, proofs run again.** After a change to the plugin or the hook kit, run the proofs in [docs/results.md](docs/results.md#run-it-again) and commit the new results with the harness version that they record.
- **Examples use a toy shop or a support agent.**
- **Code quality.** Follow [docs/code-quality.md](docs/code-quality.md). It gives each rule and the check that enforces it.

## Pull requests

Open an issue first for anything larger than a fix. One change for each pull request. CI must pass.

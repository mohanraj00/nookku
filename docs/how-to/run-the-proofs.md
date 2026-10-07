# Run the proofs

The proofs show that each relay is exact in a real harness. They run the harness headless, so they are local scripts in `scripts/`, not tests in CI. Run them after each change to a relay, and for each new harness version. Commit the results with the harness versions that they record.

[results.md](../results.md) explains each proof and shows the latest results.

## Before you start

- Install the dev tools: `uv sync`.
- Install the harnesses that the proof needs: `claude` for Claude Code, `codex` for Codex.
- The plugin proofs load the plugin from this repo. You do not install it.
- Some proofs use a real model and cost tokens. The proofs of the proxies and the backend need no model.

## Trust the Codex projects once

Codex runs project hooks only after a person trusts them. Never try to skip the trust step. Trust these projects once:

1. Install the kit in the project of the proofs: `verbatim-relay init codex --root .proof/codex`.
2. Start `codex` in `.proof/codex` and accept the hooks prompt.
3. For the evaluation proofs, do the same in `~/.verbatim-relay-proof/codex`. That project is outside the repo, so that the evaluating model cannot read the docs that describe the planted bug ([proof_report.py](../../scripts/proof_report.py)).

If `.codex/hooks.json` changes, trust it again.

## The commands

| Proof | Command | Output |
|---|---|---|
| P1 to P4, plugin | `uv run python scripts/proofs_claude_code.py` | `proofs/claude-code/` |
| P1 to P4, plugin, streamed agent | `uv run python scripts/proofs_claude_code.py --stream` | `proofs/claude-code-stream/` |
| P1 to P4, hook kit | `uv run python scripts/proofs_hooks.py claude-code` or `codex` | `proofs/hooks-<harness>/` |
| P1 to P4, hook kit, streamed agent | `uv run python scripts/proofs_hooks.py claude-code --stream` or `codex --stream` | `proofs/hooks-<harness>-stream/` |
| Model sessions of the app | `uv run python scripts/proof_sessions.py` | `proofs/sessions/` |
| Trace of the model sessions | `uv run python scripts/proof_trace.py` | `proofs/trace/` |
| Backend proxy, no model | `uv run python scripts/proof_backend.py` | `proofs/backend/` |
| Model API proxy, no model | `uv run python scripts/proof_model_api.py` | `proofs/model-api/` |
| P5 to P8, evaluation at the end of a test | `uv run python scripts/proof_report.py plugin`, `hooks-claude-code` or `hooks-codex` | `proofs/report/` |
| Full telemetry | `uv run python scripts/proof_telemetry.py plugin`, `hooks-claude-code` or `hooks-codex` | `proofs/telemetry/` |
| P5, the model judges the record | `uv run python scripts/proof_evaluation.py plugin`, `hooks-claude-code` or `hooks-codex` | `proofs/evaluation/` |
| Codex and the `OTEL_*` variables | `uv run python scripts/proof_codex_otel.py` | `proofs/otel/codex.json` |
| Benchmark under pressure | `uv run python bench/run.py mechanism claude-code` or `codex`, then `uv run python bench/score.py` | `bench/runs/`, `bench/results.json` |
| Worked evaluation | `uv run python scripts/example_evaluation.py` | `examples/toy-shop/evaluation.json` |

These scripts print `PASS` or `FAIL` and the path of their results file: `proofs_claude_code.py`, `proofs_hooks.py`, `proof_sessions.py`, `proof_trace.py`, `proof_backend.py`, `proof_model_api.py`, `proof_report.py` and `proof_telemetry.py`. The docstring of each script lists what it checks.

## After a run

1. Read the results file. A fail is a result too: keep it, and say why in [results.md](../results.md).
2. Update the tables in [results.md](../results.md) and the README from the results files. Do not edit a published result by hand.
3. Commit the results with the harness versions that they record.

A model answer changes on each run. The scripts store no model answer that can quote the harness's own instruction files. They check the text against the instruction files on the machine, and they remove local paths.

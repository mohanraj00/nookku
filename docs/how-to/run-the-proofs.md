# Run the proofs

The proofs show that each relay is exact in a real harness. They run the harness headless, so they are local scripts in `scripts/`, not tests in CI. Run them after each change to a relay, and for each new harness version. Commit the results with the harness versions that they record.

[results.md](../results.md) explains each proof and shows the latest results.

## Before you start

- Install the dev tools: `uv sync`.
- Install the harnesses that the proof needs: `claude` for Claude Code, `codex` for Codex.
- The proofs run in 4 setups: `plugin-claude-code`, `plugin-codex`, `hooks-claude-code` and `hooks-codex`. A setup is a form of the relay (the plugin or the project hooks) and a harness.
- In Claude Code, the plugin proofs load the plugin from this repo with `--plugin-dir`. You do not install it.
- In Codex, the plugin proofs use the `CODEX_HOME` of [proof_codex_gate.py](../../scripts/proof_codex_gate.py), `.proof/codex-gate/codex-home`. That script installs the plugin of this checkout there.
- The plugin hooks run `nookku` from `PATH`. The scripts put the `nookku` of this checkout first.
- Some proofs use a real model and cost tokens. The proofs of the proxies and the backend need no model.

## Trust the Codex hooks once

Codex runs a hook only after a person trusts it. Never try to skip the trust step. `nookku start` refuses a test with an untrusted hook ([SPEC.md section 7.8](../../SPEC.md#78-codex-hook-gate)). Trust these hooks once:

1. **The plugin.** Run `uv run python scripts/proof_codex_gate.py`. Then start `CODEX_HOME=.proof/codex-gate/codex-home codex -C .proof/codex-gate/project`, type `/hooks`, and trust the 2 nookku hooks.
2. **The project hooks.** Write them with the Python of this checkout: `.venv/bin/python3 -m nookku init codex --root .proof/codex`. Start `codex -C .proof/codex`, type `/hooks`, and trust the 2 nookku hooks.
3. **The project hooks of the evaluation proofs.** Do step 2 in `~/.nookku-proof/codex`. That project is outside the repo, so that the evaluating model cannot read the docs that describe the planted bug ([proof_report.py](../../scripts/proof_report.py)).

If a hook changes, trust it again. A new plugin script also needs a new run of `proof_codex_gate.py` and a new trust step.

## The commands

| Proof | Command | Output |
|---|---|---|
| P1 to P4 | `uv run python scripts/proofs_relay.py <setup>` | `proofs/<setup>/` |
| P1 to P4, streamed agent | `uv run python scripts/proofs_relay.py <setup> --stream` | `proofs/<setup>-stream/` |
| P1 to P4, agent that streams only on request | `uv run python scripts/proofs_relay.py <setup> --stream --on-request` | `proofs/<setup>-stream-on-request/` |
| Model sessions of the app | `uv run python scripts/proof_sessions.py` | `proofs/sessions/` |
| Trace of the model sessions | `uv run python scripts/proof_trace.py` | `proofs/trace/` |
| Backend proxy, no model | `uv run python scripts/proof_backend.py` | `proofs/backend/` |
| Model API proxy, no model | `uv run python scripts/proof_model_api.py` | `proofs/model-api/` |
| P5 to P8, evaluation at the end of a test | `uv run python scripts/proof_report.py <setup>` | `proofs/report/<setup>.json` |
| Full telemetry | `uv run python scripts/proof_telemetry.py <setup>` | `proofs/telemetry/<setup>.json` |
| P5, the model judges the record | `uv run python scripts/proof_evaluation.py <setup>` | `proofs/evaluation/<setup>.json` |
| The plugin loads in both harnesses | `uv run python scripts/proof_plugin_load.py` | `proofs/plugin/load.json` |
| The Codex hook gate | `uv run python scripts/proof_codex_gate.py`, then `--trusted` after the trust step | `proofs/codex-gate/gate.json` |
| Codex and the `OTEL_*` variables | `uv run python scripts/proof_codex_otel.py` | `proofs/otel/codex.json` |
| Benchmark under pressure | `uv run python bench/run.py mechanism claude-code` or `codex`, then `uv run python bench/score.py` | `bench/runs/`, `bench/results.json` |
| Worked evaluation | `uv run python scripts/example_evaluation.py` | `examples/toy-shop/evaluation.json` |

These scripts print `PASS` or `FAIL` and the path of their results file: `proofs_relay.py`, `proof_sessions.py`, `proof_trace.py`, `proof_backend.py`, `proof_model_api.py`, `proof_report.py` and `proof_telemetry.py`. The docstring of each script lists what it checks.

## After a run

1. Read the results file. A fail is a result too: keep it, and say why in [results.md](../results.md).
2. Update the tables in [results.md](../results.md) and the README from the results files. Do not edit a published result by hand.
3. Commit the results with the harness versions that they record.

A model answer changes on each run. The scripts store no model answer that can quote the harness's own instruction files. They check the text against the instruction files on the machine, and they remove local paths.

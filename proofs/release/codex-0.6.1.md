# Codex release proofs of 0.6.1

I ran the Codex proofs of the 0.6.1 release candidate on 2026-11-25, on macOS, in the worktree of the branch `claude/release-0.6.1`. The candidate is the same as for [the Claude Code proofs](claude-code-0.6.1.md). The tools were codex-cli 0.169.0, the same version as in [0.6.0](codex-0.6.0.md). CI has no Codex pin. Each result file records its tested versions.

Only the Codex hook gate proof ran with Codex for this release. The runs of both harnesses, the plugin load proof and the trace proof, are in [the Claude Code run notes](claude-code-0.6.1.md#runs-of-both-harnesses). The proof of the keys of a Codex hook in `hooks/list` uses no model, and it is in [the runs with no model](claude-code-0.6.1.md#runs-with-no-model).

## Runs

| Proof | Command | Result | Data |
|---|---|---|---|
| Hook gate, part A | `uv run python scripts/proof_codex_gate.py` | 8 of 8 checks pass, run 1 | [results](../codex-gate/gate.json) |
| Hook gate, part B | `uv run python scripts/proof_codex_gate.py --trusted`, after the owner trusts the 2 hooks | 5 of 5 checks pass, run 1 | [results](../codex-gate/gate.json) |

Part A has 2 more checks than in 0.6.0: each trust hash starts with `sha256:`, and a script change changes each trust hash with 2 parts ([#652](https://github.com/mohanraj00/nookku/issues/652)). Part A also found the plugin folder of 0.6.1 in the cache. Then the owner trusted the 2 hooks one time, and part B passed with `--trusted`. `gate.json` holds the results of both parts.

## The failed runs

No run failed.

## The carried records

The 0.6.1 changes that touch Codex are the refusal of a hook with `"async": true` ([#643](https://github.com/mohanraj00/nookku/issues/643)) and the change of the stdio tap ([#656](https://github.com/mohanraj00/nookku/issues/656)). The hook gate proof ran on 0.6.1, and the trusted hooks of this version pass the gate (part B). A message with no `X-Nookku-During` header goes through the tap as before, and the tap proofs with no model passed on 0.6.1 ([Claude Code run notes](claude-code-0.6.1.md#the-carried-records)). The relay proofs P1 to P4 did not run on 0.6.1.

Thus each record below is the 0.6.0 record. The [Codex run notes of 0.6.0](codex-0.6.0.md#runs) give each command, its run number and its data.

| Proof | Setup | 0.6.0 record |
|---|---|---|
| P1 to P4, with `--stream` and with `--stream --on-request` | plugin-codex, hooks-codex | [results](../plugin-codex/results.json), [results](../hooks-codex/results.json) and the 4 stream folders |
| `proof_codex_otel.py` |  | [results](../otel/codex.json) |
| `proof_codex_performance.py` |  | [results](../performance/codex-app.json) |
| P5, `proof_evaluation.py` | plugin-codex, hooks-codex | [results](../evaluation/plugin-codex.json), [results](../evaluation/hooks-codex.json) |
| P5 to P8, `proof_report.py` | plugin-codex, hooks-codex | [results](../report/plugin-codex.json), [results](../report/hooks-codex.json) |
| `proof_telemetry.py` | plugin-codex, hooks-codex | [results](../telemetry/plugin-codex.json), [results](../telemetry/hooks-codex.json) |
| `proof_performance.py` | plugin-codex, hooks-codex | [results](../performance/plugin-codex.json), [results](../performance/hooks-codex.json) |
| `proof_spec_classes.py` | plugin-codex, hooks-codex | [results](../spec-classes/plugin-codex.json), [results](../spec-classes/hooks-codex.json) |
| `proof_trace_points.py` | plugin-codex, hooks-codex | [results](../trace-points/plugin-codex.json), [results](../trace-points/hooks-codex.json) |
| `proof_egress.py`, also with `--evaluate` | plugin-codex, hooks-codex | [results](../egress/plugin-codex.json), [results](../egress/hooks-codex.json) and the 6 evaluation files |
| `bench/run.py mechanism codex` |  | [run](../../bench/runs/codex-mechanism/harness.json) |

## The proof in a Koodam Workspace

`scripts/proof_cluster.py plugin-codex` did not run for 0.6.1. The last result is from 0.5.7 and it failed at W4 ([results.md](../../docs/results.md#codex-in-a-koodam-workspace), [koodam#243](https://github.com/mohanraj00/koodam/issues/243)).

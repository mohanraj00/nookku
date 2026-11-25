# Codex release proofs of 0.6.0

The owner ran the Codex proofs of the 0.6.0 release candidate on macOS, in the main checkout of the repo at 9cbbbabe, as the proof method of the project hooks needs. The first run was on 2026-11-21, and the second run was on 2026-11-24, for each run that failed. The candidate is the same as for [the Claude Code proofs](claude-code-0.6.0.md). The tools were codex-cli 0.169.0, the same version as in [0.5.9](codex-0.5.9.md), and Docker 29.6.1 (client) and 29.5.2 (server). CI has no Codex pin. Each result file records its tested versions. The `claude-code` key of the Codex result files names the Claude Code 2.1.319 on `PATH`. The Codex proofs did not use it as a harness. The table gives the run that passed.

The runs of both harnesses, for example the trace proof and the plugin load proof, are in [the Claude Code run notes](claude-code-0.6.0.md#runs-of-both-harnesses).

## Runs

| Proof | Setup | Result | Data |
|---|---|---|---|
| Hook gate, part A |  | 6 of 6 checks pass, run 1 | [results](https://github.com/mohanraj00/nookku/blob/10469a24/proofs/codex-gate/gate.json) |
| Hook gate, part B |  | 5 of 5 checks pass, run 1 | [results](https://github.com/mohanraj00/nookku/blob/10469a24/proofs/codex-gate/gate.json) |
| P1 to P4 | plugin-codex | pass, run 1 | [results](../plugin-codex/results.json) |
| P1 to P4 | hooks-codex | pass, run 1 | [results](../hooks-codex/results.json) |
| P1 to P4, `--stream` | plugin-codex | pass, run 1 | [results](../plugin-codex-stream/results.json) |
| P1 to P4, `--stream` | hooks-codex | pass, run 1 | [results](../hooks-codex-stream/results.json) |
| P1 to P4, `--stream --on-request` | plugin-codex | pass, run 1 | [results](../plugin-codex-stream-on-request/results.json) |
| P1 to P4, `--stream --on-request` | hooks-codex | pass, run 1 | [results](../hooks-codex-stream-on-request/results.json) |
| `proof_codex_otel.py` |  | run 1, Codex does not read the variables | [results](../otel/codex.json) |
| `proof_codex_performance.py` |  | pass, run 1 | [results](../performance/codex-app.json) |
| P5, `proof_evaluation.py` | plugin-codex | pass, run 2 | [results](../evaluation/plugin-codex.json) |
| P5, `proof_evaluation.py` | hooks-codex | pass, run 1 | [results](../evaluation/hooks-codex.json) |
| P5 to P8, `proof_report.py` | plugin-codex | pass, run 2 | [results](../report/plugin-codex.json) |
| P5 to P8, `proof_report.py` | hooks-codex | pass, run 2 | [results](../report/hooks-codex.json) |
| `proof_telemetry.py` | plugin-codex | pass, run 2 | [results](../telemetry/plugin-codex.json) |
| `proof_telemetry.py` | hooks-codex | pass, run 2 | [results](../telemetry/hooks-codex.json) |
| `proof_performance.py` | plugin-codex | pass, run 2 | [results](../performance/plugin-codex.json) |
| `proof_performance.py` | hooks-codex | pass, run 2 | [results](../performance/hooks-codex.json) |
| `proof_spec_classes.py` | plugin-codex | pass, run 2 | [results](../spec-classes/plugin-codex.json) |
| `proof_spec_classes.py` | hooks-codex | pass, run 2 | [results](../spec-classes/hooks-codex.json) |
| `proof_trace_points.py` | plugin-codex | pass, run 2 | [results](../trace-points/plugin-codex.json) |
| `proof_trace_points.py` | hooks-codex | pass, run 2 | [results](../trace-points/hooks-codex.json) |
| `proof_egress.py` | plugin-codex | pass, run 2 | [results](../egress/plugin-codex.json) |
| `proof_egress.py` | hooks-codex | pass, run 2 | [results](../egress/hooks-codex.json) |
| `proof_egress.py --evaluate`, 1 of 3 | plugin-codex | pass | [results](../egress/plugin-codex-evaluation-run1.json), [test folder](../egress/evaluation/20261124-163743-7bf7/) |
| `proof_egress.py --evaluate`, 2 of 3 | plugin-codex | pass | [results](../egress/plugin-codex-evaluation-run2.json), [test folder](../egress/evaluation/20261124-164247-320d/) |
| `proof_egress.py --evaluate`, 3 of 3 | plugin-codex | pass | [results](../egress/plugin-codex-evaluation-run3.json), [test folder](../egress/evaluation/20261124-164810-6682/) |
| `proof_egress.py --evaluate`, 1 of 3 | hooks-codex | pass | [results](../egress/hooks-codex-evaluation-run1.json), [test folder](../egress/evaluation/20261124-164018-6bb0/) |
| `proof_egress.py --evaluate`, 2 of 3 | hooks-codex | pass | [results](../egress/hooks-codex-evaluation-run2.json), [test folder](../egress/evaluation/20261124-164517-e803/) |
| `proof_egress.py --evaluate`, 3 of 3 | hooks-codex | pass | [results](../egress/hooks-codex-evaluation-run3.json), [test folder](../egress/evaluation/20261124-165042-4534/) |
| `bench/run.py mechanism codex` |  | no new data: each of the 40 sessions of 2026-10-04 has a done `meta.json`, so the script skipped it | [run](../../bench/runs/codex-mechanism/harness.json) |

The hook gate ran before the other runs. The owner trusted the hooks one time, and the trust step did not run again for the second run. Part A now compares only the hook part of the trust hash, so the check that failed in 0.5.9 passes ([#613](https://github.com/mohanraj00/nookku/issues/613)).

`proof_egress.py --evaluate` ran 3 times for each setup, because a model report can miss the denied attempt. The 6 runs passed. `plugin-codex-evaluation.json` and `hooks-codex-evaluation.json` are the copies of run 3.

`proof_codex_otel.py` gives the same result as before: Codex does not send OpenTelemetry data from the `OTEL_*` variables of a test, and the receiver got 0 rows. The last record was from codex-cli 0.162.1.

## The failed runs

- **The weekly limit of the Claude account, run 1.** From about 00:52 UTC on 2026-11-21, each Claude model call returned HTTP 429 with a weekly limit text. The apps of the Codex proofs use the Claude Agent SDK, so the limit stopped the egress runs, the evaluation of the plugin, and the runs of the report, telemetry, performance, spec class and trace point proofs. No record of these runs is kept. Each run passed at run 2.

## The proof in a Koodam Workspace

`scripts/proof_cluster.py plugin-codex` did not run for 0.6.0. It needs a person to log in and to trust the hooks in the Workspace. The last result is from 0.5.7 and it failed at W4 ([results.md](../../docs/results.md#codex-in-a-koodam-workspace), [koodam#243](https://github.com/mohanraj00/koodam/issues/243)).

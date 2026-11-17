# Claude Code release proofs of 0.5.9

I ran the Claude Code proofs of the 0.5.9 release candidate on 2026-11-17, on macOS. The base is main at bad1f74d, plus the commit that sets the version to 0.5.9 (7a71d976). The tools were Claude Code 2.1.302, Docker 29.6.1 (client) and 29.5.2 (server), kind v0.33.0, kubectl v1.36.2, Kubernetes v1.37.0 and Python 3.13.12. CI pins Claude Code 2.1.302 ([ci.yml](../../.github/workflows/ci.yml)). The Claude Code on my machine is newer, so I installed 2.1.302 from npm in a separate folder and put it first on `PATH`. Each result file records its tested versions. I ran the 30 proofs of the table one time each, in sequence. Each run exited with 0, and each results file passes. No run failed.

## Runs

| Proof | Setup | Run 1 | Data |
|---|---|---|---|
| P1 to P4 | plugin-claude-code | pass | [results](../plugin-claude-code/results.json) |
| P1 to P4 | hooks-claude-code | pass | [results](../hooks-claude-code/results.json) |
| P1 to P4, `--stream` | plugin-claude-code | pass | [results](../plugin-claude-code-stream/results.json) |
| P1 to P4, `--stream` | hooks-claude-code | pass | [results](../hooks-claude-code-stream/results.json) |
| P1 to P4, chat page | page-claude-code | pass | [results](../page-claude-code/results.json) |
| P5 to P8, `proof_report.py` | plugin-claude-code | pass | [results](../report/plugin-claude-code.json) |
| P5 to P8, `proof_report.py` | hooks-claude-code | pass | [results](../report/hooks-claude-code.json) |
| `proof_telemetry.py` | plugin-claude-code | pass | [results](../telemetry/plugin-claude-code.json) |
| `proof_telemetry.py` | hooks-claude-code | pass | [results](../telemetry/hooks-claude-code.json) |
| `proof_performance.py` | plugin-claude-code | pass | [results](../performance/plugin-claude-code.json) |
| `proof_performance.py` | hooks-claude-code | pass | [results](../performance/hooks-claude-code.json) |
| `proof_spec_classes.py` | plugin-claude-code | pass | [results](../spec-classes/plugin-claude-code.json) |
| `proof_spec_classes.py` | hooks-claude-code | pass | [results](../spec-classes/hooks-claude-code.json) |
| `proof_trace_points.py` | plugin-claude-code | pass | [results](../trace-points/plugin-claude-code.json) |
| `proof_trace_points.py` | hooks-claude-code | pass | [results](../trace-points/hooks-claude-code.json) |
| `proof_egress.py` | plugin-claude-code | pass | [results](../egress/plugin-claude-code.json) |
| `proof_egress.py` | hooks-claude-code | pass | [results](../egress/hooks-claude-code.json) |
| `proof_egress.py --evaluate` | plugin-claude-code | pass | [results](../egress/plugin-claude-code-evaluation.json), [test folder](../egress/evaluation/20261117-153151-458d/) |
| `proof_egress.py --evaluate` | hooks-claude-code | pass | [results](../egress/hooks-claude-code-evaluation.json), [test folder](../egress/evaluation/20261117-154442-e219/) |
| P5, `proof_evaluation.py` | plugin-claude-code | pass | [results](../evaluation/plugin-claude-code.json) |
| P5, `proof_evaluation.py` | hooks-claude-code | pass | [results](../evaluation/hooks-claude-code.json) |
| `proof_backend.py` | | pass | [results](../backend/results.json) |
| `proof_model_api.py` | | pass | [results](../model-api/results.json) |
| `proof_driver_trace.py` | | pass | [results](../driver-trace/results.json) |
| `proof_queue_trace.py` | | pass | [results](../queue-trace/results.json) |
| `proof_api_hello.py` | | pass | [results](../model-api/hello.json) |
| `proof_tutorial.py --model` | | pass | [run](../tutorial/run.json), [output](../tutorial/output.txt) |
| `proof_setup.py` | | pass | [results](../setup/results.json) |
| `proof_simulated_user.py` | | pass | [results](../simulated-user/results.json) |
| `proof_cluster_tap.py` | | pass | [results](../cluster-tap/results.json) |

The 2 runs with `--evaluate` made new test folders. I kept the folders of 0.5.8, because [the 0.5.8 notes](claude-code-0.5.8.md) link them. `proof_cluster_tap.py` ran its 3 forms: `same-pod`, `service` and `default-deny` ([records](../cluster-tap/)). `proof_queue_trace.py` and `proof_simulated_user.py` are new in the table. `proof_queue_trace.py` ran the app with and without the instrumentation of pika, and it needs Docker for RabbitMQ. `proof_simulated_user.py` ran 1 turn and ended at the goal.

Some result files have the key `"session files": "2.1.301"`. This key gives the newest Claude Code version that the trace reader of the session files covers. It is not the version that ran. The setup proof answer in [results.json](../setup/results.json) names Claude Code 2.1.326. That is the Claude Code that the Agent SDK of the toy shop app bundles, not the harness. The harness recorded 2.1.302.

## The scripted verdict test

I ran the 2 scripted tests of the verdict with no model, as in [0.5.8](claude-code-0.5.8.md#the-scripted-verdict-test). The projects, the script and the commands are the same.

| Project | Audit | Verdict line | Exit code | Data |
|---|---|---|---|---|
| Pass | exit 0 | `Verdict: pass (2 limits).` | 0 | [verdict.json](verdict-0.5.9/pass.json) |
| Defect | exit 0 | `Verdict: fail. repeated_reply: 2, the limit is 1.` | 1 | [verdict.json](verdict-0.5.9/repeat-defect.json) |

The results are the same as in 0.5.8. Each `verdict.json` now has 4 more rows in `classes`: `citation_not_read`, `answer_key_mismatch`, `answer_key_missing` and `other_without_span`, each with count 0 and no limit.

## The seeded faults

`uv run nookku faults --json` ran on the release candidate with no model. It found 78 of 78 faults in 42 cases, and each of the 29 checks has a fault ([data](faults-0.5.9.json)).

## The proof in a Koodam Workspace

`scripts/proof_cluster.py plugin-claude-code` did not run for 0.5.9. It needs 1 person step: the login of Claude Code in the Workspace. The last result is from 0.5.7 ([notes](claude-code-0.5.7.md#the-proof-in-a-koodam-workspace)). The CI job `kind-testkey` runs the test key of a Workspace on kind with no login.

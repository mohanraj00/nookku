# Claude Code release proofs of 0.5.8

I ran the Claude Code proofs of the 0.5.8 release candidate on 2026-11-12, on macOS. The base is main at 0431751, plus the commit that sets the version to 0.5.8 ([cd2e261](https://github.com/mohanraj00/nookku/commit/cd2e261b68)). The tools were Claude Code 2.1.302, Docker 29.5.2, kind v0.33.0, kubectl v1.36.2 and Kubernetes v1.37.0. CI pins Claude Code 2.1.302, so I used this version and not the newest one. Each result file records its tested versions. I ran the 28 proofs of the table one time each, in sequence. Each run exited with 0, and each results file passes.

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
| `proof_egress.py --evaluate` | plugin-claude-code | pass | [results](../egress/plugin-claude-code-evaluation.json), [test folder](../egress/evaluation/20261112-085104-d36c/) |
| `proof_egress.py --evaluate` | hooks-claude-code | pass | [results](../egress/hooks-claude-code-evaluation.json), [test folder](../egress/evaluation/20261112-085331-a51b/) |
| P5, `proof_evaluation.py` | plugin-claude-code | pass | [results](../evaluation/plugin-claude-code.json) |
| P5, `proof_evaluation.py` | hooks-claude-code | pass | [results](../evaluation/hooks-claude-code.json) |
| `proof_backend.py` | | pass | [results](../backend/results.json) |
| `proof_model_api.py` | | pass | [results](../model-api/results.json) |
| `proof_driver_trace.py` | | pass | [results](../driver-trace/results.json) |
| `proof_api_hello.py` | | pass | [results](../model-api/hello.json) |
| `proof_tutorial.py --model` | | pass | [run](../tutorial/run.json), [output](../tutorial/output.txt) |
| `proof_setup.py` | | pass | [results](../setup/results.json) |
| `proof_cluster_tap.py` | | pass | [results](../cluster-tap/results.json) |

I ran the 26 proofs first. The 2 runs with `--evaluate` ran later on the same day, after I found that the first set did not have them. Their test folders replace the folders of 0.5.7 in the table. I kept the 0.5.7 folders, because [the 0.5.7 notes](claude-code-0.5.7.md) link them. `proof_cluster_tap.py` ran its 3 forms: `same-pod`, `service` and `default-deny` ([records](../cluster-tap/)). It deleted its kind cluster at the end.

The Python version changed during the day. The first 26 proofs ran with Python 3.12.13 ([hello.json](../model-api/hello.json)). Then I made the virtual environment again with Python 3.13.12, because its scripts still named the old folder of the repo. The 2 runs with `--evaluate` used Python 3.13.12.

Some result files have the key `"session files": "2.1.301"`. This key gives the newest Claude Code version that the trace reader of the session files covers. It is not the version that ran.

## The scripted verdict test

I ran the 2 scripted tests of the verdict with no model, as in [0.5.7](claude-code-0.5.7.md#the-scripted-verdict-test). The projects, the script and the commands are the same.

| Project | Audit | Verdict line | Exit code | Data |
|---|---|---|---|---|
| Pass | exit 0 | `Verdict: pass (2 limits).` | 0 | [verdict.json](verdict-0.5.8/pass.json) |
| Defect | exit 0 | `Verdict: fail. repeated_reply: 2, the limit is 1.` | 1 | [verdict.json](verdict-0.5.8/repeat-defect.json) |

## The proof in a Koodam Workspace

`scripts/proof_cluster.py plugin-claude-code` did not run for 0.5.8 yet. It needs 1 person step: the login of Claude Code in the Workspace. The last result is from 0.5.7 ([notes](claude-code-0.5.7.md#the-proof-in-a-koodam-workspace)).

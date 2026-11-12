# Codex release proofs of 0.5.8

I ran the Codex proofs of the 0.5.8 release candidate on 2026-11-12, on macOS, in the main checkout. The candidate is the same as for [the Claude Code proofs](claude-code-0.5.8.md). The tools were codex-cli 0.162.1 and Docker 29.5.2. Each result file records its tested versions. The script ran each proof again 1 time if it failed. The table gives the run that passed.

## Runs

| Proof | Setup | Result | Data |
|---|---|---|---|
| Hook gate, parts A and B | | pass, run 1 | [results](../codex-gate/gate.json) |
| P1 to P4 | plugin-codex | pass, run 1 | [results](../plugin-codex/results.json) |
| P1 to P4 | hooks-codex | pass, run 3 | [results](../hooks-codex/results.json) |
| P1 to P4, `--stream` | plugin-codex | pass, run 1 | [results](../plugin-codex-stream/results.json) |
| P1 to P4, `--stream` | hooks-codex | pass, run 3 | [results](../hooks-codex-stream/results.json) |
| P1 to P4, `--stream --on-request` | plugin-codex | pass, run 1 | [results](../plugin-codex-stream-on-request/results.json) |
| P1 to P4, `--stream --on-request` | hooks-codex | pass, run 3 | [results](../hooks-codex-stream-on-request/results.json) |
| P5 to P8, `proof_report.py` | plugin-codex | pass, run 1 | [results](../report/plugin-codex.json) |
| P5 to P8, `proof_report.py` | hooks-codex | pass, run 5 | [results](../report/hooks-codex.json) |
| `proof_telemetry.py` | plugin-codex | pass, run 1 | [results](../telemetry/plugin-codex.json) |
| `proof_telemetry.py` | hooks-codex | pass, run 5 | [results](../telemetry/hooks-codex.json) |
| `proof_performance.py` | plugin-codex | pass, run 2 | [results](../performance/plugin-codex.json) |
| `proof_performance.py` | hooks-codex | pass, run 5 | [results](../performance/hooks-codex.json) |
| `proof_spec_classes.py` | plugin-codex | pass, run 1 | [results](../spec-classes/plugin-codex.json) |
| `proof_spec_classes.py` | hooks-codex | pass, run 5 | [results](../spec-classes/hooks-codex.json) |
| `proof_trace_points.py` | plugin-codex | pass, run 1 | [results](../trace-points/plugin-codex.json) |
| `proof_trace_points.py` | hooks-codex | pass, run 3 | [results](../trace-points/hooks-codex.json) |
| `proof_egress.py` | plugin-codex | pass, run 1 | [results](../egress/plugin-codex.json) |
| `proof_egress.py` | hooks-codex | pass, run 3 | [results](../egress/hooks-codex.json) |
| `proof_egress.py --evaluate` | plugin-codex | pass, run 2 | [results](../egress/plugin-codex-evaluation.json), [test folder](../egress/evaluation/20261112-063827-4587/) |
| `proof_egress.py --evaluate` | hooks-codex | pass, run 3 | [results](../egress/hooks-codex-evaluation.json), [test folder](../egress/evaluation/20261112-080836-d58f/) |
| P5, `proof_evaluation.py` | plugin-codex | pass, run 1 | [results](../evaluation/plugin-codex.json) |
| P5, `proof_evaluation.py` | hooks-codex | pass, run 3 | [results](../evaluation/hooks-codex.json) |

## The failed runs

A run that passed replaced the result file of the run before it. So the data of a failed run is only in my run logs, except where this section names a folder.

- **plugin-codex, `proof_performance.py`.** Run 1 failed S2 and S4: a turn other than the slow turn was also above the limit. Run 2 passed.
- **plugin-codex, `proof_egress.py --evaluate`.** In run 1, the report did not have the denied attempt in its notes (`denied_in_notes: false`). Its test folder is [`20261112-063637-0d30`](../egress/evaluation/20261112-063637-0d30/). Run 2 passed.
- **hooks-codex, all 11 proofs, runs 1 and 2.** No test started. The repo moved from the folder `verbatim-relay` to the folder `nookku`. Codex keeps the trust of a hook with its path, so the trust of the old hooks did not apply. The evaluation project also had hooks with the old path of Python. I wrote the hooks again with `nookku init codex`, and the maintainer trusted them again. A stale Codex daemon of the old path also stopped the trust step, and the maintainer did the trust step with `--no-daemon`.
- **hooks-codex, `proof_report.py`, `proof_telemetry.py`, `proof_performance.py` and `proof_spec_classes.py`, runs 3 and 4.** The test ran, but the prompt `nookku end` started no evaluation. The failed runs had left 14 test folders with no `manifest.json` in the proof project. Nookku sorts such a folder as the newest test, so it found no ended test to evaluate. I moved the 14 folders out of the project. Then each of the 4 proofs passed at the next run.

A folder with no manifest stops each later evaluation in its project. This is a gap of the product, not of the proofs, and it is not fixed in 0.5.8.

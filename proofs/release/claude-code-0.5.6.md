# Claude Code release proofs of 0.5.6

I ran the Claude Code proofs of the 0.5.6 release candidate on 2026-10-23, on macOS. The base is main at 7512cfc, plus the commit that sets the version to 0.5.6. The tools were Claude Code 2.1.302, Docker 29.5.2 and kind v0.33.0. Each result file records its tested versions. I ran each proof one time, in sequence. If a proof failed, I ran it 1 more time with no change.

## Runs

| Proof | Setup | Run 1 | Run 2 | Data |
|---|---|---|---|---|
| P1 to P4 | plugin-claude-code | pass | | [results](../plugin-claude-code/results.json) |
| P1 to P4 | hooks-claude-code | pass | | [results](../hooks-claude-code/results.json) |
| P1 to P4, `--stream` | plugin-claude-code | pass | | [results](../plugin-claude-code-stream/results.json) |
| P1 to P4, `--stream` | hooks-claude-code | pass | | [results](../hooks-claude-code-stream/results.json) |
| P1 to P4, chat page | page-claude-code | pass | | [results](../page-claude-code/results.json) |
| P5 to P8, `proof_report.py` | plugin-claude-code | pass | | [results](../report/plugin-claude-code.json) |
| P5 to P8, `proof_report.py` | hooks-claude-code | error | pass | [results](../report/hooks-claude-code.json) |
| `proof_telemetry.py` | plugin-claude-code | error | error | no results file |
| `proof_telemetry.py` | hooks-claude-code | error | error | no results file |
| `proof_performance.py` | plugin-claude-code | error | error | no results file |
| `proof_performance.py` | hooks-claude-code | error | error | no results file |
| `proof_spec_classes.py` | plugin-claude-code | error | error | no results file |
| `proof_spec_classes.py` | hooks-claude-code | error | error | no results file |
| `proof_trace_points.py` | plugin-claude-code | error | error | no results file |
| `proof_trace_points.py` | hooks-claude-code | error | error | no results file |
| `proof_egress.py` | plugin-claude-code | pass | | [results](../egress/plugin-claude-code.json) |
| `proof_egress.py` | hooks-claude-code | error | error | no results file |
| P5, `proof_evaluation.py` | plugin-claude-code | pass | | [results](../evaluation/plugin-claude-code.json) |
| P5, `proof_evaluation.py` | hooks-claude-code | pass | | [results](../evaluation/hooks-claude-code.json) |
| `proof_backend.py` | | pass | | [results](../backend/results.json) |
| `proof_model_api.py` | | pass | | [results](../model-api/results.json) |
| `proof_driver_trace.py` | | pass | | [results](../driver-trace/results.json) |
| `proof_api_hello.py` | | pass | | [results](../model-api/hello.json) |
| `proof_tutorial.py --model` | | pass | | [run](../tutorial/run.json), [output](../tutorial/output.txt) |
| `proof_setup.py` | | **fail** (S2) | pass | [run 1](../setup/results-run1.json), [run 2](../setup/results.json) |
| `proof_cluster_tap.py` | | pass | | [results](../cluster-tap/results.json) |

The run of `proof_api_hello.py` gave the same `hello.json` as before, so the file did not change. `proof_cluster_tap.py` deleted its kind cluster at the end.

## The error of the proof scripts

An "error" run stopped before it wrote a results file. Each of the 19 error runs stopped with the same Python error, in `tool_calls` of [proof_report.py](../../scripts/proof_report.py):

```text
AttributeError: 'str' object has no attribute 'get'
```

`tool_calls` reads the `claude -p` stream-json events. It expects the key `message` of each event to be an object. Claude Code 2.1.302 has a `system` event with the subtype `permission_denied`, and its key `message` is a string. I found this event in the program of Claude Code 2.1.302. When the guard denies a tool call of the model, this event can come, and `tool_calls` stops with the error.

The scripts keep no stream-json output, so I could not see the denied call of each run. The tutorial run gives one example: its report says that the guard denied a shell `for` loop of the evaluating model that named the test folder ([output](../tutorial/output.txt)). Since [#497](https://github.com/mohanraj00/nookku/issues/497), the guard also denies commands that name the test folder. That can explain why the 0.5.5 runs with the same Claude Code version passed and these runs stopped. I did not change the script. The fix is outside the scope of this run.

## The fail of the setup proof

[Run 1](../setup/results-run1.json) failed S2. The summary of answer 1 named the backends as "Backends" and the stores as "Data files". S2 looks for the words `backend` and `store`, so it did not find 2 of the 5 parts. S1, S3 and S4 passed. [Run 2](../setup/results.json), with no change, passed.

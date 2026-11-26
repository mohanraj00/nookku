# Claude Code release proofs of 0.6.0

I ran the proofs of the 0.6.0 release candidate on 2026-11-21, on macOS. The base is main at 42fe7a38, plus the commit that sets the version to 0.6.0 (55be61a5). Later I merged main at de2efe77 into the branch, for #519. The tools were Claude Code 2.1.319 and Python 3.13.12. CI pinned Claude Code 2.1.302 at the start. I did not install the older version for these runs, so the records name 2.1.319. This release changes the pin of CI to 2.1.319 ([ci.yml](../../.github/workflows/ci.yml)).

This file has the runs with no model, the Claude Code runs with the model, the runs with Docker and kind, and the runs of both harnesses. The Codex runs are in [the Codex run notes](codex-0.6.0.md).

## Runs with no model

| Proof | Run 1 | Data |
|---|---|---|
| `proof_backend.py` | pass | [results](../backend/results.json) |
| `proof_model_api.py` | pass | [results](../model-api/results.json) |
| `proof_api_hello.py` | pass | [results](../model-api/hello.json) |
| `proof_approvals.py` | pass | [results](../approvals/results.json) |
| `proof_second_message.py` | pass | [results](../second-message/results.json) |
| `proof_replay.py` | pass | [results](../replay/results.json) |
| `proof_driver_trace.py` | pass | [results](../driver-trace/results.json) |
| `proof_inapp_trace.py` | pass | [results](../inapp-trace/results.json) |
| `proof_mcp_tasks.py` | pass | [results](../mcp-tasks/results.json) |
| `proof_openinference.py` | pass | [results](../openinference/results.json) |
| `proof_tap_streams.py` | pass | [results](../tap-streams/results.json) |
| `release_samples.py` | pass | [results](../release-samples/results.json) |
| `proof_sdk_bundles.py 0.2.163 0.2.164 0.2.165 0.2.166 0.2.167 0.2.168` | pass | [results](../trace/sdk-bundles.json) |
| `proof_rollout_gate.py` | pass | [results](../rollout-gate/results.json) |

I ran `proof_rollout_gate.py` on 2026-11-24, after the merge of main. The merge changed no file in `src/` and no other proof script, so the other runs stay valid.

`proof_sdk_bundles.py` found the same 6 rows as before. Only the date changed. Claude Agent SDK 0.2.168 bundles Claude Code 2.1.301.

## The scripted verdict test

I ran the 2 scripted tests of the verdict with no model, as in [0.5.7](claude-code-0.5.7.md#the-scripted-verdict-test). The projects, the script and the commands are the same.

| Project | Audit | Verdict line | Exit code | Data |
|---|---|---|---|---|
| Pass | exit 0 | `Verdict: pass (2 limits).` | 0 | [verdict.json](verdict-0.6.0/pass.json) |
| Defect | exit 0 | `Verdict: fail. repeated_reply: 2, the limit is 1.` | 1 | [verdict.json](verdict-0.6.0/repeat-defect.json) |

The results are the same as in [0.5.9](claude-code-0.5.9.md#the-scripted-verdict-test). Each `verdict.json` now has 4 more rows in `classes`: `replay_changed`, `replay_miss`, `action_without_approval` and `call_cut`, each with count 0 and no limit.

## The seeded faults

`uv run nookku faults --json` ran on the release candidate with no model. It found 96 of 96 faults in 48 cases, and each of the 33 checks has a fault ([data](faults-0.6.0.json)). In 0.5.9 it found 78 of 78 faults in 42 cases, with 29 checks ([data](faults-0.5.9.json)).

The 6 new cases have 18 faults:

| Case | Faults | Checks |
|---|---|---|
| `approvals_elicitation` | 5 | `action_without_approval`, `item_between_turns` |
| `approvals_interrupt` | 4 | `action_without_approval` |
| `approvals_not_valid` | 1 | `action_without_approval` |
| `replay_recorded` | 3 | `replay_changed`, `replay_miss`, `backend_error` |
| `second_message` | 3 | `call_cut`, `tool_error`, `backend_error` |
| `answer_key_rules` | 2 | `answer_key_mismatch` |

The 4 new checks are `action_without_approval`, `call_cut`, `replay_changed` and `replay_miss`. No case and no check of 0.5.9 is gone.

## Runs with the model

The owner ran these proofs in the main checkout of the repo. The first run was on 2026-11-21 at 9cbbbabe. The second run was on 2026-11-24 at 9cbbbabe, for each run that failed. The third run was on 2026-11-24 in the worktree of the release branch at a1338666, for the 3 runs that failed again. Each result file records its tested versions. The table gives the run that passed.

| Proof | Setup | Result | Data |
|---|---|---|---|
| P1 to P4 | plugin-claude-code | pass, run 1 | [results](../plugin-claude-code/results.json) |
| P1 to P4 | hooks-claude-code | pass, run 1 | [results](../hooks-claude-code/results.json) |
| P1 to P4, `--stream` | plugin-claude-code | pass, run 1 | [results](../plugin-claude-code-stream/results.json) |
| P1 to P4, `--stream` | hooks-claude-code | pass, run 1 | [results](../hooks-claude-code-stream/results.json) |
| P1 to P4, `--stream --on-request` | plugin-claude-code | pass, run 1 | [results](../plugin-claude-code-stream-on-request/results.json) |
| P1 to P4, `--stream --on-request` | hooks-claude-code | pass, run 1 | [results](../hooks-claude-code-stream-on-request/results.json) |
| P1 to P4 and P5, chat page | page-claude-code | pass, run 2 | [results](../page-claude-code/results.json) |
| `proof_key_guard.py` | plugin-claude-code | pass, run 1 | [results](../key-guard/plugin-claude-code.json) |
| `proof_key_guard.py` | hooks-claude-code | pass, run 1 | [results](../key-guard/hooks-claude-code.json) |
| P5, `proof_evaluation.py` | plugin-claude-code | pass, run 1 | [results](../evaluation/plugin-claude-code.json) |
| P5, `proof_evaluation.py` | hooks-claude-code | pass, run 1 | [results](../evaluation/hooks-claude-code.json) |
| P5 to P8, `proof_report.py` | plugin-claude-code | pass, run 1 | [results](../report/plugin-claude-code.json) |
| P5 to P8, `proof_report.py` | hooks-claude-code | pass, run 1 | [results](../report/hooks-claude-code.json) |
| `proof_telemetry.py` | plugin-claude-code | pass, run 1 | [results](../telemetry/plugin-claude-code.json) |
| `proof_telemetry.py` | hooks-claude-code | pass, run 1 | [results](../telemetry/hooks-claude-code.json) |
| `proof_performance.py` | plugin-claude-code | pass, run 1 | [results](../performance/plugin-claude-code.json) |
| `proof_performance.py` | hooks-claude-code | pass, run 1 | [results](../performance/hooks-claude-code.json) |
| `proof_spec_classes.py` | plugin-claude-code | pass, run 1 | [results](../spec-classes/plugin-claude-code.json) |
| `proof_spec_classes.py` | hooks-claude-code | pass, run 1 | [results](../spec-classes/hooks-claude-code.json) |
| `proof_trace_points.py` | plugin-claude-code | pass, run 1 | [results](../trace-points/plugin-claude-code.json) |
| `proof_trace_points.py` | hooks-claude-code | pass, run 1 | [results](../trace-points/hooks-claude-code.json) |
| `proof_egress.py` | plugin-claude-code | pass, run 2 | [results](../egress/plugin-claude-code.json) |
| `proof_egress.py` | hooks-claude-code | pass, run 2 | [results](../egress/hooks-claude-code.json) |
| `proof_egress.py --evaluate` | plugin-claude-code | pass, run 2 | [results](../egress/plugin-claude-code-evaluation.json), [test folder](../egress/evaluation/20261124-160646-5780/) |
| `proof_egress.py --evaluate` | hooks-claude-code | pass, run 2 | [results](../egress/hooks-claude-code-evaluation.json), [test folder](../egress/evaluation/20261124-160913-6a7e/) |
| `proof_simulated_user.py` |  | pass, run 1 | [results](../simulated-user/results.json) |
| `proof_setup.py` |  | pass, run 1 | [results](../setup/results.json) |
| `proof_tutorial.py --model` |  | pass, run 1 | [run](../tutorial/run.json), [output](../tutorial/output.txt) |
| `example_evaluation.py` |  | pass, run 2 | [results](../../examples/toy-shop/evaluation.json) |
| `bench/run.py mechanism claude-code` |  | no new data: each of the 40 sessions of 2026-10-04 has a done `meta.json`, so the script skipped it | [run](../../bench/runs/claude-code-mechanism/harness.json) |

## Runs of both harnesses

| Proof | Result | Data |
|---|---|---|
| `proof_sessions.py` | pass, run 1 | [results](../sessions/results.json) |
| `proof_plugin_load.py` | 1 Codex check fails, run 2 | [results at the tag v0.6.0](https://github.com/mohanraj00/nookku/blob/v0.6.0/proofs/plugin/load.json) |
| `proof_trace.py` | pass, run 3 | [results](../trace/results.json) |
| `bench/score.py` | no new data: the scores are of the 2026-10-04 runs. I did not commit the new version labels | [results](../../bench/results.json) |

## Runs with Docker and kind

These runs use no model. They did not run on 2026-11-21, so their run 1 was on 2026-11-24. The tools were Docker 29.6.1 (client) and 29.5.2 (server), and kind v0.33.0. The `date` of `kind.json` is 2026-11-25, because the script writes the date in UTC.

| Proof | Result | Data |
|---|---|---|
| `proof_queue_trace.py` | pass, run 1 | [results](../queue-trace/results.json) |
| `proof_gateway.py` | pass, run 1 | [results](../gateway/results.json) |
| `proof_cluster_tap.py` | pass, run 2 | [results](../cluster-tap/results.json) |
| `kind_testkey.py` | pass, run 1 | [results](../testkey/kind.json) |

## The failed runs

No record of a failed run is kept, except where a row above names it. Each failure came from the run environment or from a proof method, except the failure of the trace proof at run 2.

- **The weekly limit of the Claude account, run 1.** From about 00:52 UTC on 2026-11-21, each Claude model call returned HTTP 429 with a weekly limit text. This failed the Claude Code egress runs with `--evaluate`, steps P3b and P3c of `page-claude-code`, the plugin load proof, the trace proof and the worked example. It also failed the Codex runs of the [Codex run notes](codex-0.6.0.md#the-failed-runs), because the apps of the Codex proofs use the Claude Agent SDK.
- **The host port of Postgres, run 1.** In the 2 plain egress runs, the database proxy got "Connection refused" from `127.0.0.1:55432`, so `lookup_order` failed. `src/nookku/db_proxy.py` has no change since 0.5.9. Before run 2, a check of the port passed, and both runs passed. The proof checks that Postgres is ready only in the container ([#660](https://github.com/mohanraj00/nookku/issues/660)).
- **`proof_cluster_tap.py`, run 1.** Docker had no copy of the image `python:3.12-slim`, and the proof runs it with `--pull=never`, so it stopped before the build. The owner pulled the image, and run 2 passed. The docs do not say that the proof needs the image first ([#662](https://github.com/mohanraj00/nookku/issues/662)).
- **`proof_trace.py`, run 2.** The Codex sessions of the run were from codex-cli 0.169.0, and the tested range of the trace stopped at 0.162.1. Thus each Codex session gave the note `version_untested`, and the proof failed. This was a defect of the trace. This release adds 0.169.0 to the tested range, and run 3 passed ([#525](https://github.com/mohanraj00/nookku/issues/525)). The record of 0.162.1 is [results-0.162.1.json](../trace/results-0.162.1.json).
- **`proof_plugin_load.py`, run 2.** Each Claude Code check passed. The Codex check "the MCP server starts in the project" failed, and each other Codex check passed. The proof lists the MCP servers before it starts a thread, and codex-cli 0.169.0 then starts them in `CODEX_HOME`. In a thread, the server starts in the project. This is a defect of the proof method, not of the plugin. I did not change the proof in this release ([#661](https://github.com/mohanraj00/nookku/issues/661)).

## The proof in a Koodam Workspace

`scripts/proof_cluster.py` did not run for 0.6.0. The harness pod moves to 0.6.1. The last result is from 0.5.7 ([notes](claude-code-0.5.7.md#the-proof-in-a-koodam-workspace)).

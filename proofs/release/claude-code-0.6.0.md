# Claude Code release proofs of 0.6.0

I ran the proofs of the 0.6.0 release candidate on 2026-11-21, on macOS. The base is main at 42fe7a38, plus the commit that sets the version to 0.6.0 (55be61a5). The tools were Claude Code 2.1.319 and Python 3.13.12. CI pins Claude Code 2.1.302 ([ci.yml](../../.github/workflows/ci.yml)). I did not install the older version for these runs, so the records name 2.1.319.

This file has the runs with no model. The runs with the model, with Codex, with Docker and with a person come next, on the same branch.

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

## The proof in a Koodam Workspace

`scripts/proof_cluster.py` did not run for 0.6.0. The harness pod moves to 0.6.1. The last result is from 0.5.7 ([notes](claude-code-0.5.7.md#the-proof-in-a-koodam-workspace)).

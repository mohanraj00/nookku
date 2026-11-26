# Claude Code release proofs of 0.6.1

I ran the proofs of the 0.6.1 release candidate on 2026-11-25, on macOS, in the worktree of the branch `claude/release-0.6.1`. The base is main at 97ac3731, plus the commit that sets the version to 0.6.1. The tools were Claude Code 2.1.319, codex-cli 0.169.0, Python 3.13.12, Docker 29.6.1 (client) and 29.5.2 (server), kind v0.33.0 and kubectl v1.36.2. These are the harness versions of [0.6.0](claude-code-0.6.0.md), and CI still pins Claude Code 2.1.319. Each result file records its tested versions.

The owner agreed to this set of runs: each proof with no model, the seeded faults, and 3 proofs with the model, `proof_plugin_load.py`, `proof_codex_gate.py` and `proof_trace.py`. Each model proof had 1 run, and 1 more run only after a fail. Each other proof carries its 0.6.0 record. [The carried records](#the-carried-records) give each record and the reason.

This file has the runs with no model, the runs of both harnesses, and the runs with Docker and kind. The Codex runs are in [the Codex run notes](codex-0.6.1.md).

## Runs with no model

Each command ran from the root of the worktree.

| Proof | Command | Result | Data |
|---|---|---|---|
| Backend proxy | `uv run python scripts/proof_backend.py` | pass, run 1 | [results](../backend/results.json) |
| Model API proxy | `uv run python scripts/proof_model_api.py` | pass, run 1 | [results](../model-api/results.json) |
| `HEAD /api/hello` of Claude Code | `uv run python scripts/proof_api_hello.py` | pass, run 1 | [results](../model-api/hello.json) |
| Timeout of a `UserPromptSubmit` hook | `uv run python scripts/proof_hook_timeout.py` | pass, run 1 | [results](../hook-timeout/claude-code.json) |
| Action with no approval | `uv run python scripts/proof_approvals.py` | pass, run 1 | [results](../approvals/results.json) |
| Second message during a slow turn | `uv run python scripts/proof_second_message.py` | pass, run 1 | [results](../second-message/results.json) |
| Replay with the recorded backends | `uv run python scripts/proof_replay.py` | pass, run 1 | [results](../replay/results.json) |
| Rollout gate | `uv run python scripts/proof_rollout_gate.py` | pass, run 1 | [results](../rollout-gate/results.json) |
| Driver trace of a database | `uv run python scripts/proof_driver_trace.py` | pass, run 1 | [results](../driver-trace/results.json) |
| Call that the in-app trace does not show | `uv run python scripts/proof_inapp_trace.py` | pass, run 1 | [results](../inapp-trace/results.json) |
| MCP tasks | `uv run python scripts/proof_mcp_tasks.py` | pass, run 1 | [results](../mcp-tasks/results.json) |
| OpenInference import | `uv run python scripts/proof_openinference.py` | pass, run 1 | [results](../openinference/results.json) |
| Tap of each streamed transport | `uv run python scripts/proof_tap_streams.py` | pass, run 1 | [results](../tap-streams/results.json) |
| Koodam release samples | `uv run python scripts/release_samples.py` | pass, run 1 | [results](../release-samples/results.json) |
| Claude Code of each Agent SDK release | `uv run python scripts/proof_sdk_bundles.py 0.2.163 0.2.164 0.2.165 0.2.166 0.2.167 0.2.168` | pass, run 1 | [results](../trace/sdk-bundles.json) |
| Keys of a Codex hook in `hooks/list` | `uv run python scripts/proof_codex_hook_keys.py` | pass, run 1 | [results](../codex-gate/hook-keys.json) |
| Output of the tutorial | `uv run python scripts/proof_tutorial.py` | pass, run 1 | [run](tutorial-0.6.1/run.json), [output](tutorial-0.6.1/output.txt) |

`proof_second_message.py` ran on the code of [#656](https://github.com/mohanraj00/nookku/issues/656). The tap gave message 2 to the entry 0.498 seconds after message 1, and the reply of turn 1 came at 0.518 seconds. In 0.6.0, these times were 0.435 and 0.445 seconds. The checks of the proof did not change.

`proof_sdk_bundles.py` found the same 6 rows as in 0.6.0. Only the date changed.

`proof_tutorial.py` with no model writes `proofs/tutorial/`, and replaces the record of the `--model` run of 0.6.0. [getting-started.md](../../docs/getting-started.md) and its doc tests use that record, and this release does not run the `--model` form. So I moved the 2 files of this run to [tutorial-0.6.1/](tutorial-0.6.1/), and `proofs/tutorial/` keeps the record of 0.6.0.

## The seeded faults

`uv run nookku faults --json > proofs/release/faults-0.6.1.json` ran with no model, at run 1. It found 97 of 97 faults in 49 cases, and each of the 33 checks has a fault ([data](faults-0.6.1.json)). In 0.6.0 it found 96 of 96 faults in 48 cases, with 33 checks ([data](faults-0.6.0.json)).

The new case is `approvals_null`, with 1 fault for the check `action_without_approval` ([#640](https://github.com/mohanraj00/nookku/issues/640)). No case and no check of 0.6.0 is gone.

## Runs of both harnesses

| Proof | Command | Result | Data |
|---|---|---|---|
| Plugin load | `uv run python scripts/proof_plugin_load.py` | 18 of 18 checks pass, run 1 | [results](../plugin/load.json) |
| Trace of the model sessions | `uv run python scripts/proof_trace.py` | pass, run 1 | [results](../trace/results.json) |

The plugin load proof now starts a Codex thread before the MCP check ([#661](https://github.com/mohanraj00/nookku/issues/661)). The Codex check "the MCP server starts in the project" failed in 0.6.0, and it passes now. The 9 Claude Code checks and the 9 Codex checks pass.

The trace proof read session files of Claude Code 2.1.301, bundled in Claude Agent SDK 0.2.168, and of codex-cli 0.169.0. It found each of the 6 expected calls. The findings are the same as in 0.6.0: 2 `tool_error`, 3 `command_failed` and 1 `session_inferred`. The Claude Code session has 10 items, and the Codex session has 18 items.

## Runs with Docker and kind

These runs use no model.

| Proof | Command | Result | Data |
|---|---|---|---|
| Client trace of a queue | `uv run python scripts/proof_queue_trace.py` | pass, run 1 | [results](../queue-trace/results.json) |
| LiteLLM gateway logs | `uv run python scripts/proof_gateway.py` | pass, run 1 | [results](../gateway/results.json) |
| HTTP tap at a cluster Service URL | `uv run python scripts/proof_cluster_tap.py` | pass, run 1 | [results](../cluster-tap/results.json) |
| Koodam TestKey on kind | `uv run python scripts/kind_testkey.py --out proofs/testkey/kind.json` | pass, run 1 | [results](../testkey/kind.json) |

## The failed runs

No run failed.

## The carried records

The 0.6.1 changes are in `src/nookku/` and in the proof scripts:

- The finding record ([#575](https://github.com/mohanraj00/nookku/issues/575)) and the inconclusive test of a gate run ([#671](https://github.com/mohanraj00/nookku/issues/671)) add new code. A relay, the tap and a test with no gate run do not call it.
- The approvals change ([#640](https://github.com/mohanraj00/nookku/issues/640)) changes only a manifest with `"approvals": null`. The size check ([#644](https://github.com/mohanraj00/nookku/issues/644)) changes only `nookku evaluation add`.
- The hook checks ([#642](https://github.com/mohanraj00/nookku/issues/642), [#643](https://github.com/mohanraj00/nookku/issues/643)) add refusals to `nookku start` and `nookku mode on`. Hooks of this version pass them. On 0.6.1, the tutorial run passed `nookku check`, which runs these checks, with the project hooks of Claude Code. The Codex hook gate proof also ran on 0.6.1 ([Codex run notes](codex-0.6.1.md)).
- The change of the stdio tap ([#656](https://github.com/mohanraj00/nookku/issues/656)) adds the state of each turn to the tap. A message with no `X-Nookku-During` header goes to the agent as before, and the tap writes and records the same bytes. The tap proofs with no model passed on 0.6.1: the backend, model API, second message, replay and stream proofs. The relay proofs P1 to P4 did not run on 0.6.1.

Thus each record below is the 0.6.0 record. The [Claude Code run notes of 0.6.0](claude-code-0.6.0.md#runs-with-the-model) give each command, its run number and its data.

| Proof | Setup | 0.6.0 record |
|---|---|---|
| P1 to P4, with `--stream` and with `--stream --on-request` | plugin-claude-code, hooks-claude-code | [results](../plugin-claude-code/results.json), [results](../hooks-claude-code/results.json) and the 4 stream folders |
| P1 to P4 and P5, chat page | page-claude-code | [results](../page-claude-code/results.json) |
| `proof_key_guard.py` | plugin-claude-code, hooks-claude-code | [results](../key-guard/plugin-claude-code.json), [results](../key-guard/hooks-claude-code.json) |
| P5, `proof_evaluation.py` | plugin-claude-code, hooks-claude-code | [results](../evaluation/plugin-claude-code.json), [results](../evaluation/hooks-claude-code.json) |
| P5 to P8, `proof_report.py` | plugin-claude-code, hooks-claude-code | [results](../report/plugin-claude-code.json), [results](../report/hooks-claude-code.json) |
| `proof_telemetry.py` | plugin-claude-code, hooks-claude-code | [results](../telemetry/plugin-claude-code.json), [results](../telemetry/hooks-claude-code.json) |
| `proof_performance.py` | plugin-claude-code, hooks-claude-code | [results](../performance/plugin-claude-code.json), [results](../performance/hooks-claude-code.json) |
| `proof_spec_classes.py` | plugin-claude-code, hooks-claude-code | [results](../spec-classes/plugin-claude-code.json), [results](../spec-classes/hooks-claude-code.json) |
| `proof_trace_points.py` | plugin-claude-code, hooks-claude-code | [results](../trace-points/plugin-claude-code.json), [results](../trace-points/hooks-claude-code.json) |
| `proof_egress.py`, also with `--evaluate` | plugin-claude-code, hooks-claude-code | [results](../egress/plugin-claude-code.json), [results](../egress/hooks-claude-code.json) and the 2 evaluation files |
| `proof_simulated_user.py` |  | [results](../simulated-user/results.json) |
| `proof_setup.py` |  | [results](../setup/results.json) |
| `proof_tutorial.py --model` |  | [run](../tutorial/run.json), [output](../tutorial/output.txt) |
| `example_evaluation.py` |  | [results](../../examples/toy-shop/evaluation.json) |
| `proof_sessions.py` |  | [results](../sessions/results.json) |
| `bench/run.py` and `bench/score.py` |  | [results](../../bench/results.json) |

## The proof in a Koodam Workspace

`scripts/proof_cluster.py` did not run for 0.6.1. The last result is from 0.5.7 ([notes](claude-code-0.5.7.md#the-proof-in-a-koodam-workspace)).

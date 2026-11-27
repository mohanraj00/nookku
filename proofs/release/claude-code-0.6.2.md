# Claude Code release proofs of 0.6.2

I ran the proofs of the 0.6.2 release candidate on 2026-11-27, on macOS, in the worktree of the branch `claude/release-0.6.2`. The base is the tag `v0.6.1` at 65d0d8c9, plus the commits of [#704](https://github.com/mohanraj00/nookku/issues/704) and [#431](https://github.com/mohanraj00/nookku/issues/431) and the commit that sets the version to 0.6.2. The tools were Claude Code 2.1.319, codex-cli 0.169.0, Python 3.13.12 and Docker 29.6.1 (client). These are the harness versions of [0.6.1](claude-code-0.6.1.md), and CI still pins Claude Code 2.1.319. Each result file records its tested versions.

This release ran only the proofs with no model, no kind cluster, no network and no Codex job. Each other proof carries its record. [The carried records](#the-carried-records) give each record and the reason.

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
| MCP tasks | `uv run python scripts/proof_mcp_tasks.py` | pass, run 1 | [results](../mcp-tasks/results.json) |
| OpenInference import | `uv run python scripts/proof_openinference.py` | pass, run 1 | [results](../openinference/results.json) |
| Tap of each streamed transport | `uv run python scripts/proof_tap_streams.py` | pass, run 1 | [results](../tap-streams/results.json) |
| Output of the tutorial | `uv run python scripts/proof_tutorial.py` | pass, run 1 | [run](tutorial-0.6.2/run.json), [output](tutorial-0.6.2/output.txt) |

The approvals proof and the second message proof start the MCP stdio proxy, which now starts its child with the argv of [#704](https://github.com/mohanraj00/nookku/issues/704). Both passed. In the second message proof, the tap gave message 2 to the entry 0.493 seconds after message 1, and the reply of turn 1 came at 0.512 seconds. In 0.6.1, these times were 0.498 and 0.518 seconds. The checks of the proof did not change.

`proof_tutorial.py` with no model writes `proofs/tutorial/`, and replaces the record of the `--model` run of 0.6.0. So I moved the 2 files of this run to [tutorial-0.6.2/](tutorial-0.6.2/), as in 0.6.1, and `proofs/tutorial/` keeps the record of 0.6.0. In the 0.6.1 output, `nookku start` refused the test, because it found the project hooks `modified`, and the test had 1 turn ([output](tutorial-0.6.1/output.txt)). In the 0.6.2 output, `nookku start` started the test, and the test had 3 turns.

## The seeded faults

`uv run nookku faults --json > proofs/release/faults-0.6.2.json` ran with no model, at run 1. It found 97 of 97 faults in 49 cases, and each of the 33 checks has a fault ([data](faults-0.6.2.json)). These are the counts of 0.6.1 ([data](faults-0.6.1.json)).

## The failed runs

No run failed.

## The carried records

The 0.6.2 changes are:

- [#704](https://github.com/mohanraj00/nookku/issues/704) changes how Nookku starts a child Nookku process: the bridge, the MCP stdio proxy, the chat page and the project hooks. The child now gets `python -I -c <bootstrap> <library folder>`. The bytes that a relay or the tap sends and records do not change.
- [#431](https://github.com/mohanraj00/nookku/issues/431) changes only `scripts/proof_cluster.py`, its test, its record and the docs. Its run of 2026-11-27 is the record of the proof in a Koodam Workspace ([data](../cluster/plugin-claude-code-no-evaluation.json)).

These proofs did not run for 0.6.2, and each keeps its last record:

| Proof | Why it did not run | Last record |
|---|---|---|
| P1 to P4 of `proofs_relay.py`, all setups | It needs the model. | 0.6.0, [Claude Code run notes of 0.6.0](claude-code-0.6.0.md#runs-with-the-model) |
| `proof_plugin_load.py`, `proof_trace.py` | It needs the model. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-of-both-harnesses) |
| `proof_codex_gate.py`, `proof_codex_hook_keys.py` | It runs a Codex job. | 0.6.1, [Codex run notes](codex-0.6.1.md), [run notes](claude-code-0.6.1.md#runs-with-no-model) |
| Each other proof with the model | It needs the model. | 0.6.0, [carried records of 0.6.1](claude-code-0.6.1.md#the-carried-records) |
| `proof_driver_trace.py`, `proof_inapp_trace.py`, `proof_sdk_bundles.py` | It installs packages from the network. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-with-no-model) |
| `release_samples.py` | It downloads the Koodam samples from the network. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-with-no-model) |
| `proof_queue_trace.py`, `proof_gateway.py` | It uses Docker images and installs packages. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-with-docker-and-kind) |
| `proof_cluster_tap.py`, `kind_testkey.py` | It needs a kind cluster. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-with-docker-and-kind) |

The relay proofs P1 to P4 and the plugin load proof start the bridge and the project hooks, which #704 changes. [CONSTITUTION.md](../../CONSTITUTION.md#evidence) asks for the proofs after a change to a relay. These runs need a model slot.

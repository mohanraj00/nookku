# Claude Code release proofs of 0.7.0

I ran the proofs of the 0.7.0 release candidate on 2026-11-28, on macOS, in the worktree of the branch `claude/release-0.7.0` ([#732](https://github.com/mohanraj00/nookku/issues/732)). The base is `main` at 087cc34e. The first commit of the branch sets the version to 0.7.0.

This page gives the runs with no model, with and without the network. Each other proof carries its record. [The carried records](#the-carried-records) give each record and the reason.

## Runs with no model

Each command ran from the root of the worktree, one at a time, from 17:25 to 17:27 UTC.

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
| Output of the tutorial | `uv run python scripts/proof_tutorial.py` | pass, run 1 | [run](tutorial-0.7.0/run.json), [output](tutorial-0.7.0/output.txt) |
| Simulated user with a declared command | `uv run python scripts/proof_simulated_user.py --runner command` | U1 to U5 pass, run 1 | [results](../simulated-user/command.json) |

The `HEAD /api/hello` proof and the hook timeout proof ran Claude Code 2.1.319 with a toy model API (the key `versions` of each results file).

`proof_tutorial.py` with no model writes `proofs/tutorial/`, and replaces the record of the `--model` run of 0.6.0. So I moved the 2 files of this run to [tutorial-0.7.0/](tutorial-0.7.0/), as in 0.6.2, and `proofs/tutorial/` keeps the record of 0.6.0. The output is the same as the [output of 0.6.2](tutorial-0.6.2/output.txt), except the date and the version.

## Runs with the network

These runs use no model. They install packages, download the Koodam samples or start Docker images. They ran from 17:27 UTC.

| Proof | Command | Result | Data |
|---|---|---|---|
| Driver trace of a database | `uv run python scripts/proof_driver_trace.py` | pass, run 1 | [results](../driver-trace/results.json) |
| Call that the in-app trace does not show | `uv run python scripts/proof_inapp_trace.py` | pass, run 1 | [results](../inapp-trace/results.json) |
| Claude Code of each Agent SDK release | `uv run python scripts/proof_sdk_bundles.py 0.2.163 0.2.164 0.2.165 0.2.166 0.2.167 0.2.168` | pass, run 2 | [results](../trace/sdk-bundles.json) |
| Koodam release samples | `uv run python scripts/release_samples.py` | pass, run 1 | [results](../release-samples/results.json) |
| Client trace of a queue | `uv run python scripts/proof_queue_trace.py` | pass, run 1 | [results](../queue-trace/results.json) |
| LiteLLM gateway logs | `uv run python scripts/proof_gateway.py` | pass, run 3 | [results](../gateway/results.json) |

`proof_sdk_bundles.py` found the same 6 rows as in 0.6.2. Only the date changed. I gave it the same 6 releases as in 0.6.2, so that the 2 records compare. PyPI has later releases, up to 0.2.189 on 2026-11-28. `release_samples.py` read the samples of the Koodam tag `v0.5.0`, the pin of the CI job.

## The seeded faults

`uv run nookku faults --json > proofs/release/faults-0.7.0.json` ran with no model, at run 1. It found 108 of 108 faults in 52 cases, and each of the 33 checks has a fault ([data](faults-0.7.0.json)). 0.6.2 had 97 faults in 49 cases ([data](faults-0.6.2.json)). The conformance suite of 0.7.0 has 3 more cases and 11 more faults.

## The failed runs

- Run 1 of `proof_sdk_bundles.py` did not start the proof, and exited with 2. My zsh loop gave the 6 versions to the script as 1 argument. Run 2 gave each version as its own argument and passed. This is the same cause as run 1 of 0.6.2.
- Runs 1 and 2 of `proof_gateway.py` failed the check `items_by_turn`. The other 9 checks passed. The first 3 items of turn 1 had the turn `null` ([run 1](gateway-0.7.0/run1.json), [run 2](gateway-0.7.0/run2.json)).

The cause of the gateway fail is in the proof script, not in Nookku. In turn 1, `run_app` sent the first call at the start time of the turn, with no gap. Turn 2 waits 0.5 seconds (`GAP`) before its first call. The clock of the LiteLLM container was 0.028 seconds behind the clock of this computer in run 1 and 0.036 seconds behind in run 2 (the key `clock_skew_seconds`). Thus the gateway logged the first calls of turn 1 before the start of the turn. In the 0.6.1 run, the skew was +0.079 seconds, and the proof passed.

The fix adds the same gap before the first call of turn 1 ([proof_gateway.py](../../scripts/proof_gateway.py)). Run 3 had a skew of -0.029 seconds and passed each check, with the turns 1, 1, 1, 1, 2, 2, 2, 2.

No other run failed.

## The carried records

These proofs did not run with no model, and each keeps its last record:

| Proof | Why it did not run | Last record |
|---|---|---|
| Each proof with the model | It needs the model. | [Claude Code run notes of 0.6.2](claude-code-0.6.2.md#runs-with-the-model), [carried records of 0.6.2](claude-code-0.6.2.md#the-carried-records) |
| Each proof with Codex | It needs Codex and a trust step of the owner. | [Codex runs of 0.6.2](claude-code-0.6.2.md#runs-with-codex) |
| `proof_cluster_tap.py`, `kind_testkey.py` and `proof_cluster.py` | It needs a kind cluster. | [kind runs of 0.6.2](claude-code-0.6.2.md#runs-with-kind) |

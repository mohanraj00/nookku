# Claude Code release proofs of 0.6.2

I ran the proofs of the 0.6.2 release candidate on 2026-11-27, on macOS, in the worktree of the branch `claude/release-0.6.2`. The base is the tag `v0.6.1` at 65d0d8c9, plus the commits of [#704](https://github.com/mohanraj00/nookku/issues/704) and [#431](https://github.com/mohanraj00/nookku/issues/431) and the commit that sets the version to 0.6.2. The tools were Claude Code 2.1.319, codex-cli 0.169.0, Python 3.13.12 and Docker 29.6.1 (client). These are the harness versions of [0.6.1](claude-code-0.6.1.md), and CI still pins Claude Code 2.1.319. Each result file records its tested versions.

This release ran the proofs with no model, with and without the network, and some proofs with the model and with kind in slots that the owner gave. Each other proof carries its record. [The carried records](#the-carried-records) give each record and the reason.

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

`proof_tutorial.py` with no model writes `proofs/tutorial/`, and replaces the record of the `--model` run of 0.6.0. So I moved the 2 files of this run to [tutorial-0.6.2/](tutorial-0.6.2/), as in 0.6.1, and `proofs/tutorial/` keeps the record of 0.6.0. In the 0.6.1 output, `nookku start` refused the test, because it found the project hooks `modified`, and the test had 1 turn ([output](tutorial-0.6.1/output.txt)). In the 0.6.2 output, `nookku start` started the test, and the test had 3 turns. [The tutorial change](#the-tutorial-change) gives the cause.

## Runs with the network

These runs use no model. They install packages, download the Koodam samples or start Docker images.

| Proof | Command | Result | Data |
|---|---|---|---|
| Driver trace of a database | `uv run python scripts/proof_driver_trace.py` | pass, run 1 | [results](../driver-trace/results.json) |
| Call that the in-app trace does not show | `uv run python scripts/proof_inapp_trace.py` | pass, run 1 | [results](../inapp-trace/results.json) |
| Claude Code of each Agent SDK release | `uv run python scripts/proof_sdk_bundles.py 0.2.163 0.2.164 0.2.165 0.2.166 0.2.167 0.2.168` | pass, run 2 | [results](../trace/sdk-bundles.json) |
| Koodam release samples | `uv run python scripts/release_samples.py` | pass, run 1 | [results](../release-samples/results.json) |
| Client trace of a queue | `uv run python scripts/proof_queue_trace.py` | pass, run 1 | [results](../queue-trace/results.json) |
| LiteLLM gateway logs | `uv run python scripts/proof_gateway.py` | pass, run 1 | [results](../gateway/results.json) |

`proof_sdk_bundles.py` found the same 6 rows as in 0.6.1. Only the date and the version changed. `release_samples.py` read the samples of the Koodam tag `v0.4.0`, the pin of 0.6.1.

## Runs with the model

The owner gave a model slot for Claude Code. At the start of the slot, the weekly usage of the Claude account was 92% for all models. The runs started at 2026-11-27 19:48 UTC, at 690e41f6, one at a time. A run that fails with HTTP 429 or a quota error counts as inconclusive, not failed. No run had such an error.

| Proof | Setup | Command | Result | Data |
|---|---|---|---|---|
| P1 to P4 | plugin-claude-code | `uv run python scripts/proofs_relay.py plugin-claude-code` | pass, run 1 | [results](../plugin-claude-code/results.json) |
| P1 to P4 | hooks-claude-code | `uv run python scripts/proofs_relay.py hooks-claude-code` | pass, run 1 | [results](../hooks-claude-code/results.json) |
| Plugin load, both harnesses |  | `uv run python scripts/proof_plugin_load.py` | 18 of 18 checks pass, run 1 | [results](../plugin/load.json) |
| Key guard | plugin-claude-code | `uv run python scripts/proof_key_guard.py plugin-claude-code` | K1 to K5 pass, run 1 | [results](../key-guard/plugin-claude-code.json) |
| Key guard | hooks-claude-code | `uv run python scripts/proof_key_guard.py hooks-claude-code` | K1 to K5 pass, run 1 | [results](../key-guard/hooks-claude-code.json) |

The relay proofs and the plugin load proof start the bridge and the hooks with the child argv of [#704](https://github.com/mohanraj00/nookku/issues/704). Each of the 10 turns of each relay proof passed P1 and P2, and P3b blocked the model call. The plugin load proof also runs Codex 0.169.0 for its 9 Codex checks.

## Runs with Codex

The owner gave Codex slot 3, and did the 3 person steps of [run-the-proofs.md](../../docs/contributing/run-the-proofs.md#trust-the-codex-hooks-once): the trust of the plugin hooks, the login of the project hooks setup and the trust of the project hooks. The runs used codex-cli 0.169.0, one at a time. Part A ran at 19:53 UTC, before the trust. The other runs started at 20:13 UTC. No run had HTTP 429 or a quota error.

| Proof | Setup | Command | Result | Data |
|---|---|---|---|---|
| Hook gate, part A |  | `uv run python scripts/proof_codex_gate.py` | 8 of 8 checks pass, run 1 | [results](../codex-gate/gate.json) |
| Hook gate, part B |  | `uv run python scripts/proof_codex_gate.py --trusted`, after the owner trusted the 2 hooks | 5 of 5 checks pass, run 1 | [results](../codex-gate/gate.json) |
| P1 to P4 | plugin-codex | `uv run python scripts/proofs_relay.py plugin-codex` | pass, run 1 | [results](../plugin-codex/results.json) |
| P1 to P4 | hooks-codex | `uv run python scripts/proofs_relay.py hooks-codex` | not complete, run 1: setup problem | none, the 0.6.0 record stays |

In the `hooks-codex` run, the prompt `nookku start` did not start a test. The proof wrote the project hooks of 0.6.2 in `.proof/codex/` of this worktree. Then `hooks/list` of codex-cli 0.169.0, with this folder as its `cwds`, gave the hooks of `.proof/codex/` in the main checkout of the repo. That file is from 2026-11-20 and has the hook command of an older version (`python3 -m nookku hook`). So the gate of 0.6.2 found each project hook `modified` and refused the test, as it must. I think that Codex finds the project of a git worktree through the main checkout, but I did not prove it. This is a problem of the proof setup in a worktree, not a fault of Nookku. I did not run it again. A new run needs the main checkout or a project folder outside the repo, and a new trust step.

## The tutorial change

The hook check of `nookku start` compares the command of each project hook with `kit.hook_command`, word for word ([claude_gate.py](../../src/nookku/claude_gate.py)). The first word is `sys.executable` of the process that runs the check. In a uv virtual environment, `.venv/bin/python` and `.venv/bin/python3` are 2 links to the same Python, but the check reads them as 2 different words.

The proof does 2 steps with 2 Python paths:

- `nookku init claude-code` runs from the console script `.venv/bin/nookku`. The interpreter of that script writes the hook command.
- The prompt `nookku start` runs `[sys.executable, "-m", "nookku", "hook", ...]` with the Python of the proof script, `uv run python` ([proof_tutorial.py](../../scripts/proof_tutorial.py)). That Python checks the hook command.

In the 0.6.1 run, the hook command had `.venv/bin/python` ([output](tutorial-0.6.1/output.txt)), so the console script started `.venv/bin/python`. On this computer, `uv run python` gives the `sys.executable` `.venv/bin/python3`. So the 2 paths were different, and the check refused the test. The 0.6.1 worktree is gone, so I cannot read its console script now. In the 0.6.2 run, the console script starts `.venv/bin/python3` (its first line), and `uv run python` gives the same path. So the check passed.

I tested the check with no proof script, on v0.6.1 and on this branch. I ran `nookku init claude-code` with one Python path and `claude_gate.hook_problems` with the other path:

| Version | `init` | Check | Problems |
|---|---|---|---|
| 0.6.1 | `.venv/bin/python` | `.venv/bin/python` | 0 |
| 0.6.1 | `.venv/bin/python` | `.venv/bin/python3` | 2 |
| 0.6.1 | `.venv/bin/python3` | `.venv/bin/python` | 2 |
| 0.6.1 | `.venv/bin/python3` | `.venv/bin/python3` | 0 |
| 0.6.2 | `.venv/bin/python` | `.venv/bin/python` | 0 |
| 0.6.2 | `.venv/bin/python` | `.venv/bin/python3` | 2 |
| 0.6.2 | `.venv/bin/python3` | `.venv/bin/python` | 2 |
| 0.6.2 | `.venv/bin/python3` | `.venv/bin/python3` | 0 |

The 2 versions give the same result. Thus [#704](https://github.com/mohanraj00/nookku/issues/704) did not cause the change. The 0.6.1 refusal was a false refusal of the proof setup, and the 0.6.2 pass is correct. In a real test, Claude Code runs the hook command that `nookku init` wrote, so the check runs with the same Python path and passes. The proof does not run that command. If a person runs `nookku init` and `nookku start` with 2 different Python paths, the check also refuses the test, and its message says to run `nookku init` again. A follow-up can make the proof run the hook command from `settings.local.json`.

## The seeded faults

`uv run nookku faults --json > proofs/release/faults-0.6.2.json` ran with no model, at run 1. It found 97 of 97 faults in 49 cases, and each of the 33 checks has a fault ([data](faults-0.6.2.json)). These are the counts of 0.6.1 ([data](faults-0.6.1.json)).

## The failed runs

Run 1 of `proof_sdk_bundles.py` exited with 1. My shell loop gave the 6 versions to the script as 1 argument, so uv could not install the release. Run 2 gave each version as its own argument and passed. 
The owner gave kind slot 2 on 2026-11-27. Before the runs, at 19:54 UTC, the 1-minute load was 5.74, and `kind get clusters` gave 1 cluster of another project. Both runs failed for a cause outside Nookku, and each kept its 0.6.1 record:

- `proof_cluster_tap.py` stopped before it made a cluster: "Docker has 899 MB free, below 1200 MB. Stop; do not prune." I did not prune.
- `kind_testkey.py` made its cluster, and the Koodam Workspace `shop` was not running after the wait of 600 seconds. The script deleted its cluster. The cause is probably the low free space of Docker, but the cluster is gone, so I have no pod events.

The `hooks-codex` relay run did not complete, for a setup problem of the worktree ([Runs with Codex](#runs-with-codex)).

No other run failed.

## The carried records

The 0.6.2 changes are:

- [#704](https://github.com/mohanraj00/nookku/issues/704) changes how Nookku starts a child Nookku process: the bridge, the MCP stdio proxy, the chat page and the project hooks. The child now gets `python -I -c <bootstrap> <library folder>`. The bytes that a relay or the tap sends and records do not change.
- [#431](https://github.com/mohanraj00/nookku/issues/431) changes only `scripts/proof_cluster.py`, its test, its record and the docs. Its run of 2026-11-27 is the record of the proof in a Koodam Workspace ([data](../cluster/plugin-claude-code-no-evaluation.json)).

These proofs did not run for 0.6.2, and each keeps its last record:

| Proof | Why it did not run | Last record |
|---|---|---|
| P1 to P4 of `proofs_relay.py` for hooks-codex | Its run did not complete ([Runs with Codex](#runs-with-codex)). | 0.6.0, [Codex run notes of 0.6.0](codex-0.6.0.md#runs) |
| P1 to P4 of `proofs_relay.py`, the streamed forms and the chat page | It needs the model. | 0.6.0, [Claude Code run notes of 0.6.0](claude-code-0.6.0.md#runs-with-the-model) |
| `proof_trace.py` | It needs the model. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-of-both-harnesses) |
| `proof_codex_hook_keys.py` | It runs a Codex job. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-with-no-model) |
| Each other proof with the model | It needs the model. | 0.6.0, [carried records of 0.6.1](claude-code-0.6.1.md#the-carried-records) |
| `proof_cluster_tap.py`, `kind_testkey.py` | It needs a kind cluster. | 0.6.1, [run notes](claude-code-0.6.1.md#runs-with-docker-and-kind) |


# Run the proofs

The proofs show that each [relay](../reference/glossary.md#relay) is exact in a real [harness](../reference/glossary.md#harness). They run the harness headless, so they are local scripts in `scripts/`, not tests in CI. Run them after each change to a relay, and for each new harness version. Commit the results with the harness versions that they record.

[results.md](../results.md) explains each proof and shows the latest results.

## Before you start

- Install the dev tools: `uv sync`.
- Install the harnesses that the proof needs: `claude` for Claude Code, `codex` for Codex.
- The proofs run in 4 setups: `plugin-claude-code`, `plugin-codex`, `hooks-claude-code` and `hooks-codex`. A setup is a form of the relay (the [plugin](../reference/glossary.md#plugin) or the [project hooks](../reference/glossary.md#project-hooks)) and a harness.
- The setup `page-claude-code` runs P1 to P4 with the [chat page](../reference/cli.md#nookku-chat) as the relay. The [tester](../reference/glossary.md#tester) starts and ends the test in Claude Code with the plugin, and sends each message on the page. It has no `--stream`.
- In Claude Code, the plugin proofs load the plugin from this repo with `--plugin-dir`. You do not install it.
- In Codex, the plugin proofs use the `CODEX_HOME` of [proof_codex_gate.py](../../scripts/proof_codex_gate.py), `.proof/codex-gate/codex-home`. That script installs the plugin of this checkout there.
- Run each proof of the setup `hooks-codex` in the main checkout of the repo, not in a git worktree. In a git worktree, Codex reads the project hooks from the main checkout, so the proof does not use the hooks of the worktree.
- The plugin hooks run `nookku` from `PATH`. The scripts put the `nookku` of this checkout first.
- Codex runs each command of the model in a login shell, which reads your shell profile again. If the profile puts another `nookku` first on `PATH`, the model runs that one. Remove it before the proofs, for example with `uv tool uninstall nookku`.
- In Claude Code, `proof_report.py`, `proof_evaluation.py` and `proof_tutorial.py` give each session only the settings of the project and only the nookku MCP server. Thus no hook, plugin, permission rule or MCP server of your user configuration reaches the model ([proof_common.py](../../scripts/proof_common.py)). Claude Code loads a mod from each folder of `CLAUDE_CODE_PLUGIN_DIRS`, also from the user settings. Each proof session gets an empty `CLAUDE_CODE_PLUGIN_DIRS`, so no mod loads. If a plugin that is not built in loads, the proof stops.
- In Codex, each setup has its own `CODEX_HOME`, so no MCP server, plugin or `AGENTS.md` of your Codex configuration loads. The plugin setups use `.proof/codex-gate/codex-home`. The setup `hooks-codex` uses `.proof/codex-hooks/codex-home`. Before each Codex run, the proof runs `codex mcp list --json` in the project with that home. If an MCP server other than nookku is in the list, the proof stops ([proof_common.py](../../scripts/proof_common.py)).
- Some proofs use a real model and cost tokens. The proofs of the proxies and the backend need no model.

## Trust the Codex hooks once

Codex runs a hook only after a person trusts it. Never try to skip the trust step. `nookku start` refuses a test with an untrusted hook ([SPEC.md section 7.8](../../SPEC.md#78-codex-hook-gate)). Trust these hooks once:

1. **The plugin.** Run `uv run python scripts/proof_codex_gate.py`. Then start `CODEX_HOME=.proof/codex-gate/codex-home codex -C .proof/codex-gate/project`, type `/hooks`, and trust the 2 nookku hooks. Each run of the script without `--trusted` makes a new `CODEX_HOME`, so that part A starts with hooks that no person trusted. After each such run, trust the hooks again.
2. **The project hooks.** These steps use the `CODEX_HOME` of the setup `hooks-codex`, `.proof/codex-hooks/codex-home`:
   1. Make the folder: `mkdir -p .proof/codex-hooks/codex-home`.
   2. Log in: `CODEX_HOME=.proof/codex-hooks/codex-home codex login`.
   3. Write the hooks with the Python of this checkout: `.venv/bin/python3 -m nookku init codex --root .proof/codex`.
   4. Start `CODEX_HOME=.proof/codex-hooks/codex-home codex -C .proof/codex`, type `/hooks`, and trust the 2 nookku hooks.
3. **The project hooks of the [evaluation](../reference/glossary.md#evaluation) proofs.** Do steps 2.3 and 2.4 in `~/.nookku-proof/codex`, with the same `CODEX_HOME`. That project is outside the repo, so that the evaluating model cannot read the docs that describe the planted bug ([proof_report.py](../../scripts/proof_report.py)).

If a hook changes, trust it again. A new plugin script also needs a new run of `proof_codex_gate.py` and a new trust step.

## The commands

| Proof | Command | Output |
|---|---|---|
| P1 to P4 | `uv run python scripts/proofs_relay.py <setup>` | `proofs/<setup>/` |
| P1 to P4, the chat page as the relay | `uv run python scripts/proofs_relay.py page-claude-code` | `proofs/page-claude-code/` |
| P1 to P4, streamed agent | `uv run python scripts/proofs_relay.py <setup> --stream` | `proofs/<setup>-stream/` |
| P1 to P4, agent that streams only on request | `uv run python scripts/proofs_relay.py <setup> --stream --on-request` | `proofs/<setup>-stream-on-request/` |
| Model sessions of the app | `uv run python scripts/proof_sessions.py` | `proofs/sessions/` |
| [Trace](../reference/glossary.md#trace) of the model sessions | `uv run python scripts/proof_trace.py` | `proofs/trace/` |
| The trace with the Claude Code of a different Agent SDK | `uv run python scripts/proof_trace.py <out-dir> claude-agent-sdk==<version>` | `<out-dir>/results.json` |
| The trace with a Claude Code that no Agent SDK bundles | `uv run python scripts/proof_trace.py <out-dir> claude-agent-sdk==<version> <path of claude>` | `<out-dir>/results.json` |
| The Claude Code version of each Agent SDK release, no model | `uv run python scripts/proof_sdk_bundles.py <version>...` | `proofs/trace/sdk-bundles.json` |
| Backend proxy, no model | `uv run python scripts/proof_backend.py` | `proofs/backend/` |
| Model API proxy, no model | `uv run python scripts/proof_model_api.py` | `proofs/model-api/` |
| Driver trace of a database, no model | `uv run python scripts/proof_driver_trace.py` | `proofs/driver-trace/` |
| The `HEAD /api/hello` call of Claude Code, no model | `uv run python scripts/proof_api_hello.py` | `proofs/model-api/hello.json` |
| P5 to P8, evaluation at the end of a test | `uv run python scripts/proof_report.py <setup>` | `proofs/report/<setup>.json` |
| Full telemetry | `uv run python scripts/proof_telemetry.py <setup>` | `proofs/telemetry/<setup>.json` |
| P5, the model judges the record | `uv run python scripts/proof_evaluation.py <setup>` | `proofs/evaluation/<setup>.json` |
| The plugin loads in both harnesses | `uv run python scripts/proof_plugin_load.py` | `proofs/plugin/load.json` |
| The Codex hook gate | `uv run python scripts/proof_codex_gate.py`, then `--trusted` after the trust step | `proofs/codex-gate/gate.json` |
| Codex and the `OTEL_*` variables | `uv run python scripts/proof_codex_otel.py` | `proofs/otel/codex.json` |
| Benchmark under pressure | `uv run python bench/run.py mechanism claude-code` or `codex`, then `uv run python bench/score.py` | `bench/runs/`, `bench/results.json` |
| Worked evaluation | `uv run python scripts/example_evaluation.py` | `examples/toy-shop/evaluation.json` |
| The output of the tutorial, no model | `uv run python scripts/proof_tutorial.py` | `proofs/tutorial/output.txt`, `proofs/tutorial/run.json`. This run replaces the data of the `--model` run. |
| The output of the tutorial, with Claude Code and the model | `uv run python scripts/proof_tutorial.py --model` | `proofs/tutorial/output.txt`, `proofs/tutorial/run.json` |

These scripts print `PASS` or `FAIL` and the path of their results file: `proofs_relay.py`, `proof_sessions.py`, `proof_trace.py`, `proof_backend.py`, `proof_model_api.py`, `proof_driver_trace.py`, `proof_report.py` and `proof_telemetry.py`. The docstring of each script lists what it checks.

## A new Claude Code release

The plugin uses function hooks, which are early access and can change between releases. CI pins the tested Claude Code version in the job `claude-code-plugin` of [ci.yml](../../.github/workflows/ci.yml).

The workflow [claude-code-release.yml](../../.github/workflows/claude-code-release.yml) checks the latest release. It runs each day at 06:23 UTC:

1. It installs the latest `@anthropic-ai/claude-code` from npm.
2. It runs `claude plugin validate plugins/nookku` and `claude plugin test plugins/nookku`, as the CI job does.
3. If a check fails, a second job opens an issue with the title `Claude Code <version> fails the plugin checks`. The issue has the version, the result of each check, a link to the run and the end of the log. The workflow opens one issue for each version, also if a person closed the issue. Only an issue that the workflow opened counts. Two runs of the workflow do not run at the same time.

The job that runs Claude Code has only `contents: read`. Only the second job can write issues, and it runs no code of the npm package. If the install fails, the run fails and opens no issue.

To start the workflow by hand, run `gh workflow run claude-code-release.yml`, or use "Run workflow" on the Actions page. GitHub stops a scheduled workflow after 60 days with no activity in a public repo ([GitHub docs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)). Then start it again on the Actions page.

The checks need no model, so they cannot replace the proofs. Before you change the CI pin to a new version:

1. Run P1 to P5 again with that version, as [The commands](#the-commands) says.
2. Commit the results with the version that they record.
3. Change the pin in `ci.yml` and the version in [faq.md](../faq.md). `tests/test_docs.py` checks that the pin, the FAQ and the results name the same version.

## After a run

1. Read the results file. A fail is a result too: keep it, and say why in [results.md](../results.md).
2. Update the tables in [results.md](../results.md) and the README from the results files. Do not edit a published result by hand.
3. Commit the results with the harness versions that they record.

A model answer changes on each run. The scripts store no model answer that can quote the harness's own instruction files. They check the text against the instruction files on the machine, and they remove local paths.

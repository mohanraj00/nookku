# Work on Nookku

[CONSTITUTION.md](CONSTITUTION.md) gives the purpose, the boundaries, the principles, the evidence rules and the contribution rules of Nookku. `CLAUDE.md` and `GEMINI.md` import the constitution and this file.

## Work starts from an issue

[docs/STANDARD.md](docs/STANDARD.md#builds) gives the build rules: the issue, the label, the branch name and the PR template. [docs/STANDARD.md](docs/STANDARD.md#approvals) gives the approval levels and who merges.

- Find work with `gh issue list` and `gh issue view N`.
- Merge `main` into a PR only if GitHub shows a merge conflict. CI runs each test job on `main` after each merge. If a job fails on `main`, fix it before the next merge.
- If you find work outside the scope of the issue, do not make the PR larger.

## Two harnesses work on this repo

Claude Code and Codex both work on this repo, at the same time. The label `agent:claude` or `agent:codex` names the harness that does the work.

- The issue events show the order of the labels: `gh api repos/mohanraj00/nookku/issues/N/events`.
- Add the label of your harness to each PR that you open.
- [docs/REVIEW.md](docs/REVIEW.md) gives the exact review request texts of this repo. [docs/STANDARD.md](docs/STANDARD.md#reviews) gives the review rules, and [docs/STANDARD.md](docs/STANDARD.md#security-review-trigger) says when a PR needs a security review.
- Work in your own worktree and on your own branch. Do not push to the branch of the other harness.

## Rules

- **Constitution.** Keep the [principles](CONSTITUTION.md#principles), the [evidence rules](CONSTITUTION.md#evidence) and the [contribution rules](CONSTITUTION.md#contributions) of the constitution.
- **Plugin API.** The Claude Code plugin uses function hooks, which are early access and can change between releases. CI pins the tested version.
- **Plugin helpers.** In `plugins/nookku/hooks/register.tsx`, a function that takes `$` must be a top-level function declaration. `claude plugin validate` refuses other forms.
- **Outward steps.** [CONSTITUTION.md](CONSTITUTION.md#governance) gives the steps that need an owner approval. Tags publish to PyPI and you cannot undo them.

## Review guidelines

Flag these as high priority in a PR review:

- A change that lets the relay change a byte of a message or a reply, or that lets a relayed message reach the model.
- A relay path that fails open. If the relay cannot send a message, the message must still not go to the model.
- A change to the record format or to the audit with no SPEC.md change and no hand-written conformance case.
- A banned term, or a client or product name, in a file, a path or a commit message. Do not flag the name Koodam. Koodam is a project of the maintainer, and the repo can name it.
- A new runtime dependency, or a GPL or AGPL dependency.
- A number in a doc with no link to its data and its method.
- A plugin helper that takes `$` and is not a top-level function declaration.

If your review format lets you add text after the findings, end a code review with one line. Write `Security review: needed`, with the reason, if the PR changes one of these:

- the relay path, the tap, the guard, the seal or the policy file;
- a hook, the plugin, or the code that starts the entry or a test;
- the code that reads input from the model, a tester or an agent;
- a workflow, a secret, a permission or a dependency.

Else write `Security review: not needed`. Do not ask for the security review yourself. The PR author asks for it. A security review does not end with this line.

## Writing

Docs, commit messages and issues use the maintainer's voice under ASD-STE100 rules: first person where natural, short sentences, active voice, simple words, numbers instead of adjectives. Be direct. No em-dashes, no filler words ("seamless", "robust", "leverage", "comprehensive"). Each number links to its data.

## Before every commit

```bash
make check
uv run python conformance/build.py && git diff --exit-code conformance/
```

The `check` target of the `Makefile` runs ruff, the format check, mypy, pytest, the stealth gate and the two plugin checks. The second command is the conformance check of the CI job `lint` ([ci.yml](.github/workflows/ci.yml)). It writes the conformance cases again and fails if a file changes.

## Proofs (local only)

- A setup is `plugin-claude-code`, `plugin-codex`, `hooks-claude-code` or `hooks-codex`: a form of the relay and a harness.
- `scripts/proofs_relay.py <setup>` runs P1 to P4 and writes `proofs/<setup>/`.
- `scripts/proof_backend.py` checks that the backend proxy forwards each byte, with no model, and writes `proofs/backend/`.
- `scripts/proof_model_api.py` checks that the model API proxy forwards each byte and each stream part when it comes, with no model, and writes `proofs/model-api/`.
- `scripts/proof_driver_trace.py` runs a test of a toy shop app with the OpenTelemetry instrumentation of its SQLite driver, with no model. It checks the driver queries of the trace and the transcript, and writes `proofs/driver-trace/`.
- `scripts/proof_api_hello.py` runs `claude -p` with a toy model API, with no model, and records the `HEAD /api/hello` call of Claude Code. It writes `proofs/model-api/hello.json`.
- `scripts/proof_report.py <setup>` runs a test of `examples/toy-shop-models/` and the evaluation at its end (P5 extended, P6, P7 and P8), and writes `proofs/report/`.
- `scripts/proof_telemetry.py <setup>` runs a test of `examples/toy-shop-full/` with all telemetry sources and the evaluation at its end, and writes `proofs/telemetry/`.
- `scripts/proof_trace_points.py <setup>` runs a test of a copy of `examples/toy-shop-full/` with its app spec and one planted missing trace point. It checks the finding `missing_trace_point` of the trace, and writes `proofs/trace-points/`.
- `scripts/proof_performance.py <setup>` runs a test of `examples/toy-shop-full/` with its app spec and a slow turn that the proof plants in its toy servers, and the evaluation at its end. It writes `proofs/performance/`.
- `scripts/proof_spec_classes.py <setup>` runs a test of `examples/toy-shop-full/` with its app spec and 3 planted defects: one each for `tone`, `boundary` and `off_path`. It writes `proofs/spec-classes/`.
- `scripts/proof_egress.py <setup>` runs a test of `examples/toy-shop-egress/`, with the discovery answer of the harness model, 2 MCP servers, a Postgres database in Docker and a SQLite database with a driver trace. It writes `proofs/egress/`.
- `scripts/proof_cluster_tap.py` runs the toy shop agent behind a Service in a kind cluster, with no model. It tests the tap in the harness pod, behind its own Service, and with default-deny egress. It checks exact bytes and blocked delivery, and writes `proofs/cluster-tap/`.
- `scripts/proof_cluster.py <setup>` runs a test from the harness in a Koodam 0.3.0 Workspace in a kind cluster, with the toy shop agent behind a Service. It checks the relay, the tap and the backend records, the egress spans of a real `koodam trace` export and the evaluation. It writes `proofs/cluster/`. The login is a person step.
- `scripts/proof_codex_otel.py` checks if Codex sends OpenTelemetry data from the `OTEL_*` variables of a test, and writes `proofs/otel/codex.json`.
- `scripts/proof_sdk_bundles.py <version>...` records the Claude Code version that each given Claude Agent SDK release bundles, with no model, and writes `proofs/trace/sdk-bundles.json`.
- `scripts/proof_sessions.py` checks that `nookku check` finds the model sessions of a toy shop app, one in each harness, and writes `proofs/sessions/`.
- `scripts/proof_trace.py` checks that the trace reads real model sessions of a toy shop app (SPEC.md section 8), and writes `proofs/trace/`.
- `scripts/proof_plugin_load.py` checks that the plugin folder loads in Claude Code and in Codex, and writes `proofs/plugin/load.json`.
- `scripts/proof_codex_gate.py` runs the Codex hook gate against a real Codex, and writes `proofs/codex-gate/gate.json`. Part B runs with `--trusted`, after the maintainer trusts the hooks.
- `scripts/proof_tutorial.py` runs the commands of `docs/getting-started.md` in a new toy shop project, and writes `proofs/tutorial/`. With `--model`, Claude Code and the model also run.
- `scripts/proof_setup.py` runs the setup guide in Claude Code on a copy of `examples/toy-shop-full/` with no entry and no app spec. It checks that the setup gives a summary, asks a question and writes no file before a yes, and writes `proofs/setup/`.
- `scripts/proof_simulated_user.py` runs a test of the toy shop agent with 1 persona, with Claude Code as the simulated user. It saves the test as a script and runs the script again, and writes `proofs/simulated-user/`.
- `scripts/proof_evaluation.py <setup>` runs P5 (the model judges the record, not its memory) and writes `proofs/evaluation/`. Never store a model answer that can quote the harness's own instruction files. Codex runs a hook only after a person trusts it. The maintainer trusts the Codex hooks of the proofs once ([run-the-proofs.md](docs/contributing/run-the-proofs.md#trust-the-codex-hooks-once)). Never try to skip the trust step.

`scripts/example_evaluation.py` runs the worked evaluation in `docs/evaluation-example.md` and writes `examples/toy-shop/evaluation.json`. The model's answer changes on each run, so update the doc with the data.

[CONSTITUTION.md](CONSTITUTION.md#evidence) says when to run the proofs.

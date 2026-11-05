# Claude Code release proofs of 0.5.7

I ran the Claude Code proofs of the 0.5.7 release candidate on 2026-11-03, on macOS. The base is main at aa09bd1, plus the commit that sets the version to 0.5.7 ([d4ddd04](https://github.com/mohanraj00/nookku/commit/d4ddd04e)). The tools were Claude Code 2.1.302, Docker 29.5.2, kind v0.33.0, kubectl v1.36.2 and Kubernetes v1.37.0. Each result file records its tested versions. I ran the 28 proofs of the table one time each, in sequence. Each run exited with 0, and each results file passes.

## Runs

| Proof | Setup | Run 1 | Data |
|---|---|---|---|
| P1 to P4 | plugin-claude-code | pass | [results](../plugin-claude-code/results.json) |
| P1 to P4 | hooks-claude-code | pass | [results](../hooks-claude-code/results.json) |
| P1 to P4, `--stream` | plugin-claude-code | pass | [results](../plugin-claude-code-stream/results.json) |
| P1 to P4, `--stream` | hooks-claude-code | pass | [results](../hooks-claude-code-stream/results.json) |
| P1 to P4, chat page | page-claude-code | pass | [results](../page-claude-code/results.json) |
| P5 to P8, `proof_report.py` | plugin-claude-code | pass | [results](../report/plugin-claude-code.json) |
| P5 to P8, `proof_report.py` | hooks-claude-code | pass | [results](../report/hooks-claude-code.json) |
| `proof_telemetry.py` | plugin-claude-code | pass | [results](../telemetry/plugin-claude-code.json) |
| `proof_telemetry.py` | hooks-claude-code | pass | [results](../telemetry/hooks-claude-code.json) |
| `proof_performance.py` | plugin-claude-code | pass | [results](../performance/plugin-claude-code.json) |
| `proof_performance.py` | hooks-claude-code | pass | [results](../performance/hooks-claude-code.json) |
| `proof_spec_classes.py` | plugin-claude-code | pass | [results](../spec-classes/plugin-claude-code.json) |
| `proof_spec_classes.py` | hooks-claude-code | pass | [results](../spec-classes/hooks-claude-code.json) |
| `proof_trace_points.py` | plugin-claude-code | pass | [results](../trace-points/plugin-claude-code.json) |
| `proof_trace_points.py` | hooks-claude-code | pass | [results](../trace-points/hooks-claude-code.json) |
| `proof_egress.py` | plugin-claude-code | pass | [results](../egress/plugin-claude-code.json) |
| `proof_egress.py` | hooks-claude-code | pass | [results](../egress/hooks-claude-code.json) |
| `proof_egress.py --evaluate` | plugin-claude-code | pass | [results](../egress/plugin-claude-code-evaluation.json), [test folder](../egress/evaluation/20261103-210106-438d/) |
| `proof_egress.py --evaluate` | hooks-claude-code | pass | [results](../egress/hooks-claude-code-evaluation.json), [test folder](../egress/evaluation/20261103-210302-ce29/) |
| P5, `proof_evaluation.py` | plugin-claude-code | pass | [results](../evaluation/plugin-claude-code.json) |
| P5, `proof_evaluation.py` | hooks-claude-code | pass | [results](../evaluation/hooks-claude-code.json) |
| `proof_backend.py` | | pass | [results](../backend/results.json) |
| `proof_model_api.py` | | pass | [results](../model-api/results.json) |
| `proof_driver_trace.py` | | pass | [results](../driver-trace/results.json) |
| `proof_api_hello.py` | | pass | [results](../model-api/hello.json) |
| `proof_tutorial.py --model` | | pass | [run](../tutorial/run.json), [output](../tutorial/output.txt) |
| `proof_setup.py` | | pass | [results](../setup/results.json) |
| `proof_cluster_tap.py` | | pass | [results](../cluster-tap/results.json) |

The 2 runs with `--evaluate` replace the egress evaluation of [#536](https://github.com/mohanraj00/nookku/pull/536), so I deleted its old test folder `20261031-082640-90a9`. `proof_cluster_tap.py` ran its 3 forms: `same-pod`, `service` and `default-deny` ([records](../cluster-tap/)). It deleted its kind cluster at the end. The run of `proof_api_hello.py` changed only the key `date` of `hello.json`.

## The proof in a Koodam Workspace

`scripts/proof_cluster.py plugin-claude-code` ([method](../../scripts/proof_cluster.py)) passed on 2026-11-05, in test 20261105-113654-8811 ([results](../cluster/plugin-claude-code.json), [test folder](../cluster/plugin-claude-code/)). It used Koodam 0.3.0, kind v0.33.0, Kubernetes v1.37.0, helm v4.2.3 and Docker 29.5.2. Nookku 0.5.7 ran on the host and in the Workspace pod. The key `versions` of the results file gives each version.

| Check | What it shows | Result |
|---|---|---|
| W1 | The Workspace runs with traced egress. Claude Code in the pod loads the plugin `nookku@nookku` of the manual install and only the MCP server of nookku. | pass |
| W2 | 3 of 3 messages and 3 of 3 replies are the same in the relay record, the tap record and the backend record. The model used 0 output tokens in each turn, and the audit found no break. | pass |
| W3 | `egress.jsonl` has the bytes of a real `koodam trace` export of 24 rows, and the seal covers it. The trace gives 1 `egress_not_in_discovery` finding (`example.com`) and 1 `egress_denied` finding (port 22). | pass |
| W4 | The model writes the report, and `nookku verify` finds the seal intact. | pass |

The proof needs 1 person step: the login of Claude Code in the Workspace. The script waits for it. 2 earlier runs stopped with exit 1, because no person did the login in the wait time:

- On 2026-11-03, the wait time was 60 minutes.
- On 2026-11-04, the wait time was 180 minutes.

These 2 runs wrote no results file.

In W4, the evaluating model said that it had no permission to run the transcript tool. Thus it read the raw files of the test folder (the key `W4_evaluation.answer`). W4 checks the report and the seal, not the read path, so the run passed. [P5](../../docs/results.md#p5-the-model-judges-the-record-not-its-memory) checks the read with the transcript tool on the laptop.

The Codex part of this proof does not exist yet. The script refuses the setup `plugin-codex` ([Codex result](codex-0.5.7/cluster.json), [#461](https://github.com/mohanraj00/nookku/issues/461)).

## The scripted verdict test

I ran 2 scripted tests of the verdict with no model ([SPEC.md section 7.14](../../SPEC.md#714-verdict)). Each project has a copy of [examples/toy-shop-full/APP_SPEC.md](../../examples/toy-shop-full/APP_SPEC.md), with its `Verdict` table: 0 `agent_error` and at most 1 `repeated_reply`. Each project has the same script of 4 messages, as in [tests/test_verdict.py](../../tests/test_verdict.py).

- **Pass project.** The entry is the toy shop agent.
- **Defect project.** The entry is the toy shop agent with a planted defect: it sends its last reply again for each second message (`REPEAT_DEFECT` in [tests/test_verdict.py](../../tests/test_verdict.py)).

Each project needed an egress answer before the start. I gave each one an empty answer:

```bash
echo '{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}' | nookku register
nookku run --script script.jsonl --verdict
```

| Project | Audit | Verdict line | Exit code | Data |
|---|---|---|---|---|
| Pass | exit 0 | `Verdict: pass (2 limits).` | 0 | [verdict.json](verdict-0.5.7/pass.json) |
| Defect | exit 0 | `Verdict: fail. repeated_reply: 2, the limit is 1.` | 1 | [verdict.json](verdict-0.5.7/repeat-defect.json) |

Each data file is the `verdict.json` of its test. Each also has 4 `missing_trace_point` findings, because the toy shop agent makes none of the calls of the trace points of the full toy shop. That class has no limit, so it does not change the verdict.

## The koodam CLI

The Workspace proof needs the `koodam` CLI 0.3.0. I built it from the source of the v0.3.0 tag (904d7e1):

```bash
go build -ldflags '-X main.version=0.3.0'
```

The flag sets the version that `koodam --version` prints. The key `versions.koodam_cli` of the [results](../cluster/plugin-claude-code.json) gives `koodam 0.3.0`.

# Records and files

This page lists each file that Nooku writes, and links to the section of [SPEC.md](../../SPEC.md) that defines its format. SPEC.md is the authority. If this page and SPEC.md disagree, SPEC.md is correct.

## The state folder

`.nooku/` in your project holds the configuration and the tests.

| Path | Writer | Content |
|---|---|---|
| `config.json` | you, `nooku init` or the harness model | The configuration ([config.md](config.md)). |
| `entry.<ext>` | you or the harness model | The entry, if it is not in your app ([how-to/connect-your-agent.md](../how-to/connect-your-agent.md)). |
| `mode` | the relays | `on` or `off`: relay mode. It survives a restart of the harness ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)). |
| `current.json` | the bridge | The running test: its id, its folder, the tap URL, the pid and the start time of the bridge. The file exists only while a test runs. |
| `ending.json` | `nooku end` | The harness session that ends the test, for the bridge. |
| `relay.jsonl` | the relays | With no entry: the relay record ([how-to/http-tap.md](../how-to/http-tap.md)). |
| `tests/<test-id>/` | the bridge, the relays, the tap | One folder for each test (see below). |

Add `.nooku/tests/` to `.gitignore` if the conversation must not go into your repo ([SECURITY.md](../../SECURITY.md)).

The bridge also writes a copy of each seal to `~/.nooku/seals/<test-id>.json`, or under `NOOKU_HOME` if it is set.

## The test folder

Each test is a new conversation, with a new test id and a new entry process. The test folder is `.nooku/tests/<test-id>/`. The test id is the start time and a random part, for example `20261007-133823-0b63`.

| File | Content | Format |
|---|---|---|
| `relay.jsonl` | What you typed and saw. | [SPEC.md section 2.2](../../SPEC.md#22-relay-record) |
| `tap.jsonl` | What the entry received and sent, and the model sessions that the tap found. | [SPEC.md section 2.1](../../SPEC.md#21-tap-record) |
| `app.log` | The stderr of the entry and your app. | text |
| `bridge.log` | The steps of the bridge, and each error of the trace, the audit or the seal. | text |
| `manifest.json` | The test id, the times, the entry, the harness versions and the SHA-256 of each configuration file. | [SPEC.md section 7.2](../../SPEC.md#72-start-and-end) |
| `sessions/` | A copy of each session file of your app's model sessions. | [SPEC.md section 7.3](../../SPEC.md#73-model-sessions) |
| `trace.jsonl` | Each message, tool call and command of those sessions, and each item of `otel.jsonl`, `backend.jsonl` and `model_api.jsonl`, with its result, its turn and its line in the source file. | [SPEC.md section 8.2](../../SPEC.md#82-trace-record) |
| `findings.json` | The checks of the trace: failed tools and commands, agent errors, turns with no model item, and more. | [SPEC.md section 8.6](../../SPEC.md#86-findings) |
| `audit.json` | The audit of the two records, as `nooku audit --json` prints it. | [SPEC.md section 3](../../SPEC.md#3-audit) |
| `seal.json` | The SHA-256 of each other file at the end of the test. `nooku verify` shows if a file changed after the end. | [SPEC.md section 7.4](../../SPEC.md#74-seal) |
| `report.md` | The model's evaluation, if it ran. | [SPEC.md section 9.3](../../SPEC.md#93-report) |
| `denied.jsonl` | The model tool calls that the relay denied after the end. | `blocked_call` rows of [SPEC.md section 2.2](../../SPEC.md#22-relay-record) |
| `backend.jsonl` | The calls of your app to its backends. | [SPEC.md section 7.6](../../SPEC.md#76-backend-proxies) |
| `model_api.jsonl` | The direct calls of your app to a model API. | [SPEC.md section 7.7](../../SPEC.md#77-model-api-proxies) |
| `otel.jsonl` | The OpenTelemetry spans and logs of your app, if it sent any. | [SPEC.md section 7.5](../../SPEC.md#75-otlp-receiver) |

The seal does not contain `report.md`, `bridge.log`, `seal.json` and `denied.jsonl`, because these files change after the end.

## Versions of the formats

| Record | Version | Defined in |
|---|---|---|
| Tap record and relay record | `"0.2"`. The row of a failed stream in the tap record is `"0.3"`. A reader accepts `"0.1"`, `"0.2"` and `"0.3"`. | [SPEC.md section 2](../../SPEC.md#2-record-format) |
| Agent contract | `1` | [SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1) |
| Trace row | `"0.3"` | [SPEC.md section 8.2](../../SPEC.md#82-trace-record) |
| Seal | `1` | [SPEC.md section 7.4](../../SPEC.md#74-seal) |
| `otel.jsonl`, `backend.jsonl` and `model_api.jsonl` rows | `1` | [SPEC.md sections 7.5 to 7.7](../../SPEC.md#7-tests) |

## Conformance cases

The folders in [conformance/](../../conformance/) are the executable form of SPEC.md. [conformance/build.py](../../conformance/build.py) writes each case by hand, and the tests in `tests/` run them:

| Folder | Tests | Test file |
|---|---|---|
| [conformance/cases/](../../conformance/cases/) | the audit | [tests/test_conformance.py](../../tests/test_conformance.py) |
| [conformance/contract/](../../conformance/contract/) | the agent contract in stdio mode | [tests/test_contract.py](../../tests/test_contract.py) |
| [conformance/trace/](../../conformance/trace/) | the trace and the findings | [tests/test_trace.py](../../tests/test_trace.py) |
| [conformance/seal/](../../conformance/seal/) | `verify` | [tests/test_seal.py](../../tests/test_seal.py) |
| [conformance/otlp/](../../conformance/otlp/) | the OTLP receiver | [tests/test_otlp.py](../../tests/test_otlp.py) |

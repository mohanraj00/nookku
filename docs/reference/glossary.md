# Glossary

This page defines each term that the docs use for the parts of verbatim-relay. Each term links to the section of [SPEC.md](../../SPEC.md) that defines it exactly. SPEC.md is the authority. If this page and SPEC.md disagree, SPEC.md is correct.

The test `tests/test_docs.py` checks that each term on this page links to a section of SPEC.md.

## Agent

The chat agent under test: your app. In a test, the tap talks to the agent through the entry.

SPEC.md: [section 1](../../SPEC.md#1-parts).

## Agent contract

The line format between the tap and the entry. Each message goes in as one JSON line on stdin. Each reply or error comes out as one JSON line on stdout. The agent writes its logs to stderr. In Python, `verbatim_relay.agent.serve()` speaks the contract for one function.

SPEC.md: [section 6](../../SPEC.md#6-agent-contract-version-1).

## Audit

The program that compares the relay record with the tap record byte for byte. It names each break. It exits with 0 if the records have no break, and with 1 if they have one or more breaks. It exits with 2 if a record is missing or invalid, or if the tap record has an unparsed row. `verbatim-relay audit` runs it, and the end of a test writes its result to `audit.json`.

SPEC.md: [section 3](../../SPEC.md#3-audit), [exit codes](../../SPEC.md#34-exit-codes).

## Break

A difference between the relay record and the tap record that the audit reports, for example `altered_reply`: the tester saw a reply that is different from the reply that the agent sent. Each break has a break class.

SPEC.md: [section 3.3](../../SPEC.md#33-break-classes).

## Bridge

A background process that runs one test. `verbatim-relay start` starts it, and `verbatim-relay end` stops it. It runs the tap in stdio mode, the OTLP receiver and the proxies. At the end, it copies the session files of the app into the test folder, and writes the trace, `audit.json` and the seal.

SPEC.md: [section 7.2](../../SPEC.md#72-start-and-end).

## Entry

The command that the tap starts in a test. It is a thin wrapper that starts your app and speaks the agent contract. It is test code, not app code. The key `entry` of `.verbatim-relay/config.json` holds it. The entry is in the message path, and the tap records only what goes in and out of it. Review it before a test ([limits.md](../limits.md)).

SPEC.md: [section 1](../../SPEC.md#1-parts), [section 7.1](../../SPEC.md#71-configuration).

## Evaluation

The step at the end of a test in which the harness model judges your app. The model reads the transcript with the trace, the findings, the audit and the code of your app. Then it writes `report.md` in the test folder. The prompt `verbatim-relay end` starts it. The key `evaluate: false` stops it. A report is a model answer, so it can be wrong.

SPEC.md: [section 9](../../SPEC.md#9-evaluation).

## Findings

The results of the checks of the trace, in `findings.json` in the test folder. An example is a tool call that failed, or a turn with no model item. The findings do not change the exit code of the audit.

SPEC.md: [section 8.6](../../SPEC.md#86-findings).

## Harness

A coding harness: Claude Code or Codex. The tester types in a harness, and the relay is an extension of it. Your app can also use a harness for its own model sessions, for example through the Claude Agent SDK. Then that harness writes the session files that the test copies. The README calls verbatim-relay a "test harness". Each other use of "harness" in the docs means a coding harness.

SPEC.md: [section 1](../../SPEC.md#1-parts), [section 7.3](../../SPEC.md#73-model-sessions).

## Harness model

The model in the tester's harness. In relay mode, it does not receive the tester's messages and does not write the replies. At the end of a test, it does the evaluation.

SPEC.md: [section 5](../../SPEC.md#5-relays), [section 9](../../SPEC.md#9-evaluation).

## Relay

The harness extension that carries each message from the tester to the tap, and each reply from the tap to the tester. The model does not write either direction. A relay is the Claude Code plugin or the hook kit. A relay writes the relay record. It fails closed: if it cannot send a message, the message still does not go to the model.

SPEC.md: [section 1](../../SPEC.md#1-parts), [section 5](../../SPEC.md#5-relays).

## Relay mode

The state in which the relay sends each prompt of the tester to the tap, and the model does not receive the prompt. If relay mode is off, the relay does nothing to prompts. With an entry, `verbatim-relay start` switches it on and `verbatim-relay end` switches it off. The file `.verbatim-relay/mode` holds it.

SPEC.md: [section 5](../../SPEC.md#5-relays), [section 7.2](../../SPEC.md#72-start-and-end).

## Relay record

`relay.jsonl`: what the tester typed and what the tester saw. The relay writes it. In a test, it is in the test folder.

SPEC.md: [section 2.2](../../SPEC.md#22-relay-record).

## Seal

`seal.json` in the test folder: the SHA-256 of each file of the test at the end of the test. The bridge also writes a copy outside the project. `verbatim-relay verify` shows each file that changed after the end. The seal does not stop a change. It makes a change visible. The files that change after the end, for example `report.md`, are not in the seal.

SPEC.md: [section 7.4](../../SPEC.md#74-seal).

## Tap

A proxy between the relay and the agent. It forwards each request and each response with no change, and it writes the tap record. In stdio mode, it starts the entry and speaks the agent contract with it. A test uses this mode. In HTTP mode, it is in front of an agent that is already an HTTP server.

SPEC.md: [section 1](../../SPEC.md#1-parts), [section 4](../../SPEC.md#4-tap).

## Tap record

`tap.jsonl`: what the agent received and what it sent. The tap writes it. In a test, it is in the test folder.

SPEC.md: [section 2.1](../../SPEC.md#21-tap-record).

## Test

One run of the entry, from `verbatim-relay start` to `verbatim-relay end`. Each test is a new conversation, with a new test id and a new entry process.

SPEC.md: [section 1](../../SPEC.md#1-parts), [section 7](../../SPEC.md#7-tests).

## Test folder

`.verbatim-relay/tests/<test-id>/`: the folder of one test. It holds the two records, the copied session files, the trace, the findings, `audit.json`, the seal and `report.md`. [records.md](records.md#the-test-folder) lists each file.

SPEC.md: [section 7.2](../../SPEC.md#72-start-and-end).

## Tester

The person who types messages in the harness to test the agent.

SPEC.md: [section 1](../../SPEC.md#1-parts).

## Trace

`trace.jsonl` in the test folder: one record of the model items of your app in a test. It joins the session files, `otel.jsonl`, `backend.jsonl` and `model_api.jsonl`. Each item has its turn and its line in the source file. `verbatim-relay trace` builds it again.

SPEC.md: [section 8](../../SPEC.md#8-trace).

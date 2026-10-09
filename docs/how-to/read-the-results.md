# Read the results of a test

After a test, the test folder holds the records, the trace, the audit, the seal and, if the model ran, a report. This page tells you how to read these files in order. Read the seal first. If a file changed after the end of the test, do not trust the other results.

The sample output on this page comes from one test of the [toy shop agent](../../examples/toy-shop/agent.py) with verbatim-relay 0.3.0. The test has the 3 messages of the [tutorial](../getting-started.md#6-run-the-test). I gave each prompt to `nooku hook --harness claude-code` as a `UserPromptSubmit` event, as Claude Code does. No harness model ran, so this test has no report. The output is a sample of one run, not a measurement. To make it again, run the steps of the tutorial on the toy shop. I shortened the paths to `.../`. The test id and the times are different on your machine.

## The test folder

Each test has one folder, `.nooku/tests/<test-id>/`. The comment on each line tells which part writes the file, when it writes it, and if the seal covers it. The steps of the end are in [SPEC.md section 7.2](../../SPEC.md#72-start-and-end).

```text
.nooku/tests/20261007-224435-5353/
  manifest.json      the bridge, at the start; the end adds the end time      sealed
  relay.jsonl        the relay, at each turn                                  sealed
  tap.jsonl          the tap, at each exchange and each model session         sealed
  app.log            the entry and your app, on stderr, during the test       sealed
  otel.jsonl         the OTLP receiver, if the app sends spans or logs        sealed
  backend.jsonl      a backend proxy, if the app calls a backend              sealed
  model_api.jsonl    a model API proxy, if the app calls a model API          sealed
  sessions/
    claude-code/<session>.jsonl   the bridge, at the end (step 3)             sealed
    codex/<rollout file>          the bridge, at the end (step 3)             sealed
  trace.jsonl        the bridge, at the end (step 5)                          sealed
  findings.json      the bridge, at the end (step 5)                          sealed
  audit.json         the bridge, at the end (step 6)                          sealed
  seal.json          the bridge, at the end (step 7)                          not sealed
  bridge.log         the bridge, from the start to the end                    not sealed
  report.md          the harness model, after the end                         not sealed
  denied.jsonl       the relay, after the end, for each denied tool call      not sealed
```

- `nooku trace` writes `trace.jsonl` and `findings.json` again, and writes their new SHA-256 to the seal.
- A file exists only if its writer has data. The toy shop has no model, no backend and no telemetry, so its folder has no `sessions/`, `otel.jsonl`, `backend.jsonl` or `model_api.jsonl`.

[reference/records.md](../reference/records.md#the-test-folder) gives the format of each file.

## 1. Find the test id

The end text of a test gives its id and its folder:

```text
nooku: relay mode is off.
Test 20261007-224435-5353 ended: 3 turns, 0 model sessions.
Folder: .../toy-shop/.nooku/tests/20261007-224435-5353
Trace: 0 model items in 3 turns, no findings.
```

If you do not have the end text, list the test folders:

```bash
ls .nooku/tests/
```

```text
20261007-224433-6815
20261007-224435-5353
```

`nooku check` also makes a test folder. Do not read the check tests as your tests. A check test has one turn from the harness `nooku-check`. To find the check tests:

```bash
grep -l '"harness": "nooku-check"' .nooku/tests/*/relay.jsonl
```

```text
.nooku/tests/20261007-224433-6815/relay.jsonl
```

`nooku trace`, `verify` and `transcript --trace` use the latest test if you do not give a test id. `transcript` with no `--trace` uses the latest test only if the configuration has an `entry`. With no entry, it reads the relay record of the configuration, and shows its latest session. If you ran `check` after your test, the latest test is the check test. Then give the test id of your test to each command.

## 2. Read the seal

```bash
nooku verify 20261007-224435-5353
```

```text
Seal: intact. No record changed after the end of the test.
```

The exit code is 0 if the seal is intact. It is 2 if the seal is broken or if the test folder does not exist. If a file changed after the end, the result names the file. For this sample, I added one line end to `relay.jsonl` in a copy of the project:

```text
Seal: BROKEN. changed: relay.jsonl. Do not trust these records.
```

If the seal is broken, do not trust the changed files. `nooku verify --json` gives the lists `changed`, `missing` and `added`, and the result of the copy in your home folder ([SPEC.md section 7.4](../../SPEC.md#74-seal)). The seal shows a change. It does not stop a change.

## 3. Read the audit

`audit.json` is the audit of `tap.jsonl` against `relay.jsonl`, in the form of `nooku audit --json`:

```bash
cat .nooku/tests/20261007-224435-5353/audit.json
```

```json
{
 "v": "0.2",
 "exit": 0,
 "turns": 3,
 "exchanges": 3,
 "blocked_calls": 0,
 "model_sessions": 0,
 "breaks": [],
 "notes": [],
 "errors": [],
 "skipped": []
}
```

`exit` is the exit code of the audit ([SPEC.md section 3.4](../../SPEC.md#34-exit-codes)):

| Exit | Meaning | Where to look |
|---|---|---|
| 0 | The records are valid and have no break. | Nothing more in the audit. |
| 1 | The records are valid and have 1 or more breaks. | `breaks`: one object for each break. |
| 2 | A record is missing or invalid, or the tap has an unparsed exchange. The audit did not compare the texts. | `errors` and `skipped`: the checks that did not run. |

A clean audit means that each message reached the agent with no change, and each reply reached you with no change. It does not mean that the replies are good. The audit compares the words only. The findings, the report and the transcript tell you what the app did.

Each break has `class`, `relay_line`, `tap_line` and `evidence`. For a changed text, the evidence gives the index of the first different character, a short part of each text, and the length of each text. This break is from the conformance case [several_breaks](../../conformance/cases/several_breaks/):

```json
{
 "class": "altered_input",
 "relay_line": 1,
 "tap_line": 1,
 "evidence": {
  "first_difference": 33,
  "expected": "order #4471.  ",
  "actual": "order #4471.",
  "expected_length": 35,
  "actual_length": 33
 }
}
```

`expected` is from `relay.jsonl`, the text that you typed or saw. `actual` is from `tap.jsonl`, the text that the agent received or sent. Here, the agent did not get the 2 spaces at the end of the message.

### Break classes

The audit has 7 break classes ([audit.py](../../src/nooku/audit.py), [SPEC.md section 3.3](../../SPEC.md#33-break-classes)). The fixes follow `BREAK_FIX` in [bridge.py](../../src/nooku/bridge.py), the text that `nooku check` gives for a break.

| Class | What the records show | Fix |
|---|---|---|
| `altered_input` | The `said` text in `relay.jsonl` and the `input` text in `tap.jsonl` at that position are different. | Make sure that only one relay sends messages to the tap. |
| `injected_input` | `tap.jsonl` has an exchange that has no turn in `relay.jsonl`. `relay_line` is `null`. | Make sure that only one relay sends messages to the tap. |
| `duplicate_send` | `tap.jsonl` has more exchanges with the text of a `said` than `relay.jsonl` has turns with it. | Make sure that only one relay sends messages to the tap. For example, do not use the plugin and the hook kit in one project. |
| `out_of_order` | Both records have the message, but at different positions. | Make sure that only one relay sends messages to the tap. |
| `not_delivered` | `relay.jsonl` has a turn that has no exchange in `tap.jsonl`. `tap_line` is `null`. | Read `bridge.log` and `app.log`. |
| `altered_reply` | The `reply` text in `tap.jsonl` and the `shown` text in `relay.jsonl` are different. | Read `bridge.log`. |
| `unshown_reply` | The `shown` text in `relay.jsonl` is `null`. The relay showed no reply. | Read `bridge.log`. |

For each error of exit 2, [troubleshooting.md](../troubleshooting.md#audit-verify-and-trace) gives the cause and the fix.

## 4. Read the findings

`findings.json` holds the checks of the trace ([SPEC.md section 8.6](../../SPEC.md#86-findings)):

```bash
cat .nooku/tests/20261007-224435-5353/findings.json
```

```json
{
 "v": "0.2",
 "test": "20261007-224435-5353",
 "turns": 3,
 "items": 0,
 "sessions": [],
 "otel": null,
 "backend": null,
 "model_api": null,
 "counts": {
  "agent_error": 0,
  "tool_error": 0,
  "command_failed": 0,
  "span_error": 0,
  "backend_error": 0,
  "model_api_error": 0,
  "turn_without_model": 0,
  "item_between_turns": 0,
  "otel_tool_not_in_session": 0,
  "server_not_from_app": 0,
  "session_inferred": 0,
  "version_untested": 0
 },
 "findings": []
}
```

`items` is the number of model items in `trace.jsonl`. `counts` has one number for each check. The toy shop has no model, so the trace has no item and no finding.

A finding is a fact, not yet an issue. For example, a tool error can be the correct result of a request for an order that does not exist. The findings do not change the exit code of the audit.

`nooku trace` shows the findings on one line each. This output is from a copy of the conformance case [claude_code_toy_shop](../../conformance/trace/claude_code_toy_shop/), which has a Claude Code session file:

```text
Trace: 11 model items in 3 turns, 1 agent_error, 3 tool_error, 1 turn_without_model, 2 item_between_turns.
  agent_error (turn 2): the agent gave status 500
  tool_error (turn 2, claude-code): lookup_order: no such order
  tool_error (turn 2, claude-code): Bash: cat: returns.txt: No such file
  tool_error (no turn, claude-code): lookup_order: no tool_result in the session file
  turn_without_model (turn 3): no model item in this turn
  item_between_turns (no turn, claude-code): a message item
  item_between_turns (no turn, claude-code): a tool_call item
```

Each finding in `findings.json` has `check`, `turn` and `detail`. A finding about a model item also has `harness`, `session` and `source`, the file and the line in `sessions/`.

### Trace checks

The trace has 12 trace checks ([trace.py](../../src/nooku/trace.py)). `findings.json` sorts the findings in the order of this table.

| Check | Finding |
|---|---|
| `agent_error` | The agent gave a status that is not 200 for an exchange. |
| `tool_error` | A tool call of the app's model has an error. |
| `command_failed` | A command of the app's model has an exit code that is not 0, or an error. |
| `span_error` | An OpenTelemetry span of the app has an error. |
| `backend_error` | A call to a backend got no answer, or a status of 500 or more. |
| `model_api_error` | A direct call to a model API has an error, or a status of 400 or more. |
| `turn_without_model` | A turn has no `message`, `tool_call` or `command` item from a session file. A turn with only an OTLP, backend or model API item still gets this finding. This check runs only if the trace has at least 1 item from a session file. |
| `item_between_turns` | A model item has no turn, but it occurred at or after the start of turn 1. |
| `otel_tool_not_in_session` | A harness log says that a tool ran, but the session file of that harness and turn has no call of that tool. |
| `server_not_from_app` | A Claude Code session used an MCP server that the app's configuration cannot give: a claude.ai connector or a plugin server. |
| `session_inferred` | The tap found a Codex session from its folder and its time, not from its process. |
| `version_untested` | A session file comes from a harness version that the proofs do not cover. |

## 5. Read the report

If the harness model evaluated the test, it wrote `report.md` in the test folder ([SPEC.md section 9.3](../../SPEC.md#93-report)). The report has one table with the columns Class, Turn, Evidence and Issue, and one row for each issue. This row comes from the report of the tutorial test ([getting-started.md](../getting-started.md#9-read-the-report)):

```markdown
| Class | Turn | Evidence | Issue |
|---|---|---|---|
| missing_action | 1 | Turn 1; `agent.py:22`, `agent.py:26` | The tester said "the mug i ordered came with a crack in the handle". The app replied "Which item is this about: the mug or the teapot?". ... |
```

The issue classes:

| Class | The app ... |
|---|---|
| `business_rule` | broke a rule of the business. |
| `wrong_tool` | called a tool that does not fit the request. |
| `wrong_arguments` | called the correct tool with incorrect arguments. |
| `unsupported_reply` | said a fact that no tool result and no rule supports. |
| `missing_action` | did not do an action that the request or a rule needs. |
| `state_mismatch` | gave a reply or a trace that does not agree with its state. |

Turn is the turn number, or `-` if the issue has no turn. Evidence has 3 forms:

- `trace.jsonl:N`: line N of `trace.jsonl`. Read it with `sed -n 'Np' trace.jsonl`.
- A turn: the turn in the transcript (step 6).
- A source line, for example `agent.py:22`: line 22 of that file of your app.

The report is a model answer, so check each piece of evidence. Open each line and compare it with the issue. For the row above, the lines of the toy shop agent are:

```bash
sed -n 22p agent.py
sed -n 26p agent.py
```

```text
FALLBACK = "Which item is this about: the mug or the teapot?"
    return next((r for k, r in REPLIES.items() if k in text.lower()), FALLBACK)
```

Line 22 is the reply of turn 1, and line 26 sends it for each message with no keyword. The evidence agrees with the issue. If a line does not agree, do not trust that row.

## 6. Read the transcript with the trace

```bash
nooku transcript --trace --test 20261007-224435-5353
```

```text
Seal: intact. No record changed after the end of the test.
nooku transcript with trace, test 20261007-224435-5353: 3 turns, 0 model items. The tester and agent blocks are exact: they come from tap.jsonl. ...

════ turn 1 ════
──── tester → agent ────
hi, the mug i ordered came with a crack in the handle
──── agent → tester ────
Which item is this about: the mug or the teapot?

════ turn 2 ════
──── tester → agent ────
ok what is your refund policy
──── agent → tester ────
Our refund policy:

1. Damaged items: full refund.
2. Change of mind: 30 days.


════ turn 3 ════
──── tester → agent ────
do you ship to delhi?
──── agent → tester ────
We ship to Chennai and Pune. Delivery takes 3 to 5 days.  
```

The first line is the result of the seal. Each turn shows the message and the reply as the agent received them and sent them, from `tap.jsonl`. If the app has a model, each turn also shows the model items and the findings of that turn. Each item names its line as `[trace.jsonl:N]`. In the copy of the conformance case of step 4, turn 2 is:

```text
════ turn 2 ════
──── tester → agent ────
toy shop message
──── model items ────
[trace.jsonl:7] claude-code message, user:
Where is my order 9999?
[trace.jsonl:8] claude-code tool_call: shop.lookup_order
input: {"order": "9999"}
error:
no such order
[trace.jsonl:9] claude-code tool_call: Bash
input: {"command": "cat returns.txt"}
error:
cat: returns.txt: No such file
──── findings ────
- agent_error: the agent gave status 500
- tool_error: lookup_order: no such order [trace.jsonl:8]
- tool_error: Bash: cat: returns.txt: No such file [trace.jsonl:9]
──── agent → tester ────
(no reply: status 500, the agent failed)
```

Items with no turn come after the last turn. If `tap.jsonl` has a line that is not valid, the transcript shows `Record: INVALID.` and no turn ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)).

## 7. Decide the next step

| Result | Next step |
|---|---|
| The seal is broken. | Do not trust the changed files. Find the person or the tool that changed them. Then run the test again. |
| The audit exits with 2. | Read `errors` in `audit.json`, and find the error in [troubleshooting.md](../troubleshooting.md#audit-verify-and-trace). Fix the entry or the relay, then run the test again. |
| The audit exits with 1. | Find the class of each break in the [break classes](#break-classes) table, and do its fix. Then run the test again. Do not trust the report of this test. |
| A finding. | Find the item in the transcript. If the item shows a fault of the app, fix the app. If it is the correct result, keep it as a fact. |
| `version_untested`. | Run the proofs for the new harness version ([run-the-proofs.md](run-the-proofs.md)). |
| `server_not_from_app`. | Give the app's model only the tools of the app ([isolate-agent-sdk.md](isolate-agent-sdk.md)). |
| A row of the report. | Check its evidence (step 5). If the evidence agrees, fix the app and run the test again. |
| A clean audit, no findings and no report rows. | The words arrived exactly. Read the transcript yourself, and judge each reply. |

## Examples

[evaluation-example.md](../evaluation-example.md) has 2 worked evaluations of the toy shop. The first has a report with 4 rows, the trace lines that the report cites, and what the model got right and wrong. The second is an evaluation of the words only, with no trace.

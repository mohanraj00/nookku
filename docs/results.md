# Method and results

Two kinds of evidence: proofs that each [relay](reference/glossary.md#relay) is exact, and a benchmark under pressure. Every number here comes from a file in this repo.

## 1. Proofs

Each proof runs the [harness](reference/glossary.md#harness) headless in a test (SPEC.md section 7). The [tester](reference/glossary.md#tester) starts the test with the prompt `nookku start`. The [entry](reference/glossary.md#entry) is the toy shop agent of the tests over stdio ([tests/toy_entry.py](../tests/toy_entry.py)), which uses `nookku.agent.serve`. The proofs run in 4 setups: the [plugin](reference/glossary.md#plugin) and the [project hooks](reference/glossary.md#project-hooks), each in Claude Code and in Codex. Each setup runs the same relay, `nookku hook`. Script: [scripts/proofs_relay.py](../scripts/proofs_relay.py).

| # | Proof |
|---|---|
| P1 | Each tester message reaches the agent byte for byte (the [tap record](reference/glossary.md#tap-record)). |
| P2 | Each reply reaches the tester byte for byte (`nookku view`, which shows each turn of the [relay record](reference/glossary.md#relay-record)). |
| P3 | A system prompt that tells the model to fix the tester's grammar and summarize each reply changes nothing. |
| P3b | With [relay mode](reference/glossary.md#relay-mode) off and the test still on, the model tries to call the [tap](reference/glossary.md#tap) with `curl`. The relay denies it, and the agent receives nothing. |
| P4 | The [audit](reference/glossary.md#audit) finds 0 [breaks](reference/glossary.md#break) in the proof records, and finds each of 5 planted faults: altered reply, unshown reply, altered input, injected input, missing record. |

Each proof also checks that the test ends, and that the tap finds no model session: the toy entry has no model, and the tester's own harness session must not count as one.

The 5 test messages have trailing spaces, non-ASCII text (`Ünïcödé`, `€`, `₹`), a message with an empty line, a markdown table and slang. Each runs once without and once with the hostile system prompt.

| Form | Harness | P1 | P2 | P3 | P3b | P4 | Data |
|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/plugin-claude-code/results.json) |
| Plugin | Codex 0.162.1 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/plugin-codex/results.json) |
| Project hooks | Claude Code 2.1.302 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-claude-code/results.json) |
| Project hooks | Codex 0.162.1 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-codex/results.json) |

Each run of the first table used nookku 0.5.4 on 2026-10-20 (the keys `date` and `test.versions.nookku` of each results file). Since nookku 0.5.1, with relay mode off, the hook blocks a prompt near a [control prompt](reference/glossary.md#control-prompt) ([#413](https://github.com/mohanraj00/nookku/issues/413)). P3b runs with relay mode off, so the runs of both harnesses ran this code. In each setup, the model used 0 output tokens in every relay turn. The hook blocks the prompt before the model runs. The plugin in Codex ran in the `CODEX_HOME` of [proof_codex_gate.py](../scripts/proof_codex_gate.py), where I trusted its hooks. In both Codex setups, `nookku start` ran the hook gate first ([SPEC.md section 7.8](../SPEC.md#78-codex-hook-gate)).

**The chat page.** The setup `page-claude-code` runs the same proofs with the [chat page](reference/cli.md#nookku-chat) as the relay ([#327](https://github.com/mohanraj00/nookku/issues/327)). The tester starts and ends the test in Claude Code with the plugin, and sends the 5 messages 2 times on the page, with the headers of a browser. P2 also checks the answer of the page and the turns that the page shows. P3 is different: the proof counts the rows of the Claude Code session files of the project before and after each page turn. A page turn must add 0 rows, and the files must hold 0 of the messages. P3c: the model tries to call the page with `curl`, the guard denies it, and the agent receives nothing. For this attack, the proof gives the session cookie and the page key to the model, so the `blocked_call` row holds them. In the copy of `relay.jsonl` in `proofs/`, a marker with the SHA-256 of each value takes its place. The audit counts the `blocked_call` rows and does not read their detail, so the copy gives the same audit. The tap record has the same inputs, statuses and replies as the tap record of `plugin-claude-code`.

| Form | Harness | P1 | P2 | P3 | P3b | P3c | P4 | Same tap record | Data |
|---|---|---|---|---|---|---|---|---|---|
| Chat page | Claude Code 2.1.302 | 10/10 | 10/10 | 0 of 5 messages in 1 session file | pass | pass | 5/5 | yes | [results](../proofs/page-claude-code/results.json) |

The chat page run used nookku 0.5.4 on 2026-10-20 (the keys `nookku` and `date` of the results file).

With a streamed agent, the proof scripts take `--stream`. The toy agent sends each reply as Chat Completions SSE events, and the tap with the `openai` adapter forwards them. The relay runs in HTTP mode with no entry, so P3b does not run. P4 audits the records and finds each planted fault.

With `--stream --on-request`, the toy agent streams only if the request has `"stream": true`. The relay has the option `openai_stream`, so it asks for a stream. Each exchange must be a stream.

| Form | Harness | Agent streams | P1 | P2 | Streamed exchanges | P4 | Data |
|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | always | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/plugin-claude-code-stream/results.json) |
| Plugin | Codex 0.162.1 | always | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/plugin-codex-stream/results.json) |
| Project hooks | Claude Code 2.1.302 | always | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/hooks-claude-code-stream/results.json) |
| Project hooks | Codex 0.162.1 | always | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/hooks-codex-stream/results.json) |
| Plugin | Claude Code 2.1.302 | on request | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/plugin-claude-code-stream-on-request/results.json) |
| Plugin | Codex 0.162.1 | on request | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/plugin-codex-stream-on-request/results.json) |
| Project hooks | Claude Code 2.1.302 | on request | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/hooks-claude-code-stream-on-request/results.json) |
| Project hooks | Codex 0.162.1 | on request | 10/10 | 10/10 | 10 | 5/5 | [results](../proofs/hooks-codex-stream-on-request/results.json) |

In the 8 streamed runs, the model also used 0 output tokens in every relay turn. Each streamed result records nookku 0.5.4 in the key `nookku`, and the date 2026-10-20 in the key `date`.

Each results file has the records of the test next to it: `tap.jsonl` and `relay.jsonl`. The P5 proofs below and the benchmark ran before tests existed, with the tap in front of an HTTP agent.

### Model sessions of the app

[scripts/proof_sessions.py](../scripts/proof_sessions.py) runs `nookku check` on a toy shop app with real model sessions ([tests/toy_models_entry.py](../tests/toy_models_entry.py)). For one message, the app runs one Claude Agent SDK session with an in-process `lookup_order` tool, and one `codex app-server` thread. The check must find each session and copy its session file.

| Harness of the app | Nookku | Found by | Session file copied | Data |
|---|---|---|---|---|
| Claude Agent SDK 0.2.168 | 0.5.4 | its process | yes | [results](../proofs/sessions/results.json) |
| codex-cli 0.162.1, app-server | 0.5.4 | its folder and time | yes | [results](../proofs/sessions/results.json) |

The Agent SDK runs its own bundled Claude Code. The `claude-code` version in the results is the `claude` command on `PATH`, not the bundled one. The results keep no model reply. The run was on 2026-10-20 (the key `date`).

### Trace of the model sessions

[scripts/proof_trace.py](../scripts/proof_trace.py) runs a test of the same toy shop app with 4 messages. Now the Codex thread also has `lookup_order` as a dynamic tool, the toy MCP server `check_stock` ([tests/toy_mcp_server.py](../tests/toy_mcp_server.py)) and a shell. The [trace](reference/glossary.md#trace) must show 6 tool calls and commands, each with its result or its error, in the correct turn.

| Session file | Nookku | Items | Expected calls found | Data |
|---|---|---|---|---|
| Claude Code 2.1.301, bundled in Claude Agent SDK 0.2.168 | 0.5.4 | 10 | 2/2 | [results](../proofs/trace/results.json) |
| codex-cli 0.162.1, app-server | 0.5.4 | 16 | 4/4 | [results](../proofs/trace/results.json) |
| Claude Code 2.1.301, bundled in Claude Agent SDK 0.2.168 | 0.5.3 | 10 | 2/2 | [results](../proofs/trace/results-0.5.3-codex-usage-limit.json) |
| codex-cli 0.162.1, app-server, no usage left | 0.5.3 | 4 | **0/4** | [results](../proofs/trace/results-0.5.3-codex-usage-limit.json) |
| Claude Code 2.1.301, bundled in Claude Agent SDK 0.2.168 | 0.5.2 | 10 | 2/2 | [results at the tag v0.5.3](https://github.com/mohanraj00/nookku/blob/v0.5.3/proofs/trace/results.json) |
| codex-cli 0.162.1, app-server | 0.5.2 | 12 | 4/4 | [results at the tag v0.5.3](https://github.com/mohanraj00/nookku/blob/v0.5.3/proofs/trace/results.json) |
| Claude Code 2.1.300, bundled in Claude Agent SDK 0.2.167 | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.300.json) |
| codex-cli 0.162.1, app-server (run with Agent SDK 0.2.167) | 0.5.1 | 18 | 4/4 | [results](../proofs/trace/results-2.1.300.json) |
| Claude Code 2.1.299, bundled in Claude Agent SDK 0.2.166 | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.299.json) |
| codex-cli 0.162.1, app-server (run with Agent SDK 0.2.166) | 0.5.1 | 12 | 4/4 | [results](../proofs/trace/results-2.1.299.json) |
| Claude Code 2.1.296, Agent SDK 0.2.164 with `cli_path` | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.296.json) |
| codex-cli 0.162.1, app-server (run with Claude Code 2.1.296) | 0.5.1 | 12 | 4/4 | [results](../proofs/trace/results-2.1.296.json) |
| Claude Code 2.1.295, Agent SDK 0.2.164 with `cli_path` | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.295.json) |
| codex-cli 0.162.1, app-server (run with Claude Code 2.1.295) | 0.5.1 | 12 | 4/4 | [results](../proofs/trace/results-2.1.295.json) |
| Claude Code 2.1.294, bundled in Claude Agent SDK 0.2.165 | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.294.json) |
| codex-cli 0.162.1, app-server (run with Agent SDK 0.2.165) | 0.5.1 | 12 | 4/4 | [results](../proofs/trace/results-2.1.294.json) |
| Claude Code 2.1.293, Agent SDK 0.2.164 with `cli_path` | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.293.json) |
| codex-cli 0.162.1, app-server (run with Claude Code 2.1.293) | 0.5.1 | 12 | 4/4 | [results](../proofs/trace/results-2.1.293.json) |
| Claude Code 2.1.301, bundled in Claude Agent SDK 0.2.168 (earlier run) | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.301.json) |
| codex-cli 0.162.1, app-server (earlier run with Agent SDK 0.2.168) | 0.5.1 | 16 | 4/4 | [results](../proofs/trace/results-2.1.301.json) |
| Claude Code 2.1.292, bundled in Claude Agent SDK 0.2.164 (earlier run) | 0.5.1 | 10 | 2/2 | [results](../proofs/trace/results-2.1.292.json) |
| codex-cli 0.162.1, app-server (earlier run) | 0.5.1 | 12 | 4/4 | [results](../proofs/trace/results-2.1.292.json) |
| Claude Code 2.1.292, bundled in Claude Agent SDK 0.2.164 (earlier run) | 0.5.0 | 10 | 2/2 | [results](../proofs/trace/results-nookku-0.5.0.json) |
| codex-cli 0.162.1, app-server (earlier run) | 0.5.0 | 12 | 4/4 | [results](../proofs/trace/results-nookku-0.5.0.json) |
| Claude Code 2.1.292, bundled in Claude Agent SDK 0.2.164 (earlier run) | 0.4.2 | 10 | 2/2 | [results](../proofs/trace/results-nookku-0.4.2.json) |
| codex-cli 0.162.1, app-server (earlier run) | 0.4.2 | 17 | 4/4 | [results](../proofs/trace/results-nookku-0.4.2.json) |
| Claude Code 2.1.292, bundled in Claude Agent SDK 0.2.164 (earlier run) | 0.4.1 | 10 | 2/2 | [results](../proofs/trace/results-nookku-0.4.1.json) |
| codex-cli 0.162.1, app-server (earlier run) | 0.4.1 | 11 | **3/4** | [results](../proofs/trace/results-nookku-0.4.1.json) |
| Claude Code 2.1.292, bundled in Claude Agent SDK 0.2.164 (earlier run) | 0.4.0 | 10 | 2/2 | [results](../proofs/trace/results-nookku-0.4.0.json) |
| codex-cli 0.162.1, app-server (earlier run) | 0.4.0 | 12 | 4/4 | [results](../proofs/trace/results-nookku-0.4.0.json) |
| Claude Code 2.1.286, bundled in Claude Agent SDK 0.2.163 (earlier run) | | 11 | 2/2 | [results](../proofs/trace/results-2.1.286.json) |
| codex-cli 0.160.0, app-server (earlier run) | | 13 | 4/4 | [results](../proofs/trace/results-0.160.0.json) |

On 2026-10-16, I read the bundled Claude Code version of the 6 Agent SDK releases from 0.2.163 to 0.2.168 ([data](../proofs/trace/sdk-bundles.json), method: [scripts/proof_sdk_bundles.py](../scripts/proof_sdk_bundles.py)). 3 of these releases bundle a version from 2.1.293 to 2.1.300: 0.2.165 bundles 2.1.294, 0.2.166 bundles 2.1.299 and 0.2.167 bundles 2.1.300. On 2026-10-17, I ran the proof with each of these 3 releases. The second argument of the script sets the Agent SDK of the run. No Agent SDK release bundles 2.1.293, 2.1.295 or 2.1.296. For these 3 versions, I installed the npm package `@anthropic-ai/claude-code` of the version, and gave its `claude` program to Agent SDK 0.2.164 as `cli_path`. The third argument of the script sets this path, and the results add the version of the program to `claude-agent-sdk`. npm has no package of Claude Code 2.1.297 or 2.1.298, and no Agent SDK release bundles them. Thus these 2 versions have no proof, and a session file of them gives a `version_untested` [finding](reference/glossary.md#findings). Each of the 6 runs passed. Each Claude Code session file gave 10 items, with the same kinds, tools and turns.

The session files of 2.1.300 and 2.1.301 have 3 line types that the earlier versions do not have: `api-request`, `api-request-blob` and `api-request-shape` ([2.1.300 data](../proofs/trace/results-2.1.300.json), [2.1.301 data](../proofs/trace/results.json)). I read the fields of these lines in the 2.1.301 session file of the run. An `api-request-shape` line holds the system prompt and the tool definitions of the harness. An `api-request-blob` line holds parts of a request: the text that the harness adds, a user message, or a tool call. Each user message and each tool call in them is also in a `user` or `assistant` line of the file. An `api-request` line holds the model parameters and hashes of a request. Thus these lines give no new trace item, and the reader counts them and keeps no item ([SPEC.md section 8.4](../SPEC.md#84-readers)). The conformance case [claude_code_api_requests](../conformance/trace/claude_code_api_requests) shows this.

On 2026-10-17, I moved the Agent SDK pin of [scripts/proof_common.py](../scripts/proof_common.py) from 0.2.164 to 0.2.168, the newest Agent SDK on 2026-10-16. Then I ran the trace proof ([results-2.1.301.json](../proofs/trace/results-2.1.301.json)) and the sessions proof again. Both passed. On 2026-10-20, the trace proof, the sessions proof and the proofs of the app below also ran with this pin, so the app's session files are from Claude Code 2.1.301 (the key `versions` of each results file).

The run of nookku 0.5.4 on 2026-10-20 passed in both harnesses ([results.json](../proofs/trace/results.json)). The run of nookku 0.5.3 on 2026-10-19 failed, because the Codex account had no usage left. The Claude Code part passed. The trace gave 4 `model_error` findings, and the Codex session gave only 4 items. The 4 items are the 4 user messages, with no reply and no tool call. The data does not keep the error text of Codex.

The run of nookku 0.4.1 failed. In turn 1, the Codex model gave no answer: the `task_complete` event of the Codex session file has the error `server_overloaded` ("Selected model is at capacity"). Thus the Codex thread made no `lookup_order` call in turn 1. In turn 2, the model called `lookup_order` for order 9999 and then for order 4471. The trace put both calls in turn 2, which agrees with the session file. The trace gave no finding for the failed Codex turn, because the Codex reader ignores `task_complete` events. The 0.4.0, 0.4.2, 0.5.0 and 0.5.1 runs of the same versions passed.

In the runs of Claude Code 2.1.292 to 2.1.301 and codex-cli 0.162.1, with nookku 0.4.0, 0.4.1, 0.5.0, 0.5.1, 0.5.2 and 0.5.4, the findings are 2 `tool_error` (order 9999, one in each harness), 1 `command_failed` (`cat returns.txt`) and 1 `session_inferred` (the Codex session). The earlier codex-cli 0.160.0 run and the 0.4.2 run had 1 more `command_failed`: an `rg` search for that file by the Codex model. The number of Codex items changes with the answers of the model. In the 0.4.2 run, the Codex model wrote 1 message before its call or command in each of the 4 turns, and it made the `rg` search. Thus that run has 17 items and the 0.5.0 run has 12. The earlier 0.5.1 run with Agent SDK 0.2.168 has 16 Codex items, and the run with Agent SDK 0.2.167 has 18. Neither run has an `rg` search. The 0.5.4 run also has 16 Codex items: 3 messages and 1 call or command in each of the 4 turns, and no `rg` search. The results keep no model text: each message shows only its SHA-256 and its length. Each OpenTelemetry log of the harness, which holds the prompt and the answer, shows only its attribute names and the SHA-256 and length of its values.

### Backend calls

[scripts/proof_backend.py](../scripts/proof_backend.py) runs a test with an entry that makes 3 calls to a toy stock service through the backend proxy: a binary POST of 1,026 bytes, a UTF-8 GET, and a POST of 2,320,000 bytes. The proof compares the SHA-256 of each request body and each response body at 3 places: the entry, the stock service and `backend.jsonl`. It needs no model.

| Call | Request | Response | Same at all 3 places | Data |
|---|---|---|---|---|
| POST /scan | 1,026 bytes, binary | 2,059 bytes | yes | [results](../proofs/backend/results.json) |
| GET /stock | 0 bytes | 2,059 bytes | yes | [results](../proofs/backend/results.json) |
| POST /import | 2,320,000 bytes, cut in the record | 2,059 bytes | yes | [results](../proofs/backend/results.json) |

The record cuts the third request body at 1 MiB, but the stock service got all of its bytes. The [seal](reference/glossary.md#seal) of the [test folder](reference/glossary.md#test-folder) was intact. The run used nookku 0.5.4 on 2026-10-20 (the keys `versions` and `date` of the results file).

### Database calls from the driver trace

[scripts/proof_driver_trace.py](../scripts/proof_driver_trace.py) runs a test of a toy shop app that reads its stock from a SQLite file. The app uses the OpenTelemetry instrumentation of the sqlite3 driver, and the egress answer gives the database `record: driver`. It needs no model. In the run with nookku 0.5.4 on 2026-10-20 and opentelemetry-instrumentation-sqlite3 0.65b0, the 1 query of the turn is 1 driver query in the trace, with its statement text and no parameter values. The transcript names its source as the driver trace from the app process, and the seal is intact ([results](../proofs/driver-trace/results.json)).

### Direct model calls

[scripts/proof_model_api.py](../scripts/proof_model_api.py) runs a test with an entry that makes 7 calls to a toy model API through the model API proxies: a streamed Anthropic call, a streamed OpenAI Chat Completions call, an Anthropic call with a JSON answer, a streamed OpenAI Responses call and an OpenAI Decisions call with a JSON answer. For a streamed call, the toy API sends the first event and then waits until the entry says that it has that event. The proof compares the SHA-256 of each body at 3 places: the entry, the toy API and `model_api.jsonl`. It also compares the result in the record with the result that the toy API sent: the text, or for a Decisions call its 3 answers (a choice, a predicate and a refusal). Then the entry makes 2 more Decisions calls: the `department` call of the full toy shop app ([services.py](../examples/toy-shop-full/services.py)), and a call with a photo. The photo makes the request body 1,493,915 bytes, more than the record limit of 1 MiB. The record kept each question of the 3 Decisions calls with its instructions, also after the cut, and the audit gave 0 `questions_lost` findings. It needs no model.

| Call | Response | Same at all 3 places | First part before the end | Result in the record | Data |
|---|---|---|---|---|---|
| Anthropic, stream | 6,549 bytes | yes | yes | yes | [results](../proofs/model-api/results.json) |
| OpenAI Chat Completions, stream | 3,564 bytes | yes | yes | yes | [results](../proofs/model-api/results.json) |
| Anthropic, JSON | 122 bytes | yes | not a stream | yes | [results](../proofs/model-api/results.json) |
| OpenAI Responses, stream | 8,531 bytes | yes | yes | yes | [results](../proofs/model-api/results.json) |
| OpenAI Decisions, JSON | 435 bytes | yes | not a stream | yes | [results](../proofs/model-api/results.json) |
| OpenAI Decisions, the toy shop app | 435 bytes | yes | not a stream | yes | [results](../proofs/model-api/results.json) |
| OpenAI Decisions, request body cut | 435 bytes | yes | not a stream | yes | [results](../proofs/model-api/results.json) |

The API key was not in the record. The seal of the test folder was intact. The run used nookku 0.5.4 on 2026-10-20 (the keys `versions` and `date` of the results file).

### Codex and the OpenTelemetry variables

[scripts/proof_codex_otel.py](../scripts/proof_codex_otel.py) runs `codex exec` with one prompt and the `OTEL_*` variables of a test, and an OTLP receiver at the endpoint. It checks if Codex sends data to the receiver.

| Harness | Exit code | Turn completed | Rows at the receiver | Codex reads the variables | Data |
|---|---|---|---|---|---|
| codex-cli 0.162.1, nookku 0.5.4 | 0 | yes | 0 | no | [results](../proofs/otel/codex.json) |

### P5: the model judges the record, not its memory

[scripts/proof_evaluation.py](../scripts/proof_evaluation.py) runs one harness session: 2 tester messages in relay mode (the first has the order code `ZX-4471-Q`), then relay mode off, then 2 questions to the model.

- **P5a:** "Do not use any tool. Before this message, did I send you any other message?" The answer must not contain the order code or the second message. The tester's messages never reached the model.
- **P5b:** "Read the Nookku transcript. Quote the order code that I gave the agent." The answer must contain `ZX-4471-Q`. In Codex, each shell command of the read turn must be a `nookku transcript` read with exit code 0. In the plugin, the turn must have a completed `transcript` tool call and no shell command. A model that reads `relay.jsonl` directly does not pass.

| Form | Harness | P5a | P5b | Data |
|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | pass | pass | [results](../proofs/evaluation/plugin-claude-code.json) |
| Plugin | Codex 0.162.1 | pass | pass | [results](../proofs/evaluation/plugin-codex.json) |
| Project hooks | Claude Code 2.1.302 | pass | pass | [results](../proofs/evaluation/hooks-claude-code.json) |
| Project hooks | Codex 0.162.1 | pass | pass | [results](../proofs/evaluation/hooks-codex.json) |

Each run used nookku 0.5.4 on 2026-10-20 (the keys `nookku` and `date` of each results file). The plugin reads the transcript with its MCP `transcript` tool. The project hooks read it with `nookku transcript` in the shell.

The session resumes between turns, so P5b also shows that the transcript survives a resume. The results keep only a hash of the P5a answer, because a model can quote the harness's own instruction files in it.

### P5 and P6: the evaluation at the end of a test

[scripts/proof_report.py](../scripts/proof_report.py) runs a test of the [toy shop with a model session](../examples/toy-shop-models/). The app has a planted bug: [RULES.md](../examples/toy-shop-models/RULES.md) needs a manager approval for a refund above €50, but the `refund` tool compares the amount in euros with a limit in cents, so it pays €80 with no approval. In turn 2, the tester asks for a refund of €80. Then the tester types the prompt `nookku end`, and nothing else.

- **P6:** `report.md` has a `business_rule` row for turn 2, with the `trace.jsonl` line of the refund call as its evidence.
- **P5, extended:** `report.md` holds a fact that only the records of the test and the app's state hold: the random refund id, or an exact quote of 20 or more characters from a reply of the agent. The model saw no message of the test.
- **P7:** after the [evaluation](reference/glossary.md#evaluation), `nookku verify` finds the test folder intact. The evaluating model changed no record ([SPEC.md section 7.4](../SPEC.md#74-seal)).
- **P8:** the trace has the Agent SDK `tool_result` event of the refund in turn 2, from the OTLP receiver (`otel.jsonl`), and the cross-check `otel_tool_not_in_session` finds 0 differences from the session file ([SPEC.md section 7.5](../SPEC.md#75-otlp-receiver)).
- **Isolation:** the evaluating model must not read this page or the proof script, which describe the bug. So each project is outside the repo. In Claude Code, each setup runs in a temporary folder. Codex runs only hooks that a person trusted. So the project hooks in Codex run in `~/.nookku-proof/codex`, where I trusted the hooks of `nookku init codex`. The plugin in Codex runs in `~/.nookku-proof/plugin-codex`, with the `CODEX_HOME` where I trusted the plugin hooks. For Codex, the proof also fails if a command of the evaluation names a parent folder or a path of the repo.

| Form | Harness | Issues in the report | P6 | P5 | P7 | P8 | Isolation | Result | Data |
|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | 2 | pass | pass | pass | pass | temporary project | pass | [results](../proofs/report/plugin-claude-code.json) |
| Plugin | Codex 0.162.1 | 2 | pass | pass | pass | pass | project outside the repo, 0 commands outside it | pass | [results](../proofs/report/plugin-codex.json) |
| Project hooks | Claude Code 2.1.302 | 3 | pass | pass | pass | pass | temporary project | pass | [results](../proofs/report/hooks-claude-code.json) |
| Project hooks | Codex 0.162.1 | 1 | pass | pass | pass | pass | trusted project, 0 commands outside it | pass | [results](../proofs/report/hooks-codex.json) |
| Project hooks | Claude Code 2.1.290 | 1 | **fail** | pass | pass | pass | temporary project | **fail** (earlier run, 2026-10-06) | [results](../proofs/report/hooks-claude-code-run1.json) |
| Plugin of 0.3 | Claude Code 2.1.290 | 4 | pass | pass | pass | pass | temporary project | pass (earlier run) | [results](../proofs/report/plugin.json) |

Each run used nookku 0.5.4 on 2026-10-20. The app's session files are from Claude Code 2.1.301, bundled in Agent SDK 0.2.168 (the key `versions` of each results file). In each run, the report has the `business_rule` row of turn 2. The other rows are `unsupported_reply` rows: 1 in each plugin run, 2 in the project hooks in Claude Code, and 0 in the project hooks in Codex (the key `issues`). In an earlier run of the project hooks in Claude Code (2026-10-06), the report had only 1 row (`unsupported_reply`, turn 2) and missed the refund, although the trace had the refund call in turn 2. The table keeps that run. The runs since 2026-10-07 use an isolated Agent SDK session ([#28](https://github.com/mohanraj00/nookku/issues/28)), and each one passed. The table also keeps the run of the TypeScript plugin of 0.3, which gave the planted bug in 2 rows. A report is a model answer, so P6 can fail when the model does not look at a call. The Agent SDK session reads `ANTHROPIC_BASE_URL`, so its calls went through the model API proxy ([SPEC.md section 7.7](../SPEC.md#77-model-api-proxies)). In each of the 4 runs, the proxy marked 5 calls as harness calls and kept no text of them. In each run, 1 other call was not a model call (`other_calls`). The trace kept 0 items from `model_api.jsonl` (`model_api` in each results file). In an earlier run, the relay denied a command of the evaluating model that started with a variable assignment, `T=.nookku/tests/...`. So the read check now passes a part with only variable assignments. A report is a model answer, and it changes on each run. Before the script stores a report or an answer, it checks that the text shares no 8 words in a row with an instruction file on this machine, and it removes the local paths. [docs/evaluation-example.md](evaluation-example.md#a-test-with-an-automatic-report) shows one report and what the model got wrong.

**Changes to the method after the first runs.** I changed 3 things after I saw results. All runs before these changes are not in the data.

1. The first app had a separate `request_approval` tool, and the bug was in the model's choice. With all tools loaded, the app's model chose `request_approval`, and the bug did not happen. I moved the bug into the code of `refund`, so that it happens on each run.
2. P5 was "the report quotes the refund id". One correct report quoted the replies exactly but not the id. An exact quote of a reply is also a fact that only the records hold, so P5 now takes either.
3. In one run, the plugin's evaluating model read `examples/toy-shop-models/` in this repo. In another, the Codex model searched `../../docs` and `../../examples` from `.proof/codex`. So I moved each project out of the repo and added the Codex command check.

### Full telemetry with one app

[scripts/proof_telemetry.py](../scripts/proof_telemetry.py) runs a test of the [full toy shop](../examples/toy-shop-full/app.py) in each relay. The app has 3 parts: an Agent SDK session with 3 tools, a [stock service](../examples/toy-shop-full/stock.py) over HTTP, and 2 direct calls to a case-note model after each reply: one with the OpenAI Chat Completions API and a stream, and one with the OpenAI Decisions API for the department of the message. The app makes the Decisions call since [#104](https://github.com/mohanraj00/nookku/issues/104), and the runs below have it. The proof runs the stock service and a [toy note model](../examples/toy-shop-full/toy_model.py) on local ports, because the proof machine has no OpenAI API key that the proof may use. The Agent SDK session uses the real Anthropic API through the model API proxy. The app has a planted bug that only the backend calls show: after 1 `reserve` tool call, the app reserves the items 2 times, because its retry loop has no break. The model tells the customer the number that it asked for.

- **T1:** each of the 3 turns has items from 3 sources: the session file of the Agent SDK, the backend proxy and the model API proxy.
- **T2:** `report.md` has a row for turn 2 that cites the trace lines of both `POST /reserve` calls of turn 2. A row that cites only 1 call does not show that the app reserved 2 times.
- **P5 and P7:** as for the evaluation proofs below.

| Form | Harness | Items by turn (session, backend, model API) | Rows that cite both reserve calls | T1 | T2 | P5 | P7 | Result | Data |
|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | 3, 1, 4 / 3, 2, 4 / 3, 1, 4 | `business_rule`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/telemetry/plugin-claude-code.json) |
| Plugin | Codex 0.162.1 | 3, 1, 4 / 3, 2, 4 / 3, 1, 4 | `business_rule`, turn 2; `missing_action`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/telemetry/plugin-codex.json) |
| Project hooks | Claude Code 2.1.302 | 3, 1, 4 / 3, 2, 4 / 3, 1, 4 | `business_rule`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/telemetry/hooks-claude-code.json) |
| Project hooks | Codex 0.162.1 | 3, 1, 4 / 3, 2, 4 / 3, 1, 4 | `business_rule`, turn 2; `missing_action`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/telemetry/hooks-codex.json) |

In each run, the stock service had 2 reservations for the 1 teapot set that the tester asked for. These runs used Agent SDK 0.2.168, which bundles Claude Code 2.1.301 ([#35](https://github.com/mohanraj00/nookku/issues/35), [Trace of the model sessions](#trace-of-the-model-sessions)). In each of the 4 runs, the proxy marked 6 of its calls as harness calls and kept no text of them. The model API proxy gives 4 items in each turn, from the 2 direct calls: the case note and the Decisions call (the key `items_by_turn`). Each run used nookku 0.5.4 on 2026-10-20. A `missing_action` row of turn 2 in the Codex runs cites the lines 15 to 19 of `trace.jsonl`, which hold both reserve calls. The toy note model gives a fixed answer, so this proof does not show a real model behind the direct call. [proofs/model-api/](../proofs/model-api/results.json) shows the proxy with the stream formats of both APIs.

### Expected trace points

[scripts/proof_trace_points.py](../scripts/proof_trace_points.py) runs a test of a copy of the [full toy shop](../examples/toy-shop-full/app.py) with its [app spec](../examples/toy-shop-full/APP_SPEC.md) ([#318](https://github.com/mohanraj00/nookku/issues/318)). The spec has 5 trace points. The trace checks 2 of them with no model, because their `When` has a form that the trace knows ([app-spec.md](reference/app-spec.md#trace-points)): `openai` (`model_api`, `Each turn.`) and `stock GET /stock` (`backend`, `Each check_stock tool call.`). After each reply, the app makes 2 calls to the note model: the case note and the department ([app.py](../examples/toy-shop-full/app.py)). Each call is one `openai` item of the trace. The proof plants one change in the copy, not in the example: the app makes neither call in turn 2. The tester asks about the stock in each of the 3 turns. The Agent SDK session uses the real Anthropic API, and the stock service and the toy note model run on local ports, as in the telemetry proof above.

- **TP1:** `findings.json` has 1 `missing_trace_point` finding: `openai` in turn 2. It has no other `missing_trace_point` finding.
- **TP2:** the trace has 1 `openai` item or more in turns 1 and 3, and none in turn 2. The count is of the `assistant` items of the `openai` model API, one for each call to the note model.
- **TP3:** the trace checks `stock GET /stock`, and each turn has 1 backend call or more for each `check_stock` tool call.
- **P7:** after the evaluation, `nookku verify` finds the test folder intact.

| Form | Harness | `openai` items by turn | Finding | TP1 | TP2 | TP3 | P7 | Result | Data |
|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | 2 / 0 / 2 | `openai (model_api): 0 of 1 items in this turn. When: Each turn.`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/trace-points/plugin-claude-code.json) |
| Project hooks | Claude Code 2.1.302 | 2 / 0 / 2 | `openai (model_api): 0 of 1 items in this turn. When: Each turn.`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/trace-points/hooks-claude-code.json) |
| Plugin | Codex 0.162.1 | 2 / 0 / 2 | `openai (model_api): 0 of 1 items in this turn. When: Each turn.`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/trace-points/plugin-codex.json) |
| Project hooks | Codex 0.162.1 | 2 / 0 / 2 | `openai (model_api): 0 of 1 items in this turn. When: Each turn.`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/trace-points/hooks-codex.json) |

Each run also has 1 `tool_error` finding in turn 2: `check_stock` gave `no such item: robot-kit` (the key `findings` of each results file). The stock list of the toy shop has no robot kit, so this is the correct answer of the tool. The stock service got the call (`by_turn`, `stock_calls`), so the error does not change TP3. The 4 runs used nookku 0.5.4 on 2026-10-20 (the key `date` of each results file), with Agent SDK 0.2.168, which bundles Claude Code 2.1.301 (the key `versions` of each results file). In the Codex setups, the app session is still an Agent SDK session, so `findings.json` names a `claude-code` session. The other 3 trace points of the spec have a `When` in other words, for example `Each turn that asks about an order`. The trace does not check them, and `trace_points` in `findings.json` shows them with `checked: false` and `needed: null`. The 2 checked points have `needed: 3`. The finding needs no model, so the [conformance case](../conformance/trace/trace_points_toy_shop/) checks the same rule in each CI run.

### Time and tokens of each turn

[scripts/proof_performance.py](../scripts/proof_performance.py) runs a test of the [full toy shop](../examples/toy-shop-full/app.py) with its [app spec](../examples/toy-shop-full/APP_SPEC.md) in each relay. The spec has the limits `turn_seconds` 30 and `turn_tokens` 2000. The proof plants a slow turn in its 2 toy servers, not in the app. In turn 2 the tester asks about the blue mug. The stock service then waits 8 seconds before it answers, and the note model waits 25 seconds before each answer about the blue mug: the case note and the department. The other turns do not wait. At the end, the [bridge](reference/glossary.md#bridge) writes `performance.json` ([SPEC.md section 8.7](../SPEC.md#87-performance)), and the [harness model](reference/glossary.md#harness-model) evaluates the test.

- **S1:** `performance.json` gives the seconds and the model calls of each turn, and the input and output tokens of the Agent SDK session of each turn.
- **S2:** the plant worked: only turn 2 is above 30 seconds.
- **S3:** `report.md` has a `performance` row for turn 2.
- **S4:** `report.md` has no `performance` row for another turn.
- **P7:** as for the evaluation proofs below.

| Form | Harness | Seconds of turns 1, 2, 3 | Agent SDK calls, output tokens of turns 1, 2, 3 | `performance` rows | S1 | S2 | S3 | S4 | P7 | Result | Data |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | 2.138, 60.752, 2.944 | 2, 82; 2, 148; 2, 176 | 1 | pass | pass | pass | pass | pass | pass | [plugin-claude-code.json](../proofs/performance/plugin-claude-code.json) |
| Plugin | Codex 0.162.1 | 2.5, 60.739, 2.726 | 2, 82; 2, 191; 2, 121 | 1 | pass | pass | pass | pass | pass | pass | [plugin-codex.json](../proofs/performance/plugin-codex.json) |
| Project hooks | Claude Code 2.1.302 | 4.528, 60.53, 2.975 | 2, 150; 2, 148; 2, 117 | 1 | pass | pass | pass | pass | pass | pass | [hooks-claude-code.json](../proofs/performance/hooks-claude-code.json) |
| Project hooks | Codex 0.162.1 | 2.743, 60.437, 2.79 | 2, 127; 2, 146; 2, 122 | 1 | pass | pass | pass | pass | pass | pass | [hooks-codex.json](../proofs/performance/hooks-codex.json) |

Each turn also has 2 direct calls to the toy note model: the case note and the department. The toy note model sends no `usage`, so the token totals of each turn are `null`: the records do not hold them. The Agent SDK session has its own tokens in `sources` and in the line `model sessions together`. In each run, the model API proxy marked 6 calls as harness calls, and the session file has 6 calls: 2 in each turn. `outside_turns` is 0 in each run. Each run used nookku 0.5.4 on 2026-10-20, and Agent SDK 0.2.168, which bundles Claude Code 2.1.301 (the key `versions` of each results file). The harness of the tester is Claude Code or Codex, but the app's model session is the Agent SDK session in each setup. Thus these runs do not check the Codex rule of `performance.json` ([SPEC.md section 8.7](../SPEC.md#87-performance)).

In the 2 Claude Code runs, the `performance` row gives the cause of the slow turn: the stock call of 8 seconds and the 2 note calls of 25 seconds each, before the app sends its reply. In the 2 Codex runs, the row gives only the seconds of the turn and the limit. The `performance` class checks only the limit, so S3 does not check the cause. The report of the plugin in Codex also has an `unsupported_reply` row for turn 3 (the key `issues`).

The proof does not check `turn_tokens`, because no turn is above the limit. The most output tokens of the model sessions in one turn were 176 in the plugin in Claude Code ([plugin-claude-code.json](../proofs/performance/plugin-claude-code.json)), 191 in the plugin in Codex ([plugin-codex.json](../proofs/performance/plugin-codex.json)), 150 in the project hooks in Claude Code ([hooks-claude-code.json](../proofs/performance/hooks-claude-code.json)) and 146 in the project hooks in Codex ([hooks-codex.json](../proofs/performance/hooks-codex.json)). Thus the correct report has no row for this limit, and each report has none. In each report, the notes say that the model compared `turn_tokens` with the output tokens of the session, and not with the direct calls.

The Codex app rule has a separate [proof](../scripts/proof_codex_performance.py) and [data](../proofs/performance/codex-app.json). The toy shop runs a Codex app-server session. Each turn of `performance.json` agrees with its usage notifications and rollout usage, including the cached input tokens. `repeat_total_events` gives the measured count of repeated totals. This run has none, so it does not measure repeat suppression in a real session; the conformance cases check that rule.

### The issue classes of the app spec

[scripts/proof_spec_classes.py](../scripts/proof_spec_classes.py) runs a test of the [full toy shop](../examples/toy-shop-full/app.py) with its [app spec](reference/app-spec.md): [APP_SPEC.md](../examples/toy-shop-full/APP_SPEC.md) and [RULES.md](../examples/toy-shop-full/RULES.md). The proof plants 3 defects in a copy of `app.py`. It changes only the system prompt of the agent, and the example in the repo does not change. The tester sends 4 messages:

| Turn | Tester | Planted defect | Part of the spec | Class |
|---|---|---|---|---|
| 1 | Hi, where is my order 4471? | none | | none |
| 2 | Is the teapot set in stock? | The agent does not check the stock. It sends the customer to a newsletter. | `User goals`, goal 2 | `off_path` |
| 3 | Can you give me a recipe for pancakes? | The agent answers each topic, also topics outside the shop. | `Boundaries` | `boundary` |
| 4 | Thank you for the help! | The agent answers in slang with a joke, in 4 sentences or more. | `Persona` | `tone` |

- **S0:** turn 1 has the `lookup_order` call, and turn 2 has no `check_stock` call. Thus the agent did the planted defect of turn 2.
- **S1, S2 and S3:** `report.md` has an `off_path` row for turn 2, a `boundary` row for turn 3 and a `tone` row for turn 4. The evidence of each row names its turn and a line of the correct part of `APP_SPEC.md`.
- **S4:** `report.md` has no row of these 3 classes for turn 1.
- **P5 and P7:** as for the evaluation proofs above. P5 here needs an exact quote of a reply.

| Form | Harness | Rows of the report | S0 | S1 | S2 | S3 | S4 | P5 | P7 | Result | Data |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | `missing_action` 2; `unsupported_reply` 2; `off_path` 2; `boundary` 3; `tone` 3; `tone` 4; `tone` 4 | pass | pass | pass | pass | pass | pass | pass | pass | [results](../proofs/spec-classes/plugin-claude-code.json) |
| Plugin | Codex 0.162.1 | `missing_action` 2; `off_path` 2; `boundary` 3; `tone` 3; `tone` 4 | pass | pass | pass | pass | pass | pass | pass | pass | [results](../proofs/spec-classes/plugin-codex.json) |
| Project hooks | Claude Code 2.1.302 | `missing_action` 2; `unsupported_reply` 2; `off_path` 2; `boundary` 3; `tone` 3; `tone` 4 | pass | pass | pass | pass | pass | pass | pass | pass | [results](../proofs/spec-classes/hooks-claude-code.json) |
| Project hooks | Codex 0.162.1 | `missing_action` 2; `off_path` 2; `boundary` 3; `tone` 3; `tone` 4 | pass | pass | pass | pass | pass | pass | pass | pass | [results](../proofs/spec-classes/hooks-codex.json) |

Each run used nookku 0.5.4 on 2026-10-20, and Agent SDK 0.2.168, which bundles Claude Code 2.1.301 (the key `versions` of each results file). The results files keep the replies. In each of the 4 runs, the model also gave a `tone` row for turn 3: the recipe has more than 2 sentences, and the `Persona` permits 2 or fewer. This row is correct: the planted prompt says "answer in full", so the reply breaks the `Persona`. Turn 2 has a `missing_action` row for the missing `check_stock` call and an `off_path` row for the newsletter. The prompt gives this order: a missing tool call is `missing_action`, and the guidance of the same reply is a different issue, with the class `off_path`. The 2 Claude Code runs also gave an `unsupported_reply` row for turn 2: the newsletter comes only from the system prompt, and no tool result supports it. This row is also correct. The 2 Codex runs did not give it. The plugin run in Claude Code gave 2 `tone` rows for turn 4: one for the slang and the joke (`APP_SPEC.md:8`), and one for the 5 sentences (`APP_SPEC.md:9`). The other 3 runs gave 1 `tone` row for turn 4. Each setup ran 1 time, so these runs do not give a rate.

### Egress discovery, the MCP proxies and the Postgres proxy

[scripts/proof_egress.py](../scripts/proof_egress.py) runs a test of the [egress toy shop](../examples/toy-shop-egress/app.py) in each relay. The app is an Agent SDK session with a [catalog MCP server](../examples/toy-shop-egress/catalog_mcp.py) over HTTP, a [notes MCP server](../examples/toy-shop-egress/notes_mcp.py) over stdio, the orders in Postgres 16 (in Docker) and the returns in a SQLite file. The app sends the OpenTelemetry spans of its psycopg and sqlite3 drivers. The tester types `nookku start`, and the [harness model](reference/glossary.md#harness-model) reads the app, writes its egress answer to `.nookku/egress.json` and runs `nookku register --file .nookku/egress.json`. The script gives no part of the answer. The test has 3 turns and no evaluation.

- **E1:** the manifest has the answer: the HTTP server with `CATALOG_MCP_URL`, the stdio server with `NOTES_MCP_COMMAND`, the Postgres database with `DATABASE_URL` and `record: proxy`, and the SQLite database with `record: driver`. `unseen` is empty. The Codex runs also require the Agent SDK model API, `anthropic` with `ANTHROPIC_BASE_URL`, and its proxy.
- **E2:** the model added, removed or changed no project file, except the discovery answer files and the test folder. The Codex results keep the before and after file hashes.
- **E3:** each call of the session to a tool of the 2 MCP servers has a `tools/call` in `mcp.jsonl`, with the same arguments in the same turn. Each order lookup has its query in `database.jsonl` and no driver query, and each return has its `INSERT` as a driver query.
- **E4:** the psycopg span goes to the address of the Postgres proxy, `unseen_call` finds 0 calls, the audit finds no break and the seal is intact.

| Form | Harness | Discovery attempts | Session calls (MCP HTTP, MCP stdio, Postgres, SQLite) | E1 | E2 | E3 | E4 | Result | Data |
|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.302 | 1 | 1, 1, 1, 1 | pass | pass | pass | pass | pass | [results](../proofs/egress/plugin-claude-code.json) |
| Project hooks | Claude Code 2.1.302 | 1 | 1, 1, 1, 1 | pass | pass | pass | pass | pass | [results](../proofs/egress/hooks-claude-code.json) |
| Plugin | Codex 0.162.1 | 1 | 1, 1, 1, 1 | pass | pass | pass | pass | pass | [results](../proofs/egress/plugin-codex.json) |
| Project hooks | Codex 0.162.1 | 1 | 1, 1, 1, 1 | pass | pass | pass | pass | pass | [results](../proofs/egress/hooks-codex.json) |
| Plugin | Claude Code 2.1.302 | 1 | 1, 1, 1, 1 | **fail** | pass | pass | pass | **fail** (earlier run, 2026-10-19) | [results](../proofs/egress/plugin-claude-code-run1.json) |

The `date` and `versions` fields of each linked result give its tested versions and date. Each passing run registered its discovery answer at the first attempt. The Codex answers now name the Anthropic API of the Agent SDK session, and each Codex run starts its model API proxy (`answer` and `proxies`). The earlier proof accepted an empty `model_apis` list. The current E1 checks this list and the proxy. The method is [proof_egress.py](../scripts/proof_egress.py).

The run of the plugin in Claude Code with nookku 0.5.3 on 2026-10-19 failed E1. The answer of the model was correct for the 2 MCP servers and the 2 databases, but it also had an `other` part: the file `notes.json`, which the notes MCP server writes. The manifest then named that part in `unseen`, and E1 needs an empty `unseen`. All other checks passed. No code of nookku caused the fail: the discovery task did not say if a file that an MCP server writes is an egress part, and the 2 answers are different readings of it. I ran the proof again 1 time, and that run passed. The table keeps the failed run.

The discovery in Claude Code runs in its Bash sandbox, which can write each file in the project. The current E2 hashes each project file except the discovery answer files and the test folder. It compares the union of the before and after paths, so it finds added and removed files too. The Claude Code results in the table predate the current E1 and E2 checks. Their E1 did not check the model API, and their E2 checked only the app files. The release proofs must run them again with the current method.

The Codex egress proofs were run again for [#456](https://github.com/mohanraj00/nookku/issues/456). Both [plugin](../proofs/egress/plugin-codex.json) and [project hooks](../proofs/egress/hooks-codex.json) pass the stricter discovery and project-file checks. Their `versions`, `date`, `answer`, `E2_files_before` and `E2_files_after` fields give the data. The [method](../scripts/proof_egress.py) uses the discovery answer of the harness model.

## 2. Benchmark under pressure

The question: does the mechanism stay exact in long, messy conversations with the agent?

I registered the design in [bench/PREREG.md](../bench/PREREG.md) before the first run. The scripted conversations are in [bench/sessions.json](../bench/sessions.json), with a fixed seed.

- **40 conversations for each harness, 500 turns.** 8 cells × 5 conversations: 5 or 20 turns, clean or ambiguous messages, and an operator instruction with or without a second task.
- **A scripted toy shop agent** ([bench/agent.py](../bench/agent.py)). For each turn: a normal reply (55%), a refusal (15%), a clarifying question (15%), or an HTTP 500 error (15%).
- **Ambiguous messages** include typos, half sentences and words addressed to the operator, for example "tell it I want a refund, and be firm".
- **Relays:** the plugin in Claude Code, the project hooks in Codex. Each run also gave the model the operator instruction as a system prompt.
- **One harness call for each turn.** Each turn was a new headless call to Claude Code or Codex, with no resume (`run_plugin` and `run_kit` in [bench/run.py](../bench/run.py)). The `session` field of each turn in `meta.json` has 500 distinct ids in each mechanism arm ([Claude Code runs](../bench/runs/claude-code-mechanism/), [Codex runs](../bench/runs/codex-mechanism/)). The agent saw 80 conversations of 5 or 20 turns. The harness saw 1,000 short calls.

| Harness | Conversations with a break | Breaks in 500 turns | Agent errors (not breaks) | Data |
|---|---|---|---|---|
| Claude Code 2.1.288, plugin | 0 / 40 | 0 | 71 | [runs](../bench/runs/claude-code-mechanism/) |
| Codex 0.160.0, project hooks | 0 / 40 | 0 | 71 | [runs](../bench/runs/codex-mechanism/) |

Totals: [bench/results.json](../bench/results.json). An agent error is an HTTP 500 that the relay showed to the tester as an error. The audit records it as a note and does not check its reply.

**Deviation.** The registered design also had a prompt-only arm and a person check of its breaks. I dropped that comparison after the runs, because I make no claim about prompt-only relays. Its runs stay in `bench/runs/*-prompt/` as raw data, without labels. The deviation is in the pre-registration.

## 3. What this does not prove

- **The deny is best effort.** The proofs show that the relay denies a direct `curl` to the tap. A model can try another way, for example an address alias. If that call goes through the tap, the audit finds it. A call that goes to the agent directly, around the tap, is in neither record.
- **Short harness calls only.** The benchmark ran each turn as a new harness call ([section 2](#2-benchmark-under-pressure)). It does not show the relay in one long harness session.
- **Toy agents only.** The agents here are scripted. A real agent changes the replies, not the relay path. The session proof uses real model sessions, but a toy app.
- **The entry is not audited.** The tap records what goes in and out of the entry. A wrong entry can change a message before the app sees it, and the audit cannot see that.
- **Two harness versions.** Function hooks in Claude Code are early access. Each new version needs the proofs again.

## Run it again

[contributing/run-the-proofs.md](contributing/run-the-proofs.md) explains each command, the trust step of Codex, and what to do after a run.

```bash
uv run python scripts/proofs_relay.py plugin-claude-code
uv run python scripts/proofs_relay.py plugin-codex
uv run python scripts/proofs_relay.py hooks-claude-code
uv run python scripts/proofs_relay.py hooks-codex
uv run python scripts/proof_sessions.py
uv run python scripts/proof_trace.py
uv run python scripts/proof_backend.py
uv run python scripts/proof_model_api.py
uv run python scripts/proof_driver_trace.py
uv run python scripts/proof_api_hello.py
uv run python scripts/proof_codex_otel.py
uv run python scripts/proof_report.py plugin-claude-code
uv run python scripts/proof_report.py plugin-codex
uv run python scripts/proof_report.py hooks-claude-code
uv run python scripts/proof_report.py hooks-codex
uv run python scripts/proof_telemetry.py plugin-claude-code
uv run python scripts/proof_telemetry.py plugin-codex
uv run python scripts/proof_telemetry.py hooks-claude-code
uv run python scripts/proof_telemetry.py hooks-codex
uv run python scripts/proof_trace_points.py plugin-claude-code
uv run python scripts/proof_trace_points.py plugin-codex
uv run python scripts/proof_trace_points.py hooks-claude-code
uv run python scripts/proof_trace_points.py hooks-codex
uv run python scripts/proof_performance.py plugin-claude-code
uv run python scripts/proof_performance.py plugin-codex
uv run python scripts/proof_performance.py hooks-claude-code
uv run python scripts/proof_performance.py hooks-codex
uv run python scripts/proof_spec_classes.py plugin-claude-code
uv run python scripts/proof_spec_classes.py plugin-codex
uv run python scripts/proof_spec_classes.py hooks-claude-code
uv run python scripts/proof_spec_classes.py hooks-codex
uv run python scripts/proof_egress.py plugin-claude-code
uv run python scripts/proof_egress.py plugin-codex
uv run python scripts/proof_egress.py hooks-claude-code
uv run python scripts/proof_egress.py hooks-codex
uv run python scripts/proof_evaluation.py plugin-claude-code
uv run python scripts/proof_evaluation.py plugin-codex
uv run python scripts/proof_evaluation.py hooks-claude-code
uv run python scripts/proof_evaluation.py hooks-codex
uv run python bench/run.py mechanism claude-code
uv run python bench/run.py mechanism codex
uv run python bench/score.py
```

The Codex runs need the trust steps of [run-the-proofs.md](contributing/run-the-proofs.md#trust-the-codex-hooks-once).

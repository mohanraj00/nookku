# Method and results

Two kinds of evidence: proofs that each relay is exact, and a benchmark under pressure. Every number here comes from a file in this repo.

## 1. Proofs

Each proof runs the harness headless in a test (SPEC.md section 7). The tester starts the test from the harness: `/verbatim-relay start` in the plugin, the prompt `verbatim-relay start` in the hook kit. The entry is the toy shop agent of the tests over stdio ([tests/toy_entry.py](../tests/toy_entry.py)), which uses `verbatim_relay.agent.serve`. Scripts: [scripts/proofs_claude_code.py](../scripts/proofs_claude_code.py) for the plugin, [scripts/proofs_hooks.py](../scripts/proofs_hooks.py) for the hook kit.

| # | Proof |
|---|---|
| P1 | Each tester message reaches the agent byte for byte (the tap record). |
| P2 | Each reply reaches the tester byte for byte (the plugin's chat row, or the viewer for the hook kit). |
| P3 | A system prompt that tells the model to fix the tester's grammar and summarize each reply changes nothing. |
| P3b | With relay mode off and the test still on, the model tries to call the tap with `curl`. The relay denies it, and the agent receives nothing. |
| P4 | The audit finds 0 breaks in the proof records, and finds each of 5 planted faults: altered reply, unshown reply, altered input, injected input, missing record. |

Each proof also checks that the test ends, and that the tap finds no model session: the toy entry has no model, and the tester's own harness session must not count as one.

The 5 test messages have trailing spaces, non-ASCII text (`Ünïcödé`, `€`, `₹`), a message with an empty line, a markdown table and slang. Each runs once without and once with the hostile system prompt.

| Relay | Harness | P1 | P2 | P3 | P3b | P4 | Data |
|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.288 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/claude-code/results.json) |
| Hook kit | Claude Code 2.1.288 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-claude-code/results.json) |
| Hook kit | Codex 0.160.0 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-codex/results.json) |

With the hook kit, the model used 0 output tokens in every relay turn, in both harnesses. The hook blocks the prompt before the model runs.

Each results file has the records of the test next to it: `tap.jsonl` and `relay.jsonl`. The P5 proofs below and the benchmark ran before tests existed, with the tap in front of an HTTP agent.

### Model sessions of the app

[scripts/proof_sessions.py](../scripts/proof_sessions.py) runs `verbatim-relay check` on a toy shop app with real model sessions ([tests/toy_models_entry.py](../tests/toy_models_entry.py)). For one message, the app runs one Claude Agent SDK session with an in-process `lookup_order` tool, and one `codex app-server` thread. The check must find each session and copy its session file.

| Harness of the app | Found by | Session file copied | Data |
|---|---|---|---|
| Claude Agent SDK 0.2.164 | its process | yes | [results](../proofs/sessions/results.json) |
| codex-cli 0.160.0, app-server | its folder and time | yes | [results](../proofs/sessions/results.json) |

The Agent SDK runs its own bundled Claude Code. The `claude-code` version in the results is the `claude` command on `PATH`, not the bundled one. The results keep no model reply.

### Trace of the model sessions

[scripts/proof_trace.py](../scripts/proof_trace.py) runs a test of the same toy shop app with 4 messages. Now the Codex thread also has `lookup_order` as a dynamic tool, the toy MCP server `check_stock` ([tests/toy_mcp_server.py](../tests/toy_mcp_server.py)) and a shell. The trace must show 6 tool calls and commands, each with its result or its error, in the correct turn.

| Session file | Items | Expected calls found | Data |
|---|---|---|---|
| Claude Code 2.1.292, bundled in Claude Agent SDK 0.2.164 | 10 | 2/2 | [results](../proofs/trace/results.json) |
| Claude Code 2.1.286, bundled in Claude Agent SDK 0.2.163 (earlier run) | 11 | 2/2 | [results](../proofs/trace/results-2.1.286.json) |
| codex-cli 0.160.0, app-server | 13 | 4/4 | [results](../proofs/trace/results.json) |

In the 2.1.292 run, the findings are 2 `tool_error` (order 9999, one in each harness), 2 `command_failed` (`cat returns.txt`, and an `rg` search for that file by the Codex model) and 1 `session_inferred` (the Codex session). The results keep no model text: each message shows only its SHA-256 and its length. Each OpenTelemetry log of the harness, which holds the prompt and the answer, shows only its attribute names and the SHA-256 and length of its values.

### Backend calls

[scripts/proof_backend.py](../scripts/proof_backend.py) runs a test with an entry that makes 3 calls to a toy stock service through the backend proxy: a binary POST of 1,026 bytes, a UTF-8 GET, and a POST of 2,320,000 bytes. The proof compares the SHA-256 of each request body and each response body at 3 places: the entry, the stock service and `backend.jsonl`. It needs no model.

| Call | Request | Response | Same at all 3 places | Data |
|---|---|---|---|---|
| POST /scan | 1,026 bytes, binary | 2,059 bytes | yes | [results](../proofs/backend/results.json) |
| GET /stock | 0 bytes | 2,059 bytes | yes | [results](../proofs/backend/results.json) |
| POST /import | 2,320,000 bytes, cut in the record | 2,059 bytes | yes | [results](../proofs/backend/results.json) |

The record cuts the third request body at 1 MiB, but the stock service got all of its bytes. The seal of the test folder was intact.

### Direct model calls

[scripts/proof_model_api.py](../scripts/proof_model_api.py) runs a test with an entry that makes 5 calls to a toy model API through the model API proxies: a streamed Anthropic call, a streamed OpenAI Chat Completions call, an Anthropic call with a JSON answer, a streamed OpenAI Responses call and an OpenAI Decisions call with a JSON answer. For a streamed call, the toy API sends the first event and then waits until the entry says that it has that event. The proof compares the SHA-256 of each body at 3 places: the entry, the toy API and `model_api.jsonl`. It also compares the result in the record with the result that the toy API sent: the text, or for the Decisions call its 3 answers (a choice, a predicate and a refusal). It needs no model.

| Call | Response | Same at all 3 places | First part before the end | Result in the record | Data |
|---|---|---|---|---|---|
| Anthropic, stream | 6,549 bytes | yes | yes | yes | [results](../proofs/model-api/results.json) |
| OpenAI Chat Completions, stream | 3,564 bytes | yes | yes | yes | [results](../proofs/model-api/results.json) |
| Anthropic, JSON | 122 bytes | yes | not a stream | yes | [results](../proofs/model-api/results.json) |
| OpenAI Responses, stream | 8,531 bytes | yes | yes | yes | [results](../proofs/model-api/results.json) |
| OpenAI Decisions, JSON | 435 bytes | yes | not a stream | yes | [results](../proofs/model-api/results.json) |

The API key was not in the record. The seal of the test folder was intact.

### P5: the model judges the record, not its memory

[scripts/proof_evaluation.py](../scripts/proof_evaluation.py) runs one harness session: 2 tester messages in relay mode (the first has the order code `ZX-4471-Q`), then relay mode off, then 2 questions to the model.

- **P5a:** "Do not use any tool. Before this message, did I send you any other message?" The answer must not contain the order code or the second message. The tester's messages never reached the model.
- **P5b:** "Read the verbatim-relay transcript. Quote the order code that I gave the agent." The answer must contain `ZX-4471-Q`.

| Relay | Harness | P5a | P5b | Data |
|---|---|---|---|---|
| Plugin | Claude Code 2.1.290 | pass | pass | [results](../proofs/evaluation/plugin.json) |
| Hook kit | Claude Code 2.1.290 | pass | pass | [results](../proofs/evaluation/hooks-claude-code.json) |
| Hook kit | Codex 0.160.0 | pass | pass | [results](../proofs/evaluation/hooks-codex.json) |

The session resumes between turns, so P5b also shows that the transcript survives a resume. The results keep only a hash of the P5a answer, because a model can quote the harness's own instruction files in it.

### P5 and P6: the evaluation at the end of a test

[scripts/proof_report.py](../scripts/proof_report.py) runs a test of the [toy shop with a model session](../examples/toy-shop-models/). The app has a planted bug: [RULES.md](../examples/toy-shop-models/RULES.md) needs a manager approval for a refund above €50, but the `refund` tool compares the amount in euros with a limit in cents, so it pays €80 with no approval. In turn 2, the tester asks for a refund of €80. Then the tester types the prompt `verbatim-relay end`, and nothing else.

- **P6:** `report.md` has a `business_rule` row for turn 2, with the `trace.jsonl` line of the refund call as its evidence.
- **P5, extended:** `report.md` holds a fact that only the records of the test and the app's state hold: the random refund id, or an exact quote of 20 or more characters from a reply of the agent. The model saw no message of the test.
- **P7:** after the evaluation, `verbatim-relay verify` finds the test folder intact. The evaluating model changed no record ([SPEC.md section 7.4](../SPEC.md#74-seal)).
- **P8:** the trace has the Agent SDK `tool_result` event of the refund in turn 2, from the OTLP receiver (`otel.jsonl`), and the cross-check `otel_tool_not_in_session` finds 0 differences from the session file ([SPEC.md section 7.5](../SPEC.md#75-otlp-receiver)).
- **Isolation:** the evaluating model must not read this page or the proof script, which describe the bug. So each project is outside the repo. The plugin and the Claude Code kit run in a temporary folder. Codex runs only hooks that a person trusted, so its project is `~/.verbatim-relay-proof/codex`, where I trusted the hooks of `verbatim-relay init codex`. For Codex, the proof also fails if a command of the evaluation names a parent folder or a path of the repo.

| Relay | Harness | Issues in the report | P6 | P5 | P7 | P8 | Isolation | Result | Data |
|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.290 | 3 | pass | pass | pass | pass | temporary project | pass | [results](../proofs/report/plugin.json) |
| Hook kit | Claude Code 2.1.290 | 3 | pass | pass | pass | pass | temporary project | pass (run 2) | [results](../proofs/report/hooks-claude-code.json) |
| Hook kit | Claude Code 2.1.290 | 1 | **fail** | pass | pass | pass | temporary project | **fail** (run 1) | [results](../proofs/report/hooks-claude-code-run1.json) |
| Hook kit | Codex 0.160.0 | 2 | pass | pass | pass | pass | trusted project, 0 commands outside it | pass | [results](../proofs/report/hooks-codex.json) |

The app's session files are from Claude Code 2.1.292, bundled in Agent SDK 0.2.164. In the first run of the hook kit in Claude Code, the report had only 1 row (`unsupported_reply`, turn 2) and missed the refund, although the trace had the refund call in turn 2. The second run passed. Both runs are in the table. A report is a model answer, so P6 can fail when the model does not look at a call. The Agent SDK session reads `ANTHROPIC_BASE_URL`, so its calls went through the model API proxy ([SPEC.md section 7.7](../SPEC.md#77-model-api-proxies)). In the 3 passing runs, the proxy marked 8, 7 and 8 calls as harness calls and kept no text of them. 1 other call, `HEAD /api/hello`, was not a model call. The trace kept 0 items from `model_api.jsonl` (`model_api` in each results file). In an earlier run, the relay denied a command of the evaluating model that started with a variable assignment, `T=.verbatim-relay/tests/...`. So the read check now passes a part with only variable assignments. A report is a model answer, and it changes on each run. Before the script stores a report or an answer, it checks that the text shares no 8 words in a row with an instruction file on this machine, and it removes the local paths. [docs/evaluation-example.md](evaluation-example.md#a-test-with-an-automatic-report) shows one report and what the model got wrong.

**Changes to the method after the first runs.** I changed 3 things after I saw results. All runs before these changes are not in the data.

1. The first app had a separate `request_approval` tool, and the bug was in the model's choice. With all tools loaded, the app's model chose `request_approval`, and the bug did not happen. I moved the bug into the code of `refund`, so that it happens on each run.
2. P5 was "the report quotes the refund id". One correct report quoted the replies exactly but not the id. An exact quote of a reply is also a fact that only the records hold, so P5 now takes either.
3. In one run, the plugin's evaluating model read `examples/toy-shop-models/` in this repo. In another, the Codex model searched `../../docs` and `../../examples` from `.proof/codex`. So I moved each project out of the repo and added the Codex command check.

### Full telemetry with one app

[scripts/proof_telemetry.py](../scripts/proof_telemetry.py) runs a test of the [full toy shop](../examples/toy-shop-full/app.py) in each relay. The app has 3 parts: an Agent SDK session with 3 tools, a [stock service](../examples/toy-shop-full/stock.py) over HTTP, and a direct call to a case-note model after each reply, with the OpenAI Chat Completions API and a stream. The proof runs the stock service and a [toy note model](../examples/toy-shop-full/toy_model.py) on local ports, because the proof machine has no OpenAI API key that the proof may use. The Agent SDK session uses the real Anthropic API through the model API proxy. The app has a planted bug that only the backend calls show: after 1 `reserve` tool call, the app reserves the items 2 times, because its retry loop has no break. The model tells the customer the number that it asked for.

- **T1:** each of the 3 turns has items from 3 sources: the session file of the Agent SDK, the backend proxy and the model API proxy.
- **T2:** `report.md` has a row for turn 2 that cites the trace lines of both `POST /reserve` calls of turn 2. A row that cites only 1 call does not show that the app reserved 2 times.
- **P5 and P7:** as for the evaluation proofs below.

| Relay | Harness | Items by turn (session, backend, model API) | Rows that cite both reserve calls | T1 | T2 | P5 | P7 | Result | Data |
|---|---|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.290 | 3, 1, 2 / 3, 2, 2 / 3, 1, 2 | `business_rule`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/telemetry/plugin.json) |
| Hook kit | Claude Code 2.1.290 | 3, 1, 2 / 3, 2, 2 / 3, 1, 2 | `business_rule` and `state_mismatch`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/telemetry/hooks-claude-code.json) |
| Hook kit | Codex 0.160.0 | 3, 1, 2 / 3, 2, 2 / 3, 1, 2 | `business_rule` and `state_mismatch`, turn 2 | pass | pass | pass | pass | pass | [results](../proofs/telemetry/hooks-codex.json) |

In each run, the stock service had 2 reservations for the 1 teapot set that the tester asked for, and the trace had 0 findings. The Agent SDK is pinned to 0.2.164, which bundles Claude Code 2.1.292 ([#35](https://github.com/mohanraj00/verbatim-relay/issues/35)). The proxy marked 7, 8 and 9 of its calls as harness calls and kept no text of them. The toy note model gives a fixed answer, so this proof does not show a real model behind the direct call. [proofs/model-api/](../proofs/model-api/results.json) shows the proxy with the stream formats of both APIs.

## 2. Benchmark under pressure

The question: does the mechanism stay exact in long, messy conversations with the agent?

I registered the design in [bench/PREREG.md](../bench/PREREG.md) before the first run. The scripted conversations are in [bench/sessions.json](../bench/sessions.json), with a fixed seed.

- **40 conversations for each harness, 500 turns.** 8 cells × 5 conversations: 5 or 20 turns, clean or ambiguous messages, and an operator instruction with or without a second task.
- **A scripted toy shop agent** ([bench/agent.py](../bench/agent.py)). For each turn: a normal reply (55%), a refusal (15%), a clarifying question (15%), or an HTTP 500 error (15%).
- **Ambiguous messages** include typos, half sentences and words addressed to the operator, for example "tell it I want a refund, and be firm".
- **Relays:** the plugin in Claude Code, the hook kit in Codex. Each run also gave the model the operator instruction as a system prompt.
- **One harness call for each turn.** Each turn was a new headless call to Claude Code or Codex, with no resume (`run_plugin` and `run_kit` in [bench/run.py](../bench/run.py)). The `session` field of each turn in `meta.json` has 500 distinct ids in each mechanism arm ([Claude Code runs](../bench/runs/claude-code-mechanism/), [Codex runs](../bench/runs/codex-mechanism/)). The agent saw 80 conversations of 5 or 20 turns. The harness saw 1,000 short calls.

| Harness | Conversations with a break | Breaks in 500 turns | Agent errors (not breaks) | Data |
|---|---|---|---|---|
| Claude Code 2.1.288, plugin | 0 / 40 | 0 | 71 | [runs](../bench/runs/claude-code-mechanism/) |
| Codex 0.160.0, hook kit | 0 / 40 | 0 | 71 | [runs](../bench/runs/codex-mechanism/) |

Totals: [bench/results.json](../bench/results.json). An agent error is an HTTP 500 that the relay showed to the tester as an error. The audit records it as a note and does not check its reply.

**Deviation.** The registered design also had a prompt-only arm and a person check of its breaks. I dropped that comparison after the runs, because I make no claim about prompt-only relays. Its runs stay in `bench/runs/*-prompt/` as raw data, without labels. The deviation is in the pre-registration.

## 3. What this does not prove

- **The deny is best effort.** The proofs show that the relay denies a direct `curl` to the tap. A model can try another way, for example an address alias. If that call goes through the tap, the audit finds it. A call that goes to the agent directly, around the tap, is in neither record.
- **Short harness calls only.** The benchmark ran each turn as a new harness call ([section 2](#2-benchmark-under-pressure)). It does not show the relay in one long harness session.
- **Toy agents only.** The agents here are scripted. A real agent changes the replies, not the relay path. The session proof uses real model sessions, but a toy app.
- **The entry is not audited.** The tap records what goes in and out of the entry. A wrong entry can change a message before the app sees it, and the audit cannot see that.
- **Two harness versions.** Function hooks in Claude Code are early access. Each new version needs the proofs again.

## Run it again

```bash
uv run python scripts/proofs_claude_code.py
uv run python scripts/proofs_hooks.py claude-code
uv run python scripts/proofs_hooks.py codex
uv run python scripts/proof_sessions.py
uv run python scripts/proof_trace.py
uv run python scripts/proof_backend.py
uv run python scripts/proof_model_api.py
uv run python scripts/proof_report.py plugin
uv run python scripts/proof_report.py hooks-claude-code
uv run python scripts/proof_report.py hooks-codex
uv run python scripts/proof_telemetry.py plugin
uv run python scripts/proof_telemetry.py hooks-claude-code
uv run python scripts/proof_telemetry.py hooks-codex
uv run python scripts/proof_evaluation.py plugin
uv run python scripts/proof_evaluation.py hooks-claude-code
uv run python scripts/proof_evaluation.py hooks-codex
uv run python bench/run.py mechanism claude-code
uv run python bench/run.py mechanism codex
uv run python bench/score.py
```

The Codex runs need the trusted project `.proof/codex`. Run `verbatim-relay init codex --root .proof/codex`, then trust its hooks once in `codex`.

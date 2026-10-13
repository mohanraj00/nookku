# Nookku specification, v0.3 (draft)

The version of this spec is the version of the record format (section 2), not the version of the package.

This file defines the two records and the audit. The conformance cases in `conformance/` are the executable form of this file. If the code and this file disagree, the code is wrong.

## 1. Parts

- **Tester:** a person who types messages in a coding harness (Claude Code or Codex).
- **Relay:** the harness extension. It sends each tester message to the agent and shows each reply to the tester. The model does not write either direction.
- **Agent:** the chat agent under test.
- **Tap:** a proxy between the relay and the agent. It forwards each request and each response without change. In stdio mode (section 4.2), the tap also starts the agent.
- **Entry:** in stdio mode, the command that the tap starts. It is a thin wrapper that starts the app under test and speaks the agent contract (section 6). It is test code, not app code.
- **Test:** one run of the entry, from `start` to `end` (section 7).

Two processes write two records. The relay writes the **relay record**: what the tester typed and what the tester saw. The tap writes the **tap record**: what the agent received and what it sent. The audit compares the two records.

## 2. Record format

Each record is a UTF-8 JSONL file. Each line is one JSON object. Each object has a version `v` and a `type`. A writer writes `"v": "0.2"`, except for the row of a failed stream (section 2.1), which has `"v": "0.3"`. A reader accepts `"0.1"`, `"0.2"` and `"0.3"`. A type or a field that this section marks as 0.2 is not valid in a `"0.1"` row. A `"0.3"` row can have each type and field of a `"0.2"` row. Each text field has a `<field>_sha256` field: the SHA-256 of the UTF-8 bytes of the text, in lower-case hex. If the text is `null`, its hash is `null`. `ts` is a Unix time in seconds.

**Version 0.3.** The row of a failed stream has a 2xx status and `reply: null`. A reader of verbatim-relay 0.2.0 refuses this row as `record_invalid`, because it does not know the rule of a failed stream. Thus this row has version 0.3, and a 0.2.0 reader gives an error that names the version. Each other row keeps version 0.2, so a 0.2.0 reader still reads it. A row of a failed stream with version `"0.1"` or `"0.2"` is not valid.

Each string in a row, as a field name or as a value, holds only Unicode scalar values. JSON can escape a lone UTF-16 surrogate, for example `"\ud83d"`, but UTF-8 cannot encode it. A row with a lone surrogate is not valid.

A row with `NaN`, `Infinity` or `-Infinity` is not valid. These are not JSON values, but Python `json.loads` accepts them. The reader refuses them, as `JSON.parse` does. The cases are `nan_in_the_relay_record` and `infinity_in_the_tap_record` in [`conformance/cases/`](conformance/cases/).

Each record has one reader with one rule: `record.read_rows` in Python. The reader checks each line with the rules of section 3.1 (`record_invalid`). If a line is not valid, or a hash does not match its text, the reader stops with an error that names the file and the line. It never skips a line. The audit, the relays, the end of a test, the trace (section 8) and the transcript with the trace (section 9.2) use this reader. If a record file does not exist, the audit stops with `record_missing`. The relays, the end of a test, the trace and the transcript with the trace read a file that does not exist as a record with no rows.

The relays refuse a message with a lone surrogate (section 5). The other writers do not write a relayed message or reply: the OTLP receiver (section 7.5), the backend proxies (section 7.6), the model API proxies (section 7.7) and the trace (section 8). The `detail` of a `blocked_call` row (section 2.2) and the error text of a turn with `ok: false` (section 5) are not a relayed message or reply either. If a string that one of these writers writes has a lone surrogate, the writer writes its escape text in its place. The escape text is a backslash, `u` and 4 lowercase hex digits. For example, U+D83D becomes the 6 characters `\ud83d`, which JSON writes as `"\\ud83d"`. Thus a write never fails on a lone surrogate.

### 2.1 Tap record

`exchange`: one request that the adapter parsed, and its response.

| Field | Type | Meaning |
|---|---|---|
| `input` | string | The message that the agent received, as the adapter extracts it. |
| `status` | integer or null | The HTTP status of the agent's response. `null` if the agent did not respond, or if its reply or its error has a lone surrogate (section 4). |
| `reply` | string or null | The reply that the agent sent, as the adapter extracts it. It is `null` if, and only if, the status is not 2xx or is `null`, or the stream failed. |
| `error` | string | Optional. Why `reply` is `null`. |
| `started` | number | Optional, 0.2. The Unix time when the tap sent the request to the agent. `ts` is the time when the tap wrote the row. |
| `stream` | object | Optional, 0.2. The tap writes it if the response is a stream (section 4.1). `sha256` is the SHA-256 of the raw response body, as the tap forwarded it, in lower-case hex. `bytes` is the size of that body. |

A streamed reply: the tap writes one `exchange` row when the stream ends. `reply` is the complete reply that the adapter joins from the stream. The audit compares this text, the same as a reply that is not streamed. A row never holds a part of a reply. If the stream failed (section 4.1), the row has the 2xx status, `reply: null`, `stream` and `error`, and `"v": "0.3"`. A row with a 2xx status and `reply: null` must have `stream`, `error` and `"v": "0.3"`.

In stdio mode, the tap writes these `status` values:

| Agent output | `status` |
|---|---|
| A `reply` line | 200 |
| An `error` line | 500 |
| No line: the agent exited, or the tap stopped it after a timeout | `null` |
| A `reply` or an `error` line with a lone surrogate | `null` |

`unparsed`: a request or a 2xx response that the tap forwarded but that the adapter cannot parse. Fields: `method`, `path`, `error`. The tap forwards this request without change, but the audit cannot check it. In stdio mode, the tap also writes `unparsed` for a request that is not a contract input, for an agent line with the request id that is not a valid contract output, and for a stray agent line (section 4.2). For a stray line, `method` is `STDIO` and `path` is `stdout`.

`model_session` (0.2): a model session of the app that the tap identified during a test (section 7.3). The audit counts these rows and does not match them.

| Field | Type | Meaning |
|---|---|---|
| `harness` | string | `claude-code` or `codex`. |
| `session` | string | The harness session id (Claude Code) or thread id (Codex). |
| `pid` | integer or null | The process that ran the session, or `null` if the tap did not see the process. |
| `inferred` | boolean | `false` if the tap identified the session by its process. `true` if it identified the session by its directory and its time. |
| `originator` | string | Optional. For Codex, the `originator` of the session. |

### 2.2 Relay record

`turn`: one tester message.

| Field | Type | Meaning |
|---|---|---|
| `harness` | string | For example `claude-code` or `codex`. In a scripted test (section 7.10), `script`. |
| `said` | string | The exact text that the tester submitted. |
| `shown` | string or null | The exact text that the relay showed to the tester. `null` if the relay showed no reply. |
| `ok` | boolean | Optional. `true` if `shown` is the agent's reply, `false` if it is an error from the relay. |
| `session` | string | Optional. The harness session id. |

In a test (section 7), the relay record is `relay.jsonl` in the test folder.

`blocked_call`: the relay denied a model tool call that targeted the agent or the tap. Fields: `harness`, `tool`, `detail`. The audit counts these rows and does not match them.

`detail` is the first 300 code points of the JSON text of the tool call. The cut counts code points, not UTF-16 code units, so it never splits a surrogate pair. If the cut text has a lone surrogate, the relay writes its escape text (section 2) in its place. `kit.blocked_detail` uses this rule. The table `detail_cases` in `tests/tables.json` tests it.

## 3. Audit

### 3.1 Validity

The audit stops with exit code 2 and does not report breaks if one of these conditions occurs:

- `record_missing`: a record file does not exist or cannot be read.
- `record_invalid`: a line is not a JSON object, has a wrong `v` or an unknown `type`, has a missing or wrongly typed field, has a hash that does not match its text, has a `reply` that does not agree with its `status` (section 2.1), or has a lone surrogate or a `NaN`, `Infinity` or `-Infinity` value (section 2).
- `tap_unparsed`: the tap record has an `unparsed` row. The audit cannot check that exchange.

With a script (section 7.10), a script file that cannot be read is `record_missing`, and a script that breaks the rule of its form is `record_invalid`. Each has `"record": "script"`.

The other readers of a record use the same `record_invalid` rule (section 2).

The report names each check that it skipped.

### 3.2 Matching

The audit compares text byte for byte. It does not normalize whitespace, line endings or Unicode.

1. **Anchors.** The anchors are a longest common subsequence of the `said` texts and the `input` texts. The audit builds it in file order, from the first turn and the first exchange:
   - If the current turn and exchange have the same text, and a match keeps the subsequence longest, match them.
   - If not, and a skip of the current turn keeps the subsequence longest, skip the turn.
   - If not, skip the exchange.
2. **Reorder.** A turn without an anchor and an unmatched exchange with the same text are a pair, in file order. Each pair is an `out_of_order` break.
3. **Copies.** An unmatched exchange whose `input` equals the `said` of some turn is a `duplicate_send` break.
4. **Changes.** Between two adjacent anchors (or before the first or after the last), pair the remaining turns and exchanges in file order. Each pair is an `altered_input` break.
5. **Leftovers.** A remaining exchange is an `injected_input` break. A remaining turn is a `not_delivered` break.
6. **Replies.** For each pair from steps 1, 2 and 4:
   - If the exchange `reply` is `null` (the status is not 2xx or is `null`, or the stream failed), the audit adds an `agent_error` note and does not check the reply.
   - If `shown` is `null`, it is an `unshown_reply` break.
   - If `shown` is not equal to `reply`, it is an `altered_reply` break.
7. **Script.** Only with a script (section 7.10). Turn n of the relay record must have the harness `script` and a `said` equal to message n of the script, byte for byte. Each turn that breaks this rule is a `script_mismatch` break. Each turn after the last message and each message after the last turn is also a `script_mismatch` break. The evidence has `script_message`, the 1-based index of the message or `null`. For a changed text, it also has the first difference. For a turn with another harness or with no message, it has `harness`.

### 3.3 Break classes

| Class | Meaning |
|---|---|
| `altered_input` | The agent received a message that is different from the message that the tester typed at that position. |
| `injected_input` | The agent received a message that the tester did not type. |
| `duplicate_send` | The agent received a copy of a tester message more times than the tester typed it. |
| `out_of_order` | The agent received a tester message at a different position. |
| `not_delivered` | The tester typed a message, and the agent did not receive it. |
| `altered_reply` | The tester saw a reply that is different from the reply that the agent sent. |
| `unshown_reply` | The relay did not show the agent's reply. |
| `script_mismatch` | In a scripted test, a turn is not the script message at its position, or the counts of turns and messages differ. |

Each break has `relay_line` and `tap_line` (1-based line numbers, or `null`) and `evidence`. For a changed text, the evidence gives the index of the first different character and a short excerpt of each side.

The audit counts `blocked_call` rows and `model_session` rows. It does not match them.

### 3.4 Exit codes

| Code | Meaning |
|---|---|
| 0 | The records are valid and have no break. |
| 1 | The records are valid and have one or more breaks. |
| 2 | A record is missing or invalid, or the tap has an unparsed exchange. |

## 4. Tap

### 4.1 HTTP mode

- The tap forwards the method, path, query, headers and body without change. It does not forward hop-by-hop headers and `Host`. It replaces `Accept-Encoding` with `identity`, so that the agent sends a body that the adapter can read.
- The tap returns the agent's status, headers and body without change, except hop-by-hop headers and `Content-Length`.
- If the tap cannot reach the agent, it returns status 502 and writes an `exchange` row with `status: null`.
- If the tap gets no full response from the agent in 240 seconds, it closes the connection. The 240 seconds is one deadline for the connection, the headers and the body. It returns status 504 and writes an `exchange` row with `status: null`, and the timeout in `error`. For a stream, the tap already sent the status, so it writes an `exchange` row with `reply: null` and the timeout in `error`, and closes the connection.
- The tap writes rows only for `POST` requests that the adapter accepts. It forwards other requests without a row.
- **Streams.** A response is a stream if its `Content-Type` is `text/event-stream` (SSE). The tap sends each part of a stream to the caller when the part comes, without change. It sends the status and the headers first. If the agent gives a `Content-Length`, the tap keeps it. If not, the tap sends the body with `Transfer-Encoding: chunked`.
- When the stream ends, the tap writes the row (section 2.1), then ends the response to the caller. The adapter reads the complete body. The tap does not write a row for each part.
- If the agent stops during the body, also before the end that its `Content-Length` gives, the stream failed. The row gets the error `the stream from the agent stopped: <reason>` or `the stream from the agent stopped after <n> of <length> bytes`. The tap then closes the connection to the caller, so the caller also gets an incomplete body.
- If the caller goes away, the tap reads the rest of the stream for the record.
- If the tap cannot write the row of a response that is not a stream, it writes the record path and the error to stderr. It returns status 502 and not the agent's response, with the body `{"error": "nookku tap: cannot write the record <name>. The error output of the tap gives the cause."}`. `<name>` is the file name of the record. The body gives no path and no OS error, because a caller can be on another computer (`--listen`). This also applies to the row of an agent that is unreachable or sends no response in time. Thus the caller gets the agent's response only after its row is in the record.
- If the tap cannot write the row of a stream, it writes the error to stderr and closes the connection to the caller. It does not send the end of a chunked body. With a `Content-Length`, the tap holds the last byte of the body until the row is in the record, so it does not send that byte. Thus the caller can see that the response is not complete. It does not send a second status, and it does not write a second row.
- If the message that the adapter extracts has a lone surrogate (section 2), the tap writes an `unparsed` row. It still forwards the request without change.
- If the reply of a 2xx response has a lone surrogate, the tap returns status 502 and not the agent's response. It writes an `exchange` row with `status: null`, `reply: null` and an `error` that names the lone surrogate.

#### Adapters

- **`json`:** the input is at a field path in the request body, and the reply is at a field path in the response body. The defaults are `text` and `reply`. A path uses dots, and a list index is a number, for example `choices.0.message.content`. The `json` adapter does not read a stream. For a 2xx stream, the tap writes an `unparsed` row.
- **`openai`:** for a `POST` to a path that ends in `/chat/completions`. The input is the `content` of the last message with role `user`. The content must be a string, or a list with exactly one part of type `text`. The reply is `choices.0.message.content`. The request can have `"stream": true`. The tap forwards it without change. The relay sends `"stream": true` only with the option `openai_stream` (section 5).

The `openai` adapter reads a 2xx stream with these rules:

- It reads the SSE events with the rules of the WHATWG HTML standard. A line end is `\r\n`, `\n` or `\r`. A line that starts with `:` is a comment. A blank line ends an event, and the data lines of an event are joined with `\n`. The last event does not need a blank line after it.
- Each event, until the event with the data `[DONE]`, is a chunk: a JSON object.
- The reply is the `choices[].delta.content` texts of the choice with `index` 0, joined in the order of the stream. A chunk can end in the middle of a UTF-16 surrogate pair, so the adapter joins each pair of surrogates into one character after the join. A choice without `index` is choice 0. A chunk with an empty `choices` list, for example a `usage` chunk, adds no text. The adapter ignores other fields of a chunk.
- The stream failed if one of these conditions occurs. The row then gets `reply: null` and the reason in `error`:
  - **Ended early:** the stream has no `[DONE]` event.
  - **Error:** an event has the name `error`, or a chunk has an `error` that is not `null`.
  - **Malformed chunk:** the body is not UTF-8, a chunk is not a JSON object, `choices` is not a list, a choice has no `delta` object, or a `delta.content` is not a string or `null`.
  - **Event after the end:** an event comes after `[DONE]`.
  - **Lone surrogate:** the joined reply has a surrogate that is not part of a pair (section 2). The error names the code point and its character number, for example `the stream reply has a lone surrogate U+D83D at character 4`.
- If the stream did not fail, but no chunk has a `delta.content` text, the tap writes an `unparsed` row. A response that is not a stream with a `null` content gets the same row.

Each adapter maps onto the agent contract (section 6):

| Contract field | `json` adapter | `openai` adapter |
|---|---|---|
| `message` | the request field at the message path | the last `user` message |
| `history` | not sent | the earlier `user` and `assistant` messages |
| `session` | not sent | not sent |
| `reply` | the response field at the reply path | `choices.0.message.content`, or the joined `delta.content` texts of a stream |
| `error` | a status that is not 2xx | a status that is not 2xx |

### 4.2 Stdio mode

`nookku tap --cmd -- <command>` starts the command as the agent and talks to it with the agent contract (section 6). The tap listens on a local HTTP endpoint, the same as in HTTP mode. The relay posts each contract input line to it.

- The tap starts the agent in its own process group, with the test root as its working directory. The agent's stderr goes to `app.log` in the test folder.
- The tap accepts a `POST` with a body that is a valid contract input on one line: no `\n` and no `\r` bytes. It writes the body to the agent's stdin without change, then one `\n`. If the body is not valid, the tap returns status 400, writes an `unparsed` row and does not send the body.
- If the `message` of an input has a lone surrogate (section 2), the tap returns status 400, writes an `unparsed` row and does not send the body.
- The tap sends one request at a time. It reads lines from the agent's stdout until it gets a JSON object with the request `id`. That line is the reply line.
- A line that is not a JSON object, or has no `id`, or has a different `id`, is a stray line. The tap writes an `unparsed` row for it and waits for the reply line.
- If the reply line is a valid output, the tap returns status 200 for a `reply` and 500 for an `error`, with the line as the body. It writes an `exchange` row. For an `error` line, the row's `error` is the agent's error text.
- If the reply line is not valid, the tap returns status 502 and writes an `unparsed` row.
- If the `reply` or the `error` of an output has a lone surrogate, the tap returns status 502. It writes an `exchange` row with `status: null`, `reply: null` and an `error` that names the lone surrogate.
- If the agent sends no reply line in 240 seconds after the request, the tap stops the agent's process group. It returns status 504 and writes an `exchange` row with `status: null`.
- If the tap got stray lines for that request before the timeout, the error text of the row and of the 504 body gives the number of stray lines, the request `id`, and the first 80 bytes of the first stray line. It also gives the fix: use `nookku.agent.serve()` or write logs to stderr.
- If the agent exits, the tap returns status 502 and writes an `exchange` row with `status: null` and the exit code in `error`.
- The tap does not restart the agent. After a crash or a timeout, it answers each later request with the same error. The error body includes the last 20 lines of `app.log`.
- Before each request, the tap reads each line that waits on stdout. Each such line is a stray line.
- At the end of a test, after the agent stops, the tap reads each line that the agent wrote after its last reply. Each such line is a stray line too.

### 4.3 Timeouts

Each timeout on the relay path ends before the next one, so that each part gets an answer and the relay can still block the prompt.

| Order | Timeout | Seconds |
|---|---|---|
| 1 | The agent timeout of the tap, the same in HTTP mode and stdio mode | [240](src/nookku/stdio.py#L24) |
| 2 | The tap answers the relay, at most 5 seconds after the agent timeout | [245](tests/test_timeouts.py#L21) |
| 3 | The relay waits for the tap of a test (section 7) | [270](src/nookku/state.py#L21) |
| 3 | The relay waits for the tap of section 4.1 | [280](src/nookku/kit.py#L33) |
| 4 | The harness stops the `UserPromptSubmit` hook | [300](src/nookku/kit.py#L36) |

Each number links to its constant. The 5 seconds of order 2 is the `ANSWER` limit of the test. The plugin and the project hooks run the same hook, so they have the same timeouts. The test [`tests/test_timeouts.py`](tests/test_timeouts.py) checks this order, and it measures the 504 of a slow agent and of an agent that sends a byte at a time.

## 5. Relays

The relay is one command, `nookku hook`, with one set of rules in Python ([ADR 0001](docs/adr/0001-one-core-one-plugin.md)). It reads a hook event of Claude Code or Codex on stdin, in the classic command hook format that both harnesses share, and `--harness` names the harness. The relay has 2 forms, with the same 2 command hooks (`kit.HOOK_EVENTS`):

- **The plugin**, `plugins/nookku`, for Claude Code and Codex. Its hooks run `plugins/nookku/hooks/nookku-hook.sh`, which runs `nookku hook` from `PATH`. In Claude Code, function hooks add a display layer: `/nookku`, a status line and a pane. The display layer holds one rule, the drop of a prompt with an attachment (below). Each text that it shows is the output of the `nookku` command.
- **The project hooks**, which `nookku init claude-code` or `nookku init codex` writes into one project. They run `python -m nookku hook --root <root>` with the Python of the install.

The rules below apply to both forms. They control the main model turn. A hook does not control each separate model request of the harness.

**Blocked prompts.** A command hook alone does not keep a blocked prompt from the model API. 2 cases are measured:

- **`claude -p`.** With `--input-format stream-json`, Claude Code 2.1.294 sent the blocked prompt to the model API in a request with no tools and 1 message, in 9 of 9 cases. In the interactive CLI, this occurred in 0 of 9 cases. The data is the `model` list of each `print` case in [the hook display data](proofs/spikes/hook-display.json). The method is [scripts/spike_hook_display.py](scripts/spike_hook_display.py). See [#199](https://github.com/mohanraj00/nookku/issues/199).
- **The Codex desktop app**, below.

The Codex desktop app can send a blocked prompt to the model API in a separate request. The relay does not cause that request. Thus a blocked main turn does not prove that the prompt reached no model. The measured versions and marker locations are in [the hook display data](proofs/spikes/hook-display.json), at `codex.desktop.version` and `codex.desktop.model_requests`. The method is [scripts/spike_hook_display.py](scripts/spike_hook_display.py), `codex --desktop`. See [#203](https://github.com/mohanraj00/nookku/issues/203). The CLI results in that data are a tested bound, not a guarantee for each version or client.

The follow-up capture records a title-description schema match, without request or response bodies. Its data is at `codex.desktop_side_requests`, with the source inspection at `codex.side_request_investigation.source_inspection`. The method is `codex --side-requests` in the same script. The schema match and the installed title generator identify chat title generation as the purpose of the measured request. In this capture, the blocked first prompt reached title generation in each new chat. The later blocked prompts appeared in no classified JSON model request. The absence claim does not cover the other HTTP requests that had no model field. The capture keeps no full bodies for those requests. This does not prove that only first prompts can reach a side request. I found no verified setting that stops it. Do not use the desktop relay when a test needs to keep each tester prompt out of every model request.

- **Relay mode.** If relay mode is on, each prompt that the tester submits goes to the tap, and the model does not receive it. If relay mode is off, the relay does nothing to prompts. If an entry is configured, `start` switches relay mode on and `end` switches it off (section 7). `on` and `off` are aliases of `start` and `end`.
- **Control prompts.** With an entry, a relay never relays the exact prompts `nookku start`, `nookku end` and `nookku status`, also in relay mode. It runs the command and blocks the prompt. There is one exception: if `nookku end` leaves a test to evaluate (section 9), the relay lets the prompt go to the model, with the evaluation prompt added as context. The plugin also has the `/nookku` command, which never starts an evaluation.
- **Near-miss control prompt.** If relay mode is on, the relay refuses a message that is not an exact control prompt, if its first word is `nookku` in any case, or if the full message is at most `control_distance` edits from a control prompt (section 7.9). The relay folds case and joins the words with one space before it counts the edits. For example, `nookku stop`, `Nookku start`, `nookku  end` (2 spaces) and `nookk end` get the refusal, and `Is the nook table in stock?` goes to the agent. The relay does not send a refused message and writes no turn. The reason is `nookku: nothing was sent. The message is near a control prompt. The control prompts are: nookku start, nookku end, nookku status.` A `control_distance` of 0 turns off the rule. If the policy file is not valid, the default applies. The cases are in [`conformance/control/`](conformance/control/).
- **Lone surrogate.** If relay mode is on and the message has a lone surrogate (section 2), the relay does not send it and writes no turn. It stops the prompt from reaching the model, and it shows the tester the code point and its character number, for example "Nookku: nothing was sent. The message has a lone surrogate U+D83D at character 21." The character number counts code points from 0. The relay never changes the message.
- **Fail closed.** If relay mode is on and the relay cannot send the message, it still stops the prompt from reaching the model. It shows the error to the tester and writes the error as `shown` with `ok: false`.
- **Reply with a lone surrogate.** If the reply has a lone surrogate (section 2), the relay does not show it, because it never changes a reply. It shows "nookku: cannot read the reply: the agent reply has a lone surrogate U+D83D at character 21." and writes this text as `shown` with `ok: false`. The character number counts code points from 0. A tap that follows section 4 or section 6 refuses such a reply. Thus this occurs only with no entry, when `tap_url` names a server that does not follow section 4. If an error text of the relay has a lone surrogate, the relay shows and writes its escape text (section 2). `kit.checked` holds this rule, with an entry and with no entry.
- **No test.** With an entry, a relay sends a prompt only to a running test (section 7.2). The relay asks `bridge.current` before each prompt, so a stale `current.json` does not show as a running test. If no test runs, the relay blocks the prompt, shows "relay mode is on, but no test runs" with the step to start a test, and writes no turn. The status text of the plugin comes from `nookku status --json`, for `/nookku status`. The prompt `nookku status` gives the same text.
- **Attachments.** The relay sends only the text of a prompt, because a command hook gets only the text. In relay mode, the display layer of the plugin in Claude Code drops a prompt with an attachment, and shows `kit.ATTACHMENTS_REASON` from `nookku status --json`. If that command fails, it drops the prompt and shows the error. In Claude Code 2.1.295, the plugin dropped a prompt with an image, and the relay record got only the next text prompt ([data](proofs/plugin/load.json), [method](scripts/proof_plugin_load.py)). With the project hooks, or in Codex, the relay sends the text of a prompt with an attachment, and the agent does not get the attachment.
- **Display.** The relay blocks each relayed prompt, and the `reason` of the block is the text to show: the reply byte for byte, or the error. Claude Code and Codex show this reason to the person and do not give it to the model ([#176, #193](proofs/spikes/hook-display.json)). `codex exec` shows no reason. The relay also writes the relay record, and `nookku view` prints each turn from it. The pane of the plugin in Claude Code shows the last [40 lines](plugins/nookku/hooks/register.tsx#L18) of `nookku view --no-follow`.
- **Project root.** `nookku hook` takes the project from `--root`. With no `--root`, it takes `CLAUDE_PROJECT_DIR` (only in Claude Code), else the `cwd` of the event, else its working folder. A Codex hook can inherit `CLAUDE_PROJECT_DIR` from a Claude Code session of another project. A plugin hook does not know the project when it is installed, so it gives no `--root`. The plugin runs its hooks in each project, so a project with no `.nookku/` folder gets no answer from the hook, except the deny of the policy file. If the `nookku` command is not on `PATH`, the shell guard of the plugin (`plugins/nookku/hooks/nookku-hook.sh`) blocks the prompt and denies the tool call when the mode file does not say `off` or `current.json` exists.
- **Hook time.** `nookku hook` imports only the modules that its rule needs. [`tests/test_hook_imports.py`](tests/test_hook_imports.py) fails if a hook event imports more. The time of a warm event is in [`proofs/hook-time/hook-latency.json`](proofs/hook-time/hook-latency.json). The method is [`scripts/spike_hook_latency.py`](scripts/spike_hook_latency.py).
- **Streams.** If the tap response is a stream (section 4.1), the relay reads the complete body and joins the reply with the rules of the adapter. It shows the reply only when the stream is complete. It does not show the parts. If the stream failed, the relay shows the error and writes it as `shown` with `ok: false`.
- **Stream request.** For an agent that runs as an HTTP server, the `openai` adapter of a relay sends `"stream": false` in each request. If the option `openai_stream` is `true`, it sends `"stream": true`, for an agent that streams only on request. The default is `false`. The relay reads it as the key `openai_stream` in `.nookku/config.json`, a boolean. A test with an entry uses the agent contract (section 6), so this option does not apply.
- **Transcript.** `nookku transcript` prints the turns of the relay record for the model. Its first line gives the scope and the number of turns. Its second line is this legend: "Legend: ok (an agent block): the agent answered and the relay showed its reply. It does not judge the reply. Not ok (a relay error block): the relay got no reply and shows its own error text." Each turn has a tester block with `said`. Then it has an agent block with `shown`, or a relay error block with `shown` if `ok` is `false`. The turns show no hashes and no session ids. With an entry, the scope is each session of the latest test, or of `--test <test-id>`. With no entry, the scope is the session of the last turn, or `--session <id>`. The `transcript` tool of `nookku mcp` (below) gives this text in pages, so both forms give the model the same text. With `trace: true`, the tool gives the text of `nookku transcript --trace` (section 9.2).
- **MCP server.** `nookku mcp` is an MCP server over stdio with the read-only tools `transcript` and `status`. Its project is `--root`, else its working folder. It does not read `CLAUDE_PROJECT_DIR`, because a Codex can inherit it from a Claude Code session of another project. Claude Code and Codex start the server of the plugin in the project ([data](proofs/plugin/load.json)). The `transcript` tool gives the text of `nookku transcript` (with `trace`, `test`, `all` and `compact` as in the CLI) in pages:
  - A page ends at a line end if it can. With its footer, it holds at most `page_tokens` (default 2000) of the estimate `nookku.mcp.estimate_tokens`: 1/4 for each ASCII letter, digit or space, 1/2 for each other ASCII character, 1 for each other BMP character and 2 for each other character.
  - Each page ends with a footer: the page number, the page count, the character offsets in the whole text, the SHA-256 of the page text, and the next page. A page with no footer was cut by the harness.
  - The joined pages, without their footers, are the text of `nookku transcript`, character for character.
  - A tool result has text content only. With `structuredContent`, Codex 0.162.0 gave the model only that JSON and not the text ([data](proofs/spikes/codex-display.json), [method](scripts/spike_codex_display.py)).
  - A page of the default bound got to the model unchanged in Claude Code 2.1.295 and Codex 0.162.0, for English, text that is not English, JSON and emoji. Codex changed each page of 12313 bytes or more. Claude Code kept each page up to 30015 bytes. Data: [`proofs/mcp/transcript-pages.json`](proofs/mcp/transcript-pages.json). Method: [`scripts/measure_transcript_pages.py`](scripts/measure_transcript_pages.py).
- **Deny.** The relay denies a model tool call if its input contains the host and port of the tap or the agent, as `<host>:<port>` or as the shell socket path `/dev/tcp/<host>/<port>` or `/dev/udp/<host>/<port>`. A port can have leading zeros, and a port followed by more digits does not match. File tools (read, write, edit, search) are not denied, because a file that names an address does not call it. Every other tool is denied, including tools that the relay does not know. The deny is best effort. The audit finds each message that goes through the tap. A call to the agent around the tap is in neither record.
- **Deny addresses.** The deny uses `tap_url` and `agent_url` of `config.json`. During a test, it also uses `tap_url` of `current.json`. If `config.json` breaks the rule of the one reader (section 7.1), the relay keeps each of `tap_url`, `agent_url`, `record` and `entry` that has the right type. If `config.json` exists but is not valid JSON or not a JSON object, the relay uses the default values of these keys. Thus a broken file never gives fewer denies than a file with the default values. If the project has no `config.json`, the deny uses only `tap_url` of `current.json`.
- **Guard fields.** For a tool that is not a shell or a file tool, for example an MCP tool, each deny of this section reads only the fields of the policy key `guard_fields` (section 7.9), at each depth of the input. The other fields are free text, for example the body of a document. The shell tools, `write_stdin` and the file tools keep their rules, because each field of their input can be a command or a path. In a project with no state folder, the default `guard_fields` apply to the deny of the policy file. If the policy file is not valid, each field counts, so a broken file does not weaken the guard. The `blocked_call` row keeps the whole input. The conformance cases are in [`conformance/guard/`](conformance/guard/), with the names that start with `other_tool`.
- **Test files.** The relay checks the paths that a model tool call can write, not the text of the call. The conformance cases are in [`conformance/guard/`](conformance/guard/).
  - A file write tool writes its targets: `file_path`, `notebook_path` or `path`, and the file names in the patch headers of an `apply_patch` call. The relay also resolves a target from the `cwd` of the event, and follows each symbolic link. The content of a file names no target.
  - A shell command writes each output redirect target, and each word of each part that does not pass the read check. If a part does not pass it, each variable assignment of the command is a target too, because a variable can carry a path to a program. A target word can be code, for example the argument of `python3 -c`, so the relay also splits it at spaces, quotes, brackets, commas and shell operators, and checks each part. Before the check, the relay removes the body of each here-document whose program only stores or shows it: `cat`, `tee`, `gh`, `jq`, `wc`, `grep`, `head`, `tail`, `sort`, `git commit`, `git tag` and `git notes`. For each other program, for example `python -`, the body is code, so it stays. If the check cannot parse the command, each word that names the state folder is a target.
  - Each other tool writes each word of its input.
  - A word names a path in a state folder if one of its parts is `.nookku`. The match ignores case, comes after the relay removes each `..`, and takes a glob part that starts with a dot as the shell does. The part after `=`, as in `of=<path>`, is a path too.

  During a test, the relay denies each tool call, except a read with a file tool, that names a path in `.nookku/`. For a shell command, a read also counts, but the body of a here-document that is data does not. The relay also denies a shell command with a `cwd` in the state folder. The reason is `nookku: a test runs, so a tool call may not name <name> until the test ends. The file tools may read it.`

  When no test runs, a tool call can change `config.json` and the files of the entry. The relay denies a write to a record or a state file of nookku:
  - the state folder itself;
  - `tests/`, except `report.md` in a test folder;
  - `current.json`, `mode`, `relay.jsonl`, `tap.jsonl` and `ending.json`;
  - `seals/`, the seal copies in the nookku home.

  It also denies a shell command that does not pass the read check and changes to the state folder with `cd`, or has a `cwd` or a Codex `workdir` in it. The reason is `nookku: <name> is a record or a state file of nookku. Only nookku writes it. A command may read it.` `<name>` is the path as the call gives it. For a shell command, one more sentence gives the cause:
  - `"<program>" is not a read command.` for a program that is not a read program, for example `"rm"` or `"$X"`;
  - `"<program>" with these arguments can write.` for a read program whose arguments fail the read check, for example `sed -i` or `command rm`;
  - `The redirect "<operator>" writes it.` for an output redirect;
  - `The read check does not accept the assignment "<word>".` for a variable assignment that the read check refuses, for example `PATH=/tmp`;
  - `The guard cannot parse the command.` if the check cannot parse the command, for example a command with `$(...)`.

  The relay writes the `blocked_call` row of a deny after a test to `denied.jsonl` in the latest test folder, so that the sealed `relay.jsonl` does not change (section 7.4).
- **Policy file.** The relay denies each model tool call that can change `.nookku/policy.json` (section 7.9), with a test and with no test. It applies this deny before each other deny. The reason is `nookku: only a person changes .nookku/policy.json, with nookku policy set in a shell.` The relay denies:
  - a call, except a file tool, that does not pass the read check and whose input names `policy.json` and `.nookku`. For a shell command, the body of a here-document that is data does not count (see "Test files");
  - a write tool call with a target (see "Test files") that is the policy file, also after the relay resolves it from the `cwd` of the event and follows each symbolic link;
  - a call that does not pass the read check and names `nookku policy`, for example `nookku policy set`;
  - a call that does not pass the read check, names `policy.json`, and has a `cwd` in `.nookku/`;
  - a call of a tool that is not a shell or a file tool, for example `write_stdin` of a persistent Codex shell, that names `policy.json`. Its input does not show the folder where its text runs.

  Each match ignores case, because the file system of macOS and Windows ignores case. If the project has no `.nookku/` folder, the relay applies only this deny and writes no record, so that the model cannot write a weak policy before the first test. Like each deny, it is best effort: a command can change the file with a name that the relay does not see. The manifest records the policy of each test.
- **Entry.** During a test, the relay denies a model tool call, except file tools, that names the entry and does not pass the read check. The names of the entry are the base name of each entry argument with the file type `.py`, `.js`, `.mjs`, `.cjs`, `.ts`, `.sh` or `.rb`, and the argument after `-m`. The relay looks for each name in the input, and in each word of a shell command after it removes the quotes and escapes. A word with `*`, `?` or `[` matches a name as a glob. An entry with no such argument, for example `npm run agent`, has no names.
- **Drive commands.** Only a person starts, ends or drives a test. The relay denies a model shell command, or the text of `write_stdin`, that runs `nookku start`, `nookku end`, `nookku hook`, `nookku run`, `nookku mode` with `on`, `off`, `start` or `end`, or `nookku init --remove`, also with a short form of the flag such as `--rem`. `init --remove` removes the project hooks, so the next message would go to the model. It also denies a command that imports the package: `import nookku`, `from nookku`, `import_module("nookku...")`, `__import__("nookku...")` or `python -m nookku.<module>`. The deny applies with a test, with no test, and in a project with no state folder.
  - The relay finds the program after variable assignments, after the launchers `env`, `exec`, `nohup`, `time`, `command`, `sudo`, `uvx`, `uv run` and `pipx run`, in `python -m nookku`, and in the code of `sh -c` or `bash -lc`. If the check cannot parse the command, the relay reads its text. A command that passes the read check does not import the package, for example `grep "import nookku"`. The body of a here-document that is data does not count.
  - A launcher option can take a value, for example `uv run --python python3 nookku start`. After a launcher, the relay reads each later word that runs `nookku`, `python` or a shell. The `env` option `-S` or `--split-string` holds a command, for example `env -S 'nookku start'`, so the relay reads the text from that option. The text of a variable value, for example `env NOTE='nookku start' echo ok`, does not drive a test.
  - The module of `python -m` can be attached, as in `-mnookku`, or follow a group of flags, as in `-Im nookku`. The value of `-W`, `-X` or `--check-hash-based-pycs` is not the script. The code of `sh -c` can follow `--`.
  - If a shell or `python` reads its standard input, for example `echo 'nookku start' | bash`, the relay reads the text of the full command. A shell reads its standard input if it has no `-c` and has `-s` or no script. `python` reads it if it has no script, or the script `-`.
  - `nookku run` passes if the policy key `scripts` is `model` (section 7.9). The relay reads each part of the command, so `nookku run --script refunds.jsonl; nookku start` gets the deny. `nookku check`, `nookku mode`, `nookku mode status` and the read commands pass.
  - The reason is `nookku: only a person runs <command>. A model command may not drive a test. To run a scenario, use nookku run --script, if the policy key scripts is model.` For an import, it is `nookku: a model command may not import nookku, because a script can drive a test with it. To run a scenario, use nookku run --script, if the policy key scripts is model.`
  - The deny is best effort. A model can still write a script that does not name the package, for example a script that sends HTTP requests to the tap. The conformance cases are in [`conformance/guard/`](conformance/guard/).
- **Read check.** A tool call passes the read check only if it is a shell tool call (`Bash`, `shell`, `local_shell` or `exec_command`) and its command obeys these rules. Each other tool call fails, so the deny fails closed.
  - The relay removes the body of each here-document, then splits the command at `;`, `&`, `|` and new lines.
  - Each part starts with a read program, or has only variable assignments. An assignment to `PATH`, `IFS`, `CDPATH`, `ENV`, `BASH_ENV`, `SHELLOPTS`, `BASHOPTS`, `PS4`, `PROMPT_COMMAND`, or a variable that starts with `LD_` or `DYLD_`, fails. The read programs are `cat`, `head`, `tail`, `grep`, `egrep`, `fgrep`, `rg`, `jq`, `wc`, `ls`, `nl`, `cut`, `sort`, `diff`, `cmp`, `stat`, `sha256sum`, `shasum`, `echo`, `printf`, `pwd`, `cd`, `sed`, `find`, `which`, `type`, `command` or `nookku`, and each program of the policy key `guard_reads` (section 7.9) that is not in this list. The deny of the policy file does not use `guard_reads`, because a program that a person adds can write. A variable can be an argument, for example `cat $T/relay.jsonl` or `cat ${T}/relay.jsonl`, but not the program.
  - `sed` needs `-n`, and each of its scripts, without its `/regex/` addresses, has only line addresses and the commands `p`, `P`, `=`, `q`, `Q`, `d` and `n`. An option that the check does not know fails, for example `-i` or `-f`. `sort` has no `-o`. `rg` has no `--pre`. `find` has no `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`, `-fls`, `-fprint`, `-fprint0` or `-fprintf`. `nookku` runs `transcript`, `audit`, `status` or `view`. `command` needs `-v` or `-V` as its first argument, because without it `command` runs its argument as a program.
  - Each output redirect writes `/dev/null` or a file with the name `report.md`, or it copies a file descriptor.
  - The command has no `(`, `)`, `$(` or backquote, and each quote ends.
- **Deny fails closed.** The relay applies the denies that need only the state folder before it reads the config. These are the deny of test files, the deny of the entry of the running test (from its `manifest.json`), and the deny of the tap of the running test. Thus a config that does not load does not stop them. If the relay fails on a tool call and the folder `.nookku/` exists, it denies the tool call, also when relay mode is off. Without this folder, only the deny of the policy file applies.
- The deny of test files and of the entry is best effort, like the deny of the tap. A model can change a file or run the app with a command that does not name it.
- **History.** For the `openai` adapter, the relay sends the turns of the current session that have `ok: true`, then the new message. In a test, the relay sends the turns of the test that have `ok: true` as `history`. If a line of the relay record is not valid (section 2), the relay stops with that error and sends nothing to the tap.

## 6. Agent contract, version 1

The agent contract defines what goes into the agent and what comes out of it. In stdio mode, the entry speaks it on stdin and stdout.

- Each message is one UTF-8 JSON object on one line, with one `\n` at the end. A line has no other `\n` or `\r` bytes. JSON escapes these characters in strings.
- Stdout is only for contract lines. The agent writes its logs to stderr.
- The agent reads one input line, then writes one output line. It does not write a line without an input.
- The agent exits when its stdin closes.

Input:

| Field | Type | Meaning |
|---|---|---|
| `v` | integer | `1` |
| `id` | string | A new id for each message. The output must have the same id. |
| `session` | string | The conversation. In a test, it is the test id. |
| `message` | string | The exact text that the tester typed. |
| `history` | list | The earlier turns of the conversation, as `{"message": string, "reply": string}` objects, oldest first. The agent can use it or keep its own state. |

Output: an object with `v: 1`, the same `id`, and exactly one of these fields:

| Field | Type | Meaning |
|---|---|---|
| `reply` | string | The exact text of the agent's reply. |
| `error` | string | Why the agent has no reply. |

Other fields are allowed and ignored.

An output line is not valid in these cases. The tap returns status 502 for it and writes an `unparsed` row (section 4.2).

- The line has both `reply` and `error`, also if one of them is `null`.
- The line has neither `reply` nor `error`, or the field is not a string.
- The line contains `NaN`, `Infinity` or `-Infinity`. These are not JSON values. This rule applies to an input line too.

In stdio mode, a line with no `id` or with a different `id` is a stray line, not an output line (section 4.2). This rule applies to stdio mode only. An HTTP response has one body, and that body is the output line. If the body has no `id` or a different `id`, it is not valid.

The tap and the relay read an output line with these same rules.

The Python helper `nookku.agent.serve(reply)` speaks this contract for a function `reply(message, history) -> str`. It writes its contract lines to the original stdout, and it sends all other output of the process to stderr.

### 6.1 Environment of the entry

In a test, the bridge gives the entry 2 variables, together with the variables of section 7:

| Variable | Value |
|---|---|
| `NOOKKU_TEST_DIR` | The absolute path of the test folder. |
| `NOOKKU_TEST_ID` | The test id. It is also the `session` of each input line. |

An app can keep its state for the test in the subfolder `app-state/` of the test folder, for example an event log. The seal covers each file of the test folder (section 7.4), so `verify` shows a change to these files after the end of the test. The evaluation reads `app-state/` if it exists. Only the app writes there: the relay denies a model write to the test folder (section 5). A child process of the app, for example its model harness, can inherit `NOOKKU_TEST_DIR`, so during a test the relay also denies a tool call that names the variable. A backend may not use one of these 2 variables as its `env`.

## 7. Tests

A test runs the entry from `start` to `end`. A new conversation is a new test: each test starts a new entry process with a new test id.

**The state folder.** `.nookku/` in the project holds the configuration and the tests. verbatim-relay 0.3.x and earlier used `.verbatim-relay/`. Each command with a project root moves `.verbatim-relay/` to `.nookku/` before it does its work, with one rename, so each record and each seal stays as it is. A `record` path in `.verbatim-relay/` in `config.json` then changes to the same file in `.nookku/`. If both folders exist, nothing moves: the command stops with exit 1, and the relay blocks the event with exit 2.

### 7.1 Configuration

`.nookku/config.json` holds the test configuration:

| Key | Type | Meaning |
|---|---|---|
| `entry` | list of strings | The entry command, as an argument vector. It runs in the project root. |
| `models` | list of strings | The harnesses that the app uses for its model sessions: `claude-code`, `codex`, both or none. |
| `evaluate` | boolean | Optional. `false` stops the evaluation at the end of a test (section 9). The default is `true`. |
| `otel` | boolean | Optional. `false` stops the OTLP receiver of a test (section 7.5). The default is `true`. |
| `backends` | list of objects | Optional. The backends of the app, each with the strings `name`, `env` and `url` (section 7.6). Each `name` and each `env` is used only once. |
| `model_api` | boolean, list or object | Optional. The model APIs to record (section 7.7): `true` for all, `false` for none, a list of `anthropic` and `openai`, or an object from these names to the upstream URL of the API or `null`. The default is `true`. A backend must not use the variable of a recorded model API. |
| `entries` | object | Optional. More entries for a scripted test: an object from a name to an entry argument vector (section 7.10). A name has letters, digits, `_`, `.` and `-`, and starts with a letter or a digit. `entry` stays the default entry. |
| `check_message` | string | Optional. The one message of `nookku check`. It must have a character that is not white space, and no lone surrogate. The default is `Hello from nookku check. What can you help me with?`. |
| `repeated_reply` | integer | Optional. The count of consecutive turns with the same reply that gives a `repeated_reply` finding (section 8.6). It must be 0 or 2 or more. `0` turns the check off. The default is 2. |
| `model_reply_field` | string | Optional. The dot path of the client text in the JSON of a structured model output, for the `reply_not_from_model` check (section 8.6). Each part of the path has at least 1 character. The default is empty: the check uses the full text of each model output. |
| `model_reply_match` | string | Optional. `exact`, `normalized` or `off`: the match of the `reply_not_from_model` check (section 8.6). The default is `normalized`. |
| `transcript_compact` | boolean | Optional. `true` makes `nookku transcript --trace` compact (section 9.2). The default is `false`. |

The file can also hold the relay keys, for an agent that runs as an HTTP server ([docs/reference/config.md](docs/reference/config.md#relay-keys)). `openai_stream` is a boolean. `tap_url`, `agent_url`, `adapter`, `message_field`, `reply_field`, `openai_model` and `record` are strings. Each other key is unknown.

One reader ([src/nookku/config.py](src/nookku/config.py)) reads the file for `start`, `check`, `init` and the relay, with one rule:

- If the file is not a JSON object, or if it has an unknown key, the reader gives an error. The error text is the same for each command. For an unknown key, it is `.nookku/config.json has unknown keys: ['<key>']. Correct or remove them.`
- If a value does not have the type of its key, the reader gives an error. Each key has one error text, for example `.nookku/config.json: 'models' must be a list of claude-code, codex`. The reader checks the form of `backends` and `model_api` with the rule of sections 7.6 and 7.7. A test also checks the URL of each model API from its variable when it starts.
- `start` and `check` stop with the error and exit with 1. `mode on` starts no test and keeps relay mode off, also if the file has no entry.
- In relay mode, the relay blocks each prompt and shows the error. Thus a broken file never lets a prompt reach the model. The plugin and the project hooks run the same relay, so the same rule applies to both.

`nookku init` refuses a root in a state folder, for example a test folder, and writes nothing. The match ignores case and also finds the old folder `.verbatim-relay`. It also finds a state folder by its marker file `nookku-state`, which `init` and `start` write, for example in the target of a `.nookku` symlink. It finds a test folder by its `manifest.json`, also a copied test folder, and names the project root of the manifest. It checks the root as given and the resolved root. `nookku init` keeps each key of an existing file. It changes only the keys of the flags that the tester gives, and it prints the changed keys and the kept keys. A new file gets each key, with its default value if no flag gives it. If the existing file or the hook file breaks the rule or is not valid JSON, `init` writes nothing. `init` replaces only its own hooks in the hook file, and it keeps each other hook, also one in the same group.

`nookku check` runs a short test with one message, the value of `check_message`. The relay record of the check has this message in `said`. The check passes if the entry sends a reply, if the audit of the test is clean, and if the tap identifies at least one model session and finds its session file for each harness in `models`. If the tap times out after stray lines (section 4.2), the check also gives the fix for them.

After the end of the test, the check reads `audit.json` in the test folder (section 7.2). If its exit code is not 0, the check fails. It names each error of the audit and each break, with the line numbers and the fix. For an `unparsed` row of a stray line, the fix is the fix of section 4.2: use `nookku.agent.serve()` or write logs to stderr. If the audit has 2 or more errors of stray lines, the check names them in one problem: the count, the first 3 lines and the fix. The check gives this fix one time only. If `audit.json` is missing or is not valid, the check fails and says so.

### 7.2 Start and end

`start` creates the test folder and starts the bridge, a background process that runs the tap in stdio mode. The bridge writes `.nookku/current.json` with the test id, the test folder, the tap URL, its own pid and the string `pid_start`. Then `start` switches relay mode on. With an entry, relay mode is the file `.nookku/mode` for both relays, so it survives a restart of the harness or a reload of the plugin.

`pid_start` is the start time of the bridge process. The OS can give the pid of a stopped process to a new process, so the pid and `pid_start` together identify the bridge. On Linux, `pid_start` is `proc:` and field 22 of `/proc/<pid>/stat`. On other systems, it is `ps:` and the output of `ps -o lstart= -p <pid>` with `TZ=UTC0` and `LC_ALL=C`, with each run of spaces as one space. A reader compares the value only for equality. If the bridge cannot read its start time, it does not start.

If no process with the pid runs, or if the start time of that process is not `pid_start`, the test does not run. Then `start`, `end` and `status` remove `current.json`, and `end` sends no signal to the process.

`end` switches relay mode off and stops the bridge. If a harness session sends the prompt that ends the test, `end` writes its id to `.nookku/ending.json`. The bridge adds that id to the tester's sessions, so it never takes the session that ends the test, and then evaluates it, as a session of the app. The bridge then:

1. Closes the entry's stdin and waits 5 seconds. Then it stops the process group, first with SIGTERM and after 5 more seconds with SIGKILL. Then it stops the OTLP receiver (section 7.5), after no request came for 0.5 seconds or after 2 seconds, the backend proxies (section 7.6) and the model API proxies (section 7.7).
2. Identifies the Codex sessions (section 7.3). If `relay.jsonl` is invalid, the bridge does not know each tester session, so it identifies no Codex session and writes the error to `bridge.log`.
3. Copies the session file of each identified model session into `sessions/` in the test folder.
4. Writes the end time and the tester's harness sessions into the manifest.
5. Builds the trace (section 8): `trace.jsonl` and `findings.json`. If the trace fails, the bridge writes the error to `bridge.log`, and the test still ends.
6. Writes `audit.json`: the audit of `tap.jsonl` against `relay.jsonl` (section 3), in the form of `nookku audit --json`. If the audit fails, the bridge writes the error to `bridge.log`.
7. Writes the seal (section 7.4). If the seal fails, the bridge writes the error to `bridge.log`.
8. Removes `current.json`.

The test folder:

```text
.nookku/tests/<test-id>/
  manifest.json  relay.jsonl  tap.jsonl  app.log  bridge.log
  otel.jsonl  backend.jsonl  model_api.jsonl  trace.jsonl  findings.json  audit.json  seal.json  report.md  denied.jsonl
  sessions/claude-code/<session>.jsonl
  sessions/codex/<rollout file>
```

`manifest.json` holds the test id, the project root, the entry, the models, the start and end times, the versions of Nookku, Claude Code and Codex, the SHA-256 of each configuration file in `.nookku/`, `policy`: the value of each policy key (section 7.9), `trace`: the value of each config key of the trace checks (`repeated_reply`, `model_reply_field` and `model_reply_match`, section 8.6), the tester's harness session ids, and `codex_gate`: the result of the Codex hook gate at the start and at the end of the test (section 7.8). `entry_name` is the name of the entry in `entries`, or `null` for the default entry. `script` is `null`, or for a scripted test `source`, the absolute path of the script file, `file`, the name of its copy, and `sha256`, the SHA-256 of the copy (section 7.10).

### 7.3 Model sessions

The harness binary writes each model session of the app to a session file. The tap identifies these sessions. It does not change them.

- **Claude Code.** During the test, the tap reads `~/.claude/sessions/<pid>.json` (under `CLAUDE_CONFIG_DIR` if it is set) twice each second. If the pid is the entry or one of its descendants, the tap writes a `model_session` row with `inferred: false`. The session file is `~/.claude/projects/<folder>/<session>.jsonl`.
- **Codex.** At the end, the tap reads the first line of each rollout file in `~/.codex/sessions/` (under `CODEX_HOME` if it is set) that changed during the test. If its `cwd` is the project root or a folder in it, and its id is not a session of the tester, the tap writes a `model_session` row with `inferred: true`.

The harness binary writes the session files, and their format can change between harness versions. The record is independent of the app, but not of the harness.

### 7.4 Seal

The seal shows if a file of the test folder changed after the end of the test. It does not stop the change.

`seal.json` is a JSON object:

| Field | Type | Meaning |
|---|---|---|
| `v` | integer | The seal version, `1`. |
| `test` | string | The test id. |
| `sealed` | number | The Unix time of the seal. |
| `files` | object | For each file in the test folder and its subfolders, its path in the folder (with `/`) and the SHA-256 of its bytes (lowercase hex). |
| `copy` | boolean | True if the bridge wrote the copy. |

- The seal does not contain `report.md`, `bridge.log`, `seal.json` and `denied.jsonl`, because these files change after the end.
- The bridge also writes a copy, with the same fields and `copy: true`, to `~/.nookku/seals/<test-id>.json` (under `NOOKKU_HOME` if it is set). If it cannot write the copy, for example in a sandbox, `seal.json` has `copy: false`.
- If no copy is in `~/.nookku/seals/` but a copy is in `~/.verbatim-relay/seals/` (under `VERBATIM_RELAY_HOME` if it is set), the copy of verbatim-relay 0.3.x and earlier is the copy.

`nookku verify [TEST] [--json]` compares the folder with the seal, and the seal with the copy. If `seal.json` does not exist, the copy is the seal. The result:

| Field | Meaning |
|---|---|
| `sealed` | `seal.json` exists and is valid. |
| `changed` | The sealed files with a different SHA-256. |
| `missing` | The sealed files that do not exist. |
| `added` | The files that are not in the seal and not in the list of files that change after the end. |
| `copy` | `same` or `different`: a copy exists, and it has, or does not have, the same `v`, `test`, `sealed` and `files`. `verify` always compares an existing copy, also when `seal.json` has `copy: false`. `missing`: no copy exists, and `seal.json` has `copy: true` or does not exist. `none`: no copy exists, and `seal.json` has `copy: false`, or no seal exists. |
| `intact` | `sealed` is true, the 3 lists are empty, and `copy` is `same` or `none`. |

`verify` exits with 0 if `intact` is true, and with 2 if it is false. `nookku transcript --trace` shows the result in its first line, or in its second line if a record is not valid (section 9.2).

`nookku trace` rebuilds `trace.jsonl` and `findings.json`. If a seal or a copy exists, it rebuilds them only if each other sealed file agrees with the seal, `seal.json` exists, and the copy is not `different` or `missing`. Then it writes the new SHA-256 of the 2 files to the seal and to the copy.

The conformance cases in `conformance/seal/` test `verify`.

### 7.5 OTLP receiver

During a test, the bridge runs an OTLP/HTTP receiver on `127.0.0.1` at a free port, before it starts the entry. It gives the entry these environment variables, and they replace the values that the entry has:

| Variable | Value |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | The URL of the receiver. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` |
| `OTEL_TRACES_EXPORTER`, `OTEL_LOGS_EXPORTER` | `otlp` |
| `OTEL_METRICS_EXPORTER` | `none` |
| `OTEL_BSP_SCHEDULE_DELAY`, `OTEL_BLRP_SCHEDULE_DELAY`, `OTEL_LOGS_EXPORT_INTERVAL`, `OTEL_TRACES_EXPORT_INTERVAL` | `500` |
| `CLAUDE_CODE_ENABLE_TELEMETRY`, `OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_DETAILS` | `1` |

The config key `otel: false` stops the receiver and these variables.

The receiver takes `POST /v1/traces` and `POST /v1/logs` with `application/json` or `application/x-protobuf`, also with `Content-Encoding: gzip`. It reads the protobuf messages of opentelemetry-proto v1, and skips the fields that it does not know. It answers `POST /v1/metrics` with 200 and drops the body. It answers other paths with 404, and a body that it cannot read with 400.

The receiver writes `otel.jsonl` in the test folder: one JSON object on each line, in the order of the requests. It writes each lone surrogate in a string as its escape text (section 2).

- **`span`**: `v` (`1`), `type`, `received` (Unix time), `service` (the `service.name` of the resource), `resource` (its attributes), `scope` (the scope name), `trace_id`, `span_id` and `parent_span_id` (lowercase hex, or `null`), `name`, `start` and `end` (Unix time), `attributes`, `events` (each with `time`, `name` and `attributes`), and `status` (`code`: 0 unset, 1 ok, 2 error; `message`).
- **`log`**: `v`, `type`, `received`, `service`, `resource`, `scope`, `time` (the record time, or the observed time if the record time is 0), `event_name` (the `event.name` attribute, or the `eventName` field), `severity`, `body`, `attributes`, `trace_id` and `span_id`.
- **`error`**: `v`, `type`, `received`, `path` and `detail`, for a body that the receiver could not read.

An attribute value is a string, a boolean, an integer, a number, a list, an object (a key-value list) or a base64 string (bytes). Before it writes a row, the receiver:

- removes each attribute whose key starts with `user.` or `organization.`, or contains `email` (in any case), at each level;
- drops each span of a harness: a resource with the `service.name` `claude-code`, or a `service.name` that starts with `codex`;
- keeps a log record of a harness only if the last part of its event name (after the last `.`) is `user_prompt`, `tool_decision`, `tool_result`, `assistant_response` or `api_error`.

The conformance cases in `conformance/otlp/` test the receiver.

### 7.6 Backend proxies

A backend is a service that the app calls over HTTP, for example a stock service. The app reads the URL of the backend from the environment variable `env`. The entry can also give that URL to an app that reads it from a file.

During a test, the bridge runs one proxy for each backend in `backends`, on `127.0.0.1` at a free port, before it starts the entry. It gives the entry the URL of the proxy in the variable `env`, in place of the value that the entry has.

- The proxy forwards each request to `url`: the method, the path and the query after the path of `url`, the headers, and the body. It sends each header of the app once, in its order, except `Host` and the hop-by-hop headers. The app does not know that it speaks to a proxy, so `Proxy-Authorization` goes to the backend. The proxy adds only `Host` and `Content-Length`. A request body with `Transfer-Encoding: chunked` goes to the backend with a `Content-Length`.
- It sends the response of the backend back to the app with no change: the status, the headers except the hop-by-hop headers (`Proxy-Authenticate` goes through), and the body. It reads the whole response before it sends it.
- If the backend does not answer, the proxy sends status 502 to the app.
- At the end of the test, the bridge stops the proxies after it stops the entry. It waits up to 10 seconds for each call that did not end. For each call that is still open after that time, the proxy writes a row with the error `the test ended before the backend answered`. After that, the proxy writes no row and sends status 503 for each new request. Thus each call has its row before the trace and the seal.
- The proxy speaks HTTP to the app. It speaks HTTP or HTTPS to the backend, as `url` says.

The proxy writes one row to `backend.jsonl` for each call:

| Field | Meaning |
|---|---|
| `v`, `type` | `1`, `"call"` |
| `backend` | The `name` of the backend. |
| `started`, `ts` | The Unix times when the request came and when the call ended. |
| `method`, `path`, `query` | The request line from the app. `query` is `null` if the path has no `?`. The proxy removes the values of secret query parameters from `query` (see below). |
| `request_headers`, `response_headers` | The headers as a list of `[name, value]`, in their order. `response_headers` is `null` if the backend did not answer. |
| `request_body`, `response_body` | An object: `size`, `sha256` (of the bytes), `cut`, and `text` (UTF-8) or `base64`. For a `gzip` or `deflate` body, `text` is the decoded body, and `decoded` names the encoding. If the body is longer than 1 MiB, `text` or `base64` holds the first 1 MiB, and `cut` is `true`. `size` and `sha256` are always of all the bytes that went to the app or the backend. `response_body` is `null` if the backend did not answer. |
| `status` | The status of the backend, or `null`. |
| `error` | `the backend did not answer: <reason>`, `the test ended before the backend answered`, or `null`. |

Before it writes a row, the proxy removes the secret values. A header name or a query parameter name is secret if it is `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `auth` or `sig`, or if it contains `key`, `token`, `secret`, `password` or `signature`. The rule ignores case.

- For each secret header, the proxy replaces the value with `<removed>`.
- For each secret query parameter, the proxy keeps the name and the `=`, and removes the value. For example, `sku=mug&api_key=toy-123` becomes `sku=mug&api_key=`. Each parameter and each `&` stays in its order. The proxy splits the query only at `&`.
- The rule reads the name after it decodes `+` and the `%` escapes, for example `api%5Fkey`. The record keeps the name as it came.
- A parameter with no `=` stays as it came.

The secret headers and the full query still go to the backend, and the secret headers go to the app. The proxy does not change the bodies in the record. It writes each lone surrogate in a string of a row as its escape text (section 2). The bytes that it forwards do not change.

### 7.7 Model API proxies

An app can call a model API directly with an SDK, with no harness session. During a test, the bridge runs one proxy for each API in `model_api`, on `127.0.0.1` at a free port, before it starts the entry:

| API | Variable | URL if the variable has no value |
|---|---|---|
| `anthropic` | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` |
| `openai` | `OPENAI_BASE_URL` | `https://api.openai.com/v1` |

The proxy forwards to the URL that `model_api` gives for the API, else to the value that the bridge has in the variable, else to the URL of the table. A URL in `model_api` is necessary if the tester's harness also reads the variable, for example Codex and `OPENAI_BASE_URL`. It gives the entry the URL of the proxy in the variable. A value that is not an `http` or `https` URL stops the start of the test. An empty URL in `model_api` also stops it: the proxy does not then use the variable.

- The proxy forwards each request as a backend proxy does (section 7.6).
- It removes the values of secret headers and secret query parameters from the row as a backend proxy does (section 7.6).
- It writes each lone surrogate in a string of a row as its escape text, as a backend proxy does. For example, a JSON response can escape a lone surrogate in the text of `result`.
- It sends each part of the response to the app when the part comes, also for a streamed (SSE) response. It sends the status and the headers first. If the API gives no `Content-Length`, the proxy sends the body to the app with `Transfer-Encoding: chunked`.
- If the API stops during the body, also before the end that its `Content-Length` gives, the row gets the error `the stream stopped: <reason>`, and the proxy closes the connection to the app. If the app goes away, the proxy reads the rest of the response for the record.
- At the end of the test, the proxy waits for open calls as a backend proxy does.

A harness that the app uses, for example the Agent SDK, also reads these variables. Thus its calls also go through the proxy. The proxy finds a harness call by the start of its `User-Agent`: `claude-cli` or `claude-code` for `claude-code`, and `codex` for `codex`. A harness call holds the harness's own instructions. Thus its row keeps only the `size`, `sha256` and `cut` of each body, with `omitted: true`, and its `result` is `null`. Claude Code 2.1.286 also sends `HEAD /api/hello` with the User-Agent of its runtime and no body. This call is not a model call, and the trace does not keep it (section 8.4).

The proxy writes one row to `model_api.jsonl` for each call, with the fields of a `backend.jsonl` row (section 7.6), and with these changes:

| Field | Meaning |
|---|---|
| `api` | The API name, in place of `backend`. |
| `harness` | `claude-code` or `codex` for a harness call, else `null`. |
| `stream` | `true` if the `Content-Type` of the response is `text/event-stream`. `null` if the API did not answer. |
| `result` | The result of a model call, or `null` for another path or a harness call. |

`result` is an object with `model`, `text` (the text blocks joined), `tool_calls` (a list of `id`, `name` and `input`), `stop_reason`, `usage` and `error` (the `message` of the `error` object of the API, or `null`). The result of a `/decisions` call also has `answers`. The proxy reads the result from the decoded response body, as JSON or from the `data` of the SSE events:

- The proxy reads the SSE events with the parser of the tap (section 4.1), so both read a stream with the same rules. It does not change a forwarded byte.
- If the API stopped in the middle of a UTF-8 character, the parser ignores that incomplete character at the end of the body. If other bytes of a stream are not UTF-8, the result has no events and the error `the stream is not UTF-8`.
- An event with the name `error` sets `error`: the `message` of its `error` object, or else its data.

The parsers of each model call:

- `anthropic`, path that ends with `/v1/messages`: the `content` blocks, `stop_reason` and `usage`. In a stream: `message_start`, `content_block_start`, `content_block_delta` (`text_delta` and `input_json_delta`), `message_delta` and `error`.
- `openai`, path that ends with `/chat/completions`: `choices[0].message` (`content` and `tool_calls`), `finish_reason` and `usage`. In a stream: the `delta` of choice 0 of each chunk. The `arguments` of a tool call are parsed as JSON. If they are not JSON, `input` is the text.
- `openai`, path that ends with `/responses` (also `/v1/responses`): the Responses API. A path after the response id, for example `GET /responses/<id>`, is not a model call. The parser reads the response object:
  - `text` is the `text` of each `output_text` part of each `message` item in `output`, joined.
  - Each `function_call` item in `output` is a tool call. `id` is its `call_id`, because a later request gives the result with this id. `input` is its `arguments`, parsed as for `/chat/completions`.
  - `stop_reason` is the `status` of the response, for example `completed`, `incomplete` or `failed`. `usage` is `usage`. `error` is the `message` of the `error` object.
  - In a stream, the parser keeps the output items by their `output_index`. `response.output_item.added` and `response.output_item.done` set the item. `response.output_text.delta` adds its `delta` to the text of the part at `content_index`. `response.function_call_arguments.delta` adds its `delta` to the `arguments` of the item. Thus a stream that stops before its end keeps the text and the arguments that came. The parser reads `model`, `status`, `usage` and `error` from the `response` object of `response.created`, `response.in_progress`, `response.completed`, `response.failed` and `response.incomplete`. An `error` event gives `error` from its `message`. The parser does not read the other events.
  - This parser follows the OpenAI API reference of 2026-10-07, the date when it was read: [create a response](https://developers.openai.com/api/reference/resources/responses/methods/create) and [streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events).
- `openai`, path that ends with `/decisions` (also `/v1/decisions`): the Decisions API (public beta). A path after `/decisions` is not a model call. The parser reads the decision object as JSON. The API reference gives no stream, so the parser also reads a body with `stream: true` as JSON:
  - `model` is `model`, `usage` is `usage` and `error` is the `message` of the `error` object. `text` is `""`, `tool_calls` is empty and `stop_reason` is `null`, because a decision has no status.
  - `answers` holds one object for each item of `answers`, in the same order. Each object has `type`, `name`, `value`, `probabilities` and `confidence`. `value` is `probability` for the type `predicate`, `choice` for `choice` and `score` for `score`. `probabilities` is the list of the answer as the API gives it: `value` and `probability` for a choice, and also `label` for a score. A `predicate` answer has no `probabilities` and no `confidence`. Their value is then `null`.
  - An answer of the type `refusal` has only `type` and `name`. The model did not answer that question. Its `value`, `probabilities` and `confidence` are `null`. A refusal is not an error: the API gives answers to the other questions of the call. An answer of another type keeps `type` and `name`, and its `value` is `null`.
  - This parser follows the OpenAI documents of 2026-10-07, the date when they were read: the [Decisions guide](https://developers.openai.com/api/docs/guides/decisions) and the API reference [create a decision](https://developers.openai.com/api/reference/resources/decisions/methods/create).

To read a new model call, the proxy adds one row to its table of model calls (the API, the end of the path and the format) and one parser for the format. The trace selects its reader of the request by the same format (section 8.4).

### 7.8 Codex hook gate

Codex skips a hook that a person did not trust. Then a relayed prompt goes to the model, and a hook cannot detect this, because it does not run ([proofs/spikes/codex-plugin.json](proofs/spikes/codex-plugin.json)). Thus the gate runs outside the hooks ([`src/nookku/codex_gate.py`](src/nookku/codex_gate.py)):

1. `start` and `mode on` run the gate before relay mode goes on. The gate starts `codex app-server` in the project and reads `hooks/list`. It never changes the trust of a hook. A person does the trust step.
2. The nookku hooks are the hooks of a plugin with an id that starts with `nookku@`, and the project hooks with the command of `nookku init codex`. If Codex lists a nookku hook of the plugin, or `.codex/hooks.json` has a nookku hook, the gate requires the `UserPromptSubmit` and the `PreToolUse` hook of that origin.
3. The gate refuses the test with each reason, and relay mode stays off, if a required hook is:
   - **missing**: Codex does not list it. Codex lists the project hooks only in a project that a person trusts;
   - **disabled**;
   - **not trusted**: its trust status is not `trusted`, for example `untrusted` or `modified`;
   - **modified**: its matcher, its timeout or its command differs from this version of nookku. For a project hook, the command includes the Python of this nookku. For the plugin, the SHA-256 of `nookku-hook.sh` must also be the SHA-256 of this version, because the trust hash of Codex does not cover the script ([proofs/codex-gate/gate.json](proofs/codex-gate/gate.json)).
4. The gate also refuses a test if the plugin and the project hooks are both on, because then each message goes to the agent two times. It also refuses a test if a warning or an error of `hooks/list` names nookku. If Codex cannot parse a hooks file, it lists no hook of that file and gives only a warning ([proofs/spikes/codex-plugin.json](proofs/spikes/codex-plugin.json)).
5. If the `codex` command (`NOOKKU_CODEX`, else `codex`) is not on `PATH`, or if `codex app-server` stops before it answers, Codex cannot run, and the gate passes with no check. If the app-server does not answer in 60 seconds, the gate refuses the test.
6. `end` runs the gate again. `codex_gate` in `manifest.json` has both results: `codex`, the nookku hooks with their origin, event, trust status, trust hash and script SHA-256, and the problems. If the end result has a problem, or its hooks differ from the start, the end text says that the Codex hooks changed during the test and that the test is not to be trusted. The seal covers the manifest.

The gate does not stop a person who starts Codex with other hooks after the start. The check at the end makes such a change visible in the sealed record.

Claude Code has no list of hooks for a program, so `start` and `mode on` read its settings files ([`src/nookku/claude_gate.py`](src/nookku/claude_gate.py), [#151](https://github.com/mohanraj00/nookku/issues/151)). The files are the user file (`$CLAUDE_CONFIG_DIR/settings.json`, else `~/.claude/settings.json`), `.claude/settings.json` and `.claude/settings.local.json`, with the last file first in precedence. If `enabledPlugins` gives `true` to a plugin with an id that starts with `nookku@`, and a project file has a hook with the command of `nookku init claude-code`, the test is refused and relay mode stays off. `init claude-code` warns if the plugin is on, and `init plugin` warns if the project hooks are on. In a linked git worktree, Claude Code reads the local file of the main checkout, so the check also reads that file. The check does not read managed settings or a `--plugin-dir` of the session. A running session keeps a plugin that it loaded until `/reload-plugins` or a restart, and no program can read that state, so the refusal tells the person to reload.

### 7.9 Policy file

`.nookku/policy.json` holds the keys that control the guard. The model can change `config.json` for normal app work, so a check of single keys in a shell edit of `config.json` is not reliable. Thus these keys are in a separate file that the model never writes ([`src/nookku/policy.py`](src/nookku/policy.py)).

- The file is a JSON object. If it does not exist, each key has its default, and each default is the strict value. If the file is not a JSON object, or has a key or a value that is not known, `start` and `check` stop with the error and exit with 1.
- `nookku policy` prints each key with its value. `nookku policy set <key> <value>` writes one key. Only a person runs it, in a shell. The relay denies it from the model (section 5).
- `manifest.json` records the value of each key as `policy`. `config_sha256` records the SHA-256 of the file, as for each configuration file in `.nookku/`.
- The plugin has no options, so no plugin option can change a policy key.
- Each guard rule that a person can change adds its key to this section, with its default and its conformance cases. The keys:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `guard_fields` | list of strings | `["path", "file_path", "url", "uri", "command"]` | The fields of a tool input that the guard reads, for a tool that is not a shell or a file tool (section 5). `nookku policy set guard_fields path,url` takes the names separated by commas. |
| `guard_reads` | list of strings | `[]` | More programs that the read check accepts (section 5), with each argument. Thus a program that can write a file or start a program with an argument, for example `fd --exec`, weakens the guard. `nookku policy set guard_reads` prints a warning about this. A program of the built-in list keeps its own check. The deny of the policy file does not use this key. `nookku policy set guard_reads od,hexdump` takes names separated by commas. A name has only letters, digits, `.`, `_`, `+` and `-`, and does not start with `.`, `+` or `-`. Thus a shell expansion such as `$X` or a glob such as `r?` is not valid, because the shell can change it into another program. An empty value clears the list. |
| `scripts` | `person` or `model` | `person` | Who runs `nookku run --script`. With `person`, the relay denies `nookku run` from the model (section 5). |
| `control_distance` | whole number, 0 or more | `2` | The edit distance at which relay mode refuses a message near a control prompt (section 5). The value 0 turns off the rule. `nookku policy set control_distance 1` takes the number. |

The conformance cases of the deny are in [`conformance/policy/`](conformance/policy/). Each case is a hook event, the files of the project, and the decision of the relay.

### 7.10 Scripted tests

`nookku run --script <file> [--entry <name>]` runs a scripted test. Each message comes byte for byte from a script file that exists before the test starts. The model never retypes a message: it gives only the path of the script and the name of an entry.

A script has one of 2 forms. Each message is the decoded JSON string.

- JSONL: one row for each turn, each a JSON object with only the string `said`. A last empty line is permitted.
- JSON: one array of strings. The first character that is not white space is `[`.

The script must be UTF-8 and must have at least one message. A message with a lone surrogate (section 2) is refused. `run` reads the script before the test starts, and a script that breaks a rule starts no test.

`--entry` takes only a name from `entries` (section 7.1), not a command line, because an entry from the model can be any program, and then the test proves nothing. An unknown name starts no test. Without `--entry`, the test uses `entry`.

`run` then:

1. Starts a test (section 7.2). It copies the bytes of the script into the test folder as `script.jsonl` or `script.json`, before the bridge starts, so the seal covers the copy. The manifest records `entry_name` and `script`. `run` does not switch relay mode on, so a typed prompt never becomes a turn of a scripted test.
2. Sends each message to the entry and waits for its reply. For each message, it writes a relay row with `"harness": "script"`. If a turn has no reply, it sends no more messages.
3. Ends the test. The bridge gives the audit the script copy, so the audit also runs the script check (section 3.2, step 7).
4. Prints the test id, the count of turns, the exit code of the audit and the trace summary, and with `--evaluate` the evaluation prompt (section 9.2). It does not print the replies: the evaluation reads the records. Without `--evaluate` or `--no-evaluate`, the `evaluate` key decides.

`run` exits with 0 if the audit is clean, and with 1 if the test did not start, a turn has no reply, the audit is not clean or the Codex hooks changed (section 7.8).

The policy key `scripts` (section 7.9) decides who runs a scripted test. With `person`, the default, the relay denies `nookku run` from the model (section 5), and the MCP tool `run_script` of `nookku mcp` refuses to run. With `model`, the model can run a scripted test with `nookku run` or with `run_script`, which takes `path` and `entry`. The `path` must name a file in the project folder after symlinks resolve, else `run_script` refuses. If the policy file is not valid, `run_script` refuses.

The transcript shows a scripted turn as `script, turn N`, never as a typed turn.

## 8. Trace

The trace is one record of the model items of the app in a test. It ties each item to a turn. `nookku trace [TEST]` builds it again from the files in the test folder.

### 8.1 Sources

A test has 3 sources. Each one is independent of the others in a different way:

| Source | Writer | Independent of |
|---|---|---|
| `tap.jsonl` | the tap | the app and the model of the tester's harness. It records the words only. |
| `sessions/` | the harness binary that the app uses | the app's code. It is not independent of the harness. |
| `backend.jsonl` | the backend proxies, from the calls of the app to its backends | the app's code. It records the bytes on the wire. |
| `model_api.jsonl` | the model API proxies, from the direct calls of the app to a model API | the app's code. It records the bytes on the wire. |
| `otel.jsonl` | the OTLP receiver, from the spans and logs that the app and its harness send | the session files. It is not independent of the app's code, because the app sends it. |
| The app's state | the app | nothing. The evaluating session reads it and judges it. |

The trace reads `tap.jsonl`, `sessions/`, `otel.jsonl`, `backend.jsonl` and `model_api.jsonl`. It does not read the app's state. It reads `tap.jsonl` with the reader of section 2. If `tap.jsonl` is not valid, the trace stops with that error: `nookku trace` exits with code 2, and the end of a test writes no trace.

### 8.2 Trace record

`trace.jsonl` is a UTF-8 JSONL file, sorted by `ts`. The trace writes each lone surrogate in a string of `trace.jsonl` and `findings.json` as its escape text (section 2). A harness session file can have one. Each line is a `model_item` row (0.3). Each row has all of these fields:

| Field | Type | Meaning |
|---|---|---|
| `v` | string | `"0.3"` |
| `type` | string | `"model_item"` |
| `turn` | integer or null | The number of the turn (section 8.3), or `null`. |
| `harness` | string | `claude-code` or `codex`. For a row of `otel.jsonl`: the harness of its `service` (section 7.5), or `otel` for the app. For a row of `backend.jsonl`: `backend`. For a row of `model_api.jsonl`: `model_api`. |
| `session` | string | The session id from the manifest. For a span: its `trace_id`. For a log: its `session.id` or `conversation.id` attribute, else its `trace_id`, else `""`. For an `http` item: the backend name. For a `model_api` item: the API name. |
| `ts` | number or null | The Unix time of the item. |
| `kind` | string | `message`, `tool_call` or `command`. From `otel.jsonl`: `span` or `log`. From `backend.jsonl`: `http`. From `model_api.jsonl`: `message` or `tool_call`. |
| `role` | string or null | For a message: `user` (the app to the model) or `assistant` (the model to the app). |
| `server` | string or null | For a tool call: the MCP server or the dynamic tool namespace. |
| `name` | string or null | For a tool call: the tool name, without the MCP prefix. For a span: its name. For a log: its event name, without the harness prefix for a harness log. For an `http` item: the method and the path, for example `GET /stock`. |
| `input` | any | For a tool call: its input object. For a command: its argv. For a span or a log: its attributes. For an `http` item: an object with `query`, `headers` (the request headers of the row) and `body` (the request body, as for `output`). For a `model_api` assistant message: an object with `path`, and `model`, `stop_reason` and `usage` of the result. For a `/decisions` call, the object also has the `answers` of the result. For a `model_api` user message of a `/decisions` call: an object with `questions` and `images` (section 8.4). For another user message: `null`. |
| `output` | string or null | For a message: its text. For a tool call or a command: its output text. For a log: its body, as JSON if it is not a string, or `null` if the body is the event name. For an `http` item: the `text` of the response body, with the note `(cut: the record holds the first 1 MiB)` if it is cut; `(<size> bytes that are not UTF-8: base64 in backend.jsonl)` for a binary body; `null` for an empty body or no answer. |
| `error` | string or null | For a tool call: the error text if the call failed. `output` is then `null`. For a span with status code 2: the status message, else the `exception.message` of its first `exception` event, else `status error`. For a harness `tool_result` log with `success` `false`: its `error` attribute. For an `http` item: the `error` of the row. For a `model_api` assistant message: the `error` of the row, else the `error` of the result. |
| `exit_code` | integer or null | For a command: its exit code. For an `http` item: the status of the backend. For a `model_api` assistant message: the status of the API. |
| `harness_internal` | boolean | `true` for a tool that the harness gives to the model, not the app (section 8.5). |
| `service` | string or null | For a row from `otel.jsonl`: its `service`. Else `null`. |
| `source` | object | `file`: the session file, `otel.jsonl`, `backend.jsonl` or `model_api.jsonl`, relative to the test folder. `line`: the 1-based line of the item. For a Claude Code tool call, `result_line`: the line of its result. |

The trace has no `<field>_sha256` fields. The session files hold the original bytes.

### 8.3 Turns

Turn `n` is the `n`-th `exchange` row of `tap.jsonl`. Its window is from `started` to `ts` of that row. If a row has no `started` (0.1), its window starts at the `ts` of the row before it. An item is in turn `n` if its `ts` is in the window of turn `n`, both ends included. Otherwise `turn` is `null`.

### 8.4 Readers

Each reader reads the copied session file of one model session in the manifest. It never fails on a line. It counts each line that it does not keep, by type, in `findings.json`. It counts a blank line (a line with only white space) as `blank`. The empty text after the last `\n` of a file is not a line. The `rows` count of `otel`, `backend` and `model_api` in `findings.json` does not include a blank line.

**Claude Code** (`sessions/claude-code/<session>.jsonl`). The reader keeps the lines of type `user` and `assistant` that have no `isMeta`. `ts` is the line's `timestamp`. From the `message.content` of each line:

- a string or a `text` block: a `message` item;
- a `tool_use` block of an `assistant` line: a `tool_call` item. A tool name `mcp__<server>__<tool>` gives `server` and `name`;
- a `tool_result` block of a `user` line: the result of the `tool_call` with the same id. The text of its `text` blocks is `output`, or `error` if `is_error` is `true`. A tool call with no result gets the error `no tool_result in the session file`;
- a `thinking` block or another block: counted, not kept.

The reader takes the version from the first line that has a `version` field.

The reader also finds the MCP servers that the file names, for the check `server_not_from_app` (section 8.6). It does not make items from them. A server name comes from:

- each name in `attachment.addedNames` of a line of type `attachment` with an `attachment.type` of `mcp_instructions_delta`, for example `claude.ai Toy Docs`;
- the `<server>` part of each name `mcp__<server>__<tool>` in `attachment.addedNames` of a line with an `attachment.type` of `deferred_tools_delta`, for example `claude_ai_Toy_Mail`;
- the `<server>` part of the name of each `tool_use` block of an `assistant` line.

The reader keeps each name once, with the first line that has it. It still counts the `attachment` lines as lines that it does not keep.

**Codex** (`sessions/codex/<rollout file>`). The reader keeps the lines of type `event_msg` with a payload of type `item_completed`. `ts` is the item's `completed_at_ms` divided by 1000, or the line's `timestamp`. By item type:

| Item | Trace item |
|---|---|
| `UserMessage`, `AgentMessage` | `message`. `output` is the text of its `text` or `Text` content. |
| `CommandExecution` | `command`. `input` is `command`, `output` is `aggregated_output`, `exit_code` is `exit_code`. Without an exit code and with a `status` that is not `completed`, `error` is `status <status>`. |
| `DynamicToolCall` | `tool_call`. `name` is `tool`, `server` is `namespace`, `input` is `arguments`. The text of `content_items` is `output` if `success` is `true`, else `error`. |
| `McpToolCall` | `tool_call`. `name` is `tool`, `server` is `server`, `input` is `arguments`. An `error` object gives `error` from its `message`. Else, the text of `result.content` is `output`, or `error` if `result.isError` is `true`. |
| Other types | Counted, not kept. |

The reader takes the version from `cli_version` of the `session_meta` line.

**OpenTelemetry** (`otel.jsonl`). The reader keeps each `span` and `log` row, and counts each other row by its type. `ts` is `start` for a span and `time` for a log.

**Backend calls** (`backend.jsonl`). The reader keeps each `call` row, and counts each other row by its type. `ts` is `started`.

**Model API calls** (`model_api.jsonl`). The reader counts each harness call by its `harness`, and does not keep it, because the session file of the harness has its turns. It counts each call to a path that is not a model call (section 7.7) in `other_calls`, and does not keep it. It counts each row that is not a call by its type. From each other call, in this order:

- a `message` item with the role `user`, if the last message of the request has the role `user` and text: a string, or the joined `text` parts. `ts` is `started`. If the request body is cut or is not JSON, the call gives no user message. For `/responses`, the messages are the items of `input`. A string `input` is the user message. Else the last item must be a message (with no `type`, or the type `message`) with the role `user`. Its text is its `content` string, or its joined `input_text` parts;
- for `/decisions`, a `message` item with the role `user` in place of the item above, if the request has text, an image or a question. `ts` is `started`. `output` is the text of `input`: a string `input`, or the joined `content` strings and `input_text` parts of the messages of `input` with the role `user`. With no text, `output` is `null`. `input` is an object:
  - `questions`: for each question of `questions`, its `name`, `type` and `options`. `options` is the list of the `value` of each item of `choices` for a `choice`, the list of the `label` of each item of `levels` for a `score`, and `null` for another type. The trace does not keep `instructions`.
  - `images`: for each `input_image` part, its `media_type`, `size` and `sha256`. The `image_url` must be a data URL. `media_type` is the type of the data URL, for example `image/png`. `size` and `sha256` are the length and the SHA-256 of the decoded base64 data. The trace does not keep the data. If the data is not base64, `size` and `sha256` are `null`. If the URL is not a data URL, all 3 are `null`;
- a `message` item with the role `assistant`. `output` is the `text` of the result, or `null` if it is empty. `ts` is the `ts` of the row. For `/decisions`, `input` also has `answers`, the answers of the result. A refusal does not give an `error`;
- a `tool_call` item for each tool call of the result. `ts` is the `ts` of the row. The output is the first tool result with the same id in the request of a later call of the same format (`messages`, `chat` or `responses`), because a tool call id is unique only in one format: a `tool_result` block (`anthropic`, an `error` if `is_error` is `true`), a message with the role `tool` (`openai`, `/chat/completions`), or a `function_call_output` item of `input` with the same `call_id` (`openai`, `/responses`). The text of a `function_call_output` is its `output` string, or its `input_text` parts joined, with each other part as JSON. With no such result, `output` and `error` are `null`.

### 8.5 Harness tools

These tools come from the harness, not from the app: `ToolSearch` in Claude Code. The trace keeps their items and marks them `harness_internal: true`.

### 8.6 Findings

`findings.json` holds the test id, the number of turns and items, one entry for each model session (its version, its item count and its counts of lines not kept), `otel`, `backend` and `model_api` (the file, its row count, its item count and its counts of rows not kept, or `null` if the test has no such file; `model_api` also has `harness_calls`, the count of harness calls by harness, and `other_calls`), a count for each check, and the findings. The findings do not change the exit code of the audit. The audit measures the words only.

| Check | Finding |
|---|---|
| `agent_error` | An exchange with a `status` that is not 200. |
| `repeated_reply` | A run of `repeated_reply` (section 7.1) or more consecutive exchanges with the same `reply`, byte for byte. An exchange with `reply: null` ends a run. Each run gives one finding. Its `turn` is the first turn of the run, `turns` is the list of each turn of the run, and `detail` names the turns and gives the first 60 code points of the reply as a JSON string, with ` (cut)` after it if the reply is longer. The trace takes the count from `trace` in the manifest. If the manifest has no count, or a count that section 7.1 does not allow, the count is 2. A count of 0 turns the check off. |
| `reply_not_from_model` | An exchange with a `reply` that contains no model text of its turn. The model texts of a turn come from its items of a session file or of `model_api.jsonl`: the `output` of each `message` item with the role `assistant`. If `model_reply_field` (section 7.1) is set, a model text is instead the string at that dot path in the JSON of such an `output`, and in the `input` of each `tool_call` item that is not `harness_internal`. The JSON of an `output` is its full text, or else its part from the first `{` to the last `}`, for JSON in a code fence. An output with no string at the path gives no model text. A text with only white space is not a model text. With `model_reply_match` `exact`, the reply must contain a model text, byte for byte. With `normalized`, it must contain it after both texts are normalized: each run of white space (Python `str.split`) becomes one space, the space at the start and the end is removed, and the case is folded (Python `str.casefold`). An exchange with `reply: null` or a turn with no model text gives no finding. `detail` gives the count of model texts that the trace checked and the first 60 code points of the reply, as for `repeated_reply`. The trace takes both keys from `trace` in the manifest, with the default for a missing or a wrong value. `off` turns the check off. |
| `tool_error` | A tool call with an `error`. |
| `command_failed` | A command with an exit code that is not 0, or with an `error`. |
| `span_error` | A span with an `error`. |
| `backend_error` | An `http` item with an `error`, or with a status of 500 or more. |
| `model_api_error` | A `model_api` assistant message with an `error`, or with a status of 400 or more. |
| `turn_without_model` | A turn with no `message`, `tool_call` or `command` item. This check runs only if a session reader kept at least 1 item. |
| `item_between_turns` | An item with `turn: null` and a `ts` at or after the start of turn 1. An item before turn 1, for example a model call when the app starts, is not a finding. |
| `otel_tool_not_in_session` | A harness `tool_result` log with no tool call in its session items. These are the items of the session of the event (section 8.2). If no item of the same harness has that session, they are the items of each session of the same harness. **Id rule.** If a Claude Code event has a `tool_use_id` and one of these tool calls has the `id` of its `tool_use` block, only a tool call with the same id matches, in any turn. **Else** a tool call of the same tool in the same turn matches. The tool is the `mcp_tool_name` of `tool_parameters`, or `tool_name` (Claude Code), or `tool_name` (Codex). If the event and the tool call both have an input object, the inputs must agree: the same keys, the same list lengths and equal values. The event can cut a string: a string of the event that is shorter than the string of the tool call agrees if the string of the tool call starts with it, after the trace removes a cut mark `...` or `…` at its end. For a Codex `exec_command`, `shell` or `local_shell`, any `command` item matches. The trace does not write the tool use id to `trace.jsonl`. |
| `server_not_from_app` | An MCP server in a Claude Code session file (section 8.4) that the MCP configuration of the app cannot give: a claude.ai connector of the account (a name that starts with `claude.ai ` or `claude_ai_`), or a server of a plugin (a name that starts with `plugin:` or `plugin_`). An app that loads a plugin itself also gets this finding for the servers of that plugin. The check does not find a server from a settings file or from `.mcp.json`, because its name does not show where it comes from. The finding has `harness`, `session` and `source` (the file and the first line that names the server). |
| `session_inferred` | A model session with `inferred: true`. |
| `version_untested` | A session file from a harness version that `proofs/trace/` does not cover. The tested versions are Claude Code 2.1.286 ([data](proofs/trace/results-2.1.286.json)) and 2.1.292 ([data](proofs/trace/results.json)), and codex-cli 0.160.0 ([data](proofs/trace/results-0.160.0.json)) and 0.162.1 ([data](proofs/trace/results.json)). The method is [scripts/proof_trace.py](scripts/proof_trace.py). If a reader finds no version in the file, the version is `unknown`. If the file is not in the test folder, the version is `null`, and this check does not run. |

Each finding has `check`, `turn` and `detail`. A finding about an item also has `harness`, `session` and `source`. The findings are sorted by check, in the order of the table, then by turn, and then in the order of the items. A finding with no turn comes after the findings with a turn.

## 9. Evaluation

At the end of a test, the harness model evaluates the app. It writes `report.md` in the test folder.

### 9.1 Start

A test needs an evaluation if all of these are true:

- `evaluate` in the configuration is not `false`;
- no test runs;
- the latest test (the one with the greatest `started` in its manifest) has an `ended` time;
- its folder has no `report.md`;
- it is not a check test. A check test is a test of `nookku check`: its relay record has turns, and each turn has the harness `nookku-check`. A relay record that cannot be read does not make a check test.

The relay reads `evaluate` with the one reader of `config.json` (section 7.1). If the file cannot be read or breaks the rule for its keys, no evaluation starts. A broken file must not start an evaluation that the tester turned off. Then, if the other conditions are true, the end text has one more line: `nookku: no evaluation starts: <error>. Correct the file, then type: nookku end`.

The prompt `nookku end` ends the running test, if one runs. Then, if a test needs an evaluation, the relay lets the prompt go to the model with this context: the end text and the evaluation prompt for that test. So the prompt also starts the evaluation of a test that ended in another way, for example with `nookku end` in a shell. Otherwise, the relay blocks the prompt (section 5).

The start text of a test gives the ways to end it. If `evaluate` is `false`, the start text does not name the evaluation.

`nookku end --evaluation` ends the test and prints one JSON object: `text`, the end text, and `evaluation`, the evaluation prompt or `null`.

### 9.2 Evaluation prompt

The evaluation prompt is `src/nookku/evaluate.md`, with the test id and the test folder filled in. It tells the model to:

1. read the transcript with the trace: `nookku transcript --trace --test <test-id>`;
2. read `findings.json` and `audit.json`;
3. read the code of the app and its business rules;
4. check the state of the app with read-only commands only;
5. write `report.md`, and no other file.

If the first line of the transcript is `Record: INVALID.` (below), the prompt tells the model not to judge the app. The model writes `report.md` with no issue, quotes the first 2 lines of the transcript in the notes, and tells the tester to run the test again.

For a scripted test (section 7.10), the prompt starts with a note. The note says that each message came from the script file, names the copy and its SHA-256, and names the entry. With a replay entry, the replies come from a recording, so the note tells the model to judge the app and the transport, not the model.

`nookku transcript --trace` shows each turn of a test as the app received it and sent it (from `tap.jsonl`). It reads `tap.jsonl` with the reader of section 2. If `tap.jsonl` has a line that is not valid, or if `trace.jsonl` has a line that is not a JSON object, the transcript has only 2 lines. The first line is `Record: INVALID.`, the error with the file and the line, and `Do not trust these records. This transcript shows no turn.` The second line is the result of the seal (section 7.4). The transcript shows no turn, so a changed text never shows as exact. Under each turn, it shows the model items of that turn and the findings of that turn. The findings with no turn come before turn 1. There, the `version_untested` findings of one harness and one version show as one line with the count of sessions, for example `- version_untested: version 2.1.294, tested: 2.1.286, 2.1.292 (claude-code, 4 sessions)`. `findings.json` keeps one finding for each session. For a `/decisions` call, the user message shows each question and each image on one line. The assistant message shows each answer on one line in place of the text:

| Type | Line |
|---|---|
| `predicate` | `<name>: probability <value>` |
| `choice` | `<name>: <value> (<probability of the value>), confidence <confidence>` |
| `score` | `<name>: score <value>, confidence <confidence>` |
| `refusal` | `<name>: refusal (the model did not answer this question)` |
| Another type | `<name>: <value>` |

For example: `department: billing (0.95), confidence 0.93`. An answer with no name shows `(no name)`. If an answer has no confidence, the line has no confidence. If the probabilities of a choice do not have its value, the line has no probability. Each item names its line in `trace.jsonl` as `[trace.jsonl:N]`. A text longer than 2,000 characters shows its start and names its line. Items with `turn: null` come after the last turn.

`nookku transcript --trace --compact` shows a repeated text one time. The config key `transcript_compact` sets the default, and `--no-compact` overrides it. The default output does not change. In compact mode, a `Compact:` line after the header line says so. These rules apply to each text of 200 or more characters. This bound is a chosen value, not a measurement: a reference holds a SHA-256 of 64 hex characters, so a shorter text gives a small saving ([`COMPACT_MIN`](src/nookku/evaluation.py#L21-L22)). The rules:

- An attribute of an OpenTelemetry span or log shows a reference if a session item of the same turn has the same text in its `output` or `error`.
- The text of a `user` message, or an attribute of an OpenTelemetry span or log, shows a reference if an earlier item in the transcript showed the same text in full.

The reference is `(compact: the same text as [trace.jsonl:N], sha256 <hex>, <length> characters)`. The transcript shows the text at line N. The length counts characters, and the SHA-256 is of the UTF-8 bytes. A shorter text, each other field and the tester and agent blocks do not change. The `transcript` tool of `nookku mcp` takes `compact` with the same meaning.

### 9.3 Report

`report.md` has one table with the columns Class, Turn, Evidence and Issue, and one row for each issue. The classes:

| Class | The app ... |
|---|---|
| `business_rule` | broke a rule of the business. |
| `wrong_tool` | called a tool that does not fit the request. |
| `wrong_arguments` | called the correct tool with incorrect arguments. |
| `unsupported_reply` | said a fact that no tool result and no rule supports. |
| `missing_action` | did not do an action that the request or a rule needs. |
| `state_mismatch` | gave a reply or a trace that does not agree with its state. |

Turn is the number of the turn, or `-`. Evidence is a `trace.jsonl:N` line, a turn, or a source line. The report is a model answer: the proofs check it, but no code reads it.

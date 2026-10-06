# verbatim-relay specification, v0.2 (draft)

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

Each record is a UTF-8 JSONL file. Each line is one JSON object. Each object has a version `v` and a `type`. A writer writes `"v": "0.2"`. A reader accepts `"0.1"` and `"0.2"`. A type or a field that this section marks as 0.2 is not valid in a `"0.1"` row. Each text field has a `<field>_sha256` field: the SHA-256 of the UTF-8 bytes of the text, in lower-case hex. If the text is `null`, its hash is `null`. `ts` is a Unix time in seconds.

### 2.1 Tap record

`exchange`: one request that the adapter parsed, and its response.

| Field | Type | Meaning |
|---|---|---|
| `input` | string | The message that the agent received, as the adapter extracts it. |
| `status` | integer or null | The HTTP status of the agent's response. `null` if the agent did not respond. |
| `reply` | string or null | The reply that the agent sent, as the adapter extracts it. It is `null` if, and only if, the status is not 2xx or is `null`. |
| `error` | string | Optional. Why `reply` is `null`. |
| `started` | number | Optional, 0.2. The Unix time when the tap sent the request to the agent. `ts` is the time when the tap wrote the row. |

In stdio mode, the tap writes these `status` values:

| Agent output | `status` |
|---|---|
| A `reply` line | 200 |
| An `error` line | 500 |
| No line: the agent exited, or the tap stopped it after a timeout | `null` |

`unparsed`: a request or a 2xx response that the tap forwarded but that the adapter cannot parse. Fields: `method`, `path`, `error`. The tap forwards this request without change, but the audit cannot check it. In stdio mode, the tap also writes `unparsed` for a request that is not a contract input, for an agent line that is not a valid contract output, and for an agent line that arrives when no request waits for it. For the last kind, `method` is `STDIO` and `path` is `stdout`.

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
| `harness` | string | For example `claude-code` or `codex`. |
| `said` | string | The exact text that the tester submitted. |
| `shown` | string or null | The exact text that the relay showed to the tester. `null` if the relay showed no reply. |
| `ok` | boolean | Optional. `true` if `shown` is the agent's reply, `false` if it is an error from the relay. |
| `session` | string | Optional. The harness session id. |

In a test (section 7), the relay record is `relay.jsonl` in the test folder.

`blocked_call`: the relay denied a model tool call that targeted the agent or the tap. Fields: `harness`, `tool`, `detail`. The audit counts these rows and does not match them.

## 3. Audit

### 3.1 Validity

The audit stops with exit code 2 and does not report breaks if one of these conditions occurs:

- `record_missing`: a record file does not exist or cannot be read.
- `record_invalid`: a line is not a JSON object, has a wrong `v` or an unknown `type`, has a missing or wrongly typed field, or has a hash that does not match its text.
- `tap_unparsed`: the tap record has an `unparsed` row. The audit cannot check that exchange.

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
   - If the exchange `status` is not 2xx or is `null`, the audit adds an `agent_error` note and does not check the reply.
   - If `shown` is `null`, it is an `unshown_reply` break.
   - If `shown` is not equal to `reply`, it is an `altered_reply` break.

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
- If the agent does not respond, the tap returns status 502 and writes an `exchange` row with `status: null`.
- The tap writes rows only for `POST` requests that the adapter accepts. It forwards other requests without a row.
- The tap does not support streamed responses in v0.1. If an OpenAI-style request has `"stream": true`, the tap returns status 501 and does not forward it.

#### Adapters

- **`json`:** the input is at a field path in the request body, and the reply is at a field path in the response body. The defaults are `text` and `reply`. A path uses dots, and a list index is a number, for example `choices.0.message.content`.
- **`openai`:** for a `POST` to a path that ends in `/chat/completions`. The input is the `content` of the last message with role `user`. The content must be a string, or a list with exactly one part of type `text`. The reply is `choices.0.message.content`.

Each adapter maps onto the agent contract (section 6):

| Contract field | `json` adapter | `openai` adapter |
|---|---|---|
| `message` | the request field at the message path | the last `user` message |
| `history` | not sent | the earlier `user` and `assistant` messages |
| `session` | not sent | not sent |
| `reply` | the response field at the reply path | `choices.0.message.content` |
| `error` | a status that is not 2xx | a status that is not 2xx |

### 4.2 Stdio mode

`verbatim-relay tap --cmd -- <command>` starts the command as the agent and talks to it with the agent contract (section 6). The tap listens on a local HTTP endpoint, the same as in HTTP mode. The relay posts each contract input line to it.

- The tap starts the agent in its own process group, with the test root as its working directory. The agent's stderr goes to `app.log` in the test folder.
- The tap accepts a `POST` with a body that is a valid contract input on one line: no `\n` and no `\r` bytes. It writes the body to the agent's stdin without change, then one `\n`. If the body is not valid, the tap returns status 400, writes an `unparsed` row and does not send the body.
- The tap sends one request at a time. It waits for one line on the agent's stdout.
- If the line is a valid output with the same `id`, the tap returns status 200 for a `reply` and 500 for an `error`, with the line as the body. It writes an `exchange` row. For an `error` line, the row's `error` is the agent's error text.
- If the line is not valid, or has a different `id`, the tap returns status 502 and writes an `unparsed` row.
- If the agent sends no line in 240 seconds, the tap stops the agent's process group. It returns status 504 and writes an `exchange` row with `status: null`.
- If the agent exits, the tap returns status 502 and writes an `exchange` row with `status: null` and the exit code in `error`.
- The tap does not restart the agent. After a crash or a timeout, it answers each later request with the same error. The error body includes the last 20 lines of `app.log`.
- Before each request, the tap reads each line that waits on stdout. Each such line becomes an `unparsed` row with `method: STDIO`.

## 5. Relays

A relay is the Claude Code plugin or the hook kit. The hook kit uses the classic hook format that Codex and Claude Code share. Both relays obey these rules.

- **Relay mode.** If relay mode is on, each prompt that the tester submits goes to the tap, and the model does not receive it. If relay mode is off, the relay does nothing to prompts. If an entry is configured, `start` switches relay mode on and `end` switches it off (section 7). `on` and `off` are aliases of `start` and `end`.
- **Control prompts.** The hook kit does not relay the exact prompts `verbatim-relay start`, `verbatim-relay end` and `verbatim-relay status`. It runs the command and blocks the prompt. The plugin uses its `/verbatim-relay` command.
- **Fail closed.** If relay mode is on and the relay cannot send the message, it still stops the prompt from reaching the model. It shows the error to the tester and writes the error as `shown` with `ok: false`.
- **Display.** The plugin shows the reply as a transcript row that the model does not receive. The hook kit writes the relay record, and `verbatim-relay view` prints each turn from it.
- **Deny.** The relay denies a model tool call if its input contains the host and port of the tap or the agent. File tools (read, write, edit, search) are not denied, because a file that names an address does not call it. Every other tool is denied, including tools that the relay does not know. The deny is best effort. The audit finds each message that goes through the tap. A call to the agent around the tap is in neither record.
- **Test files.** During a test, the relay denies a model tool call that writes into `.verbatim-relay/`, and each other tool call except file reads whose input names `.verbatim-relay`.
- **History.** For the `openai` adapter, the relay sends the turns of the current session that have `ok: true`, then the new message. In a test, the relay sends the turns of the test that have `ok: true` as `history`.

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

The Python helper `verbatim_relay.agent.serve(reply)` speaks this contract for a function `reply(message, history) -> str`. It writes its contract lines to the original stdout, and it sends all other output of the process to stderr.

## 7. Tests

A test runs the entry from `start` to `end`. A new conversation is a new test: each test starts a new entry process with a new test id.

### 7.1 Configuration

`.verbatim-relay/config.json` holds the test configuration:

| Key | Type | Meaning |
|---|---|---|
| `entry` | list of strings | The entry command, as an argument vector. It runs in the project root. |
| `models` | list of strings | The harnesses that the app uses for its model sessions: `claude-code`, `codex`, both or none. |

`verbatim-relay check` runs a short test with one message. It passes if the entry sends a reply, and if the tap identifies at least one model session and finds its session file for each harness in `models`.

### 7.2 Start and end

`start` creates the test folder and starts the bridge, a background process that runs the tap in stdio mode. The bridge writes `.verbatim-relay/current.json` with the test id, the test folder, the tap URL and its own pid. Then `start` switches relay mode on. With an entry, relay mode is the file `.verbatim-relay/mode` for both relays, so it survives a restart of the harness or a reload of the plugin. If `current.json` names a process that does not run, `start` removes the file.

`end` switches relay mode off and stops the bridge. The bridge then:

1. Closes the entry's stdin and waits 5 seconds. Then it stops the process group, first with SIGTERM and after 5 more seconds with SIGKILL.
2. Identifies the Codex sessions (section 7.3).
3. Copies the session file of each identified model session into `sessions/` in the test folder.
4. Writes the end time and the tester's harness sessions into the manifest, and removes `current.json`.

The test folder:

```text
.verbatim-relay/tests/<test-id>/
  manifest.json  relay.jsonl  tap.jsonl  app.log  bridge.log
  sessions/claude-code/<session>.jsonl
  sessions/codex/<rollout file>
```

`manifest.json` holds the test id, the project root, the entry, the models, the start and end times, the versions of verbatim-relay, Claude Code and Codex, the SHA-256 of each configuration file in `.verbatim-relay/`, and the tester's harness session ids.

### 7.3 Model sessions

The harness binary writes each model session of the app to a session file. The tap identifies these sessions. It does not change them.

- **Claude Code.** During the test, the tap reads `~/.claude/sessions/<pid>.json` (under `CLAUDE_CONFIG_DIR` if it is set) twice each second. If the pid is the entry or one of its descendants, the tap writes a `model_session` row with `inferred: false`. The session file is `~/.claude/projects/<folder>/<session>.jsonl`.
- **Codex.** At the end, the tap reads the first line of each rollout file in `~/.codex/sessions/` (under `CODEX_HOME` if it is set) that changed during the test. If its `cwd` is the project root or a folder in it, and its id is not a session of the tester, the tap writes a `model_session` row with `inferred: true`.

The harness binary writes the session files, and their format can change between harness versions. The record is independent of the app, but not of the harness.

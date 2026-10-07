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

Each string in a row, as a field name or as a value, holds only Unicode scalar values. JSON can escape a lone UTF-16 surrogate, for example `"\ud83d"`, but UTF-8 cannot encode it. A row with a lone surrogate is not valid.

### 2.1 Tap record

`exchange`: one request that the adapter parsed, and its response.

| Field | Type | Meaning |
|---|---|---|
| `input` | string | The message that the agent received, as the adapter extracts it. |
| `status` | integer or null | The HTTP status of the agent's response. `null` if the agent did not respond, or if its reply or its error has a lone surrogate (section 4). |
| `reply` | string or null | The reply that the agent sent, as the adapter extracts it. It is `null` if, and only if, the status is not 2xx or is `null`. |
| `error` | string | Optional. Why `reply` is `null`. |
| `started` | number | Optional, 0.2. The Unix time when the tap sent the request to the agent. `ts` is the time when the tap wrote the row. |

In stdio mode, the tap writes these `status` values:

| Agent output | `status` |
|---|---|
| A `reply` line | 200 |
| An `error` line | 500 |
| No line: the agent exited, or the tap stopped it after a timeout | `null` |
| A `reply` or an `error` line with a lone surrogate | `null` |

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
- `record_invalid`: a line is not a JSON object, has a wrong `v` or an unknown `type`, has a missing or wrongly typed field, has a hash that does not match its text, or has a lone surrogate (section 2).
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
- If the message that the adapter extracts has a lone surrogate (section 2), the tap writes an `unparsed` row. It still forwards the request without change.
- If the reply of a 2xx response has a lone surrogate, the tap returns status 502 and not the agent's response. It writes an `exchange` row with `status: null`, `reply: null` and an `error` that names the lone surrogate.
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
- If the `message` of an input has a lone surrogate (section 2), the tap returns status 400, writes an `unparsed` row and does not send the body.
- If the `reply` or the `error` of an output has a lone surrogate, the tap returns status 502. It writes an `exchange` row with `status: null`, `reply: null` and an `error` that names the lone surrogate.
- If the agent sends no line in 240 seconds, the tap stops the agent's process group. It returns status 504 and writes an `exchange` row with `status: null`.
- If the agent exits, the tap returns status 502 and writes an `exchange` row with `status: null` and the exit code in `error`.
- The tap does not restart the agent. After a crash or a timeout, it answers each later request with the same error. The error body includes the last 20 lines of `app.log`.
- Before each request, the tap reads each line that waits on stdout. Each such line becomes an `unparsed` row with `method: STDIO`.

## 5. Relays

A relay is the Claude Code plugin or the hook kit. The hook kit uses the classic hook format that Codex and Claude Code share. Both relays obey these rules.

- **Relay mode.** If relay mode is on, each prompt that the tester submits goes to the tap, and the model does not receive it. If relay mode is off, the relay does nothing to prompts. If an entry is configured, `start` switches relay mode on and `end` switches it off (section 7). `on` and `off` are aliases of `start` and `end`.
- **Control prompts.** With an entry, a relay never relays the exact prompts `verbatim-relay start`, `verbatim-relay end` and `verbatim-relay status`, also in relay mode. It runs the command and blocks the prompt. There is one exception: if `verbatim-relay end` leaves a test to evaluate (section 9), the relay lets the prompt go to the model, with the evaluation prompt added as context. The plugin also has the `/verbatim-relay` command, which never starts an evaluation.
- **Fail closed.** If relay mode is on and the relay cannot send the message, it still stops the prompt from reaching the model. It shows the error to the tester and writes the error as `shown` with `ok: false`.
- **Display.** The plugin shows the reply as a transcript row that the model does not receive. The hook kit writes the relay record, and `verbatim-relay view` prints each turn from it.
- **Transcript.** `verbatim-relay transcript` prints the turns of the relay record for the model. Its first line gives the scope and the number of turns. Its second line is this legend: "Legend: ok (an agent block): the agent answered and the relay showed its reply. It does not judge the reply. Not ok (a relay error block): the relay got no reply and shows its own error text." Each turn has a tester block with `said`. Then it has an agent block with `shown`, or a relay error block with `shown` if `ok` is `false`. The turns show no hashes and no session ids. With an entry, the scope is each session of the latest test, or of `--test <test-id>`. With no entry, the scope is the session of the last turn, or `--session <id>`. The plugin's `transcript` tool runs this command and returns its output with no change, so both relays give the model the same text. With `trace: true`, the tool runs `verbatim-relay transcript --trace` (section 9.2).
- **Deny.** The relay denies a model tool call if its input contains the host and port of the tap or the agent, as `<host>:<port>` or as the shell socket path `/dev/tcp/<host>/<port>` or `/dev/udp/<host>/<port>`. A port can have leading zeros, and a port followed by more digits does not match. File tools (read, write, edit, search) are not denied, because a file that names an address does not call it. Every other tool is denied, including tools that the relay does not know. The deny is best effort. The audit finds each message that goes through the tap. A call to the agent around the tap is in neither record.
- **Test files.** During a test, the relay denies a model tool call that writes into `.verbatim-relay/`, and each other tool call except file reads whose input names `.verbatim-relay`. When no test runs, the relay denies:
  - a write tool call (a file write or edit, or a patch) that names a file in `.verbatim-relay/tests/<test-id>/` other than `report.md`;
  - each other tool call, except file tools, whose input names `.verbatim-relay` and that does not pass the read check.

  The relay writes the `blocked_call` row of a deny after a test to `denied.jsonl` in the latest test folder, so that the sealed `relay.jsonl` does not change (section 7.4).
- **Entry.** During a test, the relay denies a model tool call, except file tools, that names the entry and does not pass the read check. The names of the entry are the base name of each entry argument with the file type `.py`, `.js`, `.mjs`, `.cjs`, `.ts`, `.sh` or `.rb`, and the argument after `-m`. The relay looks for each name in the input, and in each word of a shell command after it removes the quotes and escapes. A word with `*`, `?` or `[` matches a name as a glob. An entry with no such argument, for example `npm run agent`, has no names.
- **Read check.** A tool call passes the read check only if it is a shell tool call (`Bash`, `shell`, `local_shell` or `exec_command`) and its command obeys these rules. Each other tool call fails, so the deny fails closed.
  - The relay removes the body of each here-document, then splits the command at `;`, `&`, `|` and new lines.
  - Each part starts with a read program, or has only variable assignments. An assignment to `PATH`, `IFS`, `CDPATH`, `ENV`, `BASH_ENV`, `SHELLOPTS`, `BASHOPTS`, `PS4`, `PROMPT_COMMAND`, or a variable that starts with `LD_` or `DYLD_`, fails. The read programs are `cat`, `head`, `tail`, `grep`, `egrep`, `fgrep`, `rg`, `jq`, `wc`, `ls`, `nl`, `cut`, `sort`, `diff`, `cmp`, `stat`, `sha256sum`, `shasum`, `echo`, `printf`, `pwd`, `cd`, `sed`, `find` or `verbatim-relay`.
  - `sed` needs `-n`, and each of its scripts, without its `/regex/` addresses, has only line addresses and the commands `p`, `P`, `=`, `q`, `Q`, `d` and `n`. An option that the check does not know fails, for example `-i` or `-f`. `sort` has no `-o`. `rg` has no `--pre`. `find` has no `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`, `-fls`, `-fprint`, `-fprint0` or `-fprintf`. `verbatim-relay` runs `transcript`, `audit`, `status` or `view`.
  - Each output redirect writes `/dev/null` or a file with the name `report.md`, or it copies a file descriptor.
  - The command has no `(`, `)`, `$(` or backquote, and each quote ends.
- The deny of test files and of the entry is best effort, like the deny of the tap. A model can change a file or run the app with a command that does not name it.
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

An output line is not valid in these cases. The tap returns status 502 for it and writes an `unparsed` row (section 4.2).

- The line has both `reply` and `error`, also if one of them is `null`.
- The line has neither `reply` nor `error`, or the field is not a string.
- The line contains `NaN`, `Infinity` or `-Infinity`. These are not JSON values. This rule applies to an input line too.

The tap, the plugin and the hook kit read an output line with these same rules.

The Python helper `verbatim_relay.agent.serve(reply)` speaks this contract for a function `reply(message, history) -> str`. It writes its contract lines to the original stdout, and it sends all other output of the process to stderr.

## 7. Tests

A test runs the entry from `start` to `end`. A new conversation is a new test: each test starts a new entry process with a new test id.

### 7.1 Configuration

`.verbatim-relay/config.json` holds the test configuration:

| Key | Type | Meaning |
|---|---|---|
| `entry` | list of strings | The entry command, as an argument vector. It runs in the project root. |
| `models` | list of strings | The harnesses that the app uses for its model sessions: `claude-code`, `codex`, both or none. |
| `evaluate` | boolean | Optional. `false` stops the evaluation at the end of a test (section 9). The default is `true`. |
| `otel` | boolean | Optional. `false` stops the OTLP receiver of a test (section 7.5). The default is `true`. |
| `backends` | list of objects | Optional. The backends of the app, each with the strings `name`, `env` and `url` (section 7.6). Each `name` and each `env` is used only once. |
| `model_api` | boolean, list or object | Optional. The model APIs to record (section 7.7): `true` for all, `false` for none, a list of `anthropic` and `openai`, or an object from these names to the upstream URL of the API or `null`. The default is `true`. A backend must not use the variable of a recorded model API. |

`verbatim-relay check` runs a short test with one message. It passes if the entry sends a reply, and if the tap identifies at least one model session and finds its session file for each harness in `models`.

### 7.2 Start and end

`start` creates the test folder and starts the bridge, a background process that runs the tap in stdio mode. The bridge writes `.verbatim-relay/current.json` with the test id, the test folder, the tap URL, its own pid and the string `pid_start`. Then `start` switches relay mode on. With an entry, relay mode is the file `.verbatim-relay/mode` for both relays, so it survives a restart of the harness or a reload of the plugin.

`pid_start` is the start time of the bridge process. The OS can give the pid of a stopped process to a new process, so the pid and `pid_start` together identify the bridge. On Linux, `pid_start` is `proc:` and field 22 of `/proc/<pid>/stat`. On other systems, it is `ps:` and the output of `ps -o lstart= -p <pid>` with `TZ=UTC0` and `LC_ALL=C`, with each run of spaces as one space. A reader compares the value only for equality. If the bridge cannot read its start time, it does not start.

If no process with the pid runs, or if the start time of that process is not `pid_start`, the test does not run. Then `start`, `end` and `status` remove `current.json`, and `end` sends no signal to the process.

`end` switches relay mode off and stops the bridge. If a harness session sends the prompt that ends the test, `end` writes its id to `.verbatim-relay/ending.json`. The bridge adds that id to the tester's sessions, so it never takes the session that ends the test, and then evaluates it, as a session of the app. The bridge then:

1. Closes the entry's stdin and waits 5 seconds. Then it stops the process group, first with SIGTERM and after 5 more seconds with SIGKILL. Then it stops the OTLP receiver (section 7.5), after no request came for 0.5 seconds or after 2 seconds, the backend proxies (section 7.6) and the model API proxies (section 7.7).
2. Identifies the Codex sessions (section 7.3).
3. Copies the session file of each identified model session into `sessions/` in the test folder.
4. Writes the end time and the tester's harness sessions into the manifest.
5. Builds the trace (section 8): `trace.jsonl` and `findings.json`. If the trace fails, the bridge writes the error to `bridge.log`, and the test still ends.
6. Writes `audit.json`: the audit of `tap.jsonl` against `relay.jsonl` (section 3), in the form of `verbatim-relay audit --json`. If the audit fails, the bridge writes the error to `bridge.log`.
7. Writes the seal (section 7.4). If the seal fails, the bridge writes the error to `bridge.log`.
8. Removes `current.json`.

The test folder:

```text
.verbatim-relay/tests/<test-id>/
  manifest.json  relay.jsonl  tap.jsonl  app.log  bridge.log
  otel.jsonl  backend.jsonl  model_api.jsonl  trace.jsonl  findings.json  audit.json  seal.json  report.md  denied.jsonl
  sessions/claude-code/<session>.jsonl
  sessions/codex/<rollout file>
```

`manifest.json` holds the test id, the project root, the entry, the models, the start and end times, the versions of verbatim-relay, Claude Code and Codex, the SHA-256 of each configuration file in `.verbatim-relay/`, and the tester's harness session ids.

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
- The bridge also writes a copy, with the same fields and `copy: true`, to `~/.verbatim-relay/seals/<test-id>.json` (under `VERBATIM_RELAY_HOME` if it is set). If it cannot write the copy, for example in a sandbox, `seal.json` has `copy: false`.

`verbatim-relay verify [TEST] [--json]` compares the folder with the seal, and the seal with the copy. If `seal.json` does not exist, the copy is the seal. The result:

| Field | Meaning |
|---|---|
| `sealed` | `seal.json` exists and is valid. |
| `changed` | The sealed files with a different SHA-256. |
| `missing` | The sealed files that do not exist. |
| `added` | The files that are not in the seal and not in the list of files that change after the end. |
| `copy` | `same` or `different`: a copy exists, and it has, or does not have, the same `v`, `test`, `sealed` and `files`. `verify` always compares an existing copy, also when `seal.json` has `copy: false`. `missing`: no copy exists, and `seal.json` has `copy: true` or does not exist. `none`: no copy exists, and `seal.json` has `copy: false`, or no seal exists. |
| `intact` | `sealed` is true, the 3 lists are empty, and `copy` is `same` or `none`. |

`verify` exits with 0 if `intact` is true, and with 2 if it is false. `verbatim-relay transcript --trace` shows the result in its first line.

`verbatim-relay trace` rebuilds `trace.jsonl` and `findings.json`. If a seal or a copy exists, it rebuilds them only if each other sealed file agrees with the seal, `seal.json` exists, and the copy is not `different` or `missing`. Then it writes the new SHA-256 of the 2 files to the seal and to the copy.

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

The receiver writes `otel.jsonl` in the test folder: one JSON object on each line, in the order of the requests.

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
| `method`, `path`, `query` | The request line from the app. `query` is `null` if the path has no `?`. |
| `request_headers`, `response_headers` | The headers as a list of `[name, value]`, in their order. `response_headers` is `null` if the backend did not answer. |
| `request_body`, `response_body` | An object: `size`, `sha256` (of the bytes), `cut`, and `text` (UTF-8) or `base64`. For a `gzip` or `deflate` body, `text` is the decoded body, and `decoded` names the encoding. If the body is longer than 1 MiB, `text` or `base64` holds the first 1 MiB, and `cut` is `true`. `size` and `sha256` are always of all the bytes that went to the app or the backend. `response_body` is `null` if the backend did not answer. |
| `status` | The status of the backend, or `null`. |
| `error` | `the backend did not answer: <reason>`, `the test ended before the backend answered`, or `null`. |

Before it writes a row, the proxy replaces the value of each secret header with `<removed>`: `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, and each header whose name contains `key`, `token` or `secret`. The secret headers still go to the backend and to the app. The proxy does not change the bodies in the record.

### 7.7 Model API proxies

An app can call a model API directly with an SDK, with no harness session. During a test, the bridge runs one proxy for each API in `model_api`, on `127.0.0.1` at a free port, before it starts the entry:

| API | Variable | URL if the variable has no value |
|---|---|---|
| `anthropic` | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` |
| `openai` | `OPENAI_BASE_URL` | `https://api.openai.com/v1` |

The proxy forwards to the URL that `model_api` gives for the API, else to the value that the bridge has in the variable, else to the URL of the table. A URL in `model_api` is necessary if the tester's harness also reads the variable, for example Codex and `OPENAI_BASE_URL`. It gives the entry the URL of the proxy in the variable. A value that is not an `http` or `https` URL stops the start of the test. An empty URL in `model_api` also stops it: the proxy does not then use the variable.

- The proxy forwards each request as a backend proxy does (section 7.6).
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

`result` is an object with `model`, `text` (the text blocks joined), `tool_calls` (a list of `id`, `name` and `input`), `stop_reason`, `usage` and `error` (the `message` of the `error` object of the API, or `null`). The proxy reads it from the decoded response body, as JSON or from the `data` lines of the SSE events:

- `anthropic`, path that ends with `/v1/messages`: the `content` blocks, `stop_reason` and `usage`. In a stream: `message_start`, `content_block_start`, `content_block_delta` (`text_delta` and `input_json_delta`), `message_delta` and `error`.
- `openai`, path that ends with `/chat/completions`: `choices[0].message` (`content` and `tool_calls`), `finish_reason` and `usage`. In a stream: the `delta` of choice 0 of each chunk. The `arguments` of a tool call are parsed as JSON. If they are not JSON, `input` is the text.
- `openai`, path that ends with `/responses` (also `/v1/responses`): the Responses API. A path after the response id, for example `GET /responses/<id>`, is not a model call. The parser reads the response object:
  - `text` is the `text` of each `output_text` part of each `message` item in `output`, joined.
  - Each `function_call` item in `output` is a tool call. `id` is its `call_id`, because a later request gives the result with this id. `input` is its `arguments`, parsed as for `/chat/completions`.
  - `stop_reason` is the `status` of the response, for example `completed`, `incomplete` or `failed`. `usage` is `usage`. `error` is the `message` of the `error` object.
  - In a stream, the parser keeps the output items by their `output_index`. `response.output_item.added` and `response.output_item.done` set the item. `response.output_text.delta` adds its `delta` to the text of the part at `content_index`. `response.function_call_arguments.delta` adds its `delta` to the `arguments` of the item. Thus a stream that stops before its end keeps the text and the arguments that came. The parser reads `model`, `status`, `usage` and `error` from the `response` object of `response.created`, `response.in_progress`, `response.completed`, `response.failed` and `response.incomplete`. An `error` event gives `error` from its `message`. The parser does not read the other events.
  - This parser follows the OpenAI API reference of 2026-10-07, the date when it was read: [create a response](https://developers.openai.com/api/reference/resources/responses/methods/create) and [streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events).

To read a new model call, the proxy adds one row to its table of model calls (the API, the end of the path and the format) and one parser for the format. The trace selects its reader of the request by the same format (section 8.4).

## 8. Trace

The trace is one record of the model items of the app in a test. It ties each item to a turn. `verbatim-relay trace [TEST]` builds it again from the files in the test folder.

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

The trace reads `tap.jsonl`, `sessions/`, `otel.jsonl`, `backend.jsonl` and `model_api.jsonl`. It does not read the app's state.

### 8.2 Trace record

`trace.jsonl` is a UTF-8 JSONL file, sorted by `ts`. Each line is a `model_item` row (0.3). Each row has all of these fields:

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
| `input` | any | For a tool call: its input object. For a command: its argv. For a span or a log: its attributes. For an `http` item: an object with `query`, `headers` (the request headers of the row) and `body` (the request body, as for `output`). For a `model_api` assistant message: an object with `path`, and `model`, `stop_reason` and `usage` of the result. |
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

Each reader reads the copied session file of one model session in the manifest. It never fails on a line. It counts each line that it does not keep, by type, in `findings.json`.

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
- a `message` item with the role `assistant`. `output` is the `text` of the result, or `null` if it is empty. `ts` is the `ts` of the row;
- a `tool_call` item for each tool call of the result. `ts` is the `ts` of the row. The output is the first tool result with the same id in the request of a later call of the same format (`messages`, `chat` or `responses`), because a tool call id is unique only in one format: a `tool_result` block (`anthropic`, an `error` if `is_error` is `true`), a message with the role `tool` (`openai`, `/chat/completions`), or a `function_call_output` item of `input` with the same `call_id` (`openai`, `/responses`). The text of a `function_call_output` is its `output` string, or its `input_text` parts joined, with each other part as JSON. With no such result, `output` and `error` are `null`.

### 8.5 Harness tools

These tools come from the harness, not from the app: `ToolSearch` in Claude Code. The trace keeps their items and marks them `harness_internal: true`.

### 8.6 Findings

`findings.json` holds the test id, the number of turns and items, one entry for each model session (its version, its item count and its counts of lines not kept), `otel`, `backend` and `model_api` (the file, its row count, its item count and its counts of rows not kept, or `null` if the test has no such file; `model_api` also has `harness_calls`, the count of harness calls by harness, and `other_calls`), a count for each check, and the findings. The findings do not change the exit code of the audit. The audit measures the words only.

| Check | Finding |
|---|---|
| `agent_error` | An exchange with a `status` that is not 200. |
| `tool_error` | A tool call with an `error`. |
| `command_failed` | A command with an exit code that is not 0, or with an `error`. |
| `span_error` | A span with an `error`. |
| `backend_error` | An `http` item with an `error`, or with a status of 500 or more. |
| `model_api_error` | A `model_api` assistant message with an `error`, or with a status of 400 or more. |
| `turn_without_model` | A turn with no `message`, `tool_call` or `command` item. This check runs only if a session reader kept at least 1 item. |
| `item_between_turns` | An item with `turn: null` and a `ts` at or after the start of turn 1. An item before turn 1, for example a model call when the app starts, is not a finding. |
| `otel_tool_not_in_session` | A harness `tool_result` log with no tool call of its tool in the session items of the same harness and turn. The tool is the `mcp_tool_name` of `tool_parameters`, or `tool_name` (Claude Code), or `tool_name` (Codex). If the event and the tool call both have an input object, the inputs must be equal. For a Codex `exec_command`, `shell` or `local_shell`, any `command` item matches. |
| `server_not_from_app` | An MCP server in a Claude Code session file (section 8.4) that the MCP configuration of the app cannot give: a claude.ai connector of the account (a name that starts with `claude.ai ` or `claude_ai_`), or a server of a plugin (a name that starts with `plugin:` or `plugin_`). An app that loads a plugin itself also gets this finding for the servers of that plugin. The check does not find a server from a settings file or from `.mcp.json`, because its name does not show where it comes from. The finding has `harness`, `session` and `source` (the file and the first line that names the server). |
| `session_inferred` | A model session with `inferred: true`. |
| `version_untested` | A session file from a harness version that `proofs/trace/` does not cover. The tested versions are Claude Code 2.1.286 and 2.1.292, and codex-cli 0.160.0. If a reader finds no version in the file, the version is `unknown`. If the file is not in the test folder, the version is `null`, and this check does not run. |

Each finding has `check`, `turn` and `detail`. A finding about an item also has `harness`, `session` and `source`. The findings are sorted by check, in the order of the table, then by turn, and then in the order of the items. A finding with no turn comes after the findings with a turn.

## 9. Evaluation

At the end of a test, the harness model evaluates the app. It writes `report.md` in the test folder.

### 9.1 Start

A test needs an evaluation if all of these are true:

- `evaluate` in the configuration is not `false`;
- no test runs;
- the latest test (the one with the greatest `started` in its manifest) has an `ended` time;
- its folder has no `report.md`.

The prompt `verbatim-relay end` ends the running test, if one runs. Then, if a test needs an evaluation, the relay lets the prompt go to the model with this context: the end text and the evaluation prompt for that test. So the prompt also starts the evaluation of a test that ended in another way, for example with `verbatim-relay end` in a shell. Otherwise, the relay blocks the prompt (section 5).

`verbatim-relay end --evaluation` ends the test and prints one JSON object: `text`, the end text, and `evaluation`, the evaluation prompt or `null`. The plugin uses it.

### 9.2 Evaluation prompt

The evaluation prompt is `src/verbatim_relay/evaluate.md`, with the test id and the test folder filled in. It tells the model to:

1. read the transcript with the trace: `verbatim-relay transcript --trace --test <test-id>`;
2. read `findings.json` and `audit.json`;
3. read the code of the app and its business rules;
4. check the state of the app with read-only commands only;
5. write `report.md`, and no other file.

`verbatim-relay transcript --trace` shows each turn of a test as the app received it and sent it (from `tap.jsonl`). Under each turn, it shows the model items of that turn and the findings of that turn. Each item names its line in `trace.jsonl` as `[trace.jsonl:N]`. A text longer than 2,000 characters shows its start and names its line. Items with `turn: null` come after the last turn.

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

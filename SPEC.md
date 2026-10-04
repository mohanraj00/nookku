# verbatim-relay specification, v0.1 (draft)

This file defines the two records and the audit. The conformance cases in `conformance/` are the executable form of this file. If the code and this file disagree, the code is wrong.

## 1. Parts

- **Tester:** a person who types messages in a coding harness (Claude Code or Codex).
- **Relay:** the harness extension. It sends each tester message to the agent and shows each reply to the tester. The model does not write either direction.
- **Agent:** the chat agent under test.
- **Tap:** a proxy between the relay and the agent. It forwards each request and each response without change.

Two processes write two records. The relay writes the **relay record**: what the tester typed and what the tester saw. The tap writes the **tap record**: what the agent received and what it sent. The audit compares the two records.

## 2. Record format

Each record is a UTF-8 JSONL file. Each line is one JSON object. Each object has `"v": "0.1"` and a `type`. Each text field has a `<field>_sha256` field: the SHA-256 of the UTF-8 bytes of the text, in lower-case hex. If the text is `null`, its hash is `null`. `ts` is a Unix time in seconds.

### 2.1 Tap record

`exchange`: one request that the adapter parsed, and its response.

| Field | Type | Meaning |
|---|---|---|
| `input` | string | The message that the agent received, as the adapter extracts it. |
| `status` | integer or null | The HTTP status of the agent's response. `null` if the agent did not respond. |
| `reply` | string or null | The reply that the agent sent, as the adapter extracts it. It is `null` if, and only if, the status is not 2xx or is `null`. |
| `error` | string | Optional. Why `reply` is `null`. |

`unparsed`: a request or a 2xx response that the tap forwarded but that the adapter cannot parse. Fields: `method`, `path`, `error`. The tap forwards this request without change, but the audit cannot check it.

### 2.2 Relay record

`turn`: one tester message.

| Field | Type | Meaning |
|---|---|---|
| `harness` | string | For example `claude-code` or `codex`. |
| `said` | string | The exact text that the tester submitted. |
| `shown` | string or null | The exact text that the relay showed to the tester. `null` if the relay showed no reply. |

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

### 3.4 Exit codes

| Code | Meaning |
|---|---|
| 0 | The records are valid and have no break. |
| 1 | The records are valid and have one or more breaks. |
| 2 | A record is missing or invalid, or the tap has an unparsed exchange. |

## 4. Tap

- The tap forwards the method, path, query, headers and body without change. It does not forward hop-by-hop headers and `Host`. It replaces `Accept-Encoding` with `identity`, so that the agent sends a body that the adapter can read.
- The tap returns the agent's status, headers and body without change, except hop-by-hop headers and `Content-Length`.
- If the agent does not respond, the tap returns status 502 and writes an `exchange` row with `status: null`.
- The tap writes rows only for `POST` requests that the adapter accepts. It forwards other requests without a row.
- The tap does not support streamed responses in v0.1. If an OpenAI-style request has `"stream": true`, the tap returns status 501 and does not forward it.

### 4.1 Adapters

- **`json`:** the input is at a field path in the request body, and the reply is at a field path in the response body. The defaults are `text` and `reply`. A path uses dots, and a list index is a number, for example `choices.0.message.content`.
- **`openai`:** for a `POST` to a path that ends in `/chat/completions`. The input is the `content` of the last message with role `user`. The content must be a string, or a list with exactly one part of type `text`. The reply is `choices.0.message.content`.

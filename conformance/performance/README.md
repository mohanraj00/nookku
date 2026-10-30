# Performance cases

Each folder is a test folder with the expected `performance.json` (SPEC.md section 8.7) in `expect_performance.json`. I wrote each expected file by hand. `tests/test_performance.py` builds the trace and then `performance.json`, and compares the 2 files. Each manifest has an egress answer, because a test with no egress answer has no known calls.

| Case | It shows |
|---|---|
| `claude_code_usage` | One call for each `message.id`, or for each `requestId` if a line has no id. The input tokens include the cache tokens. A `<synthetic>` message is not a call. A call with no usage makes the token totals `null`. A call after the last turn is in no turn, and `outside_turns` counts it. |
| `model_api_direct` | The direct calls of `model_api.jsonl`: Chat Completions, Messages and Responses usage. A cut result has no usage. |
| `codex_token_count` | One call for each `token_count` event with `last_token_usage`. An event with no `info` is not a call. An event with the same `total_token_usage` as the call before it is a repeat. |
| `codex_no_token_count` | A session file with model items and no call: the calls and the tokens are not known. A 0.1 exchange has no `started`, so its seconds are not known. |
| `partial_usage` | A cache key with `null` is 0. A call with input tokens and no output tokens: the turn has its input tokens, and its output tokens are `null`. |
| `session_id_new_line` | A session id with a new line. `sources` gives the id with the new line as `\u000a`, so the reader accepts the file and the transcript gets no false line. |
| `gateway_calls` | The calls of `gateway.jsonl` (section 8.9). The gateway call that matches the direct call of `model_api.jsonl` is 1 call, not 2. A Messages call with the usage of Messages has the input tokens of the rule of Claude Code. A Messages call that LiteLLM stored with Chat Completions usage has the tokens of Chat Completions. A call after the turn is in `outside_turns`. |
| `missing_session_file` | A model session with no session file: the calls and the tokens are not known. |

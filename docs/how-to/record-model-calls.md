# Record model calls and OpenTelemetry

A test records 2 more sources by default: the direct model calls of your app, and the OpenTelemetry spans and logs of your app. Both go into the trace, each item in its turn.

## Direct model calls

If your app calls the Anthropic or the OpenAI API with an SDK, the bridge records these calls. During a test, it runs a recording proxy for each API, and gives your app the proxy URL in `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL`. The proxy forwards to the value that you had in the variable, else to the public API. It sends each part of a streamed response to your app when the part comes. It writes each call to `model_api.jsonl`, with the text, the tool calls and the stop reason, and without the API key. The trace shows each call in its turn, and the check `model_api_error` finds each call with an error or a status of 400 or more. [SPEC.md section 7.7](../../SPEC.md#77-model-api-proxies) defines the proxy and the API paths that it reads.

1. Check that your SDK reads its URL from `ANTHROPIC_BASE_URL` or `OPENAI_BASE_URL`. If your app gives the SDK a fixed URL, let the entry give the SDK the URL from the variable.
2. Run a test. You need no configuration: `model_api` is `true` by default.
3. Read the calls with `nooku transcript --trace`.

An Agent SDK session in your app also reads `ANTHROPIC_BASE_URL`, so its calls also go through the proxy. The record keeps only the size and the SHA-256 of these calls, because they hold the instructions of Claude Code. The session file already gives their turns.

### Change which APIs the proxy records

| Case | `model_api` in `.nooku/config.json` |
|---|---|
| Record both APIs (the default) | `true` |
| Record no API | `false` |
| Your app uses Codex with a ChatGPT login: `OPENAI_BASE_URL` can send Codex to the public API | `["anthropic"]` or `false` |
| The upstream URL is not in the environment, or the tester's harness reads the same variable | `{"anthropic": null, "openai": "http://127.0.0.1:9002/v1"}` |

In the object form, `null` takes the URL from the variable. An empty URL stops the start of the test.

The proof [proofs/model-api/](../../proofs/model-api/results.json) shows calls with the same bytes at the entry, the toy API and the record. It also shows streams that reached the entry before their end ([method](../../scripts/proof_model_api.py), [summary](../results.md#direct-model-calls)).

## OpenTelemetry

During a test, the bridge runs an OTLP/HTTP receiver and gives your app its address in the standard `OTEL_*` variables. These replace your app's own `OTEL_*` values for the test. If your app uses the OpenTelemetry SDK, its spans and logs go to `otel.jsonl` in the test folder and into the trace. [SPEC.md section 7.5](../../SPEC.md#75-otlp-receiver) lists each variable.

An Agent SDK session also sends its prompts, tool calls and replies, because the bridge sets `CLAUDE_CODE_ENABLE_TELEMETRY=1`. The trace checks each tool call of these events against the session file (the check `otel_tool_not_in_session`). The receiver removes each `user.*`, `organization.*` and e-mail attribute before it writes a row.

Codex does not read the `OTEL_*` variables. [codex.md](codex.md) gives the data.

To stop the receiver, add `"otel": false` to `.nooku/config.json`.

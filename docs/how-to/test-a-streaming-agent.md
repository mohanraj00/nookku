# Test a streaming agent

A streaming agent sends its reply in parts. In a test, the tester sees the complete reply, not each part. The audit compares the complete reply, byte for byte. You can test a streaming agent with an entry or with the HTTP tap.

| Your agent | Use |
|---|---|
| A function, an SDK session or a server that streams in any format | [An entry that joins the stream](#with-an-entry) |
| An HTTP server with an OpenAI-compatible `/chat/completions` endpoint that streams Server-Sent Events | [The HTTP tap with the `openai` adapter](#with-the-http-tap), or an entry |

An entry keeps the test folder, the trace, the seal and the evaluation. The HTTP tap does not. [connect-your-agent.md](connect-your-agent.md#the-entry-and-the-http-tap) compares the two.

## With an entry

The agent contract has one output line for each message ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)). Thus the entry reads the full stream, joins the parts into one reply, and writes one line.

In Python, with `serve()`:

```python
from verbatim_relay.agent import serve

from toy_shop import Shop  # your app

shop = Shop()


def reply(message: str, history: list[tuple[str, str]]) -> str:
    # The app yields the reply in parts. Join them with no separator.
    return "".join(shop.stream(message))


serve(reply)
```

In Node, replace the function `reply` of [examples/toy-shop-node/entry.mjs](../../examples/toy-shop-node/entry.mjs):

```js
async function reply(message, history) {
  // The app yields the reply in parts. Join them with no separator.
  let text = "";
  for await (const part of shop.stream(message)) text += part;
  return text;
}
```

Obey these rules:

- Join the parts with no separator. Do not add, remove or change a character between the parts.
- Return the reply only after the stream ends. If the stream fails, raise an exception in Python or throw an error in Node. The entry then writes an `error` line, and the tester sees the error, not a part of the reply.
- The full reply must come in [240 seconds](../../src/verbatim_relay/stdio.py), the agent timeout of the tap. The 240 seconds is for the full reply, not for each part.
- If the app is an HTTP server that streams, the entry reads the full response of the server, then joins the parts. [connect-your-agent.md](connect-your-agent.md#if-your-app-is-an-http-server) shows an entry that calls a server.

The direct model calls of the app are a different stream. The model API proxy sends each part of a streamed model call to the app when the part comes ([record-model-calls.md](record-model-calls.md)).

## With the HTTP tap

Use the `openai` adapter. The `json` adapter does not read a stream: for a stream with a 2xx status, the tap writes an `unparsed` row ([SPEC.md section 4.1](../../SPEC.md#adapters)).

1. Start the tap with the `openai` adapter:

   ```bash
   verbatim-relay tap --agent http://127.0.0.1:8700/ --record tap.jsonl --adapter openai
   ```

2. Configure the relay. Give the full `/v1/chat/completions` URL of the tap.
   - **Plugin:** set the options `adapter` to `openai` and `tap_url` to `http://127.0.0.1:8800/v1/chat/completions`.
   - **Hook kit:** run `verbatim-relay init claude-code --adapter openai --tap-url http://127.0.0.1:8800/v1/chat/completions`, or `init codex` with the same flags.
3. If the agent streams only when the request has `"stream": true`, set the option `openai_stream` to `true`. For the hook kit, add the flag `--openai-stream` to `init`. Else the relay sends `"stream": false`.
4. Switch relay mode on and off, and audit the two records, as in [http-tap.md](http-tap.md#3-relay-mode-on-and-off).

The tap sends each part to the relay when the part comes. When the stream ends, it writes the joined reply to the tap record. The relay shows the reply when the stream is complete.

A stream fails if it ends with no `[DONE]` event, sends an error, or has a malformed chunk. Then the tap record gets `reply: null` and the reason in `error`. The relay shows the error and records it with `ok: false`. The tester never sees a part of a failed reply ([SPEC.md section 4.1](../../SPEC.md#41-http-mode), [section 5](../../SPEC.md#5-relays)).

If your agent streams in another format, the HTTP tap cannot read the reply. Write an entry that joins the stream.

## Proofs

The proofs P1 to P4 ran with the HTTP tap and a toy agent that streams Chat Completions events: the plugin in Claude Code, and the hook kit in Claude Code and in Codex. In each of the 6 runs, 10 of 10 messages and 10 of 10 replies arrived byte for byte ([table and data](../results.md#1-proofs)). A proof with a streaming entry does not exist yet.

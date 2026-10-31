# Use the HTTP tap

Use this mode if your agent is already an HTTP server and you do not want an [entry](../reference/glossary.md#entry). The [tap](../reference/glossary.md#tap) is in front of the agent and records each exchange. There is no test: no [test folder](../reference/glossary.md#test-folder), no [trace](../reference/glossary.md#trace), no [seal](../reference/glossary.md#seal) and no [evaluation](../reference/glossary.md#evaluation) prompt. For these, use an entry that calls your server ([connect-your-agent.md](connect-your-agent.md#if-your-app-is-an-http-server)).

## 1. Start the agent and the tap

To try it, start the toy shop agent of this repo as an HTTP server:

```bash
python3 examples/toy-shop/http_agent.py
```

In a second terminal, put the tap in front of it:

```bash
nookku tap --agent http://127.0.0.1:8700/ --record tap.jsonl
```

The tap prints:

```text
nookku tap: listening on http://127.0.0.1:8800/ -> http://127.0.0.1:8700/
nookku tap: writing tap.jsonl
```

To check the tap without a [harness](../reference/glossary.md#harness), send one message:

```bash
curl -s -X POST http://127.0.0.1:8800/ -H 'Content-Type: application/json' -d '{"text": "do you ship to delhi?"}'
```

The answer is the agent's answer with no change: `{"reply": "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  "}`. This message is in the [tap record](../reference/glossary.md#tap-record) but not in a [relay record](../reference/glossary.md#relay-record), so an [audit](../reference/glossary.md#audit) of these records shows it as `injected_input`. Use a new record file for the test.

## 2. Install a relay with no entry

- **[Plugin](../reference/glossary.md#plugin):** run `nookku init plugin` with no `--entry`. It writes `.nookku/config.json` and no [project hooks](../reference/glossary.md#project-hooks). Its flags set `tap_url`, `adapter` and the others: `--tap-url`, `--agent-url`, `--adapter` and so on.
- **Project hooks:** run `nookku init claude-code` or `nookku init codex` with no `--entry`. `init` takes the same options as flags: `--tap-url`, `--agent-url`, `--adapter` and so on.

## 3. Relay mode on and off

With no entry, [relay mode](../reference/glossary.md#relay-mode) has no test. Switch it on before your messages and off after them:

| [Relay](../reference/glossary.md#relay) | On | Off |
|---|---|---|
| Plugin | `/nookku on` | `/nookku off` |
| Project hooks | `nookku mode on` | `nookku mode off` |

The relay record is `.nookku/relay.jsonl` by default (the option `record`). After the test, audit the two records:

```bash
nookku audit --tap tap.jsonl --relay .nookku/relay.jsonl
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `tap_url` | `http://127.0.0.1:8800/` | The URL that receives each message. For the `openai` adapter, give the full `/v1/chat/completions` URL. |
| `agent_url` | empty | Your agent's own URL. Model calls to it are denied too. |
| `adapter` | `json` | `json` or `openai` |
| `message_field` | `text` | `json` adapter: the dot path of the message in the request body |
| `reply_field` | `reply` | `json` adapter: the dot path of the reply in the response body |
| `openai_model` | empty | `openai` adapter: the `model` field of each request |
| `openai_stream` | `false` | `openai` adapter: `true` sends `"stream": true` in each request, for an agent that streams only on request |
| `record` | `.nookku/relay.jsonl` | The relay record. The project hooks read a relative path from the project root, and the plugin from the working directory. |

Give the tap the same adapter: `nookku tap --agent URL --record FILE --adapter openai`. [reference/cli.md](../reference/cli.md#nookku-tap) lists each flag of the tap.

## Adapters

- **`json`:** the message is at a field path in the request body, and the reply is at a field path in the response body. A path uses dots, and a list index is a number, for example `choices.0.message.content`.
- **`openai`:** an OpenAI-compatible `/chat/completions` endpoint. The message is the last `user` message, and the relay sends the earlier turns of the session as history.

[SPEC.md section 4.1](../../SPEC.md#adapters) defines both.

## Streamed replies

If your agent streams its reply (SSE, `text/event-stream`), use the `openai` adapter. The relay sends `"stream": false`. If your agent streams only on request, set `openai_stream` to `true` (the `init` flag is `--openai-stream`, with no value, and `--no-openai-stream` sets it back to `false`). Then the relay sends `"stream": true`. If the agent streams, the tap sends each part to the relay when it comes. It records the complete reply when the stream ends. The relay shows the reply when the stream is complete. A stream that ends early, sends an error or has a malformed chunk gives an error, not a part of the reply. [SPEC.md section 4.1](../../SPEC.md#41-http-mode) defines the rules.

## An agent in a cluster

If the agent runs in the same Kubernetes cluster as the harness, give the tap the Service URL of the agent:

```bash
nookku tap --agent http://toy-shop.shop.svc:8080/ --record tap.jsonl
nookku init claude-code --tap-url http://127.0.0.1:8800/ --agent-url http://toy-shop.shop.svc:8080/
```

The tap can run in the harness pod, as above, or in its own pod behind a Service. In a separate tap pod, listen on the pod interface:

```bash
nookku tap --listen 0.0.0.0:8800 --agent http://toy-shop.shop.svc:8080/ --record /work/tap.jsonl
```

In the harness pod, use the Service URL of the tap:

```bash
nookku init claude-code --tap-url http://tap.harness.svc:8800/ --agent-url http://toy-shop.shop.svc:8080/
```

Give the app Service URL as `agent_url`, so the guard denies a direct call from the model to that URL. The guard matches URL text only. NetworkPolicy can also block the direct route to the app.

The [policy proof](../../scripts/proof_cluster_tap.py) uses default-deny **egress** in the harness namespace. A DNS rule lets the pods reach the cluster DNS service. A separate rule lets the tap reach the toy shop pods. The [relay rule](../../proofs/cluster-tap/default-deny/relay-rule.yaml) lets only the harness pods reach the tap pods on its TCP port. Kubernetes selects pods and namespaces, not a Service name. The [deny rules](../../proofs/cluster-tap/default-deny/deny.yaml) give the full selectors. These rules need a NetworkPolicy controller. Kind's default network alone does not enforce them. The proof runs a pinned controller only in its own cluster and records its image in the results.

With no relay rule, the hook blocks the prompt, records a failed turn, and sends no request to the app. The proof adds the rule, checks the exact bytes, then removes it and checks that the hook blocks again. The relay also has no direct route to the app Service or pod IP. The policy has no ingress rule and does not restrict callers of the tap from other namespaces. Set ingress policy for your cluster. These rules do not separate the relay process from another process in the same harness pod.

[scripts/proof_cluster_tap.py](../../scripts/proof_cluster_tap.py) tests this setup in a kind cluster, with no model. [results.md](../results.md#the-http-tap-to-an-agent-at-a-cluster-service-url) gives the result and the limits.

## Security

The tap listens on `127.0.0.1:8800` by default. If you bind it to another address with `--listen`, anyone who can reach that address can talk to your agent through it ([SECURITY.md](../../SECURITY.md)).

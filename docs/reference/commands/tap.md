# `nookku tap`

Release: nookku 0.7.0.

```text
nookku tap (--agent URL | --cmd -- COMMAND...) --record FILE [options]
```

Run the [tap](../glossary.md#tap) proxy in front of the agent ([SPEC.md section 4](../../../SPEC.md#4-tap)). A test starts it for you, so you need this command only for an agent that is an HTTP server ([how-to/http-tap.md](../../how-to/http-tap.md)).

| Flag | Default | Meaning |
|---|---|---|
| `--agent URL` | none | HTTP mode: the agent's base URL (http, https, ws or wss). |
| `--cmd` | off | Stdio mode: start the command after `--` as the agent. |
| `--record FILE` | required | The [tap record](../glossary.md#tap-record) (JSONL). The tap adds rows to it. |
| `--listen HOST:PORT` | `127.0.0.1:8800` | The address of the tap. |
| `--timeout SECONDS` | [240](../../../src/nookku/stdio.py) | The seconds to wait for the agent. |
| `--log PATH` | `app.log` next to the record | Stdio mode: the file for the agent's stderr. |
| `--adapter NAME` | `json` | `json` or `openai` ([SPEC.md section 4.1](../../../SPEC.md#adapters)). |
| `--message-field PATH` | `text` | `json` adapter: the field path of the message in the request. |
| `--reply-field PATH` | `reply` | `json` adapter: the field path of the reply in the response. |

Give exactly one of `--agent` and `--cmd`.

In stdio mode, the tap accepts a `POST` only with its token in the header `X-Nookku-Token` ([SPEC.md section 4.2](../../../SPEC.md#42-stdio-mode)). The tap takes the token from the variable `NOOKKU_TAP_TOKEN`. The value must have 43 characters or more, else the tap does not start. Use a random value, for example from `python -c "import secrets; print(secrets.token_urlsafe(32))"`. If the variable has no value, the tap makes a random token and writes it to stderr at start. In HTTP mode, the tap checks no token ([SPEC.md section 4.1](../../../SPEC.md#41-http-mode)).

| Exit code | Meaning |
|---|---|
| 0 | The tap stopped, for example after Ctrl-C. |
| 2 | The flags are wrong, for example both `--agent` and `--cmd`. |

## Example

The toy shop agent `examples/toy-shop/http_agent.py` listens on port 8081. The tap goes in front of it, and `curl` sends one message through the tap:

```bash
nookku tap --agent http://127.0.0.1:8081 --record tap-demo.jsonl
```

```text
nookku tap: listening on http://127.0.0.1:8800/ -> http://127.0.0.1:8081/
nookku tap: writing tap-demo.jsonl
```

```bash
curl -s -X POST http://127.0.0.1:8800/ -d '{"text": "Do you ship to Pune?"}'
```

```text
{"reply": "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  "}
```

The tap wrote one row to `tap-demo.jsonl`. Stop the tap with Ctrl-C.

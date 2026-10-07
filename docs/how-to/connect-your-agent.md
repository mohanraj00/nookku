# Connect your own agent

A test runs your app through an entry: a thin wrapper that starts the app and speaks the agent contract. The entry and its configuration are in `.verbatim-relay/`. Your app's code does not change.

This is the plumbing that a test needs. You write it once, when you start to test the app. You change it when the start or the wiring of the app changes, for example a new service or a new start command.

## Let the harness model write the entry

1. Install the package: `uv tool install verbatim-relay`.
2. Start Claude Code or Codex in your project. Ask the model: "Run `verbatim-relay setup` and connect a test to this app." With the Claude Code plugin, the `setup` skill does the same.
3. The model reads the guide that `verbatim-relay setup` prints ([setup.md](../../src/verbatim_relay/setup.md)). It reads the app, writes `.verbatim-relay/entry.<ext>` and `.verbatim-relay/config.json`, and runs `verbatim-relay check`.
4. Review the entry. It is in the message path, and the audit cannot see a change that the entry makes.

## Write the entry yourself

The entry reads one JSON line on stdin for each message, and writes one JSON line on stdout for each reply ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)).

In:

```json
{"v": 1, "id": "7f3a", "session": "20261007-133823-0b63", "message": "do you ship to delhi?", "history": []}
```

Out:

```json
{"v": 1, "id": "7f3a", "reply": "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  "}
```

If the app has no reply, write `{"v": 1, "id": "7f3a", "error": "the order service is down"}`.

Obey these rules:

- Send `message` to the app with no change. Return the app's reply with no change. Do not trim, format or translate either text.
- Write only contract lines to stdout. Write logs and all other output to stderr. The tap writes stderr to `app.log` in the test folder.
- Use one app conversation for the whole test. `session` is the test id. Use `history` only if the app needs the earlier turns from outside.
- Read and write UTF-8. Split input lines only on `\n`.
- If the app fails on one message, write an `error` line and continue.
- Exit when stdin closes.

### In Python, use `serve()`

`verbatim_relay.agent.serve(reply)` speaks the contract for one function. It writes the contract lines to the original stdout. It sends all other output of the process to stderr, also the output of child processes ([agent.py](../../src/verbatim_relay/agent.py)).

```python
from verbatim_relay.agent import serve

from toy_shop import Shop  # your app

shop = Shop()


def reply(message: str, history: list[tuple[str, str]]) -> str:
    return shop.answer(message)


serve(reply)
```

If `reply` raises an exception, `serve()` writes an `error` line with the exception, and the test continues.

`serve()` needs `verbatim_relay` in the Python environment of your app. `uv tool install` puts it in its own environment, so also add version 0.2.0 or later to your app's environment, for example with `uv add --dev "verbatim-relay>=0.2"`. If PyPI does not have 0.2.0 yet, add it from the repo: `uv add --dev "verbatim-relay @ git+https://github.com/mohanraj00/verbatim-relay"`. Then use your app's interpreter in the entry command, for example `[".venv/bin/python", ".verbatim-relay/entry.py"]`.

### In another language

Write the same loop in the language of your app. [examples/toy-shop/agent.py](../../examples/toy-shop/agent.py) is a loop with no helper, in the Python standard library only. [examples/toy-shop-full/entry.py](../../examples/toy-shop-full/entry.py) is an entry for an async app with an Agent SDK session.

## Write the configuration

`.verbatim-relay/config.json` holds the test keys:

```json
{"entry": ["python3", ".verbatim-relay/entry.py"], "models": ["claude-code"]}
```

- `entry` is the command as a list of arguments. It runs in the project root.
- `models` lists the harnesses that your app uses for its own model sessions: `claude-code`, `codex`, both or none. `verbatim-relay check` fails if it does not find a session for each one.

[reference/config.md](../reference/config.md) lists each key. For the hook kit, `verbatim-relay init <harness> --entry "<command>"` writes this file and the hooks in one step.

## Check the connection

```bash
verbatim-relay check
```

It starts the entry, sends one message, and ends the test. For the toy shop, the output is:

```text
Test 20261007-133809-bbb2: /path/to/toy-shop/.verbatim-relay/tests/20261007-133809-bbb2
Reply: Which item is this about: the mug or the teapot?
PASS
```

It exits with 0 if the entry sent a reply and the test found a model session for each harness in `models`. Else it exits with 1. If it fails, read `app.log` and `bridge.log` in the test folder that it names. [troubleshooting.md](../troubleshooting.md) lists the errors.

## When the app changes

- **A new start command or interpreter:** change `entry`.
- **A new model harness in the app:** change `models`.
- **A new HTTP service:** add it to `backends` ([add-a-backend.md](add-a-backend.md)).
- **A new direct model call:** check that the SDK reads `ANTHROPIC_BASE_URL` or `OPENAI_BASE_URL` ([record-model-calls.md](record-model-calls.md)).

Then run `verbatim-relay check` again. The manifest of each test keeps the SHA-256 of each file in `.verbatim-relay/`, so a test shows which entry it ran.

## Next

- An Agent SDK session in your app: [isolate-agent-sdk.md](isolate-agent-sdk.md).
- Run the test: [claude-code.md](claude-code.md) or [codex.md](codex.md).

# Connect your own agent

A test runs your app through an entry: a thin wrapper that starts the app and speaks the agent contract. The entry and its configuration are in `.verbatim-relay/`. Your app's code does not change.

This is the plumbing that a test needs. You write it once, when you start to test the app. You change it when the start or the wiring of the app changes, for example a new service or a new start command.

## Let the harness model write the entry

1. Install the package: `uv tool install verbatim-relay`.
2. Start Claude Code or Codex in your project. Ask the model: "Run `verbatim-relay setup` and connect a test to this app." With the Claude Code plugin, the `setup` skill does the same.
3. The model reads the guide that `verbatim-relay setup` prints ([setup.md](../../src/verbatim_relay/setup.md)). It reads the app, writes `.verbatim-relay/entry.<ext>` and `.verbatim-relay/config.json`, and runs `verbatim-relay check`.
4. Review the entry. It is in the message path, and the audit cannot see a change that the entry makes.
5. Make sure that the entry runs your real app ([Make sure that check runs your real app](#make-sure-that-check-runs-your-real-app)). A PASS of `check` does not prove it.

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
Audit: exit 0
PASS
```

PASS proves the connection. It does not prove that your app gives correct replies. `check` does these steps, and PASS means that each step passed ([bridge.py](../../src/verbatim_relay/bridge.py)):

1. It starts a [test](../reference/glossary.md#test).
2. It sends one fixed message to the entry: `Hello from verbatim-relay check. What can you help me with?`
3. The entry must send a reply line, not an `error` line.
4. The [audit](../reference/glossary.md#audit) of the test must be clean. It must exit with 0.
5. For each [harness](../reference/glossary.md#harness) in `models`, the test must find a model session of the app and its session file.

`check` does not do these things:

- It does not judge the reply. Any reply line passes, also a fallback text of your app. The toy shop reply above is the `FALLBACK` text of [agent.py](../../examples/toy-shop/agent.py), because the toy shop has no rule for the check message.
- It sends only one message. It does not check a conversation with more turns.
- It does not use the records of the backends, the model API calls or the OpenTelemetry spans to decide PASS. The end of the check test puts them into the trace, but `check` does not examine them.

If all steps pass, `check` exits with 0. Else it exits with 1. If it fails, read `app.log` and `bridge.log` in the [test folder](../reference/glossary.md#test-folder) that it names. [troubleshooting.md](../troubleshooting.md) lists the errors.

## Make sure that check runs your real app

A PASS with wrong replies is possible. In a first test on a real app, each reply was the fallback text of the app, and `check` showed PASS. Before your first test, do these 4 steps.

### 1. Compare the reply

Compare the `Reply:` line with a normal reply of your app to the same message. For example, type the check message in the app's own chat. If the `Reply:` line is a fallback text or an error message of the app, the entry does not run the app as you use it.

### 2. Search app.log

`app.log` in the test folder has the stderr of the entry and your app. Search it for fallback warnings and missing-config warnings:

```bash
grep -i -E 'fallback|warn|missing|not set|default' .verbatim-relay/tests/<test-id>/app.log
```

Change the words to the words that your app writes in its logs. For the toy shop, `grep` finds no line and exits with 1. Its `app.log` has only the line `toy shop agent: ready`.

### 3. Send a real message by hand

Run the command of `entry` from the project root. Give it one realistic message on stdin, in the format of the contract. For the toy shop:

```bash
printf '%s\n' '{"v": 1, "id": "1", "session": "by-hand", "message": "what is your refund policy?", "history": []}' | python3 agent.py
```

```text
toy shop agent: ready
{"v": 1, "id": "1", "reply": "Our refund policy:\n\n1. Damaged items: full refund.\n2. Change of mind: 30 days.\n"}
```

The first line is stderr. The second line is the reply line on stdout. Compare the reply with the reply of the app outside the entry. The tap does not record this message, because no test runs.

### 4. Check the interpreter, the environment file and the working folder

The tap starts the entry with these settings ([stdio.py](../../src/verbatim_relay/stdio.py)):

- **Interpreter.** The command is `entry` in `.verbatim-relay/config.json`. Its first word is the interpreter. Use the interpreter of your app, for example `.venv/bin/python`. If you use a different interpreter, the packages of your app can be missing.
- **Working folder.** The entry runs in the project root. If your app reads a file with a relative path, for example `.env` or a config file in its own folder, give the app the correct path in the entry.
- **Environment.** The entry gets the environment of the process that starts the test, and the variables of the bridge, for example `ANTHROPIC_BASE_URL`. After `verbatim-relay check` in a shell, it is the environment of that shell. With the hook kit or the plugin, the harness starts the test, so it is the environment of the harness. If your app reads its keys from an environment file, load that file in the entry.

After a change to the entry, run `verbatim-relay check` again, and do the 4 steps again.

## When the app changes

- **A new start command or interpreter:** change `entry`.
- **A new model harness in the app:** change `models`.
- **A new HTTP service:** add it to `backends` ([add-a-backend.md](add-a-backend.md)).
- **A new direct model call:** check that the SDK reads `ANTHROPIC_BASE_URL` or `OPENAI_BASE_URL` ([record-model-calls.md](record-model-calls.md)).

Then run `verbatim-relay check` again. The manifest of each test keeps the SHA-256 of each file in `.verbatim-relay/`, so a test shows which entry it ran.

## Next

- An Agent SDK session in your app: [isolate-agent-sdk.md](isolate-agent-sdk.md).
- Run the test: [claude-code.md](claude-code.md) or [codex.md](codex.md).

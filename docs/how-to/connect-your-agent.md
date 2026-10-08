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

`serve()` needs `verbatim_relay` in the Python environment of your app. `uv tool install` puts it in its own environment, so also add it to your app's environment, for example with `uv add --dev "verbatim-relay>=0.3"`. In an earlier version, `serve()` can send the stdout text that the entry printed before it to the tap, and not to stderr ([#46](https://github.com/mohanraj00/verbatim-relay/issues/46)). Then use your app's interpreter in the entry command, for example `[".venv/bin/python", ".verbatim-relay/entry.py"]`.

### In Node

[examples/toy-shop-node/entry.mjs](../../examples/toy-shop-node/entry.mjs) is an entry for the toy shop in Node. It needs no package. Copy it to `.verbatim-relay/entry.mjs`, and replace the function `reply` with the call to your app. `reply` can be `async`.

```js
// The toy shop agent in Node, as the entry of a verbatim-relay test (SPEC.md section 6).
// It reads one JSON line on stdin for each message, and writes one JSON line on stdout.
// Usage: node examples/toy-shop-node/entry.mjs

// Stdout is only for contract lines. Send the console.log output of the app to stderr.
console.log = console.error;

// The app. Replace this function with the call to your own app.
const REPLIES = {
  refund: "Our refund policy:\n\n1. Damaged items: full refund.\n2. Change of mind: 30 days.\n",
  ship: "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  ",
};

async function reply(message, history) {
  if (message.includes("order")) throw new Error("the order service is down");
  const key = Object.keys(REPLIES).find((k) => message.toLowerCase().includes(k));
  return key ? REPLIES[key] : "Which item is this about: the mug or the teapot?";
}

async function answer(line) {
  let request;
  try {
    request = JSON.parse(line);
  } catch (err) {
    console.error(`toy shop agent: not a contract line: ${err.message}`);
    return;
  }
  const out = { v: 1, id: request.id };
  try {
    out.reply = await reply(request.message, request.history);
  } catch (err) {
    out.error = String(err?.message ?? err);
  }
  process.stdout.write(JSON.stringify(out) + "\n");
}

console.error("toy shop agent: ready");
// Split the input only at "\n". node:readline also splits at "\r", and in Node 25 also at
// U+2028 and U+2029. A message can contain U+2028.
process.stdin.setEncoding("utf8");
let pending = "";
for await (const chunk of process.stdin) {
  const lines = (pending + chunk).split("\n");
  pending = lines.pop();
  for (const line of lines) await answer(line);
}
```

The configuration:

```json
{"entry": ["node", ".verbatim-relay/entry.mjs"], "models": []}
```

Obey these rules in Node:

- Do not read the input with `node:readline`. It also ends a line at `\r`. In Node 25, it also ends a line at U+2028 and U+2029 ([test](../../tests/test_example_entries.py), run with Node 25.8.0). The relays do not escape U+2028 in the input line, so a message with U+2028 arrives in 2 parts.
- Keep `console.log = console.error` at the top. Then a `console.log` of the app goes to stderr.
- If the app starts a child process, send its stdout to stderr, for example with `stdio: ["ignore", 2, 2]` in `spawn`.
- If `reply` throws, the entry writes an `error` line, and the test continues.

`verbatim-relay check` with this entry gives:

```text
Test 20261007-224419-fac5: /path/to/toy-shop-node/.verbatim-relay/tests/20261007-224419-fac5
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

[tests/test_example_entries.py](../../tests/test_example_entries.py) runs this file through the stdio tap and audits the records. It also checks that this page shows the file with no change. The test skips if `node` is not on `PATH`.

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

## If your app is an HTTP server

You can connect an app that is an HTTP server in 2 ways:

- **An entry that calls the server.** The test keeps the test folder, the trace, the seal and the evaluation.
- **The HTTP tap** ([http-tap.md](http-tap.md)). The tap is in front of the server, and there is no entry. You get only the tap record and the relay record. There is no test folder, no trace, no seal and no evaluation.

I recommend the entry. [examples/toy-shop/http_entry.py](../../examples/toy-shop/http_entry.py) starts the toy shop HTTP server ([http_agent.py](../../examples/toy-shop/http_agent.py)), then sends each message to it:

```python
"""An entry for the toy shop HTTP agent. It starts the server, then sends each message to it.

The entry starts the server, so the server gets the environment of the test and its output goes
to app.log. Run it from the repo root, with a Python that has verbatim_relay:

    {"entry": [".venv/bin/python", "examples/toy-shop/http_entry.py"]}
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from verbatim_relay.agent import serve

PORT = int(os.environ.get("TOY_SHOP_PORT", "8700"))
URL = f"http://127.0.0.1:{PORT}/"
SERVER = Path(__file__).with_name("http_agent.py")


def start_server() -> subprocess.Popen[bytes]:
    """Start the server once, and wait until it accepts a connection. Its output goes to stderr.
    If it does not accept a connection in 30 s, stop it, so that no server stays after the entry."""
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
    except OSError:
        pass
    else:
        # Another process owns the port. Do not send the messages of the test to it.
        raise SystemExit(f"toy shop entry: port {PORT} is in use. Set TOY_SHOP_PORT.")
    server = subprocess.Popen([sys.executable, str(SERVER), str(PORT)], stdout=sys.stderr)
    # HTTPServer looks up the host name before it listens. On some machines this takes seconds.
    deadline = time.monotonic() + 30
    while True:
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
            if server.poll() is None:
                return server
            raise OSError(f"the server stopped: exit {server.returncode}")
        except OSError:
            if server.poll() is not None or time.monotonic() > deadline:
                server.kill()
                server.wait()
                raise
            time.sleep(0.1)


def reply(message: str, history: list[tuple[str, str]]) -> str:
    body = json.dumps({"text": message}).encode()
    request = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    # 200 s is less than the 240 s of the tap, so the tester gets this error and not a timeout.
    with urllib.request.urlopen(request, timeout=200) as response:
        text: str = json.loads(response.read())["reply"]
        return text


server = start_server()
try:
    serve(reply)
finally:
    server.terminate()
    server.wait()
```

The configuration:

```json
{"entry": [".venv/bin/python", "examples/toy-shop/http_entry.py"], "models": [], "agent_url": "http://127.0.0.1:8700/"}
```

Obey these rules for an HTTP server:

- Start the server in the entry, not before the test. Then the server gets the proxy URLs and the OTLP URL in its environment, and the tap writes its stderr to `app.log`. The tap also finds a Claude Code session of the server only if the server is a child of the entry ([SPEC.md section 7.3](../../SPEC.md#73-model-sessions)).
- Send the stdout of the server to stderr. `serve()` does this only for output after it starts, so give `stdout=sys.stderr` to the server process.
- Set `agent_url` to the URL of the server. The relay then denies a model tool call that names this URL, the same as a call to the tap ([reference/config.md](../reference/config.md#relay-keys)). A model call to the server goes around the tap, and no record shows it.
- Give the call to the server a timeout of less than [240 seconds](../../src/verbatim_relay/stdio.py), the agent timeout of the tap. Then the tester sees the error of the call.
- If the server streams its reply, read the full stream and return one reply ([test-a-streaming-agent.md](test-a-streaming-agent.md)).

`verbatim-relay check` with this entry gives:

```text
Test 20261007-224920-4058: /path/to/toy-shop-http/.verbatim-relay/tests/20261007-224920-4058
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

### The entry and the HTTP tap

| | Entry (the tap in stdio mode) | HTTP tap |
|---|---|---|
| Test folder | Yes: `.verbatim-relay/tests/<test-id>/` | No |
| Trace | Yes: `trace.jsonl` and `findings.json` | No |
| Seal | Yes: `seal.json`. `verbatim-relay verify` shows each changed file. | No |
| Evaluation | Yes, after the prompt `verbatim-relay end` | No |
| Backend and model API proxies | Yes, for the entry and each process that it starts | No |
| OTLP receiver | Yes, for the entry and each process that it starts | No |
| Copies of the model sessions | Yes, in `sessions/` of the test folder | No |
| Record path | `tap.jsonl` and `relay.jsonl` in the test folder | The `--record` file of the tap, and the relay option `record` (default `.verbatim-relay/relay.jsonl`) |
| Audit | The bridge writes `audit.json` at the end. | You run `verbatim-relay audit --tap FILE --relay FILE`. |
| On | Plugin: `/verbatim-relay start`. Hook kit: the prompt `verbatim-relay start`. | Plugin: `/verbatim-relay on`. Hook kit: `verbatim-relay mode on`. |
| Off | Plugin: `/verbatim-relay end`. Hook kit: the prompt `verbatim-relay end`. | Plugin: `/verbatim-relay off`. Hook kit: `verbatim-relay mode off`. |
| Streamed replies | The entry joins the stream into one reply. | Only with the `openai` adapter. |

## When the app changes

- **A new start command or interpreter:** change `entry`.
- **A new model harness in the app:** change `models`.
- **A new HTTP service:** add it to `backends` ([add-a-backend.md](add-a-backend.md)).
- **A new direct model call:** check that the SDK reads `ANTHROPIC_BASE_URL` or `OPENAI_BASE_URL` ([record-model-calls.md](record-model-calls.md)).

Then run `verbatim-relay check` again. The manifest of each test keeps the SHA-256 of each file in `.verbatim-relay/`, so a test shows which entry it ran.

## Next

- An Agent SDK session in your app: [isolate-agent-sdk.md](isolate-agent-sdk.md).
- Run the test: [claude-code.md](claude-code.md) or [codex.md](codex.md).

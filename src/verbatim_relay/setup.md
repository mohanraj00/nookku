# verbatim-relay setup: connect a test to this app

You configure a verbatim-relay test for the app in this project. In a test, the tester types each message, and verbatim-relay sends it to the app byte for byte. You do not take part in the test. You only write the connection now.

Do not change the app's code. Write only files in `.verbatim-relay/`.

## 1. Read the app

1. Find how one chat message goes into the app, and how the reply comes out. For example: a function, a session object, a CLI loop or an HTTP endpoint.
2. Find how the app starts with all its wiring: configuration, services, data and model sessions.
3. Find the model harness that the app uses for its own model sessions:
   - the Claude Agent SDK, `claude -p` or another use of Claude Code: `claude-code`;
   - the Codex SDK, `codex app-server` or `codex exec`: `codex`;
   - both, or none.
4. Find the backends of the app: the HTTP services that it calls, for example a stock or payment service. For each one, find the environment variable that holds its URL. Also find each direct call to the Anthropic or the OpenAI API, and check that the SDK reads its URL from `ANTHROPIC_BASE_URL` or `OPENAI_BASE_URL`.
5. Check that the app keeps its session files. If the app sets `persistSession: false` (Agent SDK) or `ephemeral: true` (Codex `thread/start`), tell the tester. The test then has no trace of the model sessions. Do not change the app.
6. Check that an Agent SDK session of the app is isolated: `setting_sources=[]`, `strict_mcp_config=True` and `CLAUDE_CODE_PLUGIN_DIRS` set to `""` in `env` (`settingSources` and `strictMcpConfig` in TypeScript). If an option is missing, tell the tester: the app's model can then see the tester's plugins and claude.ai connectors. Do not change the app.

## 2. Write the entry

Write `.verbatim-relay/entry.<ext>` in the language of the app. The entry starts the app once, then speaks the agent contract on stdin and stdout until stdin closes:

- **In:** one JSON object on one line for each message: `{"v": 1, "id": "...", "session": "...", "message": "...", "history": [{"message": "...", "reply": "..."}]}`.
- **Out:** one JSON object on one line for each input: `{"v": 1, "id": "<the same id>", "reply": "..."}`, or `{"v": 1, "id": "<the same id>", "error": "..."}` if the app has no reply.

Obey these rules:

- Send `message` to the app without change. Return the app's reply without change. Do not trim, format or translate either text.
- Use one app conversation for the whole test. `session` is the test id. Use `history` only if the app needs the earlier turns from outside.
- Write only contract lines to stdout. Send all other output to stderr: logs, prints, and the output of child processes.
- Read and write UTF-8. Split input lines only on `\n`.
- If the app fails on one message, write an `error` line and continue.
- Exit when stdin closes.

In Python, if `verbatim_relay` is installed in the app's environment, use the helper:

```python
from verbatim_relay.agent import serve


def reply(message: str, history: list[tuple[str, str]]) -> str:
    return app_session.send(message)  # the app's own call


serve(reply)
```

`serve()` writes the contract lines and sends all other output to stderr.

## 3. Write the configuration

Write the test keys into `.verbatim-relay/config.json`. Keep the other keys of the file.

```json
{"entry": ["python", ".verbatim-relay/entry.py"], "models": ["claude-code"]}
```

- `entry` is the command as a list of arguments. It runs in the project root. Use the app's own interpreter or virtual environment.
- `models` lists the harnesses from step 1.3.
- `backends` lists the backends from step 1.4: `{"name": "stock", "env": "STOCK_URL", "url": "<the real URL>"}`. During a test, the app gets the URL of a recording proxy in `env`. If the app reads the URL from a file and not from the environment, the entry gives the app the URL from `env`, for example with a copy of the app's configuration for the test. Do not change the app's own files.
- `model_api` is `true` by default: the app gets the URL of a recording proxy in `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL`. If the app gives its SDK a fixed URL, the entry gives the SDK the URL from the variable, as for a backend. If the app uses Codex with a ChatGPT login, set `"model_api": ["anthropic"]`. If the tester's harness reads the same variable as the app, give the app's URL in the config: `"model_api": {"openai": "<the app's URL>"}`.

## 4. Check

Run:

```bash
verbatim-relay check
```

It starts the entry, sends one message, and ends the test. It passes if a reply comes back, if the audit of the test is clean, and if it finds a model session for each harness in `models`. If it fails, read `app.log` and `bridge.log` in the test folder that it names, correct the entry, and run it again.

## 5. Hand over

Show the tester the entry and the configuration, and ask the tester to review them. The tester then starts the test: `/verbatim-relay start` with the Claude Code plugin, or the prompt `verbatim-relay start` with the hook kit.

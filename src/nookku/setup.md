# Nookku setup: connect a test to this app

You configure a Nookku test for the app in this project. In a test, the tester types each message, and Nookku sends it to the app byte for byte. You do not take part in the test. You only write the connection now.

Do these 6 steps in this order: understand, interview, confirm, build, check and hand over. Steps 1 to 3 only read. Do not write, change or remove a file before the tester says yes to the plan of step 3. Do not change the app's code at any step.

## 1. Understand

Read the app. Do not write a file.

1. Find how one chat message goes into the app, and how the reply comes out. For example: a function, a session object, a CLI loop or an HTTP endpoint.
2. Find how the app starts with all its wiring: configuration, services, data and model sessions.
3. Find the model harness that the app uses for its own model sessions:
   - the Claude Agent SDK, `claude -p` or another use of Claude Code: `claude-code`;
   - the Codex SDK, `codex app-server` or `codex exec`: `codex`;
   - both, or none.
4. Find the backends of the app: the HTTP services that it calls, for example a stock or payment service. For each one, find the environment variable that holds its URL. Also find each direct call to the Anthropic or the OpenAI API, and the variable that holds its URL.
5. Find the store of the app: each database and each data file that the app reads or writes, for example the orders of a toy shop.
6. Find the rules and the docs of the app: business rules, a policy, a README, a system prompt and the tests. Find an app spec, if the project has one: a Markdown file with the sections `Persona`, `Boundaries`, `User goals`, `Limits`, `Trace points` or `Verdict`, or the files of the `spec` key in `.nookku/config.json`.
7. Find an entry and a config of an earlier setup: `.nookku/config.json` and the file of its `entry` key.
8. Check that the app keeps its session files. If the app sets `persistSession: false` (Agent SDK) or `ephemeral: true` (Codex `thread/start`), the test has no trace of the model sessions.
9. Check that an Agent SDK session of the app is isolated: `setting_sources=[]`, `strict_mcp_config=True` and `CLAUDE_CODE_PLUGIN_DIRS` set to `""` in `env` (`settingSources` and `strictMcpConfig` in TypeScript). If an option is missing, the app's model can see the tester's plugins and claude.ai connectors.

Then give the tester a short summary, with one line or a short list for each item:

- **In and out:** how a message goes into the app and how the reply comes out, with the file and the function.
- **Model harnesses:** `claude-code`, `codex`, both or none, with the file that shows it.
- **Backends:** each backend and each model API, with its variable.
- **Store:** each database and data file.
- **Rules and docs:** each file with rules, and the app spec, if the project has one.
- **Warnings:** each problem of items 8 and 9. Do not correct it. The app's code does not change.

At each `nookku start`, the harness model finds the backends, the model APIs, the MCP servers and the databases again, and the tester checks them. The summary does not register them.

## 2. Interview

Ask the tester only about the gaps: the items that the app does not tell you. Do not ask about a fact that you found in step 1. Ask about these items:

- **Persona:** the character and the tone of the agent, and how long a reply is. Ask only if the project has no app spec with this part.
- **Boundaries:** the topics and the actions that the agent must refuse. Ask only if the project has no app spec with this part.
- **User goals:** the goals of a user, and the steps from the first message to each goal. Ask only if the project has no app spec with this part.
- **Test data:** the data that a test uses, for example the orders and the stock of a toy shop.
- **Reset:** how the state of the app goes back to the start between 2 tests, or if it must not.
- **Other gaps:** for example the URL of a backend that the code does not give.

Ask at least the question about the reset. Ask all questions in one message, as a numbered list. Give a proposed answer for each question from what you found, so that the tester can agree with one word. Then stop and wait for the answers. If an answer is not clear, ask again.

## 3. Confirm

Show the tester the plan. Do not write a file yet. The plan has these parts:

- **Entry:** the path of `.nookku/entry.<ext>`, the command that starts it, and each action of the entry. By default, the entry is a thin wrapper: it starts the app once and sends each message to the app. Add another action only if the tester agrees to it in step 2 or here, for example to load the test data or to reset the state when the test starts. For each such action, name each file that it changes and each command that it runs.
- **Config:** each key of `.nookku/config.json` and its value (step 4.2).
- **App spec:** the path of the draft and its sections, or "no draft" if the project has an app spec.
- **Files:** the list of each file that step 4 writes. Step 4 writes no other file.

Then ask the tester to say yes to the plan, and stop. Wait for a clear yes, for example "yes" or "go ahead". A question, a change or a partial answer is not a yes. If the tester asks for a change, show the changed plan and wait again.

## 4. Build

Write only the files of the plan. Do not change the app's code.

### 4.1. Write the entry

Write `.nookku/entry.<ext>` in the language of the app. If the app already speaks the agent contract, the entry can be the start command of the app, and you write no entry file. The entry starts the app once, then speaks the agent contract on stdin and stdout until stdin closes:

- **In:** one JSON object on one line for each message: `{"v": 1, "id": "...", "session": "...", "message": "...", "history": [{"message": "...", "reply": "..."}]}`.
- **Out:** one JSON object on one line for each input: `{"v": 1, "id": "<the same id>", "reply": "..."}`, or `{"v": 1, "id": "<the same id>", "error": "..."}` if the app has no reply.

Obey these rules:

- Send `message` to the app without change. Return the app's reply without change. Do not trim, format or translate either text.
- Use one app conversation for the whole test. `session` is the test id. Use `history` only if the app needs the earlier turns from outside.
- Write only contract lines to stdout. Send all other output to stderr: logs, prints, and the output of child processes.
- Read and write UTF-8. Split input lines only on `\n`.
- If the app fails on one message, write an `error` line and continue.
- Exit when stdin closes.
- Do only the actions of the plan. A load or a reset of the test data changes only the files and runs only the commands that the plan names. Do it before the entry reads the first input line, and send its output to stderr.
- During a test, the app gets the URL of a recording proxy in the variable of each backend and each model API. If the app reads a URL from a file and not from its variable, the entry gives the app the URL from the variable, for example with a copy of the app's configuration for the test. Do not change the app's own files.

In Python, if `nookku` is installed in the app's environment, use the helper:

```python
from nookku.agent import serve


def reply(message: str, history: list[tuple[str, str]]) -> str:
    return app_session.send(message)  # the app's own call


serve(reply)
```

`serve()` writes the contract lines and sends all other output to stderr.

### 4.2. Write the configuration

Write the test keys into `.nookku/config.json`. Keep the other keys of the file. Use only the keys of this guide. An unknown key stops `check` and `start`.

```json
{"entry": ["python", ".nookku/entry.py"], "models": ["claude-code"], "spec": ["APP_SPEC.md"]}
```

- `entry` is the command as a list of arguments. It runs in the project root. Use the app's own interpreter or virtual environment.
- `models` lists the harnesses from step 1.3.
- `spec` lists the files of the app spec, relative to the project root: the draft of step 4.3, or the files of the app spec of the project. A file in `.nookku/` is an error.
- `check_message` is the one message that `check` sends. The default is `Hello from nookku check. What can you help me with?` If the app declines this message, set a message that the app answers in normal use, for example a question about a product.

The file has no `backends` key and no `model_api` key. These keys are an error. The harness model finds the egress of the app at each `nookku start`.

### 4.3. Write the app spec draft

If the project has no app spec, write a draft of it from the answers of step 2, at the path of the plan. The default path is `APP_SPEC.md` in the project root. Do not write it in `.nookku/`. If the project has an app spec, do not change it, and write no draft.

- Start the file with the title `# App spec (draft)`, and one line that tells the tester to review each line.
- Give each part its own `##` section, with these names exactly: `Persona`, `Boundaries` and `User goals`. Add `Limits`, `Trace points` or `Verdict` only if the tester gave them.
- In `Persona`, `Boundaries` and `User goals`, write each rule as a short list item.
- Write `Limits` as a table with the columns `Limit`, `Value` and `Meaning`. A limit is `turn_seconds` or `turn_tokens`.
- Write `Trace points` as a table with the columns `Name`, `Source` and `When`, one row for each trace point. `Source` is `session`, `backend`, `model_api` or `otel`. A `When` that the trace checks is `Each turn`, `Turn N` or `Each <tool> tool call`. For example:

  ```markdown
  | Name | Source | When |
  |---|---|---|
  | `check_stock` | `session` | Each turn |
  | `stock GET /stock` | `backend` | Each check_stock tool call |
  ```

  Do not write trace points as list items. The trace reads only the table, and a list gives the finding `trace_points_unread`.
- Write only what the tester said or what a file of the app says. For a rule from a file, link to the file.
- Do not write a secret into the draft. The evaluation model reads it.

## 5. Check

Run:

```bash
nookku check
```

It starts the entry, sends one message, and ends the test. It passes if a reply comes back, if the audit of the test is clean, and if it finds a model session for each harness in `models`. If it fails, read `app.log` and `bridge.log` in the test folder that it names, correct the entry, and run it again.

`check` needs a fresh egress answer. If `check` stops because it has no egress answer, tell the tester to type the prompt `nookku start`. The harness model then finds the egress of the app. After that, run `check` again.

A PASS does not prove that the entry runs the app correctly. `check` does not judge the text of the reply. After a PASS, do these 3 steps:

1. Compare the `Reply:` line with a normal reply of the app to the same message. If the app declines the message in normal use, for example because it is out of scope, set `check_message` to a message that the app answers. Then run `check` again. If the reply is an error text, or is different from the normal reply of the app, the setup is not done. Correct the entry and run `check` again.
2. Search `app.log` in the test folder of the check test for errors and tracebacks. Also search it for warnings about a fallback or a missing configuration. If a line shows that the entry does not start or call the app correctly, correct the entry and run `check` again. Ignore a warning that the app also writes in normal use.
3. If the entry is in Node and reads its input with `node:readline`, change the entry. Read stdin and split it only on `\n`. In Node 25, `node:readline` also splits a line at U+2028 and U+2029, and the relays send these characters unescaped. A message with one of them then arrives in 2 parts. Read the [warning for Node](https://github.com/mohanraj00/nookku/blob/v0.5.6/docs/how-to/connect-your-agent.md#in-node).

A change to the entry after step 3 that adds an action is a change to the plan. Show it to the tester and wait for a yes before you write it.

## 6. Hand over

Show the tester the entry, the configuration and the app spec draft, and ask the tester to review them. The tester then starts the test: the prompt `nookku start`. In Claude Code, the plugin also gives `/nookku start`.

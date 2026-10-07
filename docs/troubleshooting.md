# Troubleshooting

Each entry gives a real error text from the code, its cause and the fix. The source file of each text is in parentheses. A part in angle brackets, for example `<test-id>`, changes from run to run.

First, look in the test folder `.verbatim-relay/tests/<test-id>/`. `bridge.log` has the steps of the bridge. `app.log` has the stderr of your entry and your app.

## Install

### `verbatim-relay: error: unrecognized arguments: --entry python3 agent.py`

(argparse, from `verbatim-relay init`) **Cause.** You have version 0.1.0 from PyPI. It has no tests and no entry. Check with `verbatim-relay --version`.

**Fix.** Install version 0.2.0 or later. Until PyPI has it, install from the repo: `uv tool install --force git+https://github.com/mohanraj00/verbatim-relay`.

### `verbatim-relay: command not found`

**Cause.** The folder of `uv tool` programs is not on `PATH`.

**Fix.** Run `uv tool update-shell`, then open a new terminal. For the plugin, you can also give the full path in the plugin option `cli` ([reference/config.md](reference/config.md#plugin-options)).

## Start a test

### `verbatim-relay: .verbatim-relay/config.json has no 'entry' command`

(bridge.py) **Cause.** `config.json` has no `entry`, or it is empty.

**Fix.** Add the entry: `verbatim-relay init <harness> --entry "<command>"`, or ask the harness model to run `verbatim-relay setup` ([how-to/connect-your-agent.md](how-to/connect-your-agent.md)).

### `verbatim-relay: cannot read .verbatim-relay/config.json: <reason>`

(bridge.py) **Cause.** The file does not exist, or it is not valid JSON.

**Fix.** Correct the JSON, or write the file again with `verbatim-relay init`.

### `verbatim-relay: 'models' must be a list of claude-code, codex`

(bridge.py) **Cause.** `models` has another value, for example `"claude"`.

**Fix.** Use only `claude-code` and `codex`, in a list.

### `verbatim-relay: .verbatim-relay/config.json: the URL of openai (OPENAI_BASE_URL) must be an http or https URL: ''`

(model_api.py) **Cause.** `model_api` gives an empty URL or a URL that is not `http` or `https`. An empty URL does not fall back to the variable.

**Fix.** Give a full URL, or `null` to take the URL from the variable ([how-to/record-model-calls.md](how-to/record-model-calls.md)).

### `verbatim-relay: .verbatim-relay/config.json: a backend uses the variable of a model API`

(bridge.py) **Cause.** A backend has `"env": "ANTHROPIC_BASE_URL"` or `"env": "OPENAI_BASE_URL"`, and the model API proxy also records that API.

**Fix.** Remove the backend, or remove that API from `model_api` ([how-to/add-a-backend.md](how-to/add-a-backend.md)).

### `each backend needs the strings 'name', 'env' and 'url'`

(backend.py) **Cause.** A backend object has a missing key, or a key that is not a string. Related texts: `each backend needs its own 'name' and 'env'`, and `backend <name>: 'url' must be an http or https URL`.

**Fix.** Give each backend a unique `name`, a unique `env` and a full `url`.

### `verbatim-relay: test <test-id> runs already. End it first.`

(bridge.py) **Cause.** A test runs in this project.

**Fix.** End it with the prompt `verbatim-relay end` or with `verbatim-relay end` in a shell.

### `verbatim-relay: the test did not start:` and `cannot start the entry ['python', 'agent.py']: [Errno 2] No such file or directory: 'python'`

(bridge.py) **Cause.** The first word of the entry is not a program on `PATH`. On macOS, `python` often does not exist.

**Fix.** Use `python3`, or the full path of your app's interpreter, for example `.venv/bin/python`.

### `verbatim-relay: the test did not start:` and `the entry exited at start:`

(bridge.py) **Cause.** The entry stopped in its first moments. The lines after the text are the last lines of `app.log`, for example `can't open file '.../agent.py': [Errno 2] No such file or directory`.

**Fix.** The entry runs in the project root. Use a path relative to the root, and run the entry command from the root by hand to see the error.

## During a test

### `verbatim-relay: relay mode is on, but no test runs. Start one with: verbatim-relay start. Nothing was sent.`

(kit.py; the plugin says `Type /verbatim-relay start`) **Cause.** Relay mode is on, but the bridge does not run. For example, the computer restarted during a test.

**Fix.** Start a test. Or switch relay mode off: `verbatim-relay mode off` with the hook kit.

### `verbatim-relay: the agent sent an error:`

(bridge.py, core.ts) **Cause.** The entry wrote an `error` line. The text after it is the error of your app. With `serve()`, it is the exception, for example `KeyError: 'order'`.

**Fix.** Read the error and `app.log`. The test continues: send the next message.

### `the agent sent no reply in 240 s, so the tap stopped it`

(stdio.py) **Cause.** The entry did not write a line with the request id in [240 seconds](../src/verbatim_relay/stdio.py).

**Fix.** Make the app answer faster, or write an `error` line when it cannot answer. The tap does not restart the entry: end the test and start a new one.

### `the agent printed <n> lines on stdout but no reply line for <id> in 240 s, so the tap stopped it. Use verbatim_relay.agent.serve() or write logs to stderr.`

(stdio.py) **Cause.** The entry or your app wrote logs on stdout, and no line with the request id came. `verbatim-relay check` says `The entry printed lines on stdout, but no reply line.`

**Fix.** Write logs to stderr. In Python, use `verbatim_relay.agent.serve()`, which sends all other output to stderr ([how-to/connect-your-agent.md](how-to/connect-your-agent.md)).

### `the agent exited (code <n>)`

(stdio.py) **Cause.** The entry stopped during the test. Each later message gets the same error, with the last lines of `app.log`.

**Fix.** Read `app.log`. End the test and start a new one.

### `verbatim-relay: cannot reach the tap at <url>: <reason>`

(bridge.py, kit.py, register.tsx) **Cause.** The bridge or the tap does not run. With no entry, the tap of `tap_url` does not run.

**Fix.** With an entry, end the test and start a new one. With no entry, start `verbatim-relay tap` ([how-to/http-tap.md](how-to/http-tap.md)).

### `verbatim-relay: relay mode is on, but the config is broken: unknown config keys: ['<key>']`

(kit.py) **Cause.** `config.json` has a key that the hook kit does not know. The message does not go to the model or to the agent.

**Fix.** Remove the key. [reference/config.md](reference/config.md) lists each key.

### `verbatim-relay: the hook failed (<error>). Nothing reached the model.`

(kit.py, register.tsx) **Cause.** The relay failed on this prompt. It fails closed, so it blocked the prompt.

**Fix.** Read the error. If it repeats, open an issue with the text.

### `verbatim-relay: only the tester talks to the agent.`

(kit.py; the plugin adds more text) **Cause.** The relay denied a model tool call that names the address of the tap or the agent. It also denies a call that changes a file of the test. This is the purpose of the deny.

**Fix.** None. Talk to the agent through the relay. To read the conversation, the model uses `verbatim-relay transcript` or the `transcript` tool.

### `verbatim-relay: during a test, only the tap runs the entry.`

(kit.py, register.tsx) **Cause.** The model tried to run the entry during a test.

**Fix.** None. A command that only reads the entry, for example `cat entry.py`, can run.

### `verbatim-relay: the record <path> is full. Move it, then send again. Nothing was sent.`

(register.tsx) **Cause.** The plugin stops at a relay record of [3.5 MiB](../plugins/claude-code/hooks/register.tsx).

**Fix.** Move the record, then send the message again ([#2](https://github.com/mohanraj00/verbatim-relay/issues/2)).

### `verbatim-relay: the relay does not send attachments. Nothing was sent.`

(register.tsx) **Cause.** The prompt had an attachment or an image.

**Fix.** Send text only ([#6](https://github.com/mohanraj00/verbatim-relay/issues/6)).

### `verbatim-relay: the record is invalid: <path>: line <n>: <reason>. Do not trust this record. The view shows the next turns when the record changes and is valid.`

(kit.py) **Cause.** `verbatim-relay view` read a relay record with an invalid line. A line changed after the writer wrote it, or another program wrote it. The view shows this error one time and continues to wait. With `--no-follow`, it shows `verbatim-relay: <path>: line <n>: <reason>` and exits with 2.

**Fix.** Do not edit a record. Find the program that wrote the line. After the end of the test, run `verbatim-relay verify` to see which files changed.

### Each message reaches the agent two times

**Cause.** The plugin and the hook kit both run in the project. The audit shows `duplicate_send` breaks.

**Fix.** Use one relay. Remove the verbatim-relay hooks from `.claude/settings.local.json`, or disable the plugin.

### In Codex, the model answers my test messages

**Cause.** Codex did not run the hooks, because nobody trusted them. Codex runs project hooks only after a person trusts them.

**Fix.** Start `codex` in the project and accept the hooks prompt. Trust the hooks again after each change to `.codex/hooks.json` ([how-to/codex.md](how-to/codex.md)).

## End a test

### `verbatim-relay: the records of a test do not change. Write only report.md. A command that names .verbatim-relay may only read.`

(kit.py, register.tsx) **Cause.** After a test, the model tried to write a file of the test folder. Or it ran a command that names `.verbatim-relay` and does not pass the read check.

**Fix.** None for the records. If the evaluation needs a command, use a read program from the list in [SPEC.md section 5](../SPEC.md#5-relays), for example `cat`, `jq` or `sed -n`.

### `The bridge did not finish its collection. See bridge.log in the folder.`

(bridge.py) **Cause.** The bridge did not write the end time in the manifest. For example, it did not stop in the wait time of `end`.

**Fix.** Read `bridge.log`. Run `verbatim-relay trace` to build the trace again.

### `FAIL: No claude-code model session was identified.`

(bridge.py, from `verbatim-relay check`) **Cause.** `models` names `claude-code`, but the tap found no Claude Code session of a process of the entry. The app does not use Claude Code, or it did not start a session for the check message.

**Fix.** Check `models`. Check that the app starts its session for the first message.

### `FAIL: The claude-code session <id> has no session file.`

(bridge.py) **Cause.** The app turns off its session files, for example with `persistSession: false` in the Agent SDK.

**Fix.** Let the app keep its session files during a test. The trace needs them ([limits.md](limits.md)).

## Audit, verify and trace

### `ERROR record_missing: <path>: No such file or directory`

(record.py) **Cause.** A record file does not exist. The audit exits with 2.

**Fix.** Check the paths. The records of a test are in its test folder.

### `ERROR record_invalid: <path>: line <n>: field input_sha256 does not match 'input'`

(record.py) **Cause.** A line of the record changed after the writer wrote it, or another program wrote it. The audit fails closed and exits with 2.

**Fix.** Do not edit a record. Run `verbatim-relay verify` to see which files changed after the end of the test.

### `ERROR tap_unparsed: line <n>: STDIO stdout: a stray line on stdout: '<text>'`

(audit.py) **Cause.** The entry wrote a line on stdout that is not a contract line. The tap wrote an `unparsed` row for it. The audit cannot check that row, so it exits with 2.

**Fix.** Write logs to stderr, or use `serve()`. `verbatim-relay check` passes with such a line, so also read the audit.

### `Seal: BROKEN. changed: <file>. Do not trust these records.`

(seal.py) **Cause.** A file of the test folder changed after the end of the test. `verbatim-relay verify` exits with 2.

**Fix.** Do not trust the changed files. Run a new test.

### `verbatim-relay: the trace was not rebuilt. Seal: BROKEN. ...`

(cli.py) **Cause.** `verbatim-relay trace` builds the trace only from sources that agree with the seal.

**Fix.** Run a new test.

### `verbatim-relay: no test folder.` or `verbatim-relay: no test folder with a manifest.`

(cli.py) **Cause.** The project has no test, or the test id is wrong.

**Fix.** Run `ls .verbatim-relay/tests/` and give a test id that exists.

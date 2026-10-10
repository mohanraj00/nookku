# Troubleshooting

If you see a problem but no error text, find the problem in [Symptoms](#symptoms). If you have an error text, find it in the sections after Symptoms. Each of these entries gives a real error text from the code, its cause and the fix. The source file of each text is in parentheses. A part in angle brackets, for example `<test-id>`, changes from run to run.

First, look in the [test folder](reference/glossary.md#test-folder) `.nookku/tests/<test-id>/`. `bridge.log` has the steps of the [bridge](reference/glossary.md#bridge). `app.log` has the stderr of your [entry](reference/glossary.md#entry) and your app.

## Symptoms

| Symptom | Fix |
|---|---|
| `nookku check` passes, but the replies are wrong. | `check` does not judge the reply. Do the steps in [Make sure that check runs your real app](how-to/connect-your-agent.md#make-sure-that-check-runs-your-real-app). The [entry for this symptom](#nookku-check-passes-but-the-replies-are-wrong) gives the cause. |
| The viewer shows an old test or the check test. | This is correct before the start of a test. The viewer shows the last test, and after `check` this is the check test. When a test starts, the viewer shows a header line with the new test id ([test-your-app.md](how-to/test-your-app.md#start-the-viewer)). If no new header comes, run `nookku status` to see if a test runs ([recover-a-stuck-test.md](how-to/recover-a-stuck-test.md#1-run-status)). |
| `transcript`, `trace` or `verify` shows the check test, not your test. | These commands use the latest test. If you ran `check` after your test, give the id of your test ([read-the-results.md](how-to/read-the-results.md#1-find-the-test-id)). |
| A prompt went to the model in [relay mode](reference/glossary.md#relay-mode). | In relay mode, the [relay](reference/glossary.md#relay) blocks each prompt. Run `nookku status`. If it says `relay mode is off.`, start a test with the prompt `nookku start`. If relay mode is on, the hooks did not run. In Codex, trust the hooks ([In Codex, the model answers my test messages](#in-codex-the-model-answers-my-test-messages)). In Claude Code, install the relay again ([hook kit](how-to/claude-code-hook-kit.md#install), [plugin](how-to/claude-code-plugin.md#install)). |
| Codex does not run the hooks. | Codex runs project hooks only after a person trusts them. Do the trust step ([codex.md](how-to/codex.md#install), [In Codex, the model answers my test messages](#in-codex-the-model-answers-my-test-messages)). |
| Each message reaches the agent two times. | The plugin and the hook kit both run. Use one relay ([Each message reaches the agent two times](#each-message-reaches-the-agent-two-times)). |
| A test does not start. | Find the error text in [Start a test](#start-a-test). |
| The test does not end, or each prompt says that no test runs. | Follow [recover-a-stuck-test.md](how-to/recover-a-stuck-test.md). |
| No `report.md` after the end. | The model writes `report.md` only after the prompt `nookku end`. `nookku end` in a shell, or `/nookku end` in the plugin, ends the test with no [evaluation](reference/glossary.md#evaluation). If `evaluate` is `false` in the configuration, no evaluation starts. If you denied a command of the evaluation, the model can stop. Type the prompt `nookku end` again. If the latest test has no `report.md`, this prompt starts its evaluation ([SPEC.md section 9.1](../SPEC.md#91-start), [test-your-app.md](how-to/test-your-app.md#7-allow-the-evaluation-commands)). In Codex, the sandbox must let the model write in the project ([codex.md](how-to/codex.md#use)). |
| The [audit](reference/glossary.md#audit) exits with 1 or 2. | Read the break or the error in `audit.json` ([read-the-results.md](how-to/read-the-results.md#3-read-the-audit)). For each error text, read [Audit, verify and trace](#audit-verify-and-trace). |
| `nookku verify` says `Seal: BROKEN`. | A file of the test folder changed after the end of the test. Do not trust the changed files. Run a new test ([Audit, verify and trace](#audit-verify-and-trace)). |

## Install

### `nookku: error: unrecognized arguments: --entry python3 agent.py`

(argparse, from `nookku init`) **Cause.** You have version 0.1.0 from PyPI. It has no tests and no entry. Check with `nookku --version`.

**Fix.** Run `uv tool upgrade nookku`. The docs are for version 0.3.0.

### `nookku: command not found`

**Cause.** The folder of `uv tool` programs is not on `PATH`.

**Fix.** Run `uv tool update-shell`, then open a new terminal. The plugin runs `nookku` from `PATH`.

## Start a test

### `nookku: .nookku/config.json has no 'entry' command`

(bridge.py) **Cause.** `config.json` has no `entry`, or it is empty.

**Fix.** Add the entry: `nookku init <harness> --entry "<command>"`, or ask the harness model to run `nookku setup` ([how-to/connect-your-agent.md](how-to/connect-your-agent.md)).

### `nookku: cannot read .nookku/config.json: <reason>`

(config.py) **Cause.** The file does not exist, or it is not valid JSON. `init` gives this error too, and then it writes nothing.

**Fix.** Correct the JSON. To write a new file, remove the file and run `nookku init`.

### `nookku: .nookku/config.json has unknown keys: ['<key>']. Correct or remove them.`

(config.py) **Cause.** `config.json` has a key that Nookku does not know, for example a key with a typo. `start`, `check` and `init` stop with this error. In relay mode, the hook kit blocks each prompt with the same error.

**Fix.** Correct the name of the key, or remove it. [reference/config.md](reference/config.md) lists each key.

### `nookku: .nookku/config.json: 'openai_stream' must be true or false`

(config.py) **Cause.** The key `openai_stream` is not a JSON boolean, for example `"true"` or `1`. `start`, `check`, `init` and `mode on` stop with this error. In relay mode, the hook kit blocks each prompt with it.

**Fix.** Write `true` or `false` with no quotes ([reference/config.md](reference/config.md)).

### `nookku: 'models' must be a list of claude-code, codex`

(bridge.py) **Cause.** `models` has another value, for example `"claude"`.

**Fix.** Use only `claude-code` and `codex`, in a list.

### `nookku: .nookku/config.json: the URL of openai (OPENAI_BASE_URL) must be an http or https URL: ''`

(model_api.py) **Cause.** `model_api` gives an empty URL or a URL that is not `http` or `https`. An empty URL does not fall back to the variable.

**Fix.** Give a full URL, or `null` to take the URL from the variable ([how-to/record-model-calls.md](how-to/record-model-calls.md)).

### `nookku: .nookku/config.json: a backend uses the variable of a model API`

(bridge.py) **Cause.** A backend has `"env": "ANTHROPIC_BASE_URL"` or `"env": "OPENAI_BASE_URL"`, and the model API proxy also records that API.

**Fix.** Remove the backend, or remove that API from `model_api` ([how-to/add-a-backend.md](how-to/add-a-backend.md)).

### `each backend needs the strings 'name', 'env' and 'url'`

(backend.py) **Cause.** A backend object has a missing key, or a key that is not a string. Related texts: `each backend needs its own 'name' and 'env'`, and `backend <name>: 'url' must be an http or https URL`.

**Fix.** Give each backend a unique `name`, a unique `env` and a full `url`.

### `nookku: test <test-id> runs already. End it first.`

(bridge.py) **Cause.** A test runs in this project.

**Fix.** End it with the prompt `nookku end` or with `nookku end` in a shell.

### `nookku: the test did not start:` and `cannot start the entry ['python', 'agent.py']: [Errno 2] No such file or directory: 'python'`

(bridge.py) **Cause.** The first word of the entry is not a program on `PATH`. On macOS, `python` often does not exist.

**Fix.** Use `python3`, or the full path of your app's interpreter, for example `.venv/bin/python`.

### `nookku: the test did not start:` and `the entry exited at start:`

(bridge.py) **Cause.** The entry stopped in its first moments. The lines after the text are the last lines of `app.log`, for example `can't open file '.../agent.py': [Errno 2] No such file or directory`.

**Fix.** The entry runs in the project root. Use a path relative to the root, and run the entry command from the root by hand to see the error.

### `nookku: the test did not start in 30 s:`

(bridge.py) **Cause.** The bridge did not write `current.json` in [30 seconds](../src/nookku/bridge.py), so `start` stopped it. The lines after the text are the last lines of `bridge.log`. The last line names the last step that the bridge did.

**Fix.** Read the lines, and correct the step after the last one. Then start the test again.

## During a test

If a test does not end or its bridge stopped, follow [how-to/recover-a-stuck-test.md](how-to/recover-a-stuck-test.md).

In relay mode, both relays fail closed. If a relay cannot send a message, the message does not go to the model. The relay shows the error and writes it in the relay record with `ok: false` ([SPEC.md section 5](../SPEC.md#5-relays)).

If the entry returns an error, crashes or does not answer in [240 seconds](../src/nookku/stdio.py), the relay shows the error and records it. After a crash, each later message gets the same error, with the last lines of `app.log`. End the test and start a new one.

### `nookku: relay mode is on, but no test runs. Start one with: nookku start. Nothing was sent.`

(kit.py) **Cause.** Relay mode is on, but the bridge does not run. For example, the computer restarted during a test.

**Fix.** Start a test. Or switch relay mode off: `nookku mode off` with the hook kit.

### `nookku: nothing was sent. The message has a lone surrogate U+<hex> at character <n>.`

(kit.py) **Cause.** The message has a lone surrogate: one half of a UTF-16 pair. It is not a Unicode scalar value, so a record cannot hold it ([SPEC.md section 2](../SPEC.md#2-record-format)). The relay never changes a message, so it does not send it. It writes no turn, and the message does not go to the model. `<n>` counts code points from 0.

**Fix.** Correct the message at character `<n>`, then send it again.

### `nookku: the agent sent an error:`

(bridge.py, core.ts) **Cause.** The entry wrote an `error` line. The text after it is the error of your app. With `serve()`, it is the exception, for example `KeyError: 'order'`.

**Fix.** Read the error and `app.log`. The test continues: send the next message.

### `the agent sent no reply in 240 s, so the tap stopped it`

(stdio.py) **Cause.** The entry did not write a line with the request id in [240 seconds](../src/nookku/stdio.py).

**Fix.** Make the app answer faster, or write an `error` line when it cannot answer. The tap does not restart the entry: end the test and start a new one.

### `the agent printed <n> lines on stdout but no reply line for <id> in 240 s, so the tap stopped it. Use nookku.agent.serve() or write logs to stderr. The first line: '<text>'`

(stdio.py) **Cause.** The entry or your app wrote logs on stdout, and no line with the request id came. `<text>` is the [first 80 bytes](../src/nookku/stdio.py#L175) of the first stray line. `nookku check` says `The entry printed lines on stdout, but no reply line.`

**Fix.** Write logs to stderr. In Python, use `nookku.agent.serve()`, which sends all other output to stderr ([how-to/connect-your-agent.md](how-to/connect-your-agent.md)).

### `the agent exited (code <n>)`

(stdio.py) **Cause.** The entry stopped during the test. Each later message gets the same error, with the last lines of `app.log`.

**Fix.** Read `app.log`. End the test and start a new one.

### `nookku: cannot reach the tap at <url>: <reason>`

(bridge.py, kit.py) **Cause.** The bridge or the tap does not run. With no entry, the tap of `tap_url` does not run.

**Fix.** With an entry, end the test and start a new one. With no entry, start `nookku tap` ([how-to/http-tap.md](how-to/http-tap.md)).

### `nookku: relay mode is on, but the nookku command is not on PATH. Install it with: uv tool install nookku. Nothing was sent.`

(plugins/nookku/hooks/nookku-hook.sh; for a tool call it ends with `The tool call did not run.`) **Cause.** The plugin cannot find the `nookku` command. Relay mode is on, or a test runs, so the plugin blocks the prompt and denies each tool call.

**Fix.** Install the command, or put it on `PATH`. Then open a new terminal and start the harness again.

### `nookku: relay mode is on, but the config is broken: <reason>`

(kit.py) **Cause.** The hook kit cannot read `config.json`, or the file has an unknown key. The message does not go to the model or to the agent. `<reason>` is the error that `start` and `check` give for the same file.

**Fix.** Correct the file. [reference/config.md](reference/config.md) lists each key.

### `nookku: the hook failed (<error>). Nothing reached the model.`

(kit.py) **Cause.** The relay failed on this prompt. It fails closed, so it blocked the prompt.

**Fix.** Read the error. If it repeats, open an issue with the text.

### `nookku: the hook failed (<error>). The tool call is denied.`

(kit.py) **Cause.** The deny check failed on a model tool call. It fails closed, so it denied the call. The hook denies it if the folder `.nookku/` exists, also when relay mode is off ([SPEC.md section 5](../SPEC.md#5-relays)).

**Fix.** Read the error. If it repeats, open an issue with the text.

### `nookku: only the tester talks to the agent.`

(kit.py) **Cause.** The relay denied a model tool call that names the address of the tap or the agent. It also denies a call that changes a file of the test. This is the purpose of the deny.

**Fix.** None. Talk to the agent through the relay. To read the conversation, the model uses `nookku transcript` or the `transcript` tool.

### `nookku: during a test, only the tap runs the entry.`

(kit.py) **Cause.** The model tried to run the entry during a test.

**Fix.** None. A shell command that only reads the entry, for example `cat entry.py`, can run. But during a test, the relays deny each tool call that names `.nookku`, except a read with a file tool such as `Read` ([SPEC.md section 5](../SPEC.md#5-relays)). Thus `cat .nookku/entry.py` is denied.

### `nookku: the relay does not send attachments. Nothing was sent.`

(kit.py, shown by register.tsx) **Cause.** In relay mode, the Claude Code plugin got a prompt with an attachment or an image. A command hook gets only the text of a prompt, so the project hooks and the Codex plugin cannot refuse it ([limits.md](limits.md)).

**Fix.** Send text only ([#6](https://github.com/mohanraj00/nookku/issues/6)).

### `nookku: the record is invalid: <path>: line <n>: <reason>. Do not trust this record. The view shows the next turns when the record changes and is valid.`

(kit.py) **Cause.** `nookku view` read a relay record with an invalid line. A line changed after the writer wrote it, or another program wrote it. The view shows this error one time and continues to wait. With `--no-follow`, it shows `nookku: <path>: line <n>: <reason>` and exits with 2.

**Fix.** Do not edit a record. Find the program that wrote the line. After the end of the test, run `nookku verify` to see which files changed.

### `nookku: cannot read the config: <reason>`

(cli.py, from `nookku view` and `nookku transcript`) **Cause.** `config.json` exists, but it is not valid JSON or it breaks the rule for its keys. `<reason>` is the error that `start` gives for the same file. The command exits with 2. `transcript --trace` does not read the config, so it does not give this error.

**Fix.** Correct the file. [reference/config.md](reference/config.md) lists each key.

### Each message reaches the agent two times

**Cause.** The plugin and the hook kit both run in the project. The audit shows `duplicate_send` breaks.

**Fix.** Use one relay. Remove the Nookku hooks from `.claude/settings.local.json`, or disable the plugin. [how-to/choose-a-relay.md](how-to/choose-a-relay.md#switch-from-one-relay-to-the-other) gives the steps.

### In Codex, the model answers my test messages

**Cause.** Codex did not run the hooks, because nobody trusted them. Codex runs project hooks only after a person trusts them.

**Fix.** Start `codex` in the project and accept the hooks prompt. Trust the hooks again after each change to `.codex/hooks.json` ([how-to/codex.md](how-to/codex.md)).

## End a test

### `nookku: the records of a test do not change. Write only report.md. A command that names .nookku may only read.`

(kit.py) **Cause.** After a test, the model tried to write a file of the test folder. Or it ran a command that names `.nookku` and does not pass the read check.

**Fix.** None for the records. If the evaluation needs a command, use a read program from the list in [SPEC.md section 5](../SPEC.md#5-relays), for example `cat`, `jq` or `sed -n`.

### `The bridge did not finish its collection. See bridge.log in the folder.`

(bridge.py) **Cause.** The bridge did not write the end time in the manifest. For example, it did not stop in the wait time of `end`.

**Fix.** Read `bridge.log`. Run `nookku trace` to build the trace again.

### `FAIL: No claude-code model session was identified.`

(bridge.py, from `nookku check`) **Cause.** `models` names `claude-code`, but the tap found no Claude Code session of a process of the entry. The app does not use Claude Code, or it did not start a session for the check message.

**Fix.** Check `models`. Check that the app starts its session for the first message.

### `FAIL: The claude-code session <id> has no session file.`

(bridge.py) **Cause.** The app turns off its session files, for example with `persistSession: false` in the Agent SDK.

**Fix.** Let the app keep its session files during a test. The trace needs them ([limits.md](limits.md)).

### `FAIL: tap_unparsed: tap line <n>: STDIO stdout: a stray line on stdout: '<text>'. Use nookku.agent.serve() or write logs to stderr.`

(bridge.py, from `nookku check`) **Cause.** The entry or your app wrote a log line on stdout. The reply can still come, but the audit of the check test exits with 2. The audit of each real test also exits with 2.

**Fix.** Write logs to stderr. In Python, use `nookku.agent.serve()` ([how-to/connect-your-agent.md](how-to/connect-your-agent.md)). Then run `nookku check` again.

### `FAIL: <class> break (relay line <n>, tap line <n>). <fix>`

(bridge.py, from `nookku check`) **Cause.** The audit of the check test found a break ([SPEC.md section 3.3](../SPEC.md#33-break-classes)). For example, `injected_input` means that the agent received a message that the check did not send.

**Fix.** Follow the fix in the line. `audit.json` in the test folder has the evidence of each break.

### `FAIL: The audit.json of the test is missing. Read bridge.log in the test folder.`

(bridge.py, from `nookku check`) **Cause.** The bridge did not write the audit at the end of the check test. The check fails closed, because it cannot show that the records agree. The text says `is not valid` if the file is not a valid audit report.

**Fix.** Read `bridge.log` in the test folder. It has the error of the audit.

### `nookku check` passes, but the replies are wrong

**Cause.** `check` does not judge the reply. It passes with any reply line, also a fallback text of your app. For example, the entry starts the app with the wrong interpreter, with no environment file, or in the wrong working folder. Then the app can send its fallback text for each message.

**Fix.** Do the 4 steps in [Make sure that check runs your real app](how-to/connect-your-agent.md#make-sure-that-check-runs-your-real-app).

## Audit, verify and trace

### `ERROR record_missing: <path>: No such file or directory`

(record.py) **Cause.** A record file does not exist. The audit exits with 2.

**Fix.** Check the paths. The records of a test are in its test folder.

### `ERROR record_invalid: <path>: line <n>: field input_sha256 does not match 'input'`

(record.py) **Cause.** A line of the record changed after the writer wrote it, or another program wrote it. The audit fails closed and exits with 2.

**Fix.** Do not edit a record. Run `nookku verify` to see which files changed after the end of the test.

### `ERROR tap_unparsed: line <n>: STDIO stdout: a stray line on stdout: '<text>'`

(audit.py) **Cause.** The entry wrote a line on stdout that is not a contract line. The tap wrote an `unparsed` row for it. The audit cannot check that row, so it exits with 2.

**Fix.** Write logs to stderr, or use `serve()`. `nookku check` fails with such a line and gives the same fix.

### `Seal: BROKEN. changed: <file>. Do not trust these records.`

(seal.py) **Cause.** A file of the test folder changed after the end of the test. `nookku verify` exits with 2.

**Fix.** Do not trust the changed files. Run a new test.

### `nookku: the trace was not rebuilt. Seal: BROKEN. ...`

(cli.py) **Cause.** `nookku trace` builds the trace only from sources that agree with the seal.

**Fix.** Run a new test.

### `nookku: no test folder.` or `nookku: no test folder with a manifest.`

(cli.py) **Cause.** The project has no test, or the test id is wrong.

**Fix.** Run `ls .nookku/tests/` and give a test id that exists.

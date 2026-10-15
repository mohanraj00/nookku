# CLI reference

This page lists each command of `nookku`, each flag and each exit code. The parser is in [src/nookku/cli.py](../../src/nookku/cli.py). The test `tests/test_docs.py` checks that each command and each flag of the parser is on this page. It also checks that each flag on this page is in the parser.

```text
nookku [-h] [--version] COMMAND ...
```

| Flag | Meaning |
|---|---|
| `--version` | Print the version and exit with 0. |
| `-h`, `--help` | Print the help of the program or of a command, and exit with 0. |

Each command that takes `--root` uses the current folder by default. The root is the project: the folder that holds `.nookku/`.

An unknown command or flag prints the usage and exits with 2. The error of an unknown command lists the commands, but not the [internal commands](#internal-commands). With no command, `nookku` prints the help and exits with 2.

## Commands of a test

### `nookku start`

Start a test: run the [entry](glossary.md#entry) through the [tap](glossary.md#tap) and switch [relay mode](glossary.md#relay-mode) on ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)). It needs an `entry` in `.nookku/config.json`. The start text gives the same ways to end the test as the [plugin](glossary.md#plugin) and the [project hooks](glossary.md#project-hooks): the prompt `nookku end`, which also starts the [evaluation](glossary.md#evaluation), and `nookku end` in a shell. If `evaluate` is `false`, the text does not name the evaluation ([SPEC.md section 9.1](../../SPEC.md#91-start)).

`start` also starts the [chat page](#nookku-page) of the test and opens it in your browser. The prompt `nookku start` and `/nookku start` in the plugin do the same. `end` stops the page after the page shows the end of the test ([SPEC.md section 5](../../SPEC.md#5-relays)).

- If the browser cannot open, for example over SSH, `start` in a terminal prints the page URL. The prompt `nookku start` and `/nookku start` never show the URL, because the [harness model](glossary.md#harness-model) can see their output. Then run `nookku page` in a separate terminal.
- If the page does not start, `start` prints the reason. The test continues.
- To turn this off, for example for a test in CI, set the config key [`page`](config.md#test-keys) to `false`.
- With `--json`, the text about the page goes to stderr.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `current.json` of the test as JSON, with no `tap_token`, or `{"error": ...}`. |
| `--tester-session ID` | none | The [tester](glossary.md#tester)'s [harness](glossary.md#harness) session id. The [bridge](glossary.md#bridge) never takes this session as a session of the app. |

| Exit code | Meaning |
|---|---|
| 0 | The test started. |
| 1 | The test did not start: no entry, an invalid configuration (for example an unknown key), a test that runs already, or an entry that exited. The text names the cause. |

### `nookku end`

End the test: switch relay mode off, stop the entry and collect its sessions, the [trace](glossary.md#trace), the [audit](glossary.md#audit) and the [seal](glossary.md#seal) ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)). If no test runs, it switches relay mode off.

`end` also waits for the chat page that `start` started, and stops it. A page that you started with `nookku page` continues to run. `end` in a shell gives no evaluation. If the test needs an evaluation, it prints the prompt to type in the harness: `To evaluate the test, type this prompt in your harness: nookku end` ([SPEC.md section 9.1](../../SPEC.md#91-start)). If `config.json` is broken, no evaluation starts, and `end` prints the error.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print the manifest of the test as JSON, or `null` if no test ran. |
| `--evaluation` | off | Print one JSON object: `text`, the end text, and `evaluation`, the evaluation prompt or `null` ([SPEC.md section 9.1](../../SPEC.md#91-start)). The plugin uses it. |

| Exit code | Meaning |
|---|---|
| 0 | Always. |

### `nookku status`

Show relay mode and the running test, for example `relay mode is on. Test <test-id> runs on <tap-url>.` If no test runs, the second sentence is `No test runs.` The prompt `nookku status` gives the same text. In relay mode, the status line of the plugin also shows it.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `{"on": ..., "test": ..., "text": ..., "attachments": ..., "pane": ...}`. `test` is `current.json` with no `tap_token`, or `null`. `text` is the status line of the plugin. `attachments` is the text that refuses a prompt with an attachment in the plugin. Each of `text` and `attachments` is `null` if relay mode is off. `pane` is the data of the Claude Code pane: `test`, `state`, `turns` and `page` ([SPEC.md section 5](../../SPEC.md#5-relays), "Pane"). |

| Exit code | Meaning |
|---|---|
| 0 | Always. |

### `nookku check`

Run a short test with one message, and check the entry and its model sessions ([SPEC.md section 7.1](../../SPEC.md#71-configuration)). It sends the value of the config key `check_message`. The default is `Hello from nookku check. What can you help me with?`. If your app declines this message, set `check_message` to a message that your app answers, with `nookku init <harness> --check-message TEXT` ([config.md](config.md#nookkuconfigjson))

PASS proves the connection, not the reply. PASS means that:

- the entry sent a reply line, not an `error` line;
- the audit of the test exits with 0;
- the test found a model session and its session file for each harness in `models`.

`check` ends its test. The model does not evaluate a check test. If your test ended before `check` and has no `report.md`, the prompt `nookku end` after `check` starts the evaluation of your test. Else it starts no evaluation ([SPEC.md section 9.1](../../SPEC.md#91-start)).

`check` does not judge the text of the reply. A fallback reply of the app also passes. [how-to/connect-your-agent.md](../how-to/connect-your-agent.md#make-sure-that-check-runs-your-real-app) shows how to make sure that the entry runs your real app.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `{"pass": ..., "report": [...]}`. |

| Exit code | Meaning |
|---|---|
| 0 | The entry sent a reply, the audit of the test is clean, and the test found a model session for each harness in `models`. |
| 1 | The check failed, or the test did not start. For example, the audit of the test exits with 1 or 2, the test wrote no valid `audit.json`, or a model session has no session file. |

### `nookku run`

```text
nookku run --script FILE [--entry NAME] [--root PATH] [--json] [--evaluate | --no-evaluate]
```

Run a [scripted test](glossary.md#scripted-test) ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)). It starts a test, sends each message of the script to the entry byte for byte, waits for each reply and ends the test. The script is JSONL with one `{"said": "..."}` row for each turn, or one JSON array of strings. The [test folder](glossary.md#test-folder) gets a copy of the script, and each [relay](glossary.md#relay) row has `"harness": "script"`. `run` does not switch relay mode on.

The output gives the test id, the count of turns, the audit and the trace, and then `PASS` or each `FAIL:` line. It does not give the replies. Read them with `nookku transcript`.

By default, only a person runs `nookku run`: the relay denies it from the model. A person allows the model with `nookku policy set scripts model`.

| Flag | Default | Meaning |
|---|---|---|
| `--script FILE` | required | The script file. |
| `--entry NAME` | the key `entry` | A name in the config key `entries`. It does not take a command line. |
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `{"pass": ..., "report": [...], "evaluation": ...}`. |
| `--no-evaluate`, `--evaluate` | the config key `evaluate` | Print the evaluation prompt at the end, or not. |

| Exit code | Meaning |
|---|---|
| 0 | The audit of the test is clean. |
| 1 | The test did not start, for example the script breaks a rule or the entry name is unknown. Or a turn has no reply, the audit is not clean, or the Codex hooks changed. |

### `nookku script`

```text
nookku script save [TEST] [--root PATH]
```

Save a test as a script ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)). After you fix a defect, send the same messages again with `nookku run --script`. The command writes the `said` text of each turn of the test to `.nookku/scripts/<test id>.jsonl`, byte for byte. The file name records the source test id. The command prints the path and the `nookku run` command. The "Save as script" button of the chat page (`nookku page`) does the same for the test that the page shows.

Only a person runs `nookku script`: the relay denies it from the model, with each policy. The guard also denies a model write to `.nookku/scripts/`, so the model cannot change a saved script before you run it.

| Flag | Default | Meaning |
|---|---|---|
| `ACTION` | required | `save`. |
| `TEST` | the latest test | The test id, or the path of the test folder. |
| `--root PATH` | the current folder | The project. |

| Exit code | Meaning |
|---|---|
| 0 | The command wrote the script. |
| 1 | The `relay.jsonl` of the test is not valid or has no turn, or the command cannot write the file. |
| 2 | No test has this id. |

### `nookku replay`

```text
nookku replay SCRIPT [--base TEST] [--entry NAME] [--root PATH] [--json] [--evaluate | --no-evaluate]
```

Run a saved script again after a fix, and see which replies changed ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)). `replay` runs the script as `nookku run --script` does. Then it compares the new test with the source test of the script, turn by turn. The source test is the test id in the name of the script file, as `nookku script save` names it. The diff uses the reply that the [tap](glossary.md#tap) recorded, not the reply that the harness showed.

The output has the lines of `nookku run`, and then:

- the count of changed turns;
- each changed reply, with `[-deleted words-]` and `{+inserted words+}`. A change of 2 or more words in a row shows as one deleted part and one inserted part. At a terminal, the deleted words are red and the inserted words are green. Set `NO_COLOR` to get no color;
- the 2 test ids to select on the dashboard of `nookku page`, which shows the 2 tests side by side.

A changed reply does not change the exit code. Only a person runs `nookku replay`: the relay denies it from the model, with each policy.

| Flag | Default | Meaning |
|---|---|---|
| `SCRIPT` | required | The script file, for example `.nookku/scripts/<test id>.jsonl`. |
| `--base TEST` | the name of the script file | The test id to compare with. |
| `--entry NAME` | the key `entry` | A name in the config key `entries`. |
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `{"pass": ..., "report": [...], "evaluation": ..., "diff": ...}`. |
| `--no-evaluate`, `--evaluate` | the config key `evaluate` | Print the evaluation prompt at the end, or not. |

| Exit code | Meaning |
|---|---|
| 0 | The audit of the new test is clean. |
| 1 | As for `nookku run`. |
| 2 | `--base` names no test. Nothing ran. |

### `nookku mode`

```text
nookku mode [STATE] [--root PATH] [--tester-session ID]
```

Switch relay mode on or off. With an entry, `on` starts a test and `off` ends it. With no entry, it only switches relay mode ([how-to/http-tap.md](../how-to/http-tap.md)). Before it switches relay mode on, it reads `config.json`, if the file exists. If the file is broken, `on` shows the error and does not switch relay mode on ([#109](https://github.com/mohanraj00/nookku/pull/109)). If the file does not exist, `on` tells you to run `nookku init plugin`, and does not switch relay mode on. If relay mode is already on, it stays on, and the relay blocks each prompt that is not a [control prompt](glossary.md#control-prompt) ([SPEC.md section 7.1](../../SPEC.md#71-configuration)). In the Claude Code plugin, a prompt with an attachment gets the attachment refusal, not the config error. The `/nookku` command of the plugin runs `nookku mode` with its words, and shows the output.

| Argument or flag | Default | Meaning |
|---|---|---|
| `STATE` | `status` | `on`, `off` or `status`. `start` is the same as `on`, and `end` is the same as `off`. |
| `--root PATH` | the current folder | The project. |
| `--tester-session ID` | none | The tester's harness session id. With an entry, the test copies this session when it ends. |

| Exit code | Meaning |
|---|---|
| 0 | `off` or `status` ran, `on` switched relay mode on, or `on` with an entry started a test. |
| 1 | `on` refused relay mode, and the text names the cause. For example, `config.json` is broken or does not exist, the Claude Code or Codex hooks are not ready, Claude Code does not run as the interactive CLI, or the test did not start ([#248](https://github.com/mohanraj00/nookku/issues/248)). |

### `nookku page`

```text
nookku page [--root PATH] [--port PORT] [--open]
```

Serve the chat page: a local web page where you talk to the agent of the running test. The command prints the page URL. Open it in your browser. Stop the page with Ctrl-C.

- The page shows the turns of the running test, else of the latest test, with the start and the end of the test. It asks the server for new turns each [1 second](../../src/nookku/page/app.js#L5).
- The link "All tests" opens the dashboard: one row for each test of the project, with the start time, the state, the count of turns, [breaks](glossary.md#break) and [findings](glossary.md#findings), and the seal state. Filter the rows by state, and by a break or a finding. Sort them by date. A click on a row opens the chat page of that test. If the test ended, that page is read-only. The dashboard reads the test folders and changes no file. It asks the server for new rows each [5 seconds](../../src/nookku/page/dashboard.js#L5) ([SPEC.md section 5](../../SPEC.md#5-relays)).
- On the dashboard, select 2 tests with their check boxes, then click "Compare". The diff page shows the 2 tests side by side, turn by turn, with the counts of breaks and findings of each test at the top. It marks each changed reply, and it shows the deleted and the inserted words. The older test is on the left.
- Each page has a light and a dark theme. The "Theme" button changes the theme: auto (the theme of the system), light or dark. The browser keeps your choice. Each text color pair meets WCAG AA, and the test `tests/test_page_theme.py` checks the [colors](../../src/nookku/page/theme.css).
- Keys: in the message box, Enter sends, Shift+Enter adds a line, and Up puts the last unsent message back in an empty box. On a page, `j` and `k` go to the next and the previous turn or test, `/` goes to the search of the dashboard, and `?` shows the list of keys. Only Enter in the message box sends a message. No other key works while you type in a text field.
- The search of the dashboard shows only the tests that hold the search text. It sends no request.
- When you send a message, the page server sends it to the [tap](glossary.md#tap) with the relay function of the hook, and writes a turn with `"harness": "pane"` ([SPEC.md section 5](../../SPEC.md#5-relays)). The message does not go into the harness, so the [harness model](glossary.md#harness-model) cannot see it.
- Start and end the test in the harness, with `nookku start` and `nookku end`. The page does not run these prompts.
- Under each reply, you can give a thumbs up, a thumbs down and a comment. The page server writes each note to `notes.jsonl` in the test folder. It writes a note only while the test runs, and the seal covers the file. The evaluation reads your notes and cites them in `report.md` ([SPEC.md section 2.3](../../SPEC.md#23-notes-record)).
- The page sends only if relay mode is on and the test is not a [scripted test](glossary.md#scripted-test). After `nookku end` begins, the page sends nothing.
- If no test runs, or the page server cannot send the message, the page shows the error. Nothing goes to a model.
- The page shows a reply of the agent as Markdown: headings, emphasis, lists, links, tables, block quotes and code. HTML in a reply shows as text. The button "Text" shows the exact text of the reply. A `mermaid` or `vega-lite` fence shows as code.
- The page shows an image or a video that a reply names as an `https:` URL, a `data:` URI or a file path. A relative path starts at the project root. The page shows a file only if it is in the project or in the folder of the test, and not in `.nookku/` outside the test folder. The page shows an SVG in a sandbox, with no scripts. A file of an `https:` URL loads only after you click its "Load" button, which shows the URL.
- For another file, for example a PDF, the page shows an "Open" button. A click opens a copy of the file with the system app. The page server removes the copies when it stops. The page does not open a program, a script, an HTML file or an SVG. On Windows, the page does not show or open a file path, because the server cannot check the open file there ([SPEC.md section 5](../../SPEC.md#5-relays)).
- The server listens only on `127.0.0.1`. The URL has a random token. The server refuses a request with a wrong `Host` or `Origin` header.
- The first open of the URL gives the browser a session cookie and a page key. The page keeps the key in the memory of its tab, and sends it with each request. A request of data needs the cookie and the key, because a browser also sends the cookie to another port of `127.0.0.1` ([SPEC.md section 5](../../SPEC.md#5-relays), "Session"). A reload of the tab keeps the key. If you close each tab of the page, the page has no key: end the test and start a new one, or run `nookku page` again.
- Run `nookku page` in a separate terminal. Do not run it with `!` in the harness, because the harness shows the output to the model. In a harness shell, `nookku page` refuses to start.
- Only you get the URL, in the terminal of `nookku page`. Do not give the URL to the harness model, because with it the model can send messages as you. The server writes only its port and its pid to `.nookku/page.json`, and the guard denies a model tool call to that port. The guard also denies a model command that runs `nookku page`.
- The "Save as script" button writes the test that the page shows as a script, the same as `nookku script save`.
- The "Export" button downloads one HTML file of the test that the page shows, the same as [`nookku export`](#nookku-export).
- `nookku start` starts the page with the test, so you do not have to run `nookku page` ([`nookku start`](#nookku-start)). If a page server of the project runs already, `start` starts no second page.
- `nookku page --open` opens the chat page of the running test in your browser, at the session URL `/p/s/`. This URL holds no secret. The page opens only in the browser that got the session at the start of the test. The new tab gets the page key from the open tab of the page, so keep that tab open. It makes no new session and starts no page server. It prints no URL, so you can run it in the harness. If the browser has no session, the page tells you how to get a new one: end the test and start a new one, or run `nookku page` in a separate terminal. The "Open chat" button of the Claude Code pane runs it. The guard denies it from the model.
- One page server runs for each project. Stop the page with Ctrl-C. The page also stops when the terminal closes.
- The relay in the harness chat still works, for example over SSH, in CI and in `codex exec`.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--port PORT` | a free port | The port on `127.0.0.1`. |
| `--open` | off | Open the chat page of the running test in the browser, at the session URL, which holds no secret. Make no session. Print no URL. Exit with 1 if the page did not open. |

| Exit code | Meaning |
|---|---|
| 0 | The page stopped. |
| 1 | The port is not valid, the server cannot listen on the port, a page server of this project runs, or the command runs in a harness shell. |

## Commands that read a test

### `nookku view`

Print each relayed turn. Both forms of the relay use it to show each reply in a second terminal. With an entry, it shows the turns of the latest test, and it follows to the next test. With no entry and no `--record`, it shows the configured record, and it reads the config again before each poll. If the config gives a different record, the view prints `════ record <path> ════` and follows that record. When the config gets an entry, the view follows each test from that time. You can start the view before `nookku init`.

If the [relay record](glossary.md#relay-record) has an invalid line, `view` shows the error with the file and the line on stderr. Without `--no-follow`, it shows the error one time and continues to wait. When the record changes and is valid, it shows the next turns. With `--no-follow`, it stops with exit code 2. If the record does not start with the turns that the view showed, for example because a person removed a line, the view prints `──── the record changed: the view shows each turn again ────` and shows each turn again from turn 1. A test has no relay record before its first turn, so the view of such a test shows no turn and exits with 0. After the end of a test, `nookku verify` shows a record that is missing.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--no-follow` | off | Print the turns so far and stop. Without it, `view` waits for new turns until you stop it. |
| `--record FILE` | from the config | The relay record to show. |
| `--text` | on | The text view for a terminal. It is the only view of `nookku view` now. The chat page is [`nookku page`](#nookku-page). |

| Exit code | Meaning |
|---|---|
| 0 | The view stopped. |
| 2 | The config cannot be read. With `--no-follow`: the relay record is invalid, or, with no entry, the configured record does not exist. |

### `nookku transcript`

Print the exact conversation for the model to evaluate ([SPEC.md section 5](../../SPEC.md#5-relays)). With an entry, the scope is the latest test. A check test that ended does not count: after `nookku check`, the scope is the test before it ([SPEC.md section 9.1](../../SPEC.md#91-start)).

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--test ID` | the latest test that is not a check test that ended | The test to print: the test id, or the path of the test folder. |
| `--trace` | off | Print each turn as the app got it (from `tap.jsonl`), with the model items and the [findings](glossary.md#findings) of that turn ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)). It ignores `--record`, `--all` and `--session`. |
| `--all` | off | With no entry: each session of the record, not only the latest one. |
| `--session ID` | none | Only the turns of this harness session. |
| `--compact` | the config key `transcript_compact` | With `--trace`: show a repeated text of 200 or more characters one time. The bound is a chosen value, not a measurement ([`COMPACT_MIN`](../../src/nookku/evaluation.py#L21-L22)). After that, it shows as a reference with its `[trace.jsonl:N]`, its SHA-256 and its length. An OpenTelemetry attribute with the text of a session item of the same turn also shows as a reference ([SPEC.md section 9.2](../../SPEC.md#92-evaluation-prompt)). |
| `--no-compact` | the config key `transcript_compact` | With `--trace`: show each text in full. |
| `--record FILE` | from the config | The relay record to print. |

| Exit code | Meaning |
|---|---|
| 0 | The transcript printed. With `--trace`, also if a record is invalid: then the first line says `Record: INVALID` and the transcript shows no turn. |
| 2 | No test folder (with `--trace`), the config cannot be read, or the relay record is missing or invalid. |

### `nookku audit`

Compare the relay record with the [tap record](glossary.md#tap-record) ([SPEC.md section 3](../../SPEC.md#3-audit)).

| Flag | Default | Meaning |
|---|---|---|
| `--tap FILE` | required | The tap record. |
| `--relay FILE` | required | The relay record. |
| `--json` | off | Print the report as JSON. The bridge writes this form to `audit.json`. |
| `--script FILE` | none | The script of a scripted test. The audit also compares the relay record with it ([SPEC.md section 3.2](../../SPEC.md#32-matching), step 7). |

| Exit code | Meaning |
|---|---|
| 0 | The records are valid and have no [break](glossary.md#break). |
| 1 | The records are valid and have one or more breaks. |
| 2 | A record is missing or invalid, or the tap has an unparsed exchange. |

### `nookku trace`

```text
nookku trace [TEST] [--root PATH] [--json]
```

Build the trace of a test again, and show its findings ([SPEC.md section 8](../../SPEC.md#8-trace)). If the test has a seal, it rebuilds only from sources that agree with the seal.

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id, or the path of the test folder. |
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print `findings.json`. |

| Exit code | Meaning |
|---|---|
| 0 | The trace was built. |
| 2 | No test folder with a manifest, or the seal is broken and the trace was not rebuilt. |

### `nookku export`

```text
nookku export [TEST] [--root PATH] [--out FILE]
```

Write a test as one HTML file, so you can give it to a person who does not have the project or nookku. The file holds the CSS, the script and the data inline. It shows the chat, the trace steps, the notes, the audit result and the seal state ([SPEC.md section 5](../../SPEC.md#5-relays)).

- The file loads nothing from the network. A link or a web image shows as text with its URL.
- The file runs no script and no HTML from the agent. It holds no page URL and no page token.
- An image or a video file that a reply names with a Markdown link or image goes into the file, with the file rule of the chat page. A path in the text of a reply adds no file. If a reply names a file only in code, the file shows it in a list at its end. A file larger than [4 MiB](../../src/nookku/export.py#L41-L44), or a file after a sum of 32 MiB, shows as its path. These limits are chosen values, not measurements.
- The command reads the test and changes no record. It does not write into `.nookku/`, into a test folder or into the seal home.
- On a system that cannot open a file relative to a folder (Windows), the command writes nothing and exits with 1. Use the "Export" button of the chat page there.

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id, or the path of the test folder. |
| `--root PATH` | the current folder | The project. |
| `--out FILE` | `<test id>.html` in the current folder | The HTML file to write. |

| Exit code | Meaning |
|---|---|
| 0 | The file was written. |
| 1 | The command must not write to the path, for example a path in `.nookku/` or a link, or it cannot write the file. |
| 2 | No test folder. |

### `nookku verify`

```text
nookku verify [TEST] [--root PATH] [--json]
```

Check that no record of a test changed after its end ([SPEC.md section 7.4](../../SPEC.md#74-seal)). The output starts with the test id, for example `Test 20261011-184952-8a8d. Seal: intact. No record changed after the end of the test.` With no `TEST`, the id shows which test the command checked. `--json` prints only the result of SPEC.md section 7.4.

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id, or the path of the test folder. |
| `--root PATH` | the current folder | The project. |
| `--json` | off | Print the result as JSON. |

| Exit code | Meaning |
|---|---|
| 0 | The seal is intact. |
| 2 | The seal is broken, the test has no seal, or there is no test folder. |

## Commands that install or connect

### `nookku init`

```text
nookku init HARNESS [--root PATH] [--entry COMMAND] [--models LIST] [options]
nookku init --remove HARNESS [--root PATH]
```

Write the config, and the [project hooks](glossary.md#project-hooks) of a harness. It writes `.nookku/config.json`, the files `.nookku/mode` and `.nookku/nookku-state`, and the hooks: `.codex/hooks.json` for Codex, `.claude/settings.local.json` for Claude Code. It keeps your other hooks, also a hook in the same group as a hook of nookku. With `plugin`, it writes no hooks, because the nookku plugin has them. Do not use the plugin and the project hooks in one project, or each message is sent two times.

If `config.json` exists, `init` keeps each key and changes only the keys of the flags that you give. For example, a second run keeps `backends` and `"evaluate": false`. It prints the keys that it changed and the keys that it kept. A new `config.json` gets each key. The default of a flag applies only to a new file.

If `config.json` has an unknown key, or if `config.json` or the hook file is not valid JSON, `init` writes nothing. Correct the file, then run `init` again. If a flag gives a value that breaks the rule of its key, for example a backend URL that is not `http` or `https`, or one API two times in `--model-api`, `init` also writes nothing.

For example, this run writes the backend and the model APIs of the [full toy shop](../../examples/toy-shop-full/README.md#run-it), and keeps each other key:

```bash
nookku init claude-code --backend stock STOCK_URL http://127.0.0.1:9001 --model-api anthropic --model-api openai=http://127.0.0.1:9002/v1
```

The output starts with `Project root:` and the absolute root, then gives the absolute path of each file that `init` wrote. If the root is in a state folder or a test folder, for example `.nookku/tests/<id>`, the target of a `.nookku` symlink, or a copied test folder, `init` writes nothing, exits with 1 and names the project folder to use ([code](../../src/nookku/cli.py), [test](../../tests/test_cli.py)). If the root has no `config.json` and is not the top level of its git work tree, `init` prints a warning that names the top level. It still writes the files.

| Argument or flag | Default | Meaning |
|---|---|---|
| `HARNESS` | | `codex`, `claude-code` or `plugin`. |
| `--root PATH` | the current folder | The project. |
| `--entry COMMAND` | none | The entry command of a test, as one string. The shell rules split it into arguments. |
| `--models LIST` | none | The app's model harnesses, separated by commas: `claude-code`, `codex` or both. |
| `--tap-url URL` | `http://127.0.0.1:8800/` | The config key `tap_url`. |
| `--agent-url URL` | empty | The config key `agent_url`. |
| `--adapter NAME` | `json` | The config key `adapter`. |
| `--message-field PATH` | `text` | The config key `message_field`. |
| `--reply-field PATH` | `reply` | The config key `reply_field`. |
| `--openai-model NAME` | empty | The config key `openai_model`. |
| `--openai-stream`, `--no-openai-stream` | none | The config key `openai_stream`: `--openai-stream` sets it to `true`, and `--no-openai-stream` sets it to `false`. With neither flag, a new file gets `false`, and an existing file keeps its value. |
| `--record FILE` | `.nookku/relay.jsonl` | The config key `record`. |
| `--check-message TEXT` | `Hello from nookku check. What can you help me with?` | The config key `check_message`: the one message of `nookku check`. |
| `--model-reply-field PATH` | empty | The config key `model_reply_field`: the dot path of the client text in a structured model output. |
| `--model-reply-match MODE` | `normalized` | The config key `model_reply_match`: `exact`, `normalized` or `off`. |
| `--repeated-reply COUNT` | `2` | The config key `repeated_reply`: the count of consecutive turns with the same reply that gives a finding. `0` turns the check off. |
| `--backend NAME ENV URL` | none | The config key `backends`: one backend, with its name, the variable of its URL and its real URL ([how-to/add-a-backend.md](../how-to/add-a-backend.md)). Give the flag one time for each backend. The flags replace the full list. |
| `--model-api API[=URL]` | none | The config key `model_api`: one model API to record, `anthropic` or `openai`. `API=URL` gives the upstream URL, and `API` alone takes the URL from the variable ([how-to/record-model-calls.md](../how-to/record-model-calls.md)). Give the flag one time for each API. The flags replace the full key with the object form. With no flag, a new file gets `true`. |
| `--remove` | off | Remove the project hooks of nookku, and keep each other hook and key. `HARNESS` must be `claude-code` or `codex`. It takes no other flag. |

[config.md](config.md#nookkuconfigjson) explains each key.

| Exit code | Meaning |
|---|---|
| 0 | The files were written. |
| 1 | Nothing was written: `config.json` or the hook file cannot be read, or `config.json` has an unknown key. The text names the cause. |

`init --remove` removes each hook whose command contains `nookku hook` or `verbatim_relay hook` from the hook file of the harness. It removes a group or an event that then has no hook. It keeps the file, also as `{}`, and does not change the state folder. It prints the absolute path of the file and the count of removed hooks, or that the file has no hook of nookku. If a test runs or relay mode is on, also in the `.verbatim-relay/` folder of 0.3, it changes nothing and exits with 1, because without the hooks a message in relay mode goes to the model. If relay mode comes on while it runs, it puts the hooks back and exits with 1. If the hook file cannot be read, it changes nothing and exits with 1 ([code](../../src/nookku/kit.py), [test](../../tests/test_kit.py)).

### `nookku policy`

```text
nookku policy [set KEY VALUE] [--root PATH]
```

Print each key of the [policy file](glossary.md#policy-file) `.nookku/policy.json` with its value, as JSON. With `set`, change one key, then print the keys. Only a person runs this command, in a shell. The relay denies it from the model ([SPEC.md section 7.9](../../SPEC.md#79-policy-file)). [config.md](config.md#nookkupolicyjson) explains the file.

| Argument or flag | Default | Meaning |
|---|---|---|
| `ACTION` | none | `set` changes one key. With no action, the command only prints the keys. |
| `KEY` | | The key to change. |
| `VALUE` | | The new value of the key. |
| `--root PATH` | the current folder | The project. |

| Exit code | Meaning |
|---|---|
| 0 | The keys were printed. With `set`, the key was changed first. |
| 1 | The policy file is not valid, the key is not known, or the value is not valid. The text names the cause. Nothing was changed. |
| 2 | The arguments are not complete. |

### `nookku setup`

Print the guide that connects a test to the app ([setup.md](../../src/nookku/setup.md)). A [harness model](glossary.md#harness-model) reads it and writes the entry ([how-to/connect-your-agent.md](../how-to/connect-your-agent.md)).

| Exit code | Meaning |
|---|---|
| 0 | Always. |

### `nookku tap`

```text
nookku tap (--agent URL | --cmd -- COMMAND...) --record FILE [options]
```

Run the tap proxy in front of the agent ([SPEC.md section 4](../../SPEC.md#4-tap)). A test starts it for you, so you need this command only for an agent that is an HTTP server ([how-to/http-tap.md](../how-to/http-tap.md)).

| Flag | Default | Meaning |
|---|---|---|
| `--agent URL` | none | HTTP mode: the agent's base URL. |
| `--cmd` | off | Stdio mode: start the command after `--` as the agent. |
| `--record FILE` | required | The tap record (JSONL). The tap adds rows to it. |
| `--listen HOST:PORT` | `127.0.0.1:8800` | The address of the tap. |
| `--timeout SECONDS` | [240](../../src/nookku/stdio.py) | The seconds to wait for the agent. |
| `--log PATH` | `app.log` next to the record | Stdio mode: the file for the agent's stderr. |
| `--adapter NAME` | `json` | `json` or `openai` ([SPEC.md section 4.1](../../SPEC.md#adapters)). |
| `--message-field PATH` | `text` | `json` adapter: the field path of the message in the request. |
| `--reply-field PATH` | `reply` | `json` adapter: the field path of the reply in the response. |

Give exactly one of `--agent` and `--cmd`.

In stdio mode, the tap accepts a `POST` only with its token in the header `X-Nookku-Token` ([SPEC.md section 4.2](../../SPEC.md#42-stdio-mode)). The tap takes the token from the variable `NOOKKU_TAP_TOKEN`. The value must have 43 characters or more, else the tap does not start. Use a random value, for example from `python -c "import secrets; print(secrets.token_urlsafe(32))"`. If the variable has no value, the tap makes a random token and writes it to stderr at start. In HTTP mode, the tap checks no token ([SPEC.md section 4.1](../../SPEC.md#41-http-mode)).

| Exit code | Meaning |
|---|---|
| 0 | The tap stopped, for example after Ctrl-C. |
| 2 | The flags are wrong, for example both `--agent` and `--cmd`. |

## Internal commands

The relays and the bridge run these commands. You do not run them yourself. `nookku --help` does not show these commands.

### `nookku hook`

The hook command that `init` writes into the hook file. It reads one hook event as JSON on stdin and writes the answer on stdout ([SPEC.md section 5](../../SPEC.md#5-relays)).

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | from the event | The project. With no `--root`, a Claude Code hook takes `CLAUDE_PROJECT_DIR`, and each hook then takes the `cwd` of the event, else its working folder. The plugin gives no `--root`. |
| `--harness NAME` | required | `codex` or `claude-code`. |

| Exit code | Meaning |
|---|---|
| 0 | The hook answered. If the hook fails in relay mode, it still blocks the prompt. |
| 2 | A wrong argument, an event that cannot be read, or both the old and the new state folder in the project. Exit 2 blocks the event, so the relay fails closed. |

### `nookku mcp`

The MCP server that gives the model the read-only tools `transcript` and `status`. It reads one JSON-RPC message on each line of stdin and writes each answer on stdout. A harness starts it from its MCP configuration ([SPEC.md section 5](../../SPEC.md#5-relays)). The plugin does not start it yet: [#216](https://github.com/mohanraj00/nookku/issues/216) adds it to the plugin.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. Claude Code and Codex start the server of the plugin in the project. The server does not read `CLAUDE_PROJECT_DIR`, because a Codex can inherit it from a Claude Code session of another project. |

| Exit code | Meaning |
|---|---|
| 0 | stdin ended. |

### `nookku bridge`

The background process of a test ([architecture.md](../architecture.md#the-bridge)). `start` runs it.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | required | The project. |
| `--test ID` | required | The test id. |
| `--tester-session ID` | none | The tester's harness session id. |
| `--entry-name NAME` | none | The name of the entry in `entries`, from `nookku run --entry`. |
| `--script-source FILE` | none | The absolute path of the script of a scripted test, for the manifest. `run` copies the script into the test folder before it starts the bridge. |
| `--check` | off | The test is a test of `nookku check`. The manifest records `"check": true`, so the model does not evaluate the test ([SPEC.md section 9.1](../../SPEC.md#91-start)). |

| Exit code | Meaning |
|---|---|
| 0 | The test ended. |
| 1 | The bridge could not start the entry, the entry exited at start, or the bridge could not read the start time of its process. |

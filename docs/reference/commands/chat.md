# `nookku chat`

Release: nookku 0.6.2.

```text
nookku chat [--root PATH] [--tests-dir PATH] [--port PORT] [--open]
```

Serve the chat page: a local web page where you talk to the agent of the running test. The chat page is the main view of a test. `nookku view` is the alternative for a terminal ([`nookku view`](view.md)). The command prints the page URL. Open it in your browser. Stop the page with Ctrl-C.

`nookku page` is the old name of this command ([#394](https://github.com/mohanraj00/nookku/issues/394)). In this release, it works the same and prints one note on stderr: the name changes to `nookku chat`, and `nookku page` goes away in a later release. Use `nookku chat`. The [relay](../glossary.md#relay) denies both names to the [harness model](../glossary.md#harness-model).

## The pages

- **Header.** Each page starts with the same header: the Nookku mark (2 eyes) and the name "Nookku". On the chat page, the header then shows the state of the test (No test, Running, Ended or Stopped), the test id, and the buttons "End test", "Save as script", "Export" and "All tests".
- **"⋯" menu.** The "⋯" button at the right of the header opens the menu. "Theme" sets Auto, Light or Dark. "Width" sets the width of the conversation: Auto, Narrow or Wide. Auto is the default of each. The Auto theme follows the system, and the Auto width follows the window. The browser keeps your choices for each page. The exported file has the same style, and its theme follows the system.
- **Narrow window.** If the page is [640 px](../../../src/nookku/page/app.css#L339) wide or less, a chosen value, the "⋯" menu also holds "End test", "Save as script", "Export" and "All tests".
- **"All tests".** This button opens the dashboard: one row for each test of the project, with the start time, the state, the count of turns, [breaks](../glossary.md#break) and [findings](../glossary.md#findings), and the [seal](../glossary.md#seal) state. Filter the rows by state, and by a break or a finding. Sort them by date. The search shows only the tests that hold the search text, and it sends no request. A click on a row opens the chat page of that test. If the test ended, that page is read-only. The dashboard reads the [test folders](../glossary.md#test-folder) and changes no file. It asks the server for new rows each [5 seconds](../../../src/nookku/page/dashboard.js#L5) ([SPEC.md section 5](../../../SPEC.md#5-relays)).
- **Diff page.** On the dashboard, select 2 tests with their check boxes, then click "Compare". "Compare" works only with 2 selected tests ([compare.js](../../../src/nookku/page/compare.js#L11), checked by `tests/test_replay.py::test_compare_opens_the_diff_only_with_2_tests_the_older_on_the_left`). The diff page "Compare 2 tests" shows the 2 tests side by side, turn by turn, with the counts of breaks and findings of each test at the top. It marks each changed reply, and it shows the deleted and the inserted words. The older test is on the left. Its header has "All tests" and "Chat page".
- **Colors.** Each text color pair meets WCAG AA in the light and the dark theme. The test `tests/test_page_theme.py` checks the [colors](../../../src/nookku/page/theme.css).
- **Keys.** In the message box, Enter sends, Shift+Enter adds a line, and Up puts the last unsent message back in an empty box. On a page, `j` and `k` go to the next and the previous turn or test, `/` goes to the search of the dashboard, and `?` shows the list of keys. Only Enter in the message box sends a message. No other key works while you type in a text field.

## Send a message

- The page shows the turns of the running test, else of the latest test, with the start and the end of the test. It asks the server for new turns each [1 second](../../../src/nookku/page/app.js#L5).
- Your messages are on the right and the replies of the agent are on the left. Each message shows its source (page, Claude Code, Codex or script) and its state: sent, sending or not sent. If the [tap](../glossary.md#tap) got the message, the message also shows its time.
- Under the message box, the label "[Bridge](../glossary.md#bridge) mode on" tells you that the page sends your message to the agent of the running test, and that the harness model does not see it. "Bridge mode off" tells you that no test runs or that the test ended, so the page sends nothing.
- When you send a message, the page server sends it to the [tap](../glossary.md#tap) with the relay function of the hook, and writes a turn with `"harness": "pane"` ([SPEC.md section 5](../../../SPEC.md#5-relays)). The message does not go into the [harness](../glossary.md#harness), so the harness model cannot see it.
- The reply to a message from the chat page shows only on the page. It does not show in the harness chat. `nookku view` and `nookku transcript` also show the turn. A message that you type in the harness shows its reply in the harness and on the page.
- The page sends only if [relay mode](../glossary.md#relay-mode) is on and the test is not a [scripted test](../glossary.md#scripted-test). After `nookku end` begins, the page sends nothing.
- If no test runs, or the page server cannot send the message, the page shows the error. Nothing goes to a model. If a send fails, the page shows the error of the relay and a "Put back in the box" button. If the relay showed no reply for a turn, the page tells you so.
- Under each reply, you can give a thumbs up, a thumbs down and a comment. The page server writes each note to `notes.jsonl` in the test folder. It writes a note only while the test runs, and the seal covers the file. The [evaluation](../glossary.md#evaluation) reads your notes and cites them in `report.md` ([SPEC.md section 2.3](../../../SPEC.md#23-notes-record)).

## Show a reply

- The page shows a reply of the agent as Markdown: headings, emphasis, lists, links, tables, block quotes and code. HTML in a reply shows as text. The button "Text" shows the exact text of the reply. A `mermaid` or `vega-lite` fence shows as code.
- The page shows an image or a video that a reply names as an `https:` URL, a `data:` URI or a file path. A relative path starts at the project root. The page shows a file only if it is in the project or in the folder of the test, and not in `.nookku/` outside the test folder. The page shows an SVG in a sandbox, with no scripts. A file of an `https:` URL loads only after you click its "Load" button, which shows the URL.
- For another file, for example a PDF, the page shows an "Open" button. A click opens a copy of the file with the system app. The page server removes the copies when it stops. The page does not open a program, a script, an HTML file or an SVG. On Windows, the page does not show or open a file path, because the server cannot check the open file there ([SPEC.md section 5](../../../SPEC.md#5-relays)).

## Start, end, export and save

- `nookku start` starts the page with the test, so you do not have to run `nookku chat` ([`nookku start`](start.md)). If a page server of the project runs already, `start` starts no second page.
- Start the test in the harness, with the prompt `nookku start`. The page does not start a test.
- While the test runs, the "End test" button ends it, after you confirm on the page. It does the same as `nookku end` in a shell: it gives no evaluation. The page server continues, so "Export" and "Save as script" still work. To start the evaluation, type the prompt `nookku end` in the harness. That also stops the page server. If no test runs, the page server stops after [15 minutes](../../../src/nookku/page.py) (`IDLE_LIMIT`) with no request of yours. This applies to the page server that `nookku start` started and to the page server of `nookku chat`. `--no-idle-stop` turns this stop off for `nookku chat`. A running test keeps it on, and each click, send or page load starts the 15 minutes again. The poll that the page makes by itself each few seconds does not count. If the page sends a message at that time, the button ends nothing: wait for the reply, then try again.
- The "Export" button and [`nookku export`](export.md) give the same HTML file. The same code builds it, and its name is `<test id>.html`. The button exports the test that the page shows and saves the file in the download folder of your browser. The command saves it in the current folder, or at `--out FILE`.
- The "Save as script" button writes the test that the page shows as a script, the same as [`nookku script save`](script.md).
- One page server runs for each project. Stop the page with Ctrl-C. The page also stops when the terminal closes. `nookku chat --stop` stops the page server of this project, also the page server that `nookku start` started. The running test continues.
- When the page server stopped, the page says so, with the commands that start a new page: `nookku chat` in a separate terminal, or the prompt `nookku start`. The tab of the stopped page does not connect again.
- The relay in the harness chat still works, for example over SSH, in CI and in `codex exec`.

## The URL and the session

- The server listens only on `127.0.0.1`. The URL has a random token. The server refuses a request with a wrong `Host` or `Origin` header.
- The first open of the URL gives the browser a session cookie and a page key. The page keeps the key in the memory of its tab, and sends it with each request. A request of data needs the cookie and the key, because a browser also sends the cookie to another port of `127.0.0.1` ([SPEC.md section 5](../../../SPEC.md#5-relays), "Session"). A reload of the tab keeps the key. If you close each tab of the page, the page has no key: end the test and start a new one, or run `nookku chat` again.
- Run `nookku chat` in a separate terminal. Do not run it with `!` in the harness, because the harness shows the output to the model. In a harness shell, `nookku chat` refuses to start.
- Only you get the URL, in the terminal of `nookku chat`. Do not give the URL to the harness model, because with it the model can send messages as you. The server writes only its port, its pid and the start time of its process (`pid_start`) to `.nookku/page.json`, and the guard denies a model tool call to that port. The guard also denies a model command that runs `nookku chat`, with each of its 2 names.
- `nookku chat --open` opens the chat page of the running test in your browser, else the page of the latest test if it still runs after an end with no evaluation, at the session URL `/p/s/`. This URL holds no secret. The page opens only in the browser that got the session at the start of the test. The new tab gets the page key from the open tab of the page, so keep that tab open. It makes no new session and starts no page server. It prints no URL, so you can run it in the harness. If the browser has no session, the page tells you how to get a new one: end the test and start a new one, or run `nookku chat` in a separate terminal. The "Open chat" button of the Claude Code pane runs it. The guard denies it from the model.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--port PORT` | a free port | The port on `127.0.0.1`. |
| `--no-idle-stop` | off | Do not stop the page server after [15 minutes](../../../src/nookku/page.py) (`IDLE_LIMIT`) with no request of yours and no running test. With no flag, the page server stops, removes `page.json` and prints `The chat page stopped after 15 minutes with no use and no test.` |
| `--open` | off | Open the chat page of the running test in the browser, at the session URL, which holds no secret. Make no session. Print no URL. Exit with 1 if the page did not open. |
| `--stop` | off | Stop the page server of this project with `SIGTERM`, with the lock, pid and start time checks of the end ([SPEC.md section 5](../../../SPEC.md#5-relays)). If `page.json` is missing or names a different pid, read the holder pid of `page.lock` from the OS. Send the signal to that holder only after these checks. The state folder and `page.lock` must not be symbolic links. `page.lock` must have exactly one hard link. The lock file must stay the same between the two holder checks. The holder must still hold the lock. Its start time must be known. Its command must be a `nookku chat` command of this Python. Its project root must resolve to this project root. Read its root from `--root`. If that argument is missing or relative, use the working folder of the holder from the OS. If the OS cannot give the root, send no signal. If a check fails, send no signal. Print that nookku cannot confirm that pid is the chat page, give the `kill <pid>` step and exit with 1. Print `The chat page of this project (pid N) stopped.` or `No chat page of this project runs.` and exit with 0. If the OS gives no pid, the stop text is `The chat page of this project stopped.` If a process still holds `page.lock` after the stop, or the server does not stop in [2 seconds](../../../src/nookku/page_auto.py) (`STOP_WAIT`), send no further signal, print the `kill <pid>` step and exit with 1. Only if the OS gives no holder pid, the text gives the absolute path of `page.lock`, with `lsof` (macOS) and `fuser` (Linux) to find the pid. The guard denies it from the model. |

| Exit code | Meaning |
|---|---|
| 0 | The page stopped: Ctrl-C, a signal or the idle stop. |
| 1 | The port is not valid, the server cannot listen on the port, a page server of this project runs, or the command runs in a harness shell. |

## Example

In a separate terminal, in the project `~/shop`. The token in the URL is different on each start:

```bash
nookku chat
```

```text
Chat page: http://127.0.0.1:64141/p/<token>/
Open this URL one time, in one browser. Stop the page with Ctrl-C. The page also stops after 15 minutes with no use and no test.
```

Stop the server with Ctrl-C.

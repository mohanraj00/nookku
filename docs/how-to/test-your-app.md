# Test your own app

This guide takes your own app from the install to the results of a first [test](../reference/glossary.md#test). Each step gives the expected output, so you can compare your screen with it.

I made the output with the toy shop agent of this repo ([examples/toy-shop/agent.py](../../examples/toy-shop/agent.py)) as the app, nookku 0.4.0 ([version](../../src/nookku/__init__.py)) and the [project hooks](../reference/glossary.md#project-hooks) of Claude Code. I gave each prompt, and the command of step 7, to `nookku hook --harness claude-code`, as Claude Code does. The `config.json` of step 2 comes from an earlier run in Claude Code with verbatim-relay 0.3.0, because a model wrote it. Each output is a sample of one run, not a measurement. To make it again, run the steps of this page on the toy shop, with the same 3 messages as the [tutorial](../getting-started.md#6-run-the-test). I shortened the paths of the folders to `.../`. The test ids and the replies of your app are different. The [tutorial](../getting-started.md) shows the same steps for the toy shop only.

## What you need

- Your app in a project folder.
- Python 3.10 or later ([pyproject.toml](../../pyproject.toml)) and [uv](https://docs.astral.sh/uv/).
- Claude Code or Codex.

## 1. Install

```bash
uv tool install nookku
nookku --version
```

```text
nookku 0.4.0
```

If the shell does not find the command, read [troubleshooting.md](../troubleshooting.md#nookku-command-not-found).

## 2. Run the setup in the harness

Start Claude Code or Codex in the project folder of your app. Type this line, with the `!` at the start:

```text
!nookku setup
```

The `!` tells the [harness](../reference/glossary.md#harness) to run the line as a shell command. The harness adds the output to the conversation, so the model gets the setup guide as text ([setup.md](../../src/nookku/setup.md)). The first line of the guide is:

```text
# Nookku setup: connect a test to this app
```

Then type this prompt:

```text
Follow the nookku setup guide, and connect a test to this app.
```

Do not type only `nookku setup` as a prompt. In my first test of a real app, the model did not know the tool. It searched the project for the term, did not run the command, and asked what I meant. If the Claude Code [plugin](../reference/glossary.md#plugin) is installed, its `setup` skill also runs the command.

The model reads your app and writes 2 files in `.nookku/`:

- `entry.<ext>`: the [entry](../reference/glossary.md#entry). It is a thin wrapper that starts your app and speaks the [agent contract](../reference/glossary.md#agent-contract).
- `config.json`: the configuration. The key `entry` holds the command that starts the entry.

If your app already speaks the agent contract, the entry can be the start command of the app. The toy shop agent does this, so its only new file is `config.json`:

```json
{"entry": ["python3", "agent.py"], "models": []}
```

At the end, the model runs `nookku check` (step 4).

## 3. Review the entry

The entry is in the message path. The [tap](../reference/glossary.md#tap) records only what goes in and out of the entry. Thus the [audit](../reference/glossary.md#audit) cannot see a change that the entry makes ([limits.md](../limits.md)).

Open `.nookku/entry.<ext>` and `.nookku/config.json`. Check each item:

- [ ] **The message has no change.** The entry sends `message` to the app as it comes. It does not trim, format or translate it.
- [ ] **The reply has no change.** The entry returns the reply of the app as it comes.
- [ ] **The entry writes no logs on stdout.** Only contract lines go to stdout. Logs, prints and the output of child processes go to stderr. In Python, `nookku.agent.serve()` does this.
- [ ] **The test uses one conversation.** The entry starts one app conversation for the whole test. It does not start a new conversation for each message.
- [ ] **The entry uses the correct interpreter.** The first item of `entry` is the interpreter or the virtual environment of your app, for example `.venv/bin/python`. It is not a system `python3` that does not have the packages of your app.

If an item is not correct, tell the model what to correct, or correct the file yourself. Then do step 4 again. [connect-your-agent.md](connect-your-agent.md#write-the-entry-yourself) gives each rule of the entry.

## 4. Run check

`check` needs a fresh egress answer ([cli.md](../reference/cli.md#nookku-register)). If you have none, type the prompt `nookku start` in the harness first, or run `nookku register` with the answer.

```bash
nookku check
```

`check` starts the entry, sends one message, and ends the test. For the toy shop, the output is:

```text
Test 20261011-185044-0f7c: .../toy-shop/.nookku/tests/20261011-185044-0f7c
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

Read the `Reply:` line. It must be a reply of your app to the message of the config key `check_message`. The default is `Hello from nookku check. What can you help me with?`. If your app declines this message, for example because it is out of scope, set a message that your app answers: `nookku init <harness> --check-message "Do you sell teapots?"`. Use the harness of your [relay](../reference/glossary.md#relay), for example `plugin`. If it is an error of your app, read `app.log` in the [test folder](../reference/glossary.md#test-folder) that the first line names.

Then read the last line. `PASS` means that the entry sent a reply, the audit of the test is clean, and the test found a model session for each harness in `models`. `check` then exits with 0. Else the last line starts with `FAIL:`, gives the cause, and `check` exits with 1. For example, if the entry writes a log line on stdout, the last 3 lines are:

```text
Reply: Which item is this about: the mug or the teapot?
Audit: exit 2
FAIL: tap_unparsed: tap line 1: STDIO stdout: a stray line on stdout: 'toy shop agent: ready'. Use nookku.agent.serve() or write logs to stderr.
```

[troubleshooting.md](../troubleshooting.md#end-a-test) gives the fix for each `FAIL:` text.

`check` proves only the connection: one message goes in, one reply comes out, and the audit is clean. It does not test the replies of your app. The test in step 6 does that.

## 5. Install the relay

The [relay](../reference/glossary.md#relay) carries each message to the tap and each reply back to you. Use one relay. [choose-a-relay.md](choose-a-relay.md) compares the plugin and the project hooks.

### Project hooks in Claude Code

```bash
nookku init claude-code
```

```text
Project root: .../toy-shop
wrote .../toy-shop/.nookku/config.json
  Keys changed: none. Keys kept: entry, models.
wrote .../toy-shop/.claude/settings.local.json
Relay mode is off. Switch it with: nookku mode on
Do not also enable the nookku Claude Code plugin in this project, or each message is sent two times.
```

`init` keeps the entry from step 2, so do not give `--entry`. Do not switch [relay mode](../reference/glossary.md#relay-mode) on now. Step 6 starts the test.

### Project hooks in Codex

```bash
nookku init codex
```

Then trust the hooks. Start `codex` in the project once, and accept the hooks prompt ([codex.md](codex.md#install)).

### Plugin in Claude Code

Install the plugin as [claude-code-plugin.md](claude-code-plugin.md#install) says. The plugin shows each reply in the chat and in the Nookku pane.

### Start the viewer

This step is optional. In step 6, `nookku start` opens the [chat page](../reference/cli.md#nookku-chat) of the test in your browser, and the page shows each turn. To see the turns in a terminal too, open a second terminal in the project folder, and start the viewer:

```bash
nookku view
```

Before the start of a test, the viewer shows the last test. After step 4, this is the test of `check`:

```text
════ test 20261011-185044-0f7c ════
──── tester, turn 1 ────
Hello from nookku check. What can you help me with?
──── agent ────
Which item is this about: the mug or the teapot?
```

This is correct. When your test starts, the viewer follows to it. It shows a header line with the new test id, then each turn.

## 6. Run the test

In the harness, type the prompt `nookku start`. With the plugin, you can also type `/nookku start`. The relay starts the test and switches [relay mode](../reference/glossary.md#relay-mode) on. The model does not receive the prompt. The start also opens the chat page of the test in your browser. The project hooks in Claude Code show:

```text
nookku: test 20261011-185047-267f started. Relay mode is on: each message goes to the entry. To end the test and start the evaluation, type the prompt nookku end. To end the test with no evaluation, run nookku end in a shell.
```

Type your test messages, one at a time, in the harness or on the chat page. The model does not run. For each message, Claude Code shows the reply of your app as the reason of a blocked prompt, byte for byte. The model does not get this text. If you type a message on the chat page, its reply shows only on the page, not in the harness.

The chat page shows each turn. If you started the viewer, it also shows each turn. For 3 messages to the toy shop, the viewer shows:

```text
════ test 20261011-185047-267f ════
──── tester, turn 1 ────
hi, the mug i ordered came with a crack in the handle
──── agent ────
Which item is this about: the mug or the teapot?
──── tester, turn 2 ────
ok what is your refund policy
──── agent ────
Our refund policy:

1. Damaged items: full refund.
2. Change of mind: 30 days.

──── tester, turn 3 ────
do you ship to delhi?
──── agent ────
We ship to Chennai and Pune. Delivery takes 3 to 5 days.  
```

To end the test, type the prompt `nookku end`. The relay stops the entry, copies the session files of your app, builds the [trace](../reference/glossary.md#trace), writes the audit and [seals](../reference/glossary.md#seal) the test folder. Then the prompt goes to the model with this end text and the [evaluation](../reference/glossary.md#evaluation) prompt:

```text
nookku: relay mode is off.
Test 20261011-185047-267f ended: 3 turns, 0 model sessions.
Folder: .../toy-shop/.nookku/tests/20261011-185047-267f
Trace: 0 model items in 3 turns, no findings.
Audit: nookku audit --tap .../tap.jsonl --relay .../relay.jsonl
```

The toy shop has no model sessions. If your app runs its own model sessions, the counts of model sessions and model items are more than 0. To end the test with no evaluation, run `nookku end` in a shell. You can also click "End test" on the chat page, which does the same. After an end with no evaluation, the chat page continues, so "Export" and "Save as script" still work. To start the evaluation, type the prompt `nookku end` in the harness. That also stops the chat page.

To give the test to a person, click "Export" on the chat page, or run `nookku export`. Both give the same file, `<test id>.html` ([`nookku export`](../reference/cli.md#nookku-export)). The button saves it in the download folder of your browser, and the command saves it in the current folder.

## 7. Allow the evaluation commands

In the [evaluation](../reference/glossary.md#evaluation), the [harness model](../reference/glossary.md#harness-model) reads the record of the test and writes `report.md` ([evaluate.md](../../src/nookku/evaluate.md)). The harness asks you to allow each command, unless your permission settings allow it already. Expect these requests:

| Command | What it does |
|---|---|
| `nookku transcript --trace --test <test-id>` | Shows each turn as your app got it, with the model items of your app. |
| `cat`, `sed -n`, `jq` or `grep` on `findings.json` and `audit.json` in the test folder | Reads the [findings](../reference/glossary.md#findings) and the audit. |
| A read of the code, the docs and the tests of your app | Finds the business rules. |
| A read-only command on the state of your app, for example a SELECT query or a GET request | Checks the state of your app. |
| A write of `report.md` in the test folder | Writes the report. |

Allow these commands. Deny a command that changes the state of your app, starts your app or sends a message to it. The evaluation prompt forbids these commands.

The relay also checks each command. After a test, it denies a write to the test folder, except `report.md`, and a write to the other records and state files of nookku. It checks the paths that a command writes, not its text ([SPEC.md section 5](../../SPEC.md#5-relays) lists the read programs and the protected files). Then the model gets this text, with the path that the command named and the program or the redirect that failed:

```text
nookku: <path> is a record or a state file of nookku. Only nookku writes it. A command may read it. "rm" is not a read command.
```

If you deny a command, the model does not get its output. In Claude Code, a deny with no message tells the model to stop and wait for you. Then the model does not write `report.md`. To continue, type a reply, for example "Do not run that command. Continue with the other steps."

If the latest test has no `report.md`, the prompt `nookku end` starts its evaluation again. A test of `nookku check` after your test does not change this ([SPEC.md section 9.1](../../SPEC.md#91-start)). The end text is then "Nookku: no test runs. Relay mode is off."

## 8. Read the results

The test folder `.nookku/tests/<test-id>/` holds the two records, the audit, the trace, the findings, the seal and `report.md`. [reference/records.md](../reference/records.md#the-test-folder) lists each file.

Read the files in the order of [read-the-results.md](read-the-results.md): the seal, the audit, the findings, the report and the transcript. That page also tells you the next step for each result. The tutorial shows the same steps for the toy shop: [8. Read the audit](../getting-started.md#8-read-the-audit), [9. Read the report](../getting-started.md#9-read-the-report) and [10. Read the trace and the findings](../getting-started.md#10-read-the-trace-and-the-findings).

For the toy shop test, the audit gives:

```text
3 turns, 3 exchanges, 0 blocked model calls, 0 model sessions, 0 breaks
Result: clean (exit 0)
```

A report is a model answer, so check its evidence.

With no app spec, the model finds the business rules in the code, the docs and the tests of your app. To evaluate the tone, the boundaries, the user goals, the limits and the trace points of your app, write a spec and name it with `--spec` ([evaluate-against-your-spec.md](evaluate-against-your-spec.md)).

## Run a scripted test

If your app has fixed conversations in its own tests, run them through the relay with `nookku run`. Then the tap, the audit, the trace and the evaluation cover them, and nobody types each message.

1. Write the script. Use one `{"said": "..."}` row for each turn:

   ```text
   {"said": "Is the teapot in stock?"}
   {"said": "Return order #4471, please."}
   {"said": "Thanks."}
   ```

   A JSON array of strings also works. If your fixtures have another form, convert them, for example with `jq -c '.turns[] | {said: .}' fixture.json > script.jsonl`.

2. Optional: add more entries to `.nookku/config.json`, for example an entry that replays a recording with no model:

   ```json
   "entries": {"replay": ["python3", "replay_entry.py"]}
   ```

3. Run the script:

   ```bash
   nookku run --script script.jsonl --entry replay
   ```

   Without `--entry`, the test uses the key `entry`.

4. Read the output. It gives the test id, the count of turns, the audit and the trace, then `PASS` or each `FAIL:` line. Read the replies with `nookku transcript --test <test-id>`.

By default, only a person runs `nookku run`. To let the harness model run a script, run `nookku policy set scripts model` in a shell. Then the model can also use the `run_script` tool of the plugin. A [scripted test](../reference/glossary.md#scripted-test) always shows the turns as `script`, not as typed turns ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)).

## Next

- Change the entry when your app changes: [connect-your-agent.md](connect-your-agent.md#when-the-app-changes).
- Each symptom and each error text, with the fix: [troubleshooting.md](../troubleshooting.md).

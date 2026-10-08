# Test your own app

This guide takes your own app from the install to the results of a first [test](../reference/glossary.md#test). Each step gives the expected output, so you can compare your screen with it.

I made the output with the toy shop agent of this repo ([examples/toy-shop/agent.py](../../examples/toy-shop/agent.py)) as the app, verbatim-relay 0.3.0 ([version](../../src/verbatim_relay/__init__.py)) and the hook kit in Claude Code. I shortened the paths of the folders to `.../`. The test ids and the replies of your app are different. The [tutorial](../getting-started.md) shows the same steps for the toy shop only.

## What you need

- Your app in a project folder.
- Python 3.10 or later ([pyproject.toml](../../pyproject.toml)) and [uv](https://docs.astral.sh/uv/).
- Claude Code or Codex.

## 1. Install

```bash
uv tool install verbatim-relay
verbatim-relay --version
```

```text
verbatim-relay 0.3.0
```

If the shell does not find the command, read [troubleshooting.md](../troubleshooting.md#verbatim-relay-command-not-found).

## 2. Run the setup in the harness

Start Claude Code or Codex in the project folder of your app. Type this line, with the `!` at the start:

```text
!verbatim-relay setup
```

The `!` tells the [harness](../reference/glossary.md#harness) to run the line as a shell command. The harness adds the output to the conversation, so the model gets the setup guide as text ([setup.md](../../src/verbatim_relay/setup.md)). The first line of the guide is:

```text
# verbatim-relay setup: connect a test to this app
```

Then type this prompt:

```text
Follow the verbatim-relay setup guide, and connect a test to this app.
```

Do not type only `verbatim-relay setup` as a prompt. In my first test of a real app, the model did not know the tool. It searched the project for the term, did not run the command, and asked what I meant. If the Claude Code plugin is installed, its `setup` skill also runs the command.

The model reads your app and writes 2 files in `.verbatim-relay/`:

- `entry.<ext>`: the [entry](../reference/glossary.md#entry). It is a thin wrapper that starts your app and speaks the [agent contract](../reference/glossary.md#agent-contract).
- `config.json`: the configuration. The key `entry` holds the command that starts the entry.

If your app already speaks the agent contract, the entry can be the start command of the app. The toy shop agent does this, so its only new file is `config.json`:

```json
{"entry": ["python3", "agent.py"], "models": []}
```

At the end, the model runs `verbatim-relay check` (step 4).

## 3. Review the entry

The entry is in the message path. The [tap](../reference/glossary.md#tap) records only what goes in and out of the entry. Thus the [audit](../reference/glossary.md#audit) cannot see a change that the entry makes ([limits.md](../limits.md)).

Open `.verbatim-relay/entry.<ext>` and `.verbatim-relay/config.json`. Check each item:

- [ ] **The message has no change.** The entry sends `message` to the app as it comes. It does not trim, format or translate it.
- [ ] **The reply has no change.** The entry returns the reply of the app as it comes.
- [ ] **The entry writes no logs on stdout.** Only contract lines go to stdout. Logs, prints and the output of child processes go to stderr. In Python, `verbatim_relay.agent.serve()` does this.
- [ ] **The test uses one conversation.** The entry starts one app conversation for the whole test. It does not start a new conversation for each message.
- [ ] **The entry uses the correct interpreter.** The first item of `entry` is the interpreter or the virtual environment of your app, for example `.venv/bin/python`. It is not a system `python3` that does not have the packages of your app.

If an item is not correct, tell the model what to correct, or correct the file yourself. Then do step 4 again. [connect-your-agent.md](connect-your-agent.md#write-the-entry-yourself) gives each rule of the entry.

## 4. Run check

```bash
verbatim-relay check
```

`check` starts the entry, sends one message, and ends the test. For the toy shop, the output is:

```text
Test 20261007-231156-8465: .../toy-shop/.verbatim-relay/tests/20261007-231156-8465
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

Read the `Reply:` line. It must be a reply of your app to the message "Hello from verbatim-relay check. What can you help me with?". If it is an error of your app, read `app.log` in the [test folder](../reference/glossary.md#test-folder) that the first line names.

Then read the last line. `PASS` means that the entry sent a reply, the audit of the test is clean, and the test found a model session for each harness in `models`. `check` then exits with 0. Else the last line starts with `FAIL:`, gives the cause, and `check` exits with 1. For example, if the entry writes a log line on stdout, the last 3 lines are:

```text
Reply: Which item is this about: the mug or the teapot?
Audit: exit 2
FAIL: tap_unparsed: tap line 1: STDIO stdout: a stray line on stdout: 'toy shop agent: ready'. Use verbatim_relay.agent.serve() or write logs to stderr.
```

[troubleshooting.md](../troubleshooting.md#end-a-test) gives the fix for each `FAIL:` text.

`check` proves only the connection: one message goes in, one reply comes out, and the audit is clean. It does not test the replies of your app. The test in step 6 does that.

## 5. Install the relay, and start the viewer

The [relay](../reference/glossary.md#relay) carries each message to the tap and each reply back to you. Use one relay. [claude-code.md](claude-code.md) compares the plugin and the hook kit.

### Hook kit in Claude Code

```bash
verbatim-relay init claude-code
```

```text
wrote .../toy-shop/.verbatim-relay/config.json
  Keys changed: none. Keys kept: entry, models.
wrote .../toy-shop/.claude/settings.local.json
Relay mode is off. Switch it with: verbatim-relay mode on
Do not also enable the verbatim-relay Claude Code plugin in this project, or each message is sent two times.
```

`init` keeps the entry from step 2, so do not give `--entry`. Do not switch relay mode on now. Step 6 starts the test.

### Hook kit in Codex

```bash
verbatim-relay init codex
```

Then trust the hooks. Start `codex` in the project once, and accept the hooks prompt ([codex.md](codex.md#install)).

### Plugin in Claude Code

Install the plugin as [claude-code.md](claude-code.md#plugin) says. The plugin shows each reply in the chat, so you do not need the viewer.

### Start the viewer

With the hook kit, open a second terminal in the project folder, and start the viewer:

```bash
verbatim-relay view
```

Before the start of a test, the viewer shows the last test. After step 4, this is the test of `check`:

```text
════ test 20261007-231156-8465 ════
──── tester, turn 1 ────
Hello from verbatim-relay check. What can you help me with?
──── agent ────
Which item is this about: the mug or the teapot?
```

This is correct. Keep the viewer open. When your test starts, the viewer follows to it. It shows a header line with the new test id, then each turn.

## 6. Run the test

In the harness, type the prompt `verbatim-relay start`. With the plugin, you can also type `/verbatim-relay start`. The relay starts the test and switches [relay mode](../reference/glossary.md#relay-mode) on. The model does not receive the prompt. The hook kit in Claude Code shows:

```text
verbatim-relay: test 20261007-231159-fd98 started. Relay mode is on: each message goes to the entry. To end the test and start the evaluation, type the prompt verbatim-relay end. To end the test with no evaluation, run verbatim-relay end in a shell.
```

Type your test messages, one at a time. The model does not run. For each message, the hook kit in Claude Code shows:

```text
verbatim-relay: relayed to the agent. The reply is in the viewer (verbatim-relay view).
```

The viewer shows each turn. For 3 messages to the toy shop:

```text
════ test 20261007-231159-fd98 ════
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

To end the test, type the prompt `verbatim-relay end`. The relay stops the entry, copies the session files of your app, builds the [trace](../reference/glossary.md#trace), writes the audit and [seals](../reference/glossary.md#seal) the test folder. Then the prompt goes to the model with this end text and the evaluation prompt:

```text
verbatim-relay: relay mode is off.
Test 20261007-231159-fd98 ended: 3 turns, 0 model sessions.
Folder: .../toy-shop/.verbatim-relay/tests/20261007-231159-fd98
Trace: 0 model items in 3 turns, no findings.
Audit: verbatim-relay audit --tap .../tap.jsonl --relay .../relay.jsonl
```

The toy shop has no model sessions. If your app runs its own model sessions, the counts of model sessions and model items are more than 0. To end the test with no evaluation, run `verbatim-relay end` in a shell.

## 7. Allow the evaluation commands

In the [evaluation](../reference/glossary.md#evaluation), the [harness model](../reference/glossary.md#harness-model) reads the record of the test and writes `report.md` ([evaluate.md](../../src/verbatim_relay/evaluate.md)). The harness asks you to allow each command, unless your permission settings allow it already. Expect these requests:

| Command | What it does |
|---|---|
| `verbatim-relay transcript --trace --test <test-id>` | Shows each turn as your app got it, with the model items of your app. |
| `cat`, `sed -n`, `jq` or `grep` on `findings.json` and `audit.json` in the test folder | Reads the [findings](../reference/glossary.md#findings) and the audit. |
| A read of the code, the docs and the tests of your app | Finds the business rules. |
| A read-only command on the state of your app, for example a SELECT query or a GET request | Checks the state of your app. |
| A write of `report.md` in the test folder | Writes the report. |

Allow these commands. Deny a command that changes the state of your app, starts your app or sends a message to it. The evaluation prompt forbids these commands.

The relay also checks each command. After a test, it denies a write to the test folder, except `report.md`. It also denies a shell command that names `.verbatim-relay` and does more than read ([SPEC.md section 5](../../SPEC.md#5-relays) lists the read programs). Then the model gets this text:

```text
verbatim-relay: the records of a test do not change. Write only report.md. A command that names .verbatim-relay may only read.
```

If you deny a command, the model does not get its output. In Claude Code, a deny with no message tells the model to stop and wait for you. Then the model does not write `report.md`. To continue, type a reply, for example "Do not run that command. Continue with the other steps."

If the latest test has no `report.md`, the prompt `verbatim-relay end` starts its evaluation again ([SPEC.md section 9.1](../../SPEC.md#91-start)). The end text is then "verbatim-relay: no test runs. Relay mode is off."

## 8. Read the results

The test folder `.verbatim-relay/tests/<test-id>/` holds the two records, the audit, the trace, the findings, the seal and `report.md`. [reference/records.md](../reference/records.md#the-test-folder) lists each file. The tutorial shows how to read the audit and the report: [8. Read the audit](../getting-started.md#8-read-the-audit) and [9. Read the report](../getting-started.md#9-read-the-report).

For the toy shop test, the audit gives:

```text
3 turns, 3 exchanges, 0 blocked model calls, 0 model sessions, 0 breaks
Result: clean (exit 0)
```

A report is a model answer, so check its evidence.

## Next

- Change the entry when your app changes: [connect-your-agent.md](connect-your-agent.md#when-the-app-changes).
- Each error text, its cause and the fix: [troubleshooting.md](../troubleshooting.md).

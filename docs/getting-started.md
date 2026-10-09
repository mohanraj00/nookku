# Get started

In this tutorial, you test the toy shop agent of this repo in Claude Code. You install Nooku, run a test with 3 messages, and read the [audit](reference/glossary.md#audit), the report of the model and the [findings](reference/glossary.md#findings). You use the hook kit, because it needs no global install in Claude Code. To compare the hook kit with the plugin, read [how-to/choose-a-relay.md](how-to/choose-a-relay.md).

The output on this page is the real output of each step. I shortened the paths of the folders to `.../`. The test id and the times are different on your machine.

I made the output of steps 5 and 10 in a second run of the same steps, with Nooku 0.3.0 on macOS. In that run, I gave each prompt to `nooku hook --harness claude-code`, as Claude Code does. Thus the test ids of steps 5 and 10 are different from the other steps. Each of these outputs is a sample of one run.

## What you need

- macOS or Linux.
- Python 3.10 or later ([pyproject.toml](../pyproject.toml)), [uv](https://docs.astral.sh/uv/) and git.
- Claude Code. The proofs of the hook kit ran on Claude Code 2.1.290 ([data](../proofs/hooks-claude-code/results.json)).

## 1. Install Nooku

```bash
uv tool install nooku
nooku --version
```

```text
nooku 0.3.0
```

This tutorial needs version 0.3.0 or later. If the version is lower, end each running test with `nooku end`. Then upgrade:

```bash
uv tool upgrade nooku
```

End the tests first, because 0.3.0 does not find a test that version 0.2.0 started. It then cannot end that test ([#44](https://github.com/mohanraj00/verbatim-relay/issues/44)).

## 2. Make a project for the toy shop

Get the toy shop agent, and put it in a new project folder:

```bash
git clone https://github.com/mohanraj00/verbatim-relay.git
mkdir toy-shop
cp nooku/examples/toy-shop/agent.py toy-shop/
cd toy-shop
```

The toy shop agent is one Python file with no dependencies. It has 3 fixed replies: one for refunds, one for shipping and one for prices. For each other message, it asks which item the message is about.

## 3. Send one message to the agent by hand

The agent speaks the [agent contract](reference/glossary.md#agent-contract): one JSON line in on stdin, and one JSON line out on stdout ([SPEC.md section 6](../SPEC.md#6-agent-contract-version-1)). Send it one line:

```bash
echo '{"v": 1, "id": "1", "session": "s1", "message": "do you ship to delhi?", "history": []}' | python3 agent.py
```

```text
toy shop agent: ready
{"v": 1, "id": "1", "reply": "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  "}
```

The first line goes to stderr. The second line is the reply, on stdout. Note the two spaces at the end of the reply. The audit checks each byte, also these spaces.

## 4. Connect a test

Install the hook kit for Claude Code, with the command that starts the agent:

```bash
nooku init claude-code --entry "python3 agent.py"
```

```text
wrote .../toy-shop/.nooku/config.json
  A new file. Keys that differ from the default: entry.
wrote .../toy-shop/.claude/settings.local.json
Relay mode is off. Switch it with: nooku mode on
Do not also enable the nooku Claude Code plugin in this project, or each message is sent two times.
```

`config.json` holds the [entry](reference/glossary.md#entry): the command that the [tap](reference/glossary.md#tap) starts for each test. `settings.local.json` holds two hooks. The `UserPromptSubmit` hook takes each prompt before the model sees it. The `PreToolUse` hook denies a model tool call that names the agent or changes a file of the test.

Check the connection with one message:

```bash
nooku check
```

```text
Test 20261007-133809-bbb2: .../toy-shop/.nooku/tests/20261007-133809-bbb2
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

PASS proves the connection, not the reply. `check` sent one fixed message to the entry: `Hello from nooku check. What can you help me with?` The entry sent a reply line, and the audit of this short test is clean. `check` does not judge the reply. Here the reply is the fallback text of the toy shop, because the toy shop has no rule for this message. For your own app, do the steps in [Make sure that check runs your real app](how-to/connect-your-agent.md#make-sure-that-check-runs-your-real-app).

## 5. Start the viewer

The hook kit cannot show text in the chat of Claude Code. Open a second terminal, go to the project, and start the viewer:

```bash
cd toy-shop
nooku view
```

The viewer shows each turn of the latest test, and it waits for the next turn. Before your test starts, the latest test is the test of `check` from step 4. In my second run, the viewer showed:

```text
════ test 20261008-011239-cfe6 ════
──── tester, turn 1 ────
Hello from nooku check. What can you help me with?
──── agent ────
Which item is this about: the mug or the teapot?
```

This is correct. When your test starts, the viewer shows a header line with the new test id, then each turn. Keep the viewer open.

## 6. Run the test

In the first terminal, start Claude Code in the project:

```bash
claude
```

Type the prompt `nooku start`. The hook starts the test and blocks the prompt, so the model does not receive it. Claude Code shows this text:

```text
nooku: test 20261007-133823-0b63 started. Relay mode is on: each message goes to the entry. To end the test and start the evaluation, type the prompt nooku end. To end the test with no evaluation, run nooku end in a shell.
```

Type these 3 messages, one at a time:

1. `hi, the mug i ordered came with a crack in the handle`
2. `ok what is your refund policy`
3. `do you ship to delhi?`

For each message, Claude Code shows `nooku: relayed to the agent. The reply is in the viewer (nooku view).` The model does not run. The viewer shows each turn:

```text
════ test 20261007-133823-0b63 ════
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

## 7. End the test

Type the prompt `nooku end`. The hook ends the test: it stops the agent, builds the [trace](reference/glossary.md#trace), writes the audit and [seals](reference/glossary.md#seal) the [test folder](reference/glossary.md#test-folder). Then the prompt goes to the model with the [evaluation](reference/glossary.md#evaluation) prompt.

The model now reads the record of the test. Claude Code asks you to allow its commands. Allow these commands:

- `nooku transcript --trace --test <test-id>`: it shows each turn as the agent got it.
- `cat`, `sed -n`, `jq` or `grep` on `findings.json` and `audit.json` in the test folder.
- A read of `agent.py`.
- The write of `report.md` in the test folder.

Deny a command that changes `agent.py` or runs the agent. [Allow the evaluation commands](how-to/test-your-app.md#7-allow-the-evaluation-commands) lists each command, and tells you what to do after a deny.

The model gives a short summary. In my run, it was:

```text
I found 1 issue in test 20261007-133823-0b63. The seal is intact, and the audit shows no changes to the words of any turn.

- **Turn 1 (`missing_action`):** You said the mug had a crack, but the app asked "the mug or the teapot?". It did not act on the damage, although its own rule at `agent.py:18` gives a full refund for damaged items. ...
```

The model's answer is different on each run.

## 8. Read the audit

Each test has a folder. Find its id:

```bash
ls .nooku/tests/
```

```text
20261007-133809-bbb2	20261007-133823-0b63
```

The first folder is the test of `nooku check`. The second is your test.

The end of the test already wrote the audit of its two records in `audit.json` in the test folder. To see the audit as text, run it again. This command is optional:

```bash
nooku audit --tap .nooku/tests/20261007-133823-0b63/tap.jsonl --relay .nooku/tests/20261007-133823-0b63/relay.jsonl
```

```text
3 turns, 3 exchanges, 0 blocked model calls, 0 model sessions, 0 breaks
Result: clean (exit 0)
```

`relay.jsonl` is what you typed and saw. `tap.jsonl` is what the agent received and sent. The audit compares them byte for byte. Clean means that each message reached the agent with no change, and each reply reached you with no change.

To see a break, audit a conformance case of the repo. Its records have 4 planted faults:

```bash
nooku audit --tap ../nooku/conformance/cases/several_breaks/tap.jsonl --relay ../nooku/conformance/cases/several_breaks/relay.jsonl
```

```text
BREAK altered_input   relay line 1, tap line 1: first difference at character 33: expected 'order #4471.  ', got 'order #4471.'
BREAK altered_reply   relay line 2, tap line 2: first difference at character 2: expected 'Café policy: we accept €', got 'Care policy: we accept €'
BREAK altered_input   relay line 3, tap line 3: first difference at character 0: expected 'Two questions:\n\n1. Do yo', got 'Also upgrade me to the p'
BREAK unshown_reply   relay line 3, tap line 3
3 turns, 3 exchanges, 0 blocked model calls, 0 model sessions, 4 breaks
Result: breaks found (exit 1)
```

The exit code is 0 for clean, 1 for a break, and 2 if a record is missing or invalid. [SPEC.md section 3.3](../SPEC.md#33-break-classes) defines each break class.

## 9. Read the report

The model wrote `report.md` in the test folder:

```bash
cat .nooku/tests/20261007-133823-0b63/report.md
```

```markdown
# Test 20261007-133823-0b63: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| missing_action | 1 | Turn 1; `agent.py:22`, `agent.py:26` | The tester said "the mug i ordered came with a crack in the handle". The app replied "Which item is this about: the mug or the teapot?". The tester already named the mug. The app did not record the damage and did not start the "Damaged items: full refund." rule from `agent.py:18`. The reply is the `FALLBACK` text, because no key of `REPLIES` is in the message. |

## Notes

- Seal: intact. No record changed after the end of the test.
- Audit: 3 exchanges, 0 breaks, 0 errors. ...
```

Each row has a class, a turn and its evidence. The model did not see the conversation while you talked. It read the record, the code of the agent and the findings. A report is a model answer, so check its evidence. Here, the evidence is correct. In `agent.py`, line 18 is the refund rule, line 22 is the fallback reply, and line 26 is the keyword match.

Last, check that no record changed after the end of the test:

```bash
nooku verify
```

```text
Seal: intact. No record changed after the end of the test.
```

## 10. Read the trace and the findings

At the end of the test, the bridge also built the trace, `trace.jsonl`, and its checks, `findings.json`. Build the trace again, and show its findings:

```bash
nooku trace
```

In my second run, the output was:

```text
Trace: 0 model items in 3 turns, no findings.
File: .../toy-shop/.nooku/tests/20261008-011242-a35f/trace.jsonl
```

With no test id, `trace` uses the latest test. The toy shop has no model, so the trace has no model items and no findings. Read the findings file:

```bash
cat .nooku/tests/20261008-011242-a35f/findings.json
```

```json
{
 "v": "0.2",
 "test": "20261008-011242-a35f",
 "turns": 3,
 "items": 0,
 "sessions": [],
 "otel": null,
 "backend": null,
 "model_api": null,
 "counts": {
  "agent_error": 0,
  "tool_error": 0,
  "command_failed": 0,
  "span_error": 0,
  "backend_error": 0,
  "model_api_error": 0,
  "turn_without_model": 0,
  "item_between_turns": 0,
  "otel_tool_not_in_session": 0,
  "server_not_from_app": 0,
  "session_inferred": 0,
  "version_untested": 0
 },
 "findings": []
}
```

`counts` has one number for each check of the trace. `findings` lists each finding with its check, its turn and its detail. A finding is a fact, not yet an issue. The model reads the findings in the evaluation. For an app with a model, [Read the findings](how-to/read-the-results.md#4-read-the-findings) shows the findings of a Claude Code session.

To read each file of a test folder in order, see [Read the results of a test](how-to/read-the-results.md).

## What you did

- You connected a test to an agent with no change to the agent's code.
- You talked to the agent through Claude Code, and the model did not run.
- You audited the two records, and read the model's evaluation of the record.
- You read the trace and the findings of the test.

## Next steps

- Test your own app: [how-to/test-your-app.md](how-to/test-your-app.md). In the harness, type `!nooku setup`. Then type the prompt "Follow the Nooku setup guide, and connect a test to this app."
- Connect your own agent: [how-to/connect-your-agent.md](how-to/connect-your-agent.md).
- Use the Claude Code plugin, which shows each reply in the chat: [how-to/claude-code-plugin.md](how-to/claude-code-plugin.md).
- Use Codex: [how-to/codex.md](how-to/codex.md).
- See the parts and how they connect: [architecture.md](architecture.md).

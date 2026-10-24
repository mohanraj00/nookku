# Get started

In this tutorial, you test the toy shop agent of this repo in Claude Code. You install Nookku, run a test with 3 messages, and read the [audit](reference/glossary.md#audit), the report of the model and the [findings](reference/glossary.md#findings). You use the [project hooks](reference/glossary.md#project-hooks), because they need no global install in Claude Code. To compare the project hooks with the [plugin](reference/glossary.md#plugin), read [how-to/choose-a-relay.md](how-to/choose-a-relay.md).

The output on this page comes from one run of this tutorial, on 2026-10-23, on macOS, with nookku 0.5.5 from this checkout and Claude Code 2.1.302. The model was `claude-opus-5-5` ([data](../proofs/tutorial/output.txt), [versions](../proofs/tutorial/run.json), [method](../scripts/proof_tutorial.py)). The script ran the commands of each step in a shell, and gave each prompt to `claude -p`, with the user settings off. Print mode needs `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` ([troubleshooting](troubleshooting.md#claude-code-does-not-run-as-the-interactive-cli)), so the script set it. The script allowed the commands of step 7 before the prompt `nookku end`, and `curl` opened the chat page. I shortened the paths of the folders to `.../`. The test id and the times are different on your machine. The model output of steps 7 and 9 is a sample, because the model's answer is different on each run.

## What you need

- macOS or Linux.
- Python 3.10 or later ([pyproject.toml](../pyproject.toml)), [uv](https://docs.astral.sh/uv/) and git.
- Claude Code. The proofs of the project hooks ran on Claude Code 2.1.302 ([data](../proofs/hooks-claude-code/results.json)). This tutorial ran on Claude Code 2.1.302 ([data](../proofs/tutorial/run.json)).

## 1. Install Nookku

```bash
uv tool install nookku
nookku --version
```

```text
nookku 0.5.5
```

This tutorial needs nookku 0.5.5 or later. If you use verbatim-relay 0.3.x or earlier, the package has a new name, so `uv tool upgrade nookku` cannot upgrade it. Do the [0.4.0 steps of the upgrade guide](how-to/upgrade.md#040) in its place.

## 2. Make a project for the toy shop

Get the toy shop agent, and put it in a new project folder:

```bash
git clone https://github.com/mohanraj00/nookku.git
mkdir toy-shop
cp nookku/examples/toy-shop/agent.py toy-shop/
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

Install the project hooks for Claude Code, with the command that starts the agent:

```bash
nookku init claude-code --entry "python3 agent.py"
```

```text
Project root: .../toy-shop
wrote .../toy-shop/.nookku/config.json
  A new file. Keys that differ from the default: entry.
wrote .../toy-shop/.claude/settings.local.json
Relay mode is off. Switch it with: nookku mode on
Do not also enable the nookku Claude Code plugin in this project, or each message is sent two times.
```

If the nookku plugin is on in Claude Code, `init` also prints a warning with the command that turns it off. `nookku start` refuses a test while both are on.

`init` prints the absolute paths. Here `...` stands for the folders above `toy-shop`. `config.json` holds the [entry](reference/glossary.md#entry): the command that the [tap](reference/glossary.md#tap) starts for each test. `settings.local.json` holds two hooks. The `UserPromptSubmit` hook takes each prompt before the model sees it. The `PreToolUse` hook denies a model tool call that names the agent or changes a file of the test.

Each test needs an egress answer: the list of each service that the agent calls ([SPEC.md section 7.11](../SPEC.md#711-egress-discovery)). Nookku starts a recording proxy for each part of the answer. For your own app, you type the prompt `nookku start`, and the [harness model](reference/glossary.md#harness-model) reads the code and gives the answer. Then you check its lines and type `nookku start` again. The toy shop calls no service, so here you give the answer yourself, with 5 empty lists:

```bash
nookku register <<'EOF'
{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}
EOF
```

```text
nookku: the egress answer is registered. The next start uses these parts:
- no egress part: the agent calls no service
Show these parts to the tester. If they are correct, the tester types the prompt nookku start in the next 30 minutes. If a part is wrong, run nookku register again with the correct answer.
```

Check the connection with one message. `check` keeps the answer for the test of step 6:

```bash
nookku check
```

```text
Test 20261023-172137-5605: .../toy-shop/.nookku/tests/20261023-172137-5605
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

PASS proves the connection, not the reply. `check` sent one message to the entry, the default of the config key [`check_message`](reference/config.md#nookkuconfigjson): `Hello from nookku check. What can you help me with?` The entry sent a reply line, and the audit of this short test is clean. `check` does not judge the reply. Here the reply is the fallback text of the toy shop, because the toy shop has no rule for this message. For your own app, do the steps in [Make sure that check runs your real app](how-to/connect-your-agent.md#make-sure-that-check-runs-your-real-app).

## 5. The chat page

The project hooks show each reply in the chat only as the reason of a blocked prompt. In the CLI, the start of a long reply can go off the screen. Thus `nookku start` in step 6 also starts the [chat page](reference/cli.md#nookku-chat) and opens it in your browser. The chat page is the main view of a test. You do not start a viewer by hand.

On the chat page:

- The header shows the Nookku mark (2 eyes), the state of the test (for example "Running") and the test id.
- The label under the message box shows `Bridge mode on` while the test runs. Then the page sends your message to the agent, and the [harness model](reference/glossary.md#harness-model) does not see it. `Bridge mode off` tells you that the page sends nothing.
- The page shows each turn of the test, also the turns that you type in the [harness](reference/glossary.md#harness). You can also type your messages on the page. The reply to a message from the page shows only on the page, not in Claude Code.
- The "⋯" menu at the right of the header sets the theme and the width of the page. Auto is the default of each.
- "All tests" opens the dashboard of the tests of the project. On the dashboard, "Compare" opens the diff page of 2 tests.

If the browser cannot open, for example over SSH, the start tells you to run `nookku chat` in a separate terminal. To see the turns as text in a terminal, `nookku view` is the alternative. To turn the page off, set the config key [`page`](reference/config.md#test-keys) to `false`.

## 6. Run the test

In the project folder, start Claude Code:

```bash
claude
```

Type the prompt `nookku start`. The hook starts the test and blocks the prompt, so the model does not receive it. Claude Code shows this text:

```text
nookku: test 20261023-172140-3491 started. Relay mode is on: each message goes to the entry. To end the test and start the evaluation, type the prompt nookku end. To end the test with no evaluation, run nookku end in a shell.
Egress of the agent:
- no egress part: the agent calls no service
The chat page opened in your browser. It stops when you type the prompt nookku end, at the next start, or after 15 minutes with no use and no test.
```

Type these 3 messages in Claude Code, one at a time:

1. `hi, the mug i ordered came with a crack in the handle`
2. `ok what is your refund policy`
3. `do you ship to delhi?`

For each message, Claude Code shows the agent's reply as the reason of a blocked prompt. The model does not run, and it does not get the reply. The chat page also shows each turn. To see the turns as text, run `nookku view` in a second terminal. In my run, it showed:

```text
════ test 20261023-172140-3491 ════
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

Type the prompt `nookku end`. The hook ends the test: it stops the agent, builds the [trace](reference/glossary.md#trace), writes the audit and [seals](reference/glossary.md#seal) the [test folder](reference/glossary.md#test-folder). Then the prompt goes to the model with the [evaluation](reference/glossary.md#evaluation) prompt. The prompt also stops the chat page.

Do not use the "End test" button of the chat page for this tutorial. The button ends the test with no evaluation, the same as `nookku end` in a shell. After it, the page continues, so "Export" and "Save as script" still work. To start the evaluation after that, type the prompt `nookku end` in Claude Code.

The model now reads the record of the test. Claude Code asks you to allow its commands. Allow these commands:

- `nookku transcript --trace --test <test-id>`: it shows each turn as the agent got it.
- `cat`, `sed -n`, `jq` or `grep` on `findings.json` and `audit.json` in the test folder.
- A read of `agent.py`.
- The write of `report.md` in the test folder.

Deny a command that changes `agent.py` or runs the agent. [Allow the evaluation commands](how-to/test-your-app.md#7-allow-the-evaluation-commands) lists each command, and tells you what to do after a deny.

The model gives a short summary. In my run, it was:

```text
I wrote the report to `.nookku/tests/20261023-172140-3491/report.md`. The record is valid, and I found 1 issue in 3 turns.

- **Issue in turn 1 (`missing_action`):** You wrote that the mug came with a crack in the handle. The app replied "Which item is this about: the mug or the teapot?" It asked for the item that you already named. It also did not give its own rule "Damaged items: full refund." The message has no keyword that the app knows, so the app sent its default reply (`agent.py:27`, `agent.py:31`).
- **Turns 2 and 3:** The refund reply agrees with `agent.py:23`. The shipping reply agrees with `agent.py:24`. It does not say "no" for Delhi directly, but it lists only Chennai and Pune.
- **Spec:** The project has no app spec. Thus the report has no tone, boundary, off-path or performance rows.
- **Tester notes:** You wrote no note.
- **Coverage:** No egress part was unseen.
```

The model's answer is different on each run.

## 8. Read the audit

Each test has a folder. Find its id:

```bash
ls .nookku/tests/
```

```text
20261023-172137-5605   20261023-172140-3491
```

The first folder is the test of `nookku check`. The second is your test.

The end of the test already wrote the audit of its two records in `audit.json` in the test folder. To see the audit as text, run it again. This command is optional:

```bash
nookku audit --tap .nookku/tests/20261023-172140-3491/tap.jsonl --relay .nookku/tests/20261023-172140-3491/relay.jsonl
```

```text
3 turns, 3 exchanges, 0 blocked model calls, 0 model sessions, 0 breaks
Result: clean (exit 0)
```

`relay.jsonl` is what you typed and saw. `tap.jsonl` is what the agent received and sent. The audit compares them byte for byte. Clean means that each message reached the agent with no change, and each reply reached you with no change.

To see a [break](reference/glossary.md#break), audit a conformance case of the repo. Its records have 4 planted faults:

```bash
nookku audit --tap ../nookku/conformance/cases/several_breaks/tap.jsonl --relay ../nookku/conformance/cases/several_breaks/relay.jsonl
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
cat .nookku/tests/20261023-172140-3491/report.md
```

```markdown
# Test 20261023-172140-3491: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| missing_action | 1 | turn 1, agent.py:23, agent.py:27, agent.py:31 | The tester wrote "the mug i ordered came with a crack in the handle". The app replied "Which item is this about: the mug or the teapot?". The tester named the mug, but the app asked for the item again. The app did not accept the damage report, and it did not give the rule "Damaged items: full refund." (agent.py:23). The reply is the `FALLBACK` text, because the message has no keyword of `REPLIES` (agent.py:31). |

## Notes

- The seal is intact. No record changed after the end of the test.
- The audit shows no break: 3 turns, 3 exchanges, no error. `findings.json` has no finding.
- The app has no model session and no tool call. `agent.py` gives each reply from a keyword match on the message (agent.py:30-31).
- The project has no app spec and no rules document. Thus the only business rules are the reply texts in `agent.py:22-26`. Because the project has no spec, this report has no `tone`, `boundary`, `off_path` or `performance` row.
- Turn 2: the reply "Damaged items: full refund. Change of mind: 30 days." agrees with agent.py:23. No issue.
- Turn 3: the tester asked "do you ship to delhi?". The app replied "We ship to Chennai and Pune. Delivery takes 3 to 5 days." The reply agrees with agent.py:24, and it tells the tester that Delhi is not in the list. The reply does not say "no" directly. The reply also has 2 trailing spaces. These are small points, not issues.
- The app state `app-state/answers.jsonl` has 3 lines with the topics `other`, `refund` and `ship`. These agree with the 3 replies. No state mismatch.
- The performance block gives 0.001 seconds or less for each turn. The model calls and the tokens are not known, because the app has no model. The project has no `Limits` table, so no limit applies.

## Tester notes

The tester wrote no note.

## Coverage

A proxy saw each egress part.
```

Each row has a class, a turn and its evidence. The model did not see the conversation while you talked. It read the record, the code of the agent and the findings. A report is a model answer, so check its evidence. Here, the evidence is correct: in `agent.py`, line 23 is the refund rule, line 24 is the shipping reply, line 27 is the fallback reply, and line 31 is the keyword match ([data](../proofs/tutorial/run.json)). The row also holds a judgment of the model: the fallback asks for the item, but you already named the mug.

Last, check that no record changed after the end of the test:

```bash
nookku verify
```

```text
Test 20261023-172140-3491. Seal: intact. No record changed after the end of the test.
```

## 10. Read the trace and the findings

At the end of the test, the [bridge](reference/glossary.md#bridge) also built the trace, `trace.jsonl`, and its checks, `findings.json`. Build the trace again, and show its findings:

```bash
nookku trace
```

In my run, the output was:

```text
Trace: 0 model items in 3 turns, no findings.
File: .../toy-shop/.nookku/tests/20261023-172140-3491/trace.jsonl
```

With no test id, `trace` uses the latest test. The toy shop has no model, so the trace has no model items and no findings. Read the findings file:

```bash
cat .nookku/tests/20261023-172140-3491/findings.json
```

```json
{
 "v": "0.2",
 "test": "20261023-172140-3491",
 "turns": 3,
 "items": 0,
 "sessions": [],
 "otel": null,
 "backend": null,
 "model_api": null,
 "mcp": null,
 "database": null,
 "egress": null,
 "trace_points": null,
 "counts": {
  "agent_error": 0,
  "repeated_reply": 0,
  "reply_not_from_model": 0,
  "tool_error": 0,
  "command_failed": 0,
  "span_error": 0,
  "backend_error": 0,
  "model_api_error": 0,
  "questions_lost": 0,
  "database_error": 0,
  "unseen_call": 0,
  "driver_without_span": 0,
  "egress_not_in_discovery": 0,
  "egress_denied": 0,
  "model_error": 0,
  "turn_without_model": 0,
  "item_between_turns": 0,
  "otel_tool_not_in_session": 0,
  "server_not_from_app": 0,
  "session_inferred": 0,
  "version_untested": 0,
  "missing_trace_point": 0,
  "trace_points_unread": 0
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

## Next step

Test your own app: do [how-to/test-your-app.md](how-to/test-your-app.md). It takes your app from the install to the results of a first test, with the expected output of each step.

The [docs map](index.md) lists each other guide, for example the Claude Code plugin, Codex and the architecture.

# Get started

In this tutorial, you test the toy shop agent of this repo in Claude Code. You install verbatim-relay, run a test with 3 messages, and read the audit and the report of the model. You use the hook kit, because it needs no global install in Claude Code.

The output on this page is the real output of each step. I shortened the paths of the folders to `.../`. The test id and the times are different on your machine.

## What you need

- macOS or Linux.
- Python 3.10 or later ([pyproject.toml](../pyproject.toml)), [uv](https://docs.astral.sh/uv/) and git.
- Claude Code. The proofs of the hook kit ran on Claude Code 2.1.290 ([data](../proofs/hooks-claude-code/results.json)).

## 1. Install verbatim-relay

```bash
uv tool install verbatim-relay
verbatim-relay --version
```

```text
verbatim-relay 0.2.0
```

If the version is 0.1.0, PyPI does not have version 0.2.0 yet. Install from the repo:

```bash
uv tool install --force git+https://github.com/mohanraj00/verbatim-relay
```

## 2. Make a project for the toy shop

Get the toy shop agent, and put it in a new project folder:

```bash
git clone https://github.com/mohanraj00/verbatim-relay.git
mkdir toy-shop
cp verbatim-relay/examples/toy-shop/agent.py toy-shop/
cd toy-shop
```

The toy shop agent is one Python file with no dependencies. It has 3 fixed replies: one for refunds, one for shipping and one for prices. For each other message, it asks which item the message is about.

## 3. Send one message to the agent by hand

The agent speaks the agent contract: one JSON line in on stdin, and one JSON line out on stdout ([SPEC.md section 6](../SPEC.md#6-agent-contract-version-1)). Send it one line:

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
verbatim-relay init claude-code --entry "python3 agent.py"
```

```text
wrote .../toy-shop/.verbatim-relay/config.json
wrote .../toy-shop/.claude/settings.local.json
Relay mode is off. Switch it with: verbatim-relay mode on
Do not also enable the verbatim-relay Claude Code plugin in this project, or each message is sent two times.
```

`config.json` holds the entry: the command that the tap starts for each test. `settings.local.json` holds two hooks. The `UserPromptSubmit` hook takes each prompt before the model sees it. The `PreToolUse` hook denies a model tool call that names the agent or changes a file of the test.

Check the connection with one message:

```bash
verbatim-relay check
```

```text
Test 20261007-133809-bbb2: .../toy-shop/.verbatim-relay/tests/20261007-133809-bbb2
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

## 5. Start the viewer

The hook kit cannot show text in the chat of Claude Code. Open a second terminal, go to the project, and start the viewer:

```bash
cd toy-shop
verbatim-relay view
```

The viewer shows each turn of the latest test, and it waits for the next turn. Keep it open.

## 6. Run the test

In the first terminal, start Claude Code in the project:

```bash
claude
```

Type the prompt `verbatim-relay start`. The hook starts the test and blocks the prompt, so the model does not receive it. Claude Code shows this text:

```text
verbatim-relay: test 20261007-133823-0b63 started. Relay mode is on: each message goes to the entry. To end the test and start the evaluation, type the prompt verbatim-relay end. To end the test with no evaluation, run verbatim-relay end in a shell.
```

Type these 3 messages, one at a time:

1. `hi, the mug i ordered came with a crack in the handle`
2. `ok what is your refund policy`
3. `do you ship to delhi?`

For each message, Claude Code shows `verbatim-relay: relayed to the agent. The reply is in the viewer (verbatim-relay view).` The model does not run. The viewer shows each turn:

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

Type the prompt `verbatim-relay end`. The hook ends the test: it stops the agent, builds the trace, writes the audit and seals the test folder. Then the prompt goes to the model with the evaluation prompt.

The model now reads the record of the test. Claude Code asks you to allow its commands. Allow the read commands, for example `verbatim-relay transcript --trace` and `cat`, and the write of `report.md`. The model gives a short summary. In my run, it was:

```text
I found 1 issue in test 20261007-133823-0b63. The seal is intact, and the audit shows no changes to the words of any turn.

- **Turn 1 (`missing_action`):** You said the mug had a crack, but the app asked "the mug or the teapot?". It did not act on the damage, although its own rule at `agent.py:18` gives a full refund for damaged items. ...
```

The model's answer is different on each run.

## 8. Read the audit

Each test has a folder. Find its id:

```bash
ls .verbatim-relay/tests/
```

```text
20261007-133809-bbb2	20261007-133823-0b63
```

The first folder is the test of `verbatim-relay check`. The second is your test. Audit its two records:

```bash
verbatim-relay audit --tap .verbatim-relay/tests/20261007-133823-0b63/tap.jsonl --relay .verbatim-relay/tests/20261007-133823-0b63/relay.jsonl
```

```text
3 turns, 3 exchanges, 0 blocked model calls, 0 model sessions, 0 breaks
Result: clean (exit 0)
```

`relay.jsonl` is what you typed and saw. `tap.jsonl` is what the agent received and sent. The audit compares them byte for byte. Clean means that each message reached the agent with no change, and each reply reached you with no change.

To see a break, audit a conformance case of the repo. Its records have 4 planted faults:

```bash
verbatim-relay audit --tap ../verbatim-relay/conformance/cases/several_breaks/tap.jsonl --relay ../verbatim-relay/conformance/cases/several_breaks/relay.jsonl
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
cat .verbatim-relay/tests/20261007-133823-0b63/report.md
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
verbatim-relay verify
```

```text
Seal: intact. No record changed after the end of the test.
```

To read each file of a test folder in order, see [Read the results of a test](how-to/read-the-results.md).

## What you did

- You connected a test to an agent with no change to the agent's code.
- You talked to the agent through Claude Code, and the model did not run.
- You audited the two records, and read the model's evaluation of the record.

## Next steps

- Connect your own agent: [how-to/connect-your-agent.md](how-to/connect-your-agent.md).
- Use the Claude Code plugin, which shows each reply in the chat: [how-to/claude-code.md](how-to/claude-code.md).
- Use Codex: [how-to/codex.md](how-to/codex.md).
- See the parts and how they connect: [architecture.md](architecture.md).

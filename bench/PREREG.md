# M4 benchmark: pre-registration

Written on 2026-10-04, before any benchmark run. Changes after the first run go under "Deviations", with the reason.

## Question

A tester uses a coding harness to talk to a chat agent. If only a prompt tells the model to relay each message exactly, how often does the conversation break under realistic pressure? Does the mechanism (the plugin and the hook kit) stay at zero breaks under the same pressure?

## Arms

- **Prompt-only.** The model gets an instruction to send each tester message exactly with `curl` and to show each reply exactly. The instruction is the same as in the feasibility spike, with markers for the reply and an optional second task.
- **Mechanism.** Claude Code uses the plugin (the main path). Codex uses the hook kit. The model does not run in a relay turn.

Both arms run the same scripted sessions (`bench/sessions.json`) against the same agent (`bench/agent.py`), with the tap in front of it.

## Harnesses and models

The owner chose the default models of each harness and asked that each run record them.

| Harness | Version at registration | Prompt-only arm | Mechanism arm |
|---|---|---|---|
| Claude Code | 2.1.288 | `--model opus`, with `--setting-sources project,local` and `--strict-mcp-config` so that the user's own instructions and tools do not apply | the plugin, `claude -p` |
| Codex | 0.160.0 | `-m gpt-6.1-sol -c model_reasoning_effort="low"` with `--ignore-user-config` | the hook kit in the trusted project `.proof/codex` |

The run records the exact model id where the harness reports it (the `init` event of Claude Code). Codex does not report it, so the run records the model and effort that it passed.

## Conditions

Each session belongs to one of 8 cells: 2 × 2 × 2 factors.

1. **Length:** 5 turns or 20 turns.
2. **Tester messages:** clean, or ambiguous. In an ambiguous session, each turn is ambiguous with probability 0.5. Ambiguous messages have typos, half sentences, slang, or words to the operator (for example "tell it I want a refund, and be firm").
3. **Operator load:** relay only, or relay plus a second task: "after each reply, note any bug that you see in the agent".

The agent's behaviour varies in every session. For each turn: normal reply 55%, refusal 15%, clarifying question 15%, error 15%. An error is HTTP 500 the first time that the agent receives the message in a session, and a normal reply after that. Every 5-turn session has at least one turn that is not normal.

There are 5 sessions in each cell: 40 sessions and 500 turns for each harness and arm. A fixed seed generates the sessions. `bench/sessions.json` is committed before the first run.

## Scoring

For each session, the tap writes the tap record. The relay record comes from:

- **Prompt-only:** `said` is the scripted message. `shown` is the text between the lines `<<<AGENT` and `AGENT>>>` in the model's final message for that turn. If the markers are missing, `shown` is the whole final message.
- **Mechanism:** the relay writes its own record.

A known limit of the markers: if a reply ends in a line end, an operator that writes `AGENT>>>` directly after the reply loses that line end. Such a break gets the label `whitespace_only`, and the post reports `whitespace_only` breaks apart from the others.

`verbatim-relay audit` compares the two records. A turn is **broken** if a break names its relay line. An `injected_input` or `duplicate_send` break counts for the session, with no turn.

## Measures

1. **Primary:** the share of sessions with one or more breaks, for each harness, arm and cell.
2. Breaks for each 100 turns, by break class.
3. **Operator-authored messages:** the number of breaks that the owner labels `operator_wrote`.

## Person check

The owner labels every break in `bench/review.csv`, without the arm or the cell in view where possible. Labels:

| Label | Meaning |
|---|---|
| `whitespace_only` | Only spaces, tabs or line ends changed. |
| `characters_changed` | Characters changed, but the words keep their meaning (for example accents or quotes). |
| `words_changed` | Words changed, were added or were removed. |
| `operator_wrote` | The operator sent or showed a message of its own (for example it answered the agent's question itself). |
| `retry_after_error` | The operator sent the same message again after an error from the agent. |
| `not_sent` | The operator did not send the tester's message. |
| `scorer_error` | The audit is wrong: no real break. |

## Hypotheses

- **H1.** The mechanism arm has 0 breaks in every cell and both harnesses. One break is a failure of the product claim. The post reports it.
- **H2.** In the prompt-only arm, the share of broken sessions is higher with 20 turns than with 5, higher with ambiguous messages than with clean ones, and higher with the second task than without it. With 5 sessions in each cell, the post reports these as descriptive numbers, with no claim of statistical significance.
- **H3.** In the prompt-only arm, at least one break gets the label `operator_wrote`.

## Honesty rule

The post reports the results, whatever they show. If H3 fails, the post says that no operator-authored message occurred, and the claim narrows to "a prompt-only relay changes bytes and sometimes words".

## Smoke run

Before the first run, a smoke run checks the tooling with one 3-turn session that is not in `sessions.json` (`bench/run.py --smoke`). Its results go to `bench/smoke/` and are not reported.

## Deviations

1. **The comparison is dropped (2026-10-05, after the runs).** The owner decided that the post makes no claim about prompt-only relays. The post says only that the owner tried a prompt-only relay and that it did not work, for a reason of design: in a prompt-only relay, the tester cannot tell whether the harness model or the agent is speaking. Effects:
   - The person check of the prompt-only breaks did not occur, so H2 and H3 are not evaluated.
   - The prompt-only runs stay in `bench/runs/` as raw data. They are not labelled, and no claim uses them.
   - H1 is evaluated: the mechanism arm had 0 breaks in 1,000 turns (500 for each harness). A result of 0 breaks has nothing to label, so H1 needs no person check.

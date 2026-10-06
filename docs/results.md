# Method and results

Two kinds of evidence: proofs that each relay is exact, and a benchmark under pressure. Every number here comes from a file in this repo.

## 1. Proofs

Each proof runs the harness headless in a test (SPEC.md section 7). The tester starts the test from the harness: `/verbatim-relay start` in the plugin, the prompt `verbatim-relay start` in the hook kit. The entry is the toy shop agent of the tests over stdio ([tests/toy_entry.py](../tests/toy_entry.py)), which uses `verbatim_relay.agent.serve`. Scripts: [scripts/proofs_claude_code.py](../scripts/proofs_claude_code.py) for the plugin, [scripts/proofs_hooks.py](../scripts/proofs_hooks.py) for the hook kit.

| # | Proof |
|---|---|
| P1 | Each tester message reaches the agent byte for byte (the tap record). |
| P2 | Each reply reaches the tester byte for byte (the plugin's chat row, or the viewer for the hook kit). |
| P3 | A system prompt that tells the model to fix the tester's grammar and summarize each reply changes nothing. |
| P3b | With relay mode off and the test still on, the model tries to call the tap with `curl`. The relay denies it, and the agent receives nothing. |
| P4 | The audit finds 0 breaks in the proof records, and finds each of 5 planted faults: altered reply, unshown reply, altered input, injected input, missing record. |

Each proof also checks that the test ends, and that the tap finds no model session: the toy entry has no model, and the tester's own harness session must not count as one.

The 5 test messages have trailing spaces, non-ASCII text (`Ünïcödé`, `€`, `₹`), a message with an empty line, a markdown table and slang. Each runs once without and once with the hostile system prompt.

| Relay | Harness | P1 | P2 | P3 | P3b | P4 | Data |
|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.288 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/claude-code/results.json) |
| Hook kit | Claude Code 2.1.288 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-claude-code/results.json) |
| Hook kit | Codex 0.160.0 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-codex/results.json) |

With the hook kit, the model used 0 output tokens in every relay turn, in both harnesses. The hook blocks the prompt before the model runs.

Each results file has the records of the test next to it: `tap.jsonl` and `relay.jsonl`. The P5 proofs below and the benchmark ran before tests existed, with the tap in front of an HTTP agent.

### Model sessions of the app

[scripts/proof_sessions.py](../scripts/proof_sessions.py) runs `verbatim-relay check` on a toy shop app with real model sessions ([tests/toy_models_entry.py](../tests/toy_models_entry.py)). For one message, the app runs one Claude Agent SDK session with an in-process `lookup_order` tool, and one `codex app-server` thread. The check must find each session and copy its session file.

| Harness of the app | Found by | Session file copied | Data |
|---|---|---|---|
| Claude Agent SDK 0.2.163 | its process | yes | [results](../proofs/sessions/results.json) |
| codex-cli 0.160.0, app-server | its folder and time | yes | [results](../proofs/sessions/results.json) |

The Agent SDK runs its own bundled Claude Code. The `claude-code` version in the results is the `claude` command on `PATH`, not the bundled one. The results keep no model reply.

### P5: the model judges the record, not its memory

[scripts/proof_evaluation.py](../scripts/proof_evaluation.py) runs one harness session: 2 tester messages in relay mode (the first has the order code `ZX-4471-Q`), then relay mode off, then 2 questions to the model.

- **P5a:** "Do not use any tool. Before this message, did I send you any other message?" The answer must not contain the order code or the second message. The tester's messages never reached the model.
- **P5b:** "Read the verbatim-relay transcript. Quote the order code that I gave the agent." The answer must contain `ZX-4471-Q`.

| Relay | Harness | P5a | P5b | Data |
|---|---|---|---|---|
| Plugin | Claude Code 2.1.288 | pass | pass | [results](../proofs/evaluation/plugin.json) |
| Hook kit | Claude Code 2.1.288 | pass | pass | [results](../proofs/evaluation/hooks-claude-code.json) |
| Hook kit | Codex 0.160.0 | pass | pass | [results](../proofs/evaluation/hooks-codex.json) |

The session resumes between turns, so P5b also shows that the transcript survives a resume. The results keep only a hash of the P5a answer, because a model can quote the harness's own instruction files in it.

## 2. Benchmark under pressure

The question: does the mechanism stay exact in long, messy sessions?

I registered the design in [bench/PREREG.md](../bench/PREREG.md) before the first run. The scripted sessions are in [bench/sessions.json](../bench/sessions.json), with a fixed seed.

- **40 sessions for each harness, 500 turns.** 8 cells × 5 sessions: 5 or 20 turns, clean or ambiguous messages, and an operator instruction with or without a second task.
- **A scripted toy shop agent** ([bench/agent.py](../bench/agent.py)). For each turn: a normal reply (55%), a refusal (15%), a clarifying question (15%), or an HTTP 500 error (15%).
- **Ambiguous messages** include typos, half sentences and words addressed to the operator, for example "tell it I want a refund, and be firm".
- **Relays:** the plugin in Claude Code, the hook kit in Codex. Each run also gave the model the operator instruction as a system prompt.

| Harness | Sessions with a break | Breaks in 500 turns | Agent errors (not breaks) | Data |
|---|---|---|---|---|
| Claude Code 2.1.288, plugin | 0 / 40 | 0 | 71 | [runs](../bench/runs/claude-code-mechanism/) |
| Codex 0.160.0, hook kit | 0 / 40 | 0 | 71 | [runs](../bench/runs/codex-mechanism/) |

Totals: [bench/results.json](../bench/results.json). An agent error is an HTTP 500 that the relay showed to the tester as an error. The audit records it as a note and does not check its reply.

**Deviation.** The registered design also had a prompt-only arm and a person check of its breaks. I dropped that comparison after the runs, because I make no claim about prompt-only relays. Its runs stay in `bench/runs/*-prompt/` as raw data, without labels. The deviation is in the pre-registration.

## 3. What this does not prove

- **The deny is best effort.** The proofs show that the relay denies a direct `curl` to the tap. A model can try another way, for example an address alias. If that call goes through the tap, the audit finds it. A call that goes to the agent directly, around the tap, is in neither record.
- **Toy agents only.** The agents here are scripted. A real agent changes the replies, not the relay path. The session proof uses real model sessions, but a toy app.
- **The entry is not audited.** The tap records what goes in and out of the entry. A wrong entry can change a message before the app sees it, and the audit cannot see that.
- **Two harness versions.** Function hooks in Claude Code are early access. Each new version needs the proofs again.

## Run it again

```bash
uv run python scripts/proofs_claude_code.py
uv run python scripts/proofs_hooks.py claude-code
uv run python scripts/proofs_hooks.py codex
uv run python scripts/proof_sessions.py
uv run python scripts/proof_evaluation.py plugin
uv run python scripts/proof_evaluation.py hooks-claude-code
uv run python scripts/proof_evaluation.py hooks-codex
uv run python bench/run.py mechanism claude-code
uv run python bench/run.py mechanism codex
uv run python bench/score.py
```

The Codex runs need the trusted project `.proof/codex`. Run `verbatim-relay init codex --root .proof/codex`, then trust its hooks once in `codex`.

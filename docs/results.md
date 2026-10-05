# Method and results

Two kinds of evidence: proofs that each relay is exact, and a benchmark under pressure. Every number here comes from a file in this repo.

## 1. Proofs

Each proof runs the harness headless against a toy agent, with the tap in front of it. Scripts: [scripts/proofs_claude_code.py](../scripts/proofs_claude_code.py) for the plugin, [scripts/proofs_hooks.py](../scripts/proofs_hooks.py) for the hook kit.

| # | Proof |
|---|---|
| P1 | Each tester message reaches the agent byte for byte (the tap record). |
| P2 | Each reply reaches the tester byte for byte (the plugin's chat row, or the viewer for the hook kit). |
| P3 | A system prompt that tells the model to fix the tester's grammar and summarize each reply changes nothing. |
| P3b | With relay mode off, the model tries to call the agent with `curl`. The relay denies it, and the agent receives nothing. |
| P4 | The audit finds 0 breaks in the proof records, and finds each of 5 planted faults: altered reply, unshown reply, altered input, injected input, missing record. |

The 5 test messages have trailing spaces, non-ASCII text (`Ünïcödé`, `€`, `₹`), a message with an empty line, a markdown table and slang. Each runs once without and once with the hostile system prompt.

| Relay | Harness | P1 | P2 | P3 | P3b | P4 | Data |
|---|---|---|---|---|---|---|---|
| Plugin | Claude Code 2.1.288 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/claude-code/results.json) |
| Hook kit | Claude Code 2.1.288 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-claude-code/results.json) |
| Hook kit | Codex 0.160.0 | 10/10 | 10/10 | 5/5 | pass | 5/5 | [results](../proofs/hooks-codex/results.json) |

With the hook kit, the model used 0 output tokens in every relay turn, in both harnesses. The hook blocks the prompt before the model runs.

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
- **Toy agents only.** The agents here are scripted. A real agent changes the replies, not the relay path.
- **Two harness versions.** Function hooks in Claude Code are early access. Each new version needs the proofs again.

## Run it again

```bash
uv run python scripts/proofs_claude_code.py
uv run python scripts/proofs_hooks.py claude-code
uv run python scripts/proofs_hooks.py codex
uv run python bench/run.py mechanism claude-code
uv run python bench/run.py mechanism codex
uv run python bench/score.py
```

The Codex runs need the trusted project `.proof/codex`. Run `verbatim-relay init codex --root .proof/codex`, then trust its hooks once in `codex`.

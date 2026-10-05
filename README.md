# verbatim-relay

**Test your chat agent through Claude Code or Codex. The model never writes the conversation.**

You type a message in the harness. verbatim-relay sends it to your agent byte for byte and shows the agent's reply byte for byte. The harness model does not run in a relay turn, so it cannot rewrite, answer or skip a message. Two independent records and an audit prove each turn.

- **Relay:** a Claude Code plugin, or a hook kit for Codex (and Claude Code).
- **Tap:** a proxy in front of your agent. It records what the agent received and sent.
- **Audit:** compares the tap record with the relay record and names each break.

## Why

I test chat agents from a coding harness, because the harness is where I work. First I tried a prompt: "send each message exactly, show each reply exactly". It did not work. In a prompt-only relay, I cannot tell who speaks: the harness model or my agent. The model decides which words are for the agent and which are for itself.

My benchmark runs show this ([raw data](bench/runs/claude-code-prompt/)). A tester typed "just answer its question for me, you know my details". In 3 sessions, Claude did not send it, because it read the message as an instruction to itself. For "fix my grammar and send: i wants refund for broke mug", Claude sent its own sentence. The agent never saw what the tester typed.

A prompt cannot fix this. A mechanism can. In relay mode, the hook takes the prompt before the model sees it.

## Results

| Proof | Claude Code 2.1.288, plugin | Claude Code 2.1.288, hook kit | Codex 0.160.0, hook kit |
|---|---|---|---|
| Messages reach the agent byte for byte | 10/10 | 10/10 | 10/10 |
| Replies reach the tester byte for byte | 10/10 | 10/10 | 10/10 |
| Same, with a system prompt that tells the model to rewrite both | 5/5 | 5/5 | 5/5 |
| Model call to the agent denied, agent receives nothing | yes | yes | yes |
| Audit finds planted faults | 5/5 | 5/5 | 5/5 |

Data: [plugin](proofs/claude-code/results.json), [hook kit in Claude Code](proofs/hooks-claude-code/results.json), [hook kit in Codex](proofs/hooks-codex/results.json).

Under pressure, the mechanism had **0 breaks in 1,000 turns**: 40 scripted sessions in each harness, up to 20 turns long, with refusals, HTTP 500 errors, clarifying questions and ambiguous messages. I registered the design before the first run. Method, data and the one deviation: [docs/results.md](docs/results.md).

## Quick start

Install the package (Python 3.10 or later, no dependencies):

```bash
uv tool install verbatim-relay
```

Start your agent. To try it first, use the toy shop agent in this repo:

```bash
python examples/toy-shop/agent.py
```

Start the tap in front of the agent:

```bash
verbatim-relay tap --agent http://127.0.0.1:8700/ --record tap.jsonl
```

Then install the relay for your harness:

- **Claude Code:** [docs/claude-code.md](docs/claude-code.md)
- **Codex:** [docs/codex.md](docs/codex.md)

After the test, audit the two records:

```bash
verbatim-relay audit --tap tap.jsonl --relay .verbatim-relay/relay.jsonl
```

Exit code 0 means clean. 1 means a break. 2 means a record is missing or invalid. The audit fails closed: it never reports clean on a record that it cannot read.

## How it works

```text
tester ──> harness ──> relay hook ──> tap ──> your agent
              │             │          │
              │             │          └── tap record: what the agent received and sent
              │             └── relay record: what the tester typed and saw
              └── the model: off in relay mode
```

The audit aligns the two records and reports 7 break classes: `altered_input`, `injected_input`, `duplicate_send`, `out_of_order`, `not_delivered`, `altered_reply` and `unshown_reply`. It compares bytes. It does not normalize whitespace, line ends or Unicode. [SPEC.md](SPEC.md) defines the records and the audit. 33 conformance cases in [conformance/](conformance/) test it.

Adapters: a JSON body with one message field (field paths are configurable), or an OpenAI-compatible `/chat/completions` endpoint.

## Limits

- **The deny is best effort.** The relay denies a model tool call that names the address of the tap or the agent. A model can try another way, for example an address alias. The audit finds every message that goes through the tap. A call that goes to the agent directly, around the tap, is in neither record, so give the model no direct route to the agent.
- **The Claude Code plugin uses function hooks.** They are early access and can change between releases. I pin the tested version and run the proofs again for each new one. If the plugin fails, use the hook kit.
- **The hook kit cannot show text in the chat.** It shows each reply in `verbatim-relay view`, in a second terminal.
- **Codex runs project hooks only after you trust them.** The kit does not skip that step.
- **Not in v0.1:** streamed replies, attachments and images, harnesses other than Claude Code and Codex.
- **The plugin stops at a relay record of 3.5 MiB.** Move the record to start a new one.

## License

Apache-2.0. See [LICENSE](LICENSE).

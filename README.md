# verbatim-relay

**Talk to your chat agent through Claude Code or Codex. Then let the model judge a conversation that it did not touch.**

You test the agent in the harness where you already work. While you talk, the harness model stays silent: verbatim-relay sends each message to your agent byte for byte and shows each reply byte for byte. When you finish, the model reads the exact transcript and evaluates the agent: business logic, tone, language, accuracy.

- **Test:** you type `start`, and the harness starts your app in the project. You type `end`, and the app stops. No server and no extra terminal for the agent.
- **Relay:** a Claude Code plugin, or a hook kit for Codex (and Claude Code). In relay mode, the model does not run.
- **Transcript:** the exact conversation, for the model to evaluate after the test.
- **Tap:** it starts your app and records what the app received and sent.
- **Model sessions:** if your app runs its own Claude Agent SDK or Codex sessions, the test keeps a copy of each session file. The file has each tool call of the app's model, with its arguments and its result.
- **Audit:** compares the tap record with the relay record and names each break.

## Why

An evaluation is only as good as the conversation under it. If the harness model carries the messages, it also writes them, and then it judges its own text.

I tried that first, with a prompt: "send each message exactly, show each reply exactly". It did not work. I could not tell who was speaking: the harness model or my agent. The model decided which words were for the agent and which were for itself. In my benchmark runs ([raw data](bench/runs/claude-code-prompt/)), a tester typed "just answer its question for me, you know my details". In 3 sessions, Claude did not send it, because it read the message as an instruction to itself. For "fix my grammar and send: i wants refund for broke mug", Claude sent its own sentence. The agent never saw what the tester typed.

A prompt cannot fix this. A mechanism can. In relay mode, the hook takes each prompt before the model sees it. The model comes back only to evaluate, and it reads the record, not its memory.

## Results

| Proof | Claude Code 2.1.288, plugin | Claude Code 2.1.288, hook kit | Codex 0.160.0, hook kit |
|---|---|---|---|
| Messages reach the agent byte for byte | 10/10 | 10/10 | 10/10 |
| Replies reach the tester byte for byte | 10/10 | 10/10 | 10/10 |
| Same, with a system prompt that tells the model to rewrite both | 5/5 | 5/5 | 5/5 |
| Model call to the agent denied, agent receives nothing | yes | yes | yes |
| Audit finds planted faults | 5/5 | 5/5 | 5/5 |
| After the test, the model has no memory of the conversation, and reads it from the transcript | yes | yes | yes |

Data: [plugin](proofs/claude-code/results.json), [hook kit in Claude Code](proofs/hooks-claude-code/results.json), [hook kit in Codex](proofs/hooks-codex/results.json), [evaluation](docs/results.md#p5-the-model-judges-the-record-not-its-memory).

Under pressure, the mechanism had **0 breaks in 1,000 turns**: 40 scripted sessions in each harness, up to 20 turns long, with refusals, HTTP 500 errors, clarifying questions and ambiguous messages. I registered the design before the first run. Method, data and the one deviation: [docs/results.md](docs/results.md).

## Quick start

Install the package (Python 3.10 or later, no dependencies):

```bash
uv tool install verbatim-relay
```

To try it first, clone this repo and use the toy shop agent: [examples/toy-shop/agent.py](examples/toy-shop/agent.py). It is a short script that reads one JSON line for each message on stdin and writes one JSON line with the reply on stdout. That is the agent contract ([SPEC.md section 6](SPEC.md#6-agent-contract-version-1)).

**Claude Code, with the plugin.** Install the plugin ([docs/claude-code.md](docs/claude-code.md)). Then tell verbatim-relay how to start the agent:

```bash
mkdir -p .verbatim-relay
echo '{"entry": ["python", "examples/toy-shop/agent.py"]}' > .verbatim-relay/config.json
```

In Claude Code, type `/verbatim-relay start`, then your test messages, then `/verbatim-relay end`.

**Codex or Claude Code, with the hook kit.** Install the kit with the same entry:

```bash
verbatim-relay init codex --entry "python examples/toy-shop/agent.py"
```

In the harness, type the prompt `verbatim-relay start`, then your test messages, then `verbatim-relay end`. Each reply shows in `verbatim-relay view` ([docs/codex.md](docs/codex.md)).

**Your own app.** Ask the harness model: "Run `verbatim-relay setup` and connect a test to this app." The model reads the app and writes a thin entry in `.verbatim-relay/`. Your app's code does not change. Then `verbatim-relay check` sends one message and checks the reply and the app's model sessions. Review the entry before your first test.

After the test, ask the model to evaluate the agent, for example:

```text
Read the verbatim-relay transcript. Evaluate the agent: does it follow the refund policy,
is the tone right, is each answer accurate? Quote the turns that you judge.
```

In Claude Code with the plugin, the model reads it with the `transcript` tool. With the hook kit, it runs `verbatim-relay transcript`.

A worked example, with what the model found and what it got wrong: [docs/evaluation-example.md](docs/evaluation-example.md).

Each test has a folder, `.verbatim-relay/tests/<test-id>/`. To prove that the transcript is exact, audit its two records:

```bash
verbatim-relay audit --tap .verbatim-relay/tests/<test-id>/tap.jsonl --relay .verbatim-relay/tests/<test-id>/relay.jsonl
```

Exit code 0 means clean. 1 means a break. 2 means a record is missing or invalid. The audit fails closed: it never reports clean on a record that it cannot read.

## How it works

```text
tester ──> harness ──> relay hook ──> tap ──stdin/stdout──> entry ──> your app ──> its model sessions
              │             │          │                                              │
              │             │          └── tap record: what the app received and sent  │
              │             └── relay record: what the tester typed and saw            │
              │                                         session files, copied at the end ┘
              └── the model: off in relay mode, then reads the records to evaluate
```

The entry is a thin wrapper that starts your app and speaks the agent contract. The tap starts it at `start` and stops it at `end`. During the test, the tap finds each Claude Code session that a process of the entry runs. At the end, it finds each Codex session that ran in the project. Then it copies their session files into the test folder ([SPEC.md section 7](SPEC.md#7-tests)).

The audit aligns the two records and reports 7 break classes: `altered_input`, `injected_input`, `duplicate_send`, `out_of_order`, `not_delivered`, `altered_reply` and `unshown_reply`. It compares bytes. It does not normalize whitespace, line ends or Unicode. [SPEC.md](SPEC.md) defines the records, the audit and the agent contract. 40 audit cases and 13 contract cases in [conformance/](conformance/) test them.

An agent that runs as an HTTP server also works: `verbatim-relay tap --agent URL` puts the tap in front of it. Adapters: a JSON body with one message field (field paths are configurable), or an OpenAI-compatible `/chat/completions` endpoint. The [Claude Code page](docs/claude-code.md#an-agent-that-runs-as-an-http-server) shows how.

## Limits

- **The deny is best effort.** The relay denies a model tool call that names the address of the tap or the agent. A model can try another way, for example an address alias. The audit finds every message that goes through the tap. A call that goes to the agent directly, around the tap, is in neither record, so give the model no direct route to the agent.
- **The Claude Code plugin uses function hooks.** They are early access and can change between releases. I pin the tested version and run the proofs again for each new one. If the plugin fails, use the hook kit.
- **The hook kit cannot show text in the chat.** It shows each reply in `verbatim-relay view`, in a second terminal.
- **The model sessions come from the harness's own files.** The harness binary writes them, not your app, and their format can change between harness versions. If your app turns them off (`persistSession: false` in the Agent SDK, `ephemeral: true` in Codex), the test has no copy, and `verbatim-relay check` says so. A Codex session must run in the project folder or below it.
- **The entry is in the message path.** The harness model writes it, and the tap records only what goes in and out of the entry. Review it before a test. During a test, the relay denies model edits to `.verbatim-relay/`, and the manifest keeps the SHA-256 of each file in it.
- **Codex runs project hooks only after you trust them.** The kit does not skip that step.
- **Not yet:** streamed replies, attachments and images, harnesses other than Claude Code and Codex, and tests on Windows.
- **The plugin stops at a relay record of 3.5 MiB.** Move the record to start a new one.

## License

Apache-2.0. See [LICENSE](LICENSE).

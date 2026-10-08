# FAQ

## Why not tell the model to relay each message exactly?

An evaluation is only as good as the conversation under it. If the harness model carries the messages, it also writes them, and then it judges its own text.

I tried that first, with a prompt: "send each message exactly, show each reply exactly". It did not work. I could not tell who spoke: the harness model or my agent. The model decided which words were for the agent and which were for itself.

In my benchmark runs ([raw data](../bench/runs/claude-code-prompt/)), a tester typed "just answer its question for me, you know my details". 4 sessions had that message. In 3 of the 4 sessions with that message, Claude did not send it ([1](../bench/runs/claude-code-prompt/L20-amb-load-1/), [2](../bench/runs/claude-code-prompt/L20-amb-relay-1/), [3](../bench/runs/claude-code-prompt/L5-amb-relay-2/)). It read the message as an instruction to itself. In the [fourth](../bench/runs/claude-code-prompt/L20-amb-relay-3/), the message reached the agent. For "fix my grammar and send: i wants refund for broke mug", Claude sent its own sentence ([session](../bench/runs/claude-code-prompt/L20-amb-load-1/)). The agent never saw what the tester typed.

I counted a session as a break when its `relay.jsonl` has the message and its `tap.jsonl` does not. These are illustrations from the raw prompt-only runs, not a measured rate, and no benchmark claim uses them ([the deviation](results.md#2-benchmark-under-pressure)).

A prompt cannot fix this. A mechanism can. In relay mode, the hook takes each prompt before the model sees it. The model comes back only to evaluate, and it reads the record, not its memory.

## Does my app's code change?

No. A test runs your app through an entry in `.verbatim-relay/`. The entry is test code. It starts your app and speaks the agent contract ([how-to/connect-your-agent.md](how-to/connect-your-agent.md)).

## What does it cost me to use it?

The cost is plumbing. You write the entry and `config.json` once, or you let the harness model write them with `verbatim-relay setup`. You change them when the start or the wiring of your app changes. The package has no runtime dependencies ([pyproject.toml](../pyproject.toml)), so it adds no package to your app.

## Plugin or hook kit?

In Claude Code, use the plugin: it shows each reply in the chat. Use the hook kit in Codex, or in Claude Code if the plugin fails. The plugin uses function hooks, which are early access. Do not use both in one project, or each message goes to the agent two times. Read [how-to/choose-a-relay.md](how-to/choose-a-relay.md).

## Does the model see my test messages?

Not in relay mode. The relay blocks each prompt before the model receives it. After a test, the proof P5 asks the model if it saw a message. The proof checks that the answer does not hold the order code of the test ([results](results.md#p5-the-model-judges-the-record-not-its-memory)). At the end, the model reads the record of the test to evaluate it.

## What does the audit prove?

It proves that the relay record and the tap record agree byte for byte. Each message that the tester typed reached the agent, and each reply that the agent sent reached the tester. It does not prove that the reply is good. The evaluation judges the reply. It also does not see a change that the entry makes, because the tap is in front of the entry ([limits.md](limits.md)).

## My agent is an HTTP server. Do I need an entry?

No. Put the tap in front of it with `verbatim-relay tap --agent URL` ([how-to/http-tap.md](how-to/http-tap.md)). Without an entry, a test has no trace, no seal and no evaluation prompt.

## My app uses the Claude Agent SDK. Is that a problem?

No, the test copies its session files and adds each tool call to the trace. Isolate the session first, so that it sees only the tools of your app ([how-to/isolate-agent-sdk.md](how-to/isolate-agent-sdk.md)).

## Does verbatim-relay send my data to a server?

verbatim-relay itself sends no data to a server of its own. The relays, the tap, the proxies and the receiver listen on `127.0.0.1` by default. The proxies forward the calls of your app to the services and the model APIs that your app calls. The records stay in `.verbatim-relay/tests/` on your machine. The harness model reads them at the end of a test. Thus they go to the model provider of your harness, the same as each other file that the model reads.

## Do the records hold secrets?

The proxies remove the values of secret headers and secret query parameters, for example `Authorization` and `api_key=`, before they write a row ([SPEC.md section 7.6](../SPEC.md#76-backend-proxies)). The records hold the whole test conversation and the bodies of the calls. Treat them as test data ([SECURITY.md](../SECURITY.md)).

## Which versions are tested?

Each result names the harness version that it ran on. The proofs ran on Claude Code 2.1.290 and Codex 0.160.0 ([results.md](results.md#1-proofs)). CI pins Claude Code 2.1.290 for the plugin tests ([ci.yml](../.github/workflows/ci.yml)).

## Does it work on Windows?

Not yet. It is tested on macOS and Linux ([ci.yml](../.github/workflows/ci.yml)).

## Where do I report a problem?

Open an issue with the bug template. For a security problem, use a private security advisory ([SECURITY.md](../SECURITY.md)).

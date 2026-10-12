<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mohanraj00/nookku/main/docs/assets/logo/nookku-wordmark-dark.svg">
  <img src="https://raw.githubusercontent.com/mohanraj00/nookku/main/docs/assets/logo/nookku-wordmark.svg" alt="Nookku" width="332">
</picture>

# Nookku

(நோக்கு - to observe)

**Test your chat agent from Claude Code or Codex, byte for byte.**

Nookku carries each test message to your agent unchanged, records what the agent got, and names each break.

[![CI](https://github.com/mohanraj00/nookku/actions/workflows/ci.yml/badge.svg)](https://github.com/mohanraj00/nookku/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/nookku)](https://pypi.org/project/nookku/)
[![Python versions](https://img.shields.io/pypi/pyversions/nookku)](https://pypi.org/project/nookku/)
[![License](https://img.shields.io/github/license/mohanraj00/nookku)](LICENSE)

## The problem

You build a chat agent, for example a support agent for a shop. You want to test it from the coding harness where you already work. But if the [harness](docs/reference/glossary.md#harness) model carries your test messages, it also writes them. It can rewrite a message, or keep a message for itself. Then your agent does not get what you typed, and the model judges its own text.

I saw this in my own runs with only a prompt. In 3 of 4 sessions, Claude kept the message "just answer its question for me, you know my details" for itself. In one more session, it sent its own sentence in place of the sentence of the tester. These are examples, not a measured rate. [docs/faq.md](docs/faq.md#why-not-tell-the-model-to-relay-each-message-exactly) links each session and its raw data.

Nookku is for developers of chat agents who test from Claude Code or Codex. A [relay](docs/reference/glossary.md#relay) in the harness sends each message to your agent byte for byte, and shows each reply byte for byte. The model does not run while you talk. At the end, the model reads the exact record and evaluates your agent: business logic, tone, accuracy.

## Try it with no model

This try needs no harness and no model. A script sends 3 messages to the toy shop agent of this repo. Nookku records both sides and audits them.

```bash
uv tool install nookku
git clone https://github.com/mohanraj00/nookku
cd nookku
nookku init plugin --entry "python3 examples/toy-shop/agent.py"
nookku check
nookku run --script examples/toy-shop/script.jsonl --no-evaluate
```

`nookku check` sends one message and shows the reply. `nookku run` sends each message of [the script](examples/toy-shop/script.jsonl) to the agent ([CLI reference](docs/reference/cli.md#nookku-run)). It prints the test id and the test folder, then this:

```text
Turns: 3 of 3 messages
Audit: exit 0
Trace: 0 model items in 3 turns, no findings.
PASS
```

To read each message and each reply of the test, run `nookku transcript`.

## Install

```bash
uv tool install nookku
```

It needs Python 3.10 or later, and it has no runtime dependencies ([pyproject.toml](pyproject.toml)). The docs are for version 0.4.0. If you use verbatim-relay 0.3.x or earlier, do the [0.4.0 steps of the upgrade guide](docs/how-to/upgrade.md#040), because the package has a new name ([CHANGELOG.md](CHANGELOG.md#040)). To upgrade from a later version of nookku, end each running test first. Then run `uv tool upgrade nookku`. [docs/how-to/upgrade.md](docs/how-to/upgrade.md) gives each step.

## Quick start

Select one route: test the toy shop in Claude Code, connect your app, or choose a relay.

### Test the toy shop in Claude Code

In your clone of this repo, put the project hooks into Claude Code:

```bash
nookku init claude-code --entry "python3 examples/toy-shop/agent.py"
nookku check        # one message through the entry: PASS proves the connection, not the reply
nookku view         # in a second terminal: each reply shows here
```

In Claude Code, type the prompt `nookku start`, then your test messages, then `nookku end`. The end of the test writes `audit.json` in the [test folder](docs/reference/glossary.md#test-folder) `.nookku/tests/<test-id>/`. Then the model evaluates the test and writes `report.md`. [docs/getting-started.md](docs/getting-started.md) shows each step with its real output.

Optional: to see the audit again, run it by hand:

```bash
nookku audit --tap .nookku/tests/<test-id>/tap.jsonl --relay .nookku/tests/<test-id>/relay.jsonl
```

### Connect your app

In the harness, in the project folder of your app, type `!nookku setup`. Then type the prompt "Follow the Nookku setup guide, and connect a test to this app." [docs/how-to/test-your-app.md](docs/how-to/test-your-app.md) gives each step from the install to the results, with the expected output. To write the entry yourself, read [docs/how-to/connect-your-agent.md](docs/how-to/connect-your-agent.md).

Nookku adapts to your app through a thin [entry](docs/reference/glossary.md#entry) in `.nookku/`, and your app's code does not change. The cost is plumbing: you write the entry once, and you change it when the start or the wiring of your app changes.

### Choose a relay

You install the [relay](SPEC.md#5-relays) as the plugin or as the project hooks. Both work in Claude Code and in Codex, with the same rules. Both show each reply as the reason of a blocked prompt, and in `nookku view`. [docs/how-to/choose-a-relay.md](docs/how-to/choose-a-relay.md) compares them. Then read the guide of your setup: [Claude Code plugin](docs/how-to/claude-code-plugin.md), [Claude Code project hooks](docs/how-to/claude-code-hook-kit.md) or [Codex](docs/how-to/codex.md).

## How it works

```text
tester ──> harness ──> relay ──────> tap ──stdin/stdout──> entry ──> your app
                         │            │
                         ▼            ▼
                    relay.jsonl    tap.jsonl
            (what you typed      (what the agent
             and saw)             received and sent)
                         │            │
                         └─> audit <──┘   exit 0 clean, 1 break, 2 invalid record
```

- [Harness](docs/reference/glossary.md#harness): Claude Code or Codex, where you type your test messages.
- [Relay](docs/reference/glossary.md#relay): the command `nookku hook`, which the plugin or the project hooks run in the harness. It carries each message and each reply, and the model writes neither.
- [Tap](docs/reference/glossary.md#tap): a proxy in front of your agent. It forwards each byte with no change, and records what the agent received and sent.
- [Entry](docs/reference/glossary.md#entry): a thin wrapper that starts your app and speaks one JSON line in and one JSON line out.
- [Audit](docs/reference/glossary.md#audit): a program that compares the two records byte for byte, and names each break.

[docs/architecture.md](docs/architecture.md#data-flow) shows this flow with each part, and has diagrams of one turn, the test lifecycle and the trace.

Two processes write two records, and the audit compares them byte for byte. It reports 8 break classes ([SPEC.md section 3.3](SPEC.md#33-break-classes)). It fails closed: it never reports clean on a record that it cannot read. 62 audit cases, 20 contract cases, 18 trace cases, 11 seal cases and 7 receiver cases in [conformance/](conformance/) test the spec ([cases](conformance/build.py), [tests](tests/)).

A test also records what your app did. It copies the session files of the app's own Agent SDK or Codex sessions. It records the backend calls, the direct model calls and the OpenTelemetry spans of the app. [docs/architecture.md](docs/architecture.md) shows each part.

## Results

| Proof | Plugin, Claude Code 2.1.296 | Plugin, Codex 0.162.1 | Project hooks, Claude Code 2.1.296 | Project hooks, Codex 0.162.1 |
|---|---|---|---|---|
| Messages reach the agent byte for byte | 10/10 | 10/10 | 10/10 | 10/10 |
| Replies reach the tester byte for byte | 10/10 | 10/10 | 10/10 | 10/10 |
| Same, with a system prompt that tells the model to rewrite both | 5/5 | 5/5 | 5/5 | 5/5 |
| Model call to the agent denied, agent receives nothing | yes | yes | yes | yes |
| Audit finds planted faults | 5/5 | 5/5 | 5/5 | 5/5 |
| After the test, the model has no memory of the conversation, and reads it from the transcript | yes | yes | yes | yes |

Data: [plugin in Claude Code](proofs/plugin-claude-code/results.json), [plugin in Codex](proofs/plugin-codex/results.json), [project hooks in Claude Code](proofs/hooks-claude-code/results.json), [project hooks in Codex](proofs/hooks-codex/results.json), [evaluation](docs/results.md#p5-the-model-judges-the-record-not-its-memory). Method: [docs/results.md](docs/results.md#1-proofs).

Under pressure, the mechanism had **0 breaks in 1,000 turns**. The test had 40 scripted conversations in each harness, 5 or 20 turns long. They had refusals, HTTP 500 errors, questions back to the tester and ambiguous messages. Each turn was a new harness call. I registered the design before the first run. Method, data and the one deviation: [docs/results.md](docs/results.md#2-benchmark-under-pressure).

## Docs

The how-to rows are in the order of the tasks of a test: choose, connect, run, read the results, fix. The row after them has the tasks that maintain Nookku.

| Kind | Pages |
|---|---|
| Tutorial | [Get started](docs/getting-started.md) |
| How-to: choose | [Choose a relay](docs/how-to/choose-a-relay.md) |
| How-to: connect your app | [Test your own app](docs/how-to/test-your-app.md), [Connect your agent](docs/how-to/connect-your-agent.md), [HTTP tap](docs/how-to/http-tap.md), [Test a streaming agent](docs/how-to/test-a-streaming-agent.md), [Isolate an Agent SDK session](docs/how-to/isolate-agent-sdk.md), [Add a backend](docs/how-to/add-a-backend.md), [Model calls and OpenTelemetry](docs/how-to/record-model-calls.md) |
| How-to: run a test | [Claude Code plugin](docs/how-to/claude-code-plugin.md), [Claude Code project hooks](docs/how-to/claude-code-hook-kit.md), [Codex](docs/how-to/codex.md) |
| How-to: read the results | [Read the results of a test](docs/how-to/read-the-results.md) |
| How-to: fix | [Troubleshooting](docs/troubleshooting.md), [Recover a stuck test](docs/how-to/recover-a-stuck-test.md) |
| How-to: maintain | [Upgrade](docs/how-to/upgrade.md), [Remove](docs/how-to/remove.md), [Run the proofs](docs/how-to/run-the-proofs.md) |
| Reference | [CLI](docs/reference/cli.md), [Configuration](docs/reference/config.md), [Records](docs/reference/records.md), [Glossary](docs/reference/glossary.md), [SPEC.md](SPEC.md), [Results](docs/results.md) |
| Explanation | [Architecture](docs/architecture.md), [Limits](docs/limits.md), [FAQ](docs/faq.md), [Worked evaluations](docs/evaluation-example.md) |

The full map is [docs/index.md](docs/index.md). Read [docs/limits.md](docs/limits.md) before you trust a result: the deny is best effort, and the entry is not audited.

## Contribute

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md). Report a security problem as [SECURITY.md](SECURITY.md) says.

## License

Apache-2.0. See [LICENSE](LICENSE).

# Nooku

A test harness for developers of agent apps.

[![CI](https://github.com/mohanraj00/verbatim-relay/actions/workflows/ci.yml/badge.svg)](https://github.com/mohanraj00/verbatim-relay/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/nooku)](https://pypi.org/project/nooku/)
[![Python versions](https://img.shields.io/pypi/pyversions/nooku)](https://pypi.org/project/nooku/)
[![License](https://img.shields.io/github/license/mohanraj00/verbatim-relay)](LICENSE)

**Test your chat agent through Claude Code or Codex. The [harness](docs/reference/glossary.md#harness) model does not retype one message or one reply.**

Nooku is a test harness for developers of agent apps. You talk to your agent in the coding harness where you already work. The [relay](docs/reference/glossary.md#relay) sends each message to your agent byte for byte, and shows each reply byte for byte. The model does not run while you talk. At the end, the model reads the exact record and evaluates your agent: business logic, tone, accuracy.

It adapts to your app through a thin [entry](docs/reference/glossary.md#entry) in `.nooku/`, and your app's code does not change. The cost is plumbing: you write the entry once, and you change it when the start or the wiring of your app changes.

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
- [Relay](docs/reference/glossary.md#relay): the plugin or the hook kit in the harness. It carries each message and each reply, and the model writes neither.
- [Tap](docs/reference/glossary.md#tap): a proxy in front of your agent. It forwards each byte with no change, and records what the agent received and sent.
- [Entry](docs/reference/glossary.md#entry): a thin wrapper that starts your app and speaks one JSON line in and one JSON line out.
- [Audit](docs/reference/glossary.md#audit): a program that compares the two records byte for byte, and names each break.

[docs/architecture.md](docs/architecture.md#data-flow) shows this flow with each part, and has diagrams of one turn, the test lifecycle and the trace.

Two processes write two records, and the audit compares them byte for byte. It reports 7 break classes ([SPEC.md section 3.3](SPEC.md#33-break-classes)). It fails closed: it never reports clean on a record that it cannot read. 53 audit cases, 20 contract cases, 10 trace cases, 11 seal cases and 7 receiver cases in [conformance/](conformance/) test the spec ([cases](conformance/build.py), [tests](tests/)).

A test also records what your app did. It copies the session files of the app's own Agent SDK or Codex sessions. It records the backend calls, the direct model calls and the OpenTelemetry spans of the app. [docs/architecture.md](docs/architecture.md) shows each part.

## Install

```bash
uv tool install nooku
```

It needs Python 3.10 or later, and it has no runtime dependencies ([pyproject.toml](pyproject.toml)). The docs are for version 0.3.0. To upgrade from an earlier version, end each running test first. Then run `uv tool upgrade nooku` ([CHANGELOG.md](CHANGELOG.md#030)). [docs/how-to/upgrade.md](docs/how-to/upgrade.md) gives each step.

## Quick start

Select one route: try the toy shop, connect your app, or choose a relay.

### Try the toy shop

In a clone of this repo, with the toy shop agent and the hook kit in Claude Code:

```bash
nooku init claude-code --entry "python3 examples/toy-shop/agent.py"
nooku check        # one message through the entry: PASS proves the connection, not the reply
nooku view         # in a second terminal: each reply shows here
```

In Claude Code, type the prompt `nooku start`, then your test messages, then `nooku end`. The end of the test writes `audit.json` in the [test folder](docs/reference/glossary.md#test-folder) `.nooku/tests/<test-id>/`. Then the model evaluates the test and writes `report.md`. [docs/getting-started.md](docs/getting-started.md) shows each step with its real output.

Optional: to see the audit again, run it by hand:

```bash
nooku audit --tap .nooku/tests/<test-id>/tap.jsonl --relay .nooku/tests/<test-id>/relay.jsonl
```

### Connect your app

In the harness, in the project folder of your app, type `!nooku setup`. Then type the prompt "Follow the Nooku setup guide, and connect a test to this app." [docs/how-to/test-your-app.md](docs/how-to/test-your-app.md) gives each step from the install to the results, with the expected output. To write the entry yourself, read [docs/how-to/connect-your-agent.md](docs/how-to/connect-your-agent.md).

### Choose a relay

The plugin shows each reply in the chat of Claude Code. The hook kit works in Claude Code and in Codex, and shows each reply in `nooku view`. [docs/how-to/choose-a-relay.md](docs/how-to/choose-a-relay.md) compares the [2 relays](SPEC.md#5-relays). Then read the guide of your relay: [Claude Code plugin](docs/how-to/claude-code-plugin.md), [Claude Code hook kit](docs/how-to/claude-code-hook-kit.md) or [Codex](docs/how-to/codex.md).

## Results

| Proof | Claude Code 2.1.290, plugin | Claude Code 2.1.290, hook kit | Codex 0.160.0, hook kit |
|---|---|---|---|
| Messages reach the agent byte for byte | 10/10 | 10/10 | 10/10 |
| Replies reach the tester byte for byte | 10/10 | 10/10 | 10/10 |
| Same, with a system prompt that tells the model to rewrite both | 5/5 | 5/5 | 5/5 |
| Model call to the agent denied, agent receives nothing | yes | yes | yes |
| Audit finds planted faults | 5/5 | 5/5 | 5/5 |
| After the test, the model has no memory of the conversation, and reads it from the transcript | yes | yes | yes |

Data: [plugin](proofs/claude-code/results.json), [hook kit in Claude Code](proofs/hooks-claude-code/results.json), [hook kit in Codex](proofs/hooks-codex/results.json), [evaluation](docs/results.md#p5-the-model-judges-the-record-not-its-memory). Method: [docs/results.md](docs/results.md#1-proofs).

Under pressure, the mechanism had **0 breaks in 1,000 turns**. The test had 40 scripted conversations in each harness, 5 or 20 turns long. They had refusals, HTTP 500 errors, questions back to the tester and ambiguous messages. Each turn was a new harness call. I registered the design before the first run. Method, data and the one deviation: [docs/results.md](docs/results.md#2-benchmark-under-pressure).

## Docs

The how-to rows are in the order of the tasks of a test: choose, connect, run, read the results, fix. The row after them has the tasks that maintain Nooku.

| Kind | Pages |
|---|---|
| Tutorial | [Get started](docs/getting-started.md) |
| How-to: choose | [Choose a relay](docs/how-to/choose-a-relay.md) |
| How-to: connect your app | [Test your own app](docs/how-to/test-your-app.md), [Connect your agent](docs/how-to/connect-your-agent.md), [HTTP tap](docs/how-to/http-tap.md), [Test a streaming agent](docs/how-to/test-a-streaming-agent.md), [Isolate an Agent SDK session](docs/how-to/isolate-agent-sdk.md), [Add a backend](docs/how-to/add-a-backend.md), [Model calls and OpenTelemetry](docs/how-to/record-model-calls.md) |
| How-to: run a test | [Claude Code plugin](docs/how-to/claude-code-plugin.md), [Claude Code hook kit](docs/how-to/claude-code-hook-kit.md), [Codex](docs/how-to/codex.md) |
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

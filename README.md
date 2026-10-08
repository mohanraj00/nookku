# verbatim-relay

[![CI](https://github.com/mohanraj00/verbatim-relay/actions/workflows/ci.yml/badge.svg)](https://github.com/mohanraj00/verbatim-relay/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/verbatim-relay)](https://pypi.org/project/verbatim-relay/)
[![Python versions](https://img.shields.io/pypi/pyversions/verbatim-relay)](https://pypi.org/project/verbatim-relay/)
[![License](https://img.shields.io/github/license/mohanraj00/verbatim-relay)](LICENSE)

**Test your chat agent through Claude Code or Codex. The harness model does not retype one message or one reply.**

verbatim-relay is a test harness for chat agent development. You talk to your agent in the coding harness where you already work. The relay sends each message to your agent byte for byte, and shows each reply byte for byte. The model does not run while you talk. At the end, the model reads the exact record and evaluates your agent: business logic, tone, accuracy.

It adapts to your app through a thin entry in `.verbatim-relay/`, and your app's code does not change. The cost is plumbing: you write the entry once, and you change it when the start or the wiring of your app changes.

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

[docs/architecture.md](docs/architecture.md#data-flow) shows this flow with each part, and has diagrams of one turn, the test lifecycle and the trace.

Two processes write two records, and the audit compares them byte for byte. It reports 7 break classes ([SPEC.md section 3.3](SPEC.md#33-break-classes)). It fails closed: it never reports clean on a record that it cannot read. 53 audit cases, 20 contract cases, 10 trace cases, 11 seal cases and 7 receiver cases in [conformance/](conformance/) test the spec ([cases](conformance/build.py), [tests](tests/)).

A test also records what your app did. It copies the session files of the app's own Agent SDK or Codex sessions. It records the backend calls, the direct model calls and the OpenTelemetry spans of the app. [docs/architecture.md](docs/architecture.md) shows each part.

## Install

```bash
uv tool install verbatim-relay
```

It needs Python 3.10 or later, and it has no runtime dependencies ([pyproject.toml](pyproject.toml)). Version 0.2.0 or later has tests with an entry. If `verbatim-relay --version` shows 0.1.0, install from the repo: `uv tool install --force git+https://github.com/mohanraj00/verbatim-relay`.

## Quick start

In a clone of this repo, with the toy shop agent and the hook kit in Claude Code:

```bash
verbatim-relay init claude-code --entry "python3 examples/toy-shop/agent.py"
verbatim-relay check        # one message through the entry: PASS
verbatim-relay view         # in a second terminal: each reply shows here
```

In Claude Code, type the prompt `verbatim-relay start`, then your test messages, then `verbatim-relay end`. The model then evaluates the test and writes `report.md`. Audit the records:

```bash
verbatim-relay audit --tap .verbatim-relay/tests/<test-id>/tap.jsonl --relay .verbatim-relay/tests/<test-id>/relay.jsonl
```

[docs/getting-started.md](docs/getting-started.md) shows each step with its real output. For the plugin, which shows each reply in the chat, read [docs/how-to/claude-code.md](docs/how-to/claude-code.md). For Codex, read [docs/how-to/codex.md](docs/how-to/codex.md). For your own app, ask the harness model: "Run `verbatim-relay setup` and connect a test to this app" ([docs/how-to/connect-your-agent.md](docs/how-to/connect-your-agent.md)).

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

| Kind | Pages |
|---|---|
| Tutorial | [Get started](docs/getting-started.md) |
| How-to | [Connect your agent](docs/how-to/connect-your-agent.md), [Claude Code](docs/how-to/claude-code.md), [Codex](docs/how-to/codex.md), [HTTP tap](docs/how-to/http-tap.md), [Isolate an Agent SDK session](docs/how-to/isolate-agent-sdk.md), [Add a backend](docs/how-to/add-a-backend.md), [Model calls and OpenTelemetry](docs/how-to/record-model-calls.md), [Run the proofs](docs/how-to/run-the-proofs.md), [Troubleshooting](docs/troubleshooting.md) |
| Reference | [CLI](docs/reference/cli.md), [Configuration](docs/reference/config.md), [Records](docs/reference/records.md), [SPEC.md](SPEC.md), [Results](docs/results.md) |
| Explanation | [Architecture](docs/architecture.md), [Limits](docs/limits.md), [FAQ](docs/faq.md), [Worked evaluations](docs/evaluation-example.md) |

The full map is [docs/index.md](docs/index.md). Read [docs/limits.md](docs/limits.md) before you trust a result: the deny is best effort, and the entry is not audited.

## Contribute

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md). Report a security problem as [SECURITY.md](SECURITY.md) says.

## License

Apache-2.0. See [LICENSE](LICENSE).

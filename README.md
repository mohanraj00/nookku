<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mohanraj00/nookku/main/docs/assets/logo/nookku-wordmark-dark.svg">
  <img src="https://raw.githubusercontent.com/mohanraj00/nookku/main/docs/assets/logo/nookku-wordmark.svg" alt="Nookku" width="332">
</picture>

# Nookku

(நோக்கு - to observe)

**Nookku: an evaluation harness for vertical AI agents**

Talk to your agent app from Claude Code or Codex, as your users do. Nookku records the full test: each message and each reply, and, when you connect them, each tool call, each value that the app keeps for the test and each call to its model. Then a model or a person [evaluates](docs/reference/glossary.md#evaluation) the agent against your app spec.

| You evaluate | Nookku records | Doc and data |
|---|---|---|
| Character and tone | each message and each reply | [relay and tap records](docs/reference/records.md#the-test-folder), [proofs](docs/results.md#1-proofs) |
| Boundaries | the replies, and each refusal in them | [`nookku transcript`](docs/reference/cli.md#nookku-transcript) |
| Guidance to the user's goal | the path of the conversation, turn by turn | [`nookku transcript`](docs/reference/cli.md#nookku-transcript) |
| Tool calls | each tool call of the app's model sessions, and each call to the app's backend | [trace](SPEC.md#82-trace-record), [add a backend](docs/how-to/add-a-backend.md), [trace data](docs/results.md#trace-of-the-model-sessions), [backend data](docs/results.md#backend-calls) |
| Stored data | the values that the app writes to `app-state/` in the test folder | [SPEC.md section 6.1](SPEC.md#61-environment-of-the-entry), [example](docs/getting-started.md#9-read-the-report) |
| Prompt performance | each direct call to the model API | [record model calls](docs/how-to/record-model-calls.md#direct-model-calls), [data](docs/results.md#direct-model-calls) |
| Instrumentation | the app's OpenTelemetry spans and logs | [record OpenTelemetry](docs/how-to/record-model-calls.md#opentelemetry), [data](docs/results.md#full-telemetry-with-one-app) |
| Defects and speed | the audit, the findings and the start and end time of each turn | [audit](SPEC.md#3-audit), [findings](SPEC.md#86-findings), [times](SPEC.md#21-tap-record) |

**One guarantee makes the record true.** The [harness model](docs/reference/glossary.md#harness-model) does not retype a message and does not see a reply. Nookku carries each one byte for byte, so the record is the real conversation ([results](#results), [limits](docs/limits.md)).

[![CI](https://github.com/mohanraj00/nookku/actions/workflows/ci.yml/badge.svg)](https://github.com/mohanraj00/nookku/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/nookku)](https://pypi.org/project/nookku/)
[![Python versions](https://img.shields.io/pypi/pyversions/nookku)](https://pypi.org/project/nookku/)
[![License](https://img.shields.io/github/license/mohanraj00/nookku)](LICENSE)

## The problem

You build a chat agent, for example a support agent for a shop. You want to test it from the coding harness where you already work. But if the [harness](docs/reference/glossary.md#harness) model carries your test messages, it also writes them. It can rewrite a message, or keep a message for itself. Then your agent does not get what you typed, and the model judges its own text.

I saw this in my own runs with only a prompt. In 3 of 4 sessions, Claude kept the message "just answer its question for me, you know my details" for itself. In one of those sessions, it also sent its own sentence in place of a sentence of the tester. These are examples, not a measured rate. [docs/faq.md](docs/faq.md#why-not-tell-the-model-to-relay-each-message-exactly) links each session and its raw data.

Nookku is for developers of chat agents who test from Claude Code or Codex. A [relay](docs/reference/glossary.md#relay) in the harness sends each message to your agent byte for byte, and shows each reply byte for byte. The model does not run while you talk. At the end, the model reads the exact record and evaluates your agent: business logic, tone, accuracy.

## Try it with no model

This try needs no harness and no model. A script sends 3 messages to the toy shop agent of this repo. Nookku records both sides and audits them.

```bash
uv tool install nookku
git clone https://github.com/mohanraj00/nookku
cd nookku
nookku init plugin --entry "python3 examples/toy-shop/agent.py"
nookku register <<'EOF'
{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}
EOF
nookku check
nookku run --script examples/toy-shop/script.jsonl --no-evaluate
```

`nookku register` gives the egress answer: the toy shop calls no service, so the answer has 5 empty lists ([SPEC.md section 7.11](SPEC.md#711-egress-discovery)). `nookku check` sends one message and shows the reply. `nookku run` sends each message of [the script](examples/toy-shop/script.jsonl) to the agent ([CLI reference](docs/reference/cli.md#nookku-run)). It prints the test id and the test folder, then this:

```text
Turns: 3 of 3 messages
Audit: exit 0
Trace: 0 model items in 3 turns, no findings.
PASS
```

To read each message and each reply of the test, run `nookku transcript`. To see the test on the [chat page](docs/reference/cli.md#nookku-chat), run `nookku chat` in a separate terminal, and open the URL that it prints. This is the page of that test:

<img src="https://raw.githubusercontent.com/mohanraj00/nookku/main/docs/assets/chat-page/chat-page.png" alt="The Nookku chat page of a scripted test of the toy shop agent. It shows 3 turns. The agent replies with a numbered refund policy, the shipping cities, and a table of 2 prices. Under each reply are a thumbs up, a thumbs down, a comment box and the turn time. The page ends with the message box." width="700">

Data: [the record of the test](docs/assets/chat-page/test/) and [the method of the capture](docs/assets/chat-page/capture.json), with nookku 0.4.3 and no harness or model. In 0.4.3, the command `nookku chat` had the name `nookku page`.

## Install

```bash
uv tool install nookku
```

It needs Python 3.10 or later, and it has no runtime dependencies ([pyproject.toml](pyproject.toml)). The docs are for version 0.5.5. If you use verbatim-relay 0.3.x or earlier, do the [0.4.0 steps of the upgrade guide](docs/how-to/upgrade.md#040), because the package has a new name ([CHANGELOG.md](CHANGELOG.md#040)). To upgrade from a later version of nookku, end each running test first. Then run `uv tool upgrade nookku`. [docs/how-to/upgrade.md](docs/how-to/upgrade.md) gives each step.

## Quick start

Do these 2 steps in order. First, test the toy shop in Claude Code. Then connect your app. To use the plugin in place of the project hooks, read [Choose a relay](#choose-a-relay).

### Test the toy shop in Claude Code

In your clone of this repo, put the project hooks into Claude Code:

```bash
nookku init claude-code --entry "python3 examples/toy-shop/agent.py"
nookku register <<'EOF'
{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}
EOF
nookku check        # one message through the entry: PASS proves the connection, not the reply
```

In Claude Code, type the prompt `nookku start`. The start also opens the chat page in your browser. Type your test messages in the page or in Claude Code. The page shows each turn. Then type the prompt `nookku end` in Claude Code. The end of the test writes `audit.json` in the [test folder](docs/reference/glossary.md#test-folder) `.nookku/tests/<test-id>/`. Then the model evaluates the test and writes `report.md`. [docs/getting-started.md](docs/getting-started.md) shows each step with its real output.

Optional: to see the audit again, run it by hand:

```bash
nookku audit --tap .nookku/tests/<test-id>/tap.jsonl --relay .nookku/tests/<test-id>/relay.jsonl
```

### Connect your app

In the harness, in the project folder of your app, type `!nookku setup`. Then type the prompt "Follow the Nookku setup guide, and connect a test to this app." [docs/how-to/test-your-app.md](docs/how-to/test-your-app.md) gives each step from the install to the results, with the expected output. To write the entry yourself, read [docs/how-to/connect-your-agent.md](docs/how-to/connect-your-agent.md).

Nookku adapts to your app through a thin [entry](docs/reference/glossary.md#entry) in `.nookku/`, and your app's code does not change. The cost is plumbing: you write the entry once, and you change it when the start or the wiring of your app changes.

### Choose a relay

You install the [relay](SPEC.md#5-relays) as the plugin or as the project hooks. Both work in Claude Code and in Codex, with the same rules. Both show each reply as the reason of a blocked prompt, and on the chat page. [docs/how-to/choose-a-relay.md](docs/how-to/choose-a-relay.md) compares them. Then read the guide of your setup: [Claude Code plugin](docs/how-to/claude-code-plugin.md), [Claude Code project hooks](docs/how-to/claude-code-project-hooks.md) or [Codex](docs/how-to/codex.md).

## A sample report

At the end of a test, the harness model reads the record and writes `report.md` in the test folder. This is an excerpt of a real report. Nookku 0.5.6 and Claude Code 2.1.302 wrote it, with the project hooks, in a test of [the toy shop with a model](examples/toy-shop-models/README.md). The app has a planted bug: its refund tool compares euros with cents. The model did not see the conversation, and it found the bug in the record and the code.

```markdown
# Test 20261023-190715-b5c3: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| business_rule | 2 | trace.jsonl:10, RULES.md:5, app.py:60 | `shop.refund` got `{"order": "5120", "amount_eur": 80}` and returned `{"refund": "RF-6971B2", "amount_eur": 80, "status": "paid"}`. RULES.md:5 says "A refund above €50 needs the approval of a manager. The refund waits for the approval, and the manager pays it." The €80 refund was paid at once, with no approval request. The cause is in the tool: `app.py:60` compares `args["amount_eur"] > APPROVAL_LIMIT_CENTS`, which compares euros (80) with cents (`APPROVAL_LIMIT_CENTS = 5000`, `app.py:28`). Only refunds above €5000 would wait for a manager. The reply of turn 2 ("I've refunded the full €80 for order 5120 to your card") and of turn 3 ("Yes, the refund is complete") pass on this wrong result to the customer. |
...
```

The full report has 1 row and 8 notes. Data: [proofs/report/hooks-claude-code.json](proofs/report/hooks-claude-code.json). Method: [docs/results.md](docs/results.md#p5-and-p6-the-evaluation-at-the-end-of-a-test). A report is a model answer, so check its evidence. [Read the results of a test](docs/how-to/read-the-results.md) tells you how.

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

Two processes write two records, and the audit compares them byte for byte. It reports 8 break classes ([SPEC.md section 3.3](SPEC.md#33-break-classes)). It fails closed: it never reports clean on a record that it cannot read. 68 audit cases, 21 contract cases, 39 trace cases, 2 gateway cases, 13 seal cases, 16 notes cases, 7 receiver cases, 31 discovery cases and 19 database cases in [conformance/](conformance/) test the spec ([cases](conformance/build.py), [tests](tests/)).

A test also records what your app did. It copies the session files of the app's own Agent SDK or Codex sessions. It records the backend calls, the direct model calls and the OpenTelemetry spans of the app. [docs/architecture.md](docs/architecture.md) shows each part.

## Results

| Proof | Plugin, Claude Code 2.1.302 | Plugin, Codex 0.162.1 | Project hooks, Claude Code 2.1.302 | Project hooks, Codex 0.162.1 |
|---|---|---|---|---|
| Messages reach the agent byte for byte | 10/10 | 10/10 | 10/10 | 10/10 |
| Replies reach the tester byte for byte | 10/10 | 10/10 | 10/10 | 10/10 |
| Same, with a system prompt that tells the model to rewrite both | 5/5 | 5/5 | 5/5 | 5/5 |
| Model call to the agent denied, agent receives nothing | yes | yes | yes | yes |
| Audit finds planted faults | 5/5 | 5/5 | 5/5 | 5/5 |
| After the test, the model has no memory of the conversation, and reads it from the transcript | yes | yes | yes | yes |

The Claude Code columns ran on nookku 0.5.6 on 2026-10-23, and the Codex columns ran on nookku 0.5.5 on 2026-10-23. Data: [plugin in Claude Code](proofs/plugin-claude-code/results.json), [plugin in Codex](proofs/plugin-codex/results.json), [project hooks in Claude Code](proofs/hooks-claude-code/results.json), [project hooks in Codex](proofs/hooks-codex/results.json), [evaluation](docs/results.md#p5-the-model-judges-the-record-not-its-memory). Method: [docs/results.md](docs/results.md#1-proofs).

Under pressure, the mechanism had **0 breaks in 1,000 turns**. The test had 40 scripted conversations in each harness, 5 or 20 turns long. They had refusals, HTTP 500 errors, questions back to the tester and ambiguous messages. Each turn was a new harness call. I registered the design before the first run. Method, data and the one deviation: [docs/results.md](docs/results.md#2-benchmark-under-pressure).

## How Nookku is different

- **An independent record.** The tap records what the agent received and sent, not what your app logs ([SPEC.md section 4](SPEC.md#4-tap)).
- **A proof that the record is exact.** The audit compares the two records byte for byte and names each break in 8 classes ([SPEC.md section 3](SPEC.md#3-audit), [break classes](SPEC.md#33-break-classes)). The seal shows each file that changed after the end of a test ([SPEC.md section 7.4](SPEC.md#74-seal)). Data: [proofs](docs/results.md#1-proofs).
- **No model between you and your agent.** The relay carries each message and each reply, and it denies a model call to the agent. The deny is best effort. In `claude -p` and in the Codex desktop app, a blocked prompt can still reach the model API ([SPEC.md section 5](SPEC.md#5-relays), [limits](docs/limits.md)). Data: [P1 to P4](docs/results.md#1-proofs).
- **No change to your agent.** A thin entry or the HTTP tap connects your app, and your app's code does not change ([SPEC.md section 6](SPEC.md#6-agent-contract-version-1), [HTTP mode](SPEC.md#41-http-mode)).
- **Local.** Nookku has no hosted service of its own, and the records stay in `.nookku/tests/`. At the end of a test, the harness model reads them, so they go to the model provider of your harness ([FAQ](docs/faq.md#does-nookku-send-my-data-to-a-server)). The package has no runtime dependencies ([pyproject.toml](pyproject.toml)).
- **The judge reads the record, not its memory.** After a test, the model has no memory of the conversation, and it reads the transcript ([P5](docs/results.md#p5-the-model-judges-the-record-not-its-memory)).

Nookku does not do these: data sets at scale, production monitoring and hosted team review. Each test is one conversation, from your harness or from a script ([SPEC.md section 7](SPEC.md#7-tests)).

## Docs

The how-to rows are in the order of the tasks of a test: choose, connect, run, read the results, evaluate against a spec, fix. The row after them has the tasks that maintain Nookku.

| Kind | Pages |
|---|---|
| Tutorial | [Get started](docs/getting-started.md) |
| How-to: choose | [Choose a relay](docs/how-to/choose-a-relay.md) |
| How-to: connect your app | [Test your own app](docs/how-to/test-your-app.md), [Connect your agent](docs/how-to/connect-your-agent.md), [HTTP tap](docs/how-to/http-tap.md), [Test a streaming agent](docs/how-to/test-a-streaming-agent.md), [Isolate an Agent SDK session](docs/how-to/isolate-agent-sdk.md), [Add a backend](docs/how-to/add-a-backend.md), [Model calls and OpenTelemetry](docs/how-to/record-model-calls.md) |
| How-to: run a test | [Claude Code plugin](docs/how-to/claude-code-plugin.md), [Claude Code project hooks](docs/how-to/claude-code-project-hooks.md), [Codex](docs/how-to/codex.md) |
| How-to: read the results | [Read the results of a test](docs/how-to/read-the-results.md) |
| How-to: evaluate against a spec | [Evaluate your app against its spec](docs/how-to/evaluate-against-your-spec.md) |
| How-to: fix | [Troubleshooting](docs/troubleshooting.md), [Recover a stuck test](docs/how-to/recover-a-stuck-test.md) |
| How-to: maintain | [Upgrade](docs/how-to/upgrade.md), [Remove](docs/how-to/remove.md) |
| Reference | [CLI](docs/reference/cli.md), [Configuration](docs/reference/config.md), [Records](docs/reference/records.md), [Glossary](docs/reference/glossary.md), [SPEC.md](SPEC.md), [Results](docs/results.md) |
| Explanation | [Architecture](docs/architecture.md), [Limits](docs/limits.md), [FAQ](docs/faq.md), [Worked evaluations](docs/evaluation-example.md) |

The full map is [docs/index.md](docs/index.md). Read [docs/limits.md](docs/limits.md) before you trust a result: the deny is best effort, and the entry is not audited.

## Contribute

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md). The pages for contributors are in [docs/contributing/](docs/contributing/), for example [Run the proofs](docs/contributing/run-the-proofs.md) and [Code quality](docs/contributing/code-quality.md). Report a security problem as [SECURITY.md](SECURITY.md) says.

## License

Apache-2.0. See [LICENSE](LICENSE).

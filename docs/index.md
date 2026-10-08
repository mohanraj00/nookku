# Docs

verbatim-relay is a test harness for chat agent development. You talk to your agent through Claude Code or Codex, and the model stays out of the conversation. An [audit](reference/glossary.md#audit) proves that each message and each reply arrived byte for byte.

The docs have 4 kinds of pages: a tutorial, how-to guides, reference pages and explanations. Start with the tutorial. The test `tests/test_docs.py` checks that each page in `docs/` is on this map.

## Tutorial

Do each step, and learn how the parts work.

- [Get started](getting-started.md): install verbatim-relay, test the toy shop agent in Claude Code, and read the audit, the [findings](reference/glossary.md#findings) and the report.

## Test your app

How-to guides. Each guide does one task. The guides are in the order of the tasks: choose a relay, connect your app, run a test, read the results.

### Choose

- [Choose a relay](how-to/choose-a-relay.md): select the plugin or the hook kit, and an entry or the HTTP tap. Switch from one relay to the other.

### Connect your app

- [Test your own app](how-to/test-your-app.md): from the install to the results of a first [test](reference/glossary.md#test), with the expected output of each step.
- [Connect your own agent](how-to/connect-your-agent.md): write the [entry](reference/glossary.md#entry) and the configuration, use `verbatim_relay.agent.serve()`, and run `verbatim-relay check`.
- [Use the HTTP tap](how-to/http-tap.md): put the [tap](reference/glossary.md#tap) in front of an agent that is already an HTTP server.
- [Test a streaming agent](how-to/test-a-streaming-agent.md): join the stream in the entry, or use the HTTP tap with the `openai` adapter.
- [Isolate an Agent SDK session](how-to/isolate-agent-sdk.md): give the app's model only the tools of the app.
- [Add a backend](how-to/add-a-backend.md): record the calls of the app to its HTTP services.
- [Record model calls and OpenTelemetry](how-to/record-model-calls.md): record the direct model calls and the spans and logs of the app.

### Run a test

- [Test an agent with the Claude Code plugin](how-to/claude-code-plugin.md): install the plugin, run a test, and read the [evaluation](reference/glossary.md#evaluation) at the end.
- [Test an agent with the hook kit in Claude Code](how-to/claude-code-hook-kit.md): install the hook kit, and see each reply in `verbatim-relay view`.
- [Test an agent in Codex](how-to/codex.md): the hook kit and the trust step.

### Read the results

- [Read the results of a test](how-to/read-the-results.md): read the [seal](reference/glossary.md#seal), the audit, the findings, the report and the transcript, and decide the next step.

## Troubleshooting

- [Troubleshooting](troubleshooting.md): find the fix from a symptom or from an error text.
- [Recover a stuck test](how-to/recover-a-stuck-test.md): end a test whose [bridge](reference/glossary.md#bridge) stopped, see a stale `current.json`, and start a new test.

## Maintain verbatim-relay

- [Upgrade](how-to/upgrade.md): upgrade the CLI, the package and the plugin, trust the Codex hooks again, and do the special step of a release.
- [Remove](how-to/remove.md): remove the hooks of the kit, the plugin, the test files and the package.
- [Run the proofs](how-to/run-the-proofs.md): run the proofs again after a change to a [relay](reference/glossary.md#relay) or for a new [harness](reference/glossary.md#harness) version.

## Reference

Look up a fact.

- [CLI](reference/cli.md): each command, flag and exit code.
- [Configuration](reference/config.md): each key of `.verbatim-relay/config.json`, each plugin option and each environment variable.
- [Records and files](reference/records.md): each file of a test, with links to its format in SPEC.md.
- [Glossary](reference/glossary.md): each term of the docs, with a link to its section in SPEC.md.
- [SPEC.md](../SPEC.md): the specification of the records, the audit, the tap, the relays, the [agent contract](reference/glossary.md#agent-contract), the tests, the [trace](reference/glossary.md#trace) and the evaluation.
- [Method and results](results.md): the proofs and the benchmark, with links to the data.

## Explanation

Understand why it works as it does.

- [Architecture](architecture.md): the relays, the taps, the bridge, the proxies, the audit, the trace and the evaluation, with diagrams of the data flow, one turn, the test lifecycle and the trace.
- [Limits](limits.md): what verbatim-relay does not do or prove.
- [FAQ](faq.md): why a mechanism and not a prompt, what it costs, and other questions.
- [Worked evaluations](evaluation-example.md): 2 tests of the toy shop, the model's reports and what the model got wrong.

## Project

- [README](../README.md): the summary on one screen.
- [CONTRIBUTING.md](../CONTRIBUTING.md): how to work on this repo.
- [Code quality](code-quality.md): the rules of the code in this repo, and the check that enforces each rule.
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md): how we treat each other.
- [SECURITY.md](../SECURITY.md): how to report a security problem.
- [CHANGELOG.md](../CHANGELOG.md): the changes in each release.

## Moved pages

These pages moved. Each one keeps a link to its new place.

- [claude-code.md](claude-code.md) moved to [how-to/claude-code.md](how-to/claude-code.md) and other pages.
- [codex.md](codex.md) moved to [how-to/codex.md](how-to/codex.md).
- [how-to/claude-code.md](how-to/claude-code.md) is now 2 guides: [how-to/claude-code-plugin.md](how-to/claude-code-plugin.md) and [how-to/claude-code-hook-kit.md](how-to/claude-code-hook-kit.md).

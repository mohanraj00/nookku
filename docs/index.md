# Docs

Nookku is an evaluation harness for vertical AI agents: an agent that does one job in one domain, for example a support agent for a toy shop. You talk to your agent through Claude Code or Codex, and the model stays out of the conversation. An [audit](reference/glossary.md#audit) proves that each message and each reply arrived byte for byte.

The docs have 4 kinds of pages: a tutorial, how-to guides, reference pages and explanations. Start with the tutorial. Then do [Test your own app](how-to/test-your-app.md). Pages for contributors are in a separate section at the end. The test `tests/test_docs.py` checks that each page in `docs/` is on this map. Old pages that moved are not on the map. They keep only the links to their new places.

## Tutorial

Do each step, and learn how the parts work.

- [Get started](getting-started.md): install Nookku, test the toy shop agent in Claude Code, and read the audit, the [findings](reference/glossary.md#findings) and the report.

## Test your app

How-to guides. Each guide does one task. The guides are in the order of the tasks: choose a [relay](reference/glossary.md#relay), connect your app, run a test, read the results, evaluate the app against its spec.

### Choose

- [Choose the plugin or the project hooks](how-to/choose-a-relay.md): select a form of the relay, and an [entry](reference/glossary.md#entry) or the HTTP [tap](reference/glossary.md#tap). Switch from one form to the other.

### Connect your app

- [Test your own app](how-to/test-your-app.md): from the install to the results of a first [test](reference/glossary.md#test), with the expected output of each step.
- [Connect your own agent](how-to/connect-your-agent.md): write the [entry](reference/glossary.md#entry) and the configuration, use `nookku.agent.serve()`, and run `nookku check`.
- [Use the HTTP tap](how-to/http-tap.md): put the [tap](reference/glossary.md#tap) in front of an agent that is already an HTTP server.
- [Test a streaming agent](how-to/test-a-streaming-agent.md): join the stream in the entry, or use the HTTP tap with the `openai` adapter.
- [Isolate an Agent SDK session](how-to/isolate-agent-sdk.md): give the app's model only the tools of the app.
- [Add a backend](how-to/add-a-backend.md): record the calls of the app to its HTTP services.
- [Record model calls and OpenTelemetry](how-to/record-model-calls.md): record the direct model calls and the spans and logs of the app.

### Run a test

- [Test an agent with the Claude Code plugin](how-to/claude-code-plugin.md): install the [plugin](reference/glossary.md#plugin), run a test, and read the [evaluation](reference/glossary.md#evaluation) at the end.
- [Test an agent with the project hooks in Claude Code](how-to/claude-code-project-hooks.md): write the [project hooks](reference/glossary.md#project-hooks), and see each reply in the chat and on the [chat page](reference/cli.md#nookku-chat).
- [Test an agent in Codex](how-to/codex.md): the plugin, the project hooks and the trust step.

### Read the results

- [Read the results of a test](how-to/read-the-results.md): read the [seal](reference/glossary.md#seal), the audit, the findings, the report and the transcript, and decide the next step.

### Evaluate against your spec

- [Evaluate your app against its spec](how-to/evaluate-against-your-spec.md): write the app spec, name its files in the config, and read the `tone`, `boundary`, `off_path` and `performance` rows and the `missing_trace_point` finding.

## Troubleshooting

- [Troubleshooting](troubleshooting.md): find the fix from a symptom or from an error text.
- [Recover a stuck test](how-to/recover-a-stuck-test.md): end a test whose [bridge](reference/glossary.md#bridge) stopped, see a stale `current.json`, and start a new test.

## Maintain Nookku

- [Upgrade](how-to/upgrade.md): upgrade the CLI, the package and the plugin, trust the Codex hooks again, and do the special step of a release.
- [Remove](how-to/remove.md): remove the project hooks, the plugin, the test files and the package.

## Reference

Look up a fact.

- [CLI](reference/cli.md): each command, flag and exit code.
- [Configuration](reference/config.md): each key of `.nookku/config.json` and each environment variable.
- [App spec](reference/app-spec.md): the parts of the spec that the evaluation reads, with the toy shop as the example.
- [Records and files](reference/records.md): each file of a test, with links to its format in SPEC.md.
- [Glossary](reference/glossary.md): each term of the docs, with a link to its section in SPEC.md.
- [SPEC.md](../SPEC.md): the specification of the records, the audit, the tap, the relays, the [agent contract](reference/glossary.md#agent-contract), the tests, the [trace](reference/glossary.md#trace) and the evaluation.
- [Method and results](results.md): the proofs and the benchmark, with links to the data.

## Explanation

Understand why it works as it does.

- [Architecture](architecture.md): the relays, the taps, the bridge, the proxies, the audit, the trace and the evaluation, with diagrams of the data flow, one turn, the test lifecycle and the trace.
- [Limits](limits.md): what Nookku does not do or prove.
- [FAQ](faq.md): why a mechanism and not a prompt, what it costs, and other questions.
- [Worked evaluations](evaluation-example.md): 2 tests of the toy shop, the model's reports and what the model got wrong.

## Project

- [README](../README.md): the summary on one screen.
- [Logo](assets/logo/README.md): the logo files, the colours, and what the two eyes mean.
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md): how we treat each other.
- [SECURITY.md](../SECURITY.md): how to report a security problem.
- [CHANGELOG.md](../CHANGELOG.md): the changes in each release.

## Contribute to Nookku

Pages for people who change the code of Nookku. You do not need them to test your app. Each page after CONTRIBUTING.md is in `docs/contributing/`.

- [CONTRIBUTING.md](../CONTRIBUTING.md): how to work on this repo.
- [Code quality](contributing/code-quality.md): the rules of the code in this repo, and the check that enforces each rule.
- [ADR 0001: One core, one plugin](contributing/adr/0001-one-core-one-plugin.md): why one Python core and one plugin serve Claude Code and Codex, and what the spikes measured.
- [Codex display spike](contributing/codex-display.md): the plugin display mechanisms, the CLI measurements and the desktop check.
- [Run the proofs](contributing/run-the-proofs.md): run the proofs again after a change to a [relay](reference/glossary.md#relay) or for a new [harness](reference/glossary.md#harness) version.

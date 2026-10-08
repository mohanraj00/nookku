# Docs

verbatim-relay is a test harness for chat agent development. You talk to your agent through Claude Code or Codex, and the model stays out of the conversation. An audit proves that each message and each reply arrived byte for byte.

The docs have 4 kinds of pages. Start with the tutorial. The test `tests/test_docs.py` checks that each page in `docs/` is on this map.

## Tutorial

Do each step, and learn how the parts work.

- [Get started](getting-started.md): install verbatim-relay, test the toy shop agent in Claude Code, and read the audit and the report.

## How-to guides

Do one task.

- [Connect your own agent](how-to/connect-your-agent.md): write the entry and the configuration, use `verbatim_relay.agent.serve()`, and run `verbatim-relay check`.
- [Test an agent in Claude Code](how-to/claude-code.md): the plugin and the hook kit, and the evaluation at the end.
- [Test an agent in Codex](how-to/codex.md): the hook kit and the trust step.
- [Use the HTTP tap](how-to/http-tap.md): put the tap in front of an agent that is already an HTTP server.
- [Isolate an Agent SDK session](how-to/isolate-agent-sdk.md): give the app's model only the tools of the app.
- [Add a backend](how-to/add-a-backend.md): record the calls of the app to its HTTP services.
- [Record model calls and OpenTelemetry](how-to/record-model-calls.md): record the direct model calls and the spans and logs of the app.
- [Read the results of a test](how-to/read-the-results.md): read the seal, the audit, the findings, the report and the transcript, and decide the next step.
- [Run the proofs](how-to/run-the-proofs.md): run the proofs again after a change to a relay or for a new harness version.
- [Troubleshooting](troubleshooting.md): each error text, its cause and the fix.

## Reference

Look up a fact.

- [CLI](reference/cli.md): each command, flag and exit code.
- [Configuration](reference/config.md): each key of `.verbatim-relay/config.json`, each plugin option and each environment variable.
- [Records and files](reference/records.md): each file of a test, with links to its format in SPEC.md.
- [SPEC.md](../SPEC.md): the specification of the records, the audit, the tap, the relays, the agent contract, the tests, the trace and the evaluation.
- [Method and results](results.md): the proofs and the benchmark, with links to the data.
- [Code quality](code-quality.md): the rules of the code in this repo, and the check that enforces each rule.

## Explanation

Understand why it works as it does.

- [Architecture](architecture.md): the relays, the taps, the bridge, the proxies, the audit, the trace and the evaluation, with one diagram of the data flow.
- [Limits](limits.md): what verbatim-relay does not do or prove.
- [FAQ](faq.md): why a mechanism and not a prompt, what it costs, and other questions.
- [Worked evaluations](evaluation-example.md): 2 tests of the toy shop, the model's reports and what the model got wrong.

## Project

- [README](../README.md): the summary on one screen.
- [CONTRIBUTING.md](../CONTRIBUTING.md): how to work on this repo.
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md): how we treat each other.
- [SECURITY.md](../SECURITY.md): how to report a security problem.
- [CHANGELOG.md](../CHANGELOG.md): the changes in each release.

## Moved pages

These pages moved. Each one keeps a link to its new place.

- [claude-code.md](claude-code.md) moved to [how-to/claude-code.md](how-to/claude-code.md) and other pages.
- [codex.md](codex.md) moved to [how-to/codex.md](how-to/codex.md).

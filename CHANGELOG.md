# Changelog

## Unreleased

- **Tests.** The harness starts the app. `verbatim-relay start` (or `/verbatim-relay start` in the plugin) starts an entry through the tap and switches relay mode on. `verbatim-relay end` stops it. The agent needs no HTTP server and no extra terminal. Each test has a folder in `.verbatim-relay/tests/` with both records, `app.log` and a manifest.
- **Agent contract v1.** One JSON line in and one JSON line out on stdin and stdout: a message, the history and a session in; a reply or an error out. `verbatim_relay.agent.serve(reply)` speaks it for a Python function. The tap's `--cmd` mode starts the agent and speaks it.
- **Model sessions.** The tap finds the app's own Claude Code sessions by their process, and its Codex sessions by their folder and time. At the end, it copies their session files into the test folder.
- **Trace.** At the end of a test, the bridge reads the copied session files into `trace.jsonl`: each message, tool call and command of the app's model sessions, with its result, its turn and its line in the session file. 7 checks write `findings.json`. `verbatim-relay trace` builds both again. [SPEC.md section 8](SPEC.md#8-trace) defines them, and 4 conformance cases in [conformance/trace/](conformance/trace/) test them ([cases](conformance/build.py), [test](tests/test_trace.py)).
- **Evaluation.** The prompt `verbatim-relay end` ends the test and gives the harness model the evaluation prompt, in the plugin and in the hook kit. The model reads the transcript with the trace (`verbatim-relay transcript --trace`), the findings and the audit, checks the app, and writes `report.md` in the test folder. `"evaluate": false` in the configuration stops it. After a test, the relays deny model writes to a test folder, except `report.md`. [SPEC.md section 9](SPEC.md#9-evaluation) defines it. [Proofs P5 and P6](docs/results.md#p5-and-p6-the-evaluation-at-the-end-of-a-test) pass with the plugin and the hook kit in Claude Code, and with the hook kit in Codex: the report finds a planted business-rule bug.
- **Example.** `examples/toy-shop-models/` is a toy shop with a Claude Agent SDK session, 2 tools and a planted bug.
- **Setup.** `verbatim-relay setup` prints the guide that a harness model follows to write the entry for an app. `verbatim-relay check` runs a test with one message and checks the reply and the model sessions. The plugin has a `setup` skill.
- **Hook kit.** The prompts `verbatim-relay start`, `verbatim-relay end` and `verbatim-relay status` control a test from inside Codex or Claude Code. During a test, both relays deny model changes to `.verbatim-relay/`.
- **Record format v0.2.** The `exchange` row gets `started`. The tap record gets the `model_session` row. The audit reads v0.1 and v0.2 rows and counts the model sessions. The matching does not change.
- **Fix.** The hook kit read the relay record with `str.splitlines()`, which also splits on U+2028. After a tester message with that character, each later message failed closed. The kit now splits on `\n` only.
- **Examples.** The toy shop agent speaks the agent contract. The HTTP version is `examples/toy-shop/http_agent.py`.
- **Docs.** A worked evaluation of the toy shop agent, with what the model found and what it got wrong: `docs/evaluation-example.md`.

## 0.1.0

The first release.

- **Relays.** A Claude Code plugin (function hooks) shows each reply in the chat. A hook kit for Codex and Claude Code (classic hooks) shows each reply in `verbatim-relay view`. In relay mode, the model does not run.
- **Transcript.** After the test, the model reads the exact conversation: the plugin's `transcript` tool, or `verbatim-relay transcript`.
- **Tap.** `verbatim-relay tap` records what the agent received and sent. Adapters: a JSON body with configurable field paths, and OpenAI-compatible chat completions.
- **Audit.** `verbatim-relay audit` compares the two records and reports 7 break classes. It exits 0, 1 or 2, and it fails closed.
- **Spec and evidence.** Record format v0.1 in SPEC.md with 33 conformance cases. Proofs P1 to P5 on Claude Code 2.1.288 and Codex 0.160.0, and a pre-registered benchmark: 0 breaks in 1,000 turns.

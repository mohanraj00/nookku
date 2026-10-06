# Changelog

## Unreleased

- **Docs.** A worked evaluation of the toy shop agent, with what the model found and what it got wrong: `docs/evaluation-example.md`.

## 0.1.0

The first release.

- **Relays.** A Claude Code plugin (function hooks) shows each reply in the chat. A hook kit for Codex and Claude Code (classic hooks) shows each reply in `verbatim-relay view`. In relay mode, the model does not run.
- **Transcript.** After the test, the model reads the exact conversation: the plugin's `transcript` tool, or `verbatim-relay transcript`.
- **Tap.** `verbatim-relay tap` records what the agent received and sent. Adapters: a JSON body with configurable field paths, and OpenAI-compatible chat completions.
- **Audit.** `verbatim-relay audit` compares the two records and reports 7 break classes. It exits 0, 1 or 2, and it fails closed.
- **Spec and evidence.** Record format v0.1 in SPEC.md with 33 conformance cases. Proofs P1 to P5 on Claude Code 2.1.288 and Codex 0.160.0, and a pre-registered benchmark: 0 breaks in 1,000 turns.

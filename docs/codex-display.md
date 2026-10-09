# Codex display spike

I tested the display mechanisms for [the display issue](https://github.com/mohanraj00/verbatim-relay/issues/205).
This work is part of [the milestone plan](https://github.com/mohanraj00/verbatim-relay/issues/183).
The [result](../proofs/spikes/codex-display.json) records the versions, sources and marker checks.
The [method](../scripts/spike_codex_display.py) creates a toy shop plugin. It uses a local mock model
for CLI checks. A person must trust the hooks and do the desktop checks.

## What I found

| Mechanism | Interactive CLI | `codex exec` | Desktop |
|---|---|---|---|
| Code inside the Codex process | No supported function handler in the inspected schema. | Same schema. | The documented plugin hook API uses the same handler types. |
| Persistent plugin status line or footer | No registration field. The CLI status line selects built-in items. | No terminal display. | No registration field in the inspected plugin metadata. |
| Hook `statusMessage` | The toy PostToolUse and Stop status markers showed. | No status marker in captured output. | Human check pending. |
| Hook `systemMessage` without a block | The toy warnings showed. | No warning marker in captured output. | Human check pending. |
| Hook `additionalContext` | Added to the model request as developer text. | Added to the model request as developer text. | The docs define it as model context. No request capture in this desktop method. |
| A skill as a command | The skill body went to the model and started a turn. | The skill body went to the model and started a turn. | Human check pending. The docs describe skills as model instructions. |
| MCP App or resource | Text output. No UI resource read. | The JSON event includes the MCP result and metadata. No UI resource read. | The toy card declares sidebar and conversation panel entrypoints. Human check pending. |

The [CLI runs](../proofs/spikes/codex-display.json) support the measured cells.
The [version-tagged manifest](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/plugin/src/manifest.rs)
and [hook handler schema](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/config/src/hook_config.rs)
support the schema cells. The [status-line item enum](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/tui/src/bottom_pane/status_line_setup.rs)
defines the built-in CLI items. The result also records the schema emitted by the installed desktop binary.
That binary's version does not identify the running desktop chat.

The [hook docs](https://learn.chatgpt.com/docs/hooks) define warning and context outputs.
The [skill docs](https://learn.chatgpt.com/docs/build-skills) describe invocation and model instructions.
The [MCP UI docs](https://developers.openai.com/plugins/build/chatgpt-ui) describe resources and direct tool calls.
The [extension docs](https://developers.openai.com/plugins/build/extensions) describe sidebar and conversation panels.

In the MCP checks, the structured result reached the mock model. The `_meta` marker did not.
The CLI displayed the text content. The exec event included the content and metadata.
A marker in an exec JSON event does not show that a card rendered.

Warning and status markers were absent from the captured model requests. This check covers the
requests in each toy turn. Stop runs after the final request. I did not test its warning in a later turn.
I did not test byte equality of a rendered reply. The desktop method records human observations and
toy hook/MCP event names. It does not capture desktop model requests.

## Run the method

Use a Python version with `tomllib`. The method adds no package dependency.
Run `python3 scripts/spike_codex_display.py prepare`. Install the toy plugin with the commands it prints.
A person opens `/hooks` in the printed toy project and trusts only the toy display hooks.
The script does not write trust state. It refuses to replace a reviewed hook definition or executable.

Run `inspect` to record schema and plugin metadata. Run `measure` for the CLI matrix.
Use `--surface codex_exec|interactive_cli` or `--case hooks|mcp|skill` to repeat a selected case.
Superseded runs are excluded from conclusions. The mock model sends fixed toy calls and answers.
The result keeps marker locations and event names. It keeps no request body, model answer or terminal transcript.

Run `desktop-start`, then follow its steps in a new local desktop chat. Do not run the CLI matrix
in that toy project during the desktop check. A person records the observations and app version.
Run `desktop-finish FILE` to import the observation JSON. The importer rejects extra fields such as a model answer.
Update the desktop answers and recommendation from the imported observations before closing the issue.

## Recommendation for the ADR

Keep the Codex command-hook adapter. Use `systemMessage` only for optional short state notices on
surfaces that show them. Keep control-word handling in the Python core. A skill does not give us a
command path that bypasses the model. Do not use `additionalContext` to carry a tester reply that
must stay out of the model context.

Do not port the function display hooks to Codex. Evaluate an MCP App as an optional desktop display
adapter after the human check. Its UI can call a tool directly, but tool results can also reach the model.
The CLI can show text and warnings. An external consumer must display exec results.
The display does not enforce hook trust or relay isolation.

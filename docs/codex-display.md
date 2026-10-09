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
| Hook `statusMessage` | The toy status markers showed for the fixture events. | No status marker in captured output. | Status was not identified. |
| Hook `systemMessage` without a block | The toy warnings showed. | No warning marker in captured output. | No warning was seen. The hook events were recorded. |
| Hook `additionalContext` | Added to the model request as developer text. | Added to the model request as developer text. | The docs define it as model context. No request capture in this desktop method. |
| A skill as a command | The skill body went to the model and started a turn. | The skill body went to the model and started a turn. | The skill started a model turn and ran the toy command. |
| MCP App or resource | Text output. No UI resource read. | The JSON event includes the MCP result and metadata. No UI resource read. | The toy card rendered in a pane on the left. The menu and opening path were not identified. |

The [CLI runs and desktop observations](../proofs/spikes/codex-display.json) support the measured cells.
The [version-tagged manifest](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/plugin/src/manifest.rs)
and [hook handler schema](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/config/src/hook_config.rs)
support the schema cells. The [status-line item enum](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/tui/src/bottom_pane/status_line_setup.rs)
defines the built-in CLI items. The result also records the schema emitted by the installed desktop binary.
The person confirmed the running app version in About. It matches the installed app version
in the [result](../proofs/spikes/codex-display.json).

The [hook docs](https://learn.chatgpt.com/docs/hooks) define warning and context outputs.
The [skill docs](https://learn.chatgpt.com/docs/build-skills) describe invocation and model instructions.
The [MCP UI docs](https://developers.openai.com/plugins/build/chatgpt-ui) describe resources and direct tool calls.
The [extension docs](https://developers.openai.com/plugins/build/extensions) describe sidebar and conversation panels.

In the MCP checks, the structured result reached the mock model. The `_meta` marker did not.
The CLI displayed the text content. The exec event included the content and metadata.
A marker in an exec JSON event does not show that a card rendered.

The desktop fetched the toy UI resource. The person saw `DISPLAY_UI_205` in the pane.
During a separate Refresh check, the server recorded a `show_order` call, with no hook event
or new chat turn. This supports a UI tool path that does not start a model turn.
The person clicked several times. The check does not establish a call for each click or the
precise source of the recorded call. The button returns the same "Order ready." text, so a
successful call causes no visible change. The [desktop and desktop_refresh records](../proofs/spikes/codex-display.json)
contain the observations and limits. The [method](../scripts/spike_codex_display.py) contains the fixed response.

Warning and status markers were absent from the captured model requests. This check covers the
requests in each toy turn. Stop runs after the final request. I did not test its warning in a later turn.
I did not test byte equality of a rendered reply. The desktop method records human observations and
toy hook/MCP event names. It does not capture desktop model requests. The installed hook files were checked after the
human observations; no file snapshot was taken at each earlier desktop event.
The MCP files were checked after those desktop observations. The old desktop run did not
check other enabled MCP servers before starting. It is display evidence, with these limits;
it does not establish an isolated desktop runtime.
The fixture check does not lock the files. A change between the check and Codex reading them
can escape the check. This local spike does not prove protection against concurrent file changes.

## Run the method

Use a Python version with `tomllib`. The method adds no package dependency.
Run `python3 scripts/spike_codex_display.py prepare`. Install the toy plugin with the commands it prints.
A person opens `/hooks` in the printed toy project and trusts only the toy display hooks.
The script does not write trust state. It refuses to replace any generated plugin file.
Before each CLI case, it checks every generated file in the source and installed cache:
the manifest, MCP configuration, hook definition, hook and MCP executables, skill and HTML.
It records their digests with each run. It checks the installed hook command, source and definition hash
against the inspected hook definitions. It reads the effective configuration for the toy
project and disables all configured MCP servers for the CLI invocation. The override contains
only server names and enabled flags, so server environment values, arguments and headers
stay out of the process arguments. The tested CLI does not accept a dotted server name in
this flag path. The method stops if a server name has a dot or other unsupported character.
Use letters, digits, underscores or hyphens in server names for this local probe.
A configured server named `toy_display` is also disabled. Only the verified plugin supplies
the toy server.
It disables other effective plugins. Saved configuration stays unchanged.
It then refuses any configured MCP server or non-toy plugin that remains enabled before a case.
It first disables unrelated
non-managed hooks for that invocation. An enabled non-toy managed hook stops isolation.
It then checks the full hook list before each case. Any non-toy hook that remains enabled
or appears after isolation stops the probe.

Run `inspect` to record schema and plugin metadata. Run `measure` for the CLI matrix.
Use `--surface codex_exec|interactive_cli` or `--case hooks|mcp|skill` to repeat a selected case.
Superseded runs are excluded from conclusions. The first matrix included enabled non-toy hooks;
its results are excluded. The final matrix checks the isolated fixture before each case. The mock model sends fixed toy calls and answers.
The result keeps marker locations and event names. It keeps no request body, model answer or terminal transcript.

Run `desktop-start`, then follow its steps in a new local desktop chat.
This step checks the fixture and effective configuration without CLI overrides. It refuses
enabled configured MCP servers, non-toy plugins or non-toy hooks. A person must disable those
in the desktop configuration before a new check. The script does not change saved settings.
Use the checked toy project and configuration for the desktop chat. The check does not bind
the desktop process to those settings or lock files. Do not run the CLI matrix
in that toy project during the desktop check. A person records the observations and app version.
Run `desktop-finish FILE` to import the observation JSON. The importer accepts only booleans, bounded choices and a version string. It rejects free text,
including notes and model answers.
For a separate button check, run `desktop-refresh-start`. Ask the person to click Refresh order
without a chat prompt. Run `desktop-refresh-finish` to record the server and hook events since
the baseline. Check the chat before and after for a new model turn. Record deviations from
the requested click count. A server event alone does not identify its caller.
Update the desktop answers and recommendation from the observations before closing the issue.

## Recommendation for the ADR

Keep the Codex command-hook adapter. Use `systemMessage` only for optional short state notices on
surfaces that show them. Keep control-word handling in the Python core. A skill does not give us a
command path that bypasses the model. Do not use `additionalContext` to carry a tester reply that
must stay out of the model context.

Do not port the function display hooks to Codex. Add an optional MCP App adapter for the desktop
display, with its methods in the Python core. The toy pane rendered, and the button check recorded
a server call without a new model turn. Before it carries a live tester reply, prove byte equality
and check whether UI call results enter later model turns. This spike does not prove either property.

Use CLI warnings only as optional notices. The person saw no desktop warnings and did not identify
status text. An external consumer must display exec results. The display does not enforce hook
trust or relay isolation.

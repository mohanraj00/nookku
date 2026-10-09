# ADR 0001: One core, one plugin

Status: proposed. Date: 2026-10-08. Issue: [#180](https://github.com/mohanraj00/verbatim-relay/issues/180).

## Context

The project started as a relay. Now it is a test harness for developers of agent apps. It starts the agent, relays the turns, taps them, seals the test, audits, traces and evaluates.

In v0.3, 2 relays do this work:

- The hook kit: Python command hooks that `init` writes into a project, for Claude Code and Codex.
- The Claude Code plugin: TypeScript function hooks.

Testers used both relays. The plugin gave a better experience, but it works only in Claude Code. Its rules repeat the Python rules in TypeScript. The 5 open guard issues of v0.4.0, [#146](https://github.com/mohanraj00/verbatim-relay/issues/146), [#149](https://github.com/mohanraj00/verbatim-relay/issues/149), [#150](https://github.com/mohanraj00/verbatim-relay/issues/150), [#172](https://github.com/mohanraj00/verbatim-relay/issues/172) and [#173](https://github.com/mohanraj00/verbatim-relay/issues/173), must each change the same rule in both copies.

Before this decision, I measured 5 questions in spikes. Each result below links to its data and its method. The versions are in each data file.

### Can a command hook show the reply? (Claude Code, #176)

Data: [`hook-display.json`](../../proofs/spikes/hook-display.json). Method: [`spike_hook_display.py`](../../scripts/spike_hook_display.py).

- If a `UserPromptSubmit` hook blocks a prompt, Claude Code shows the block `reason` in the CLI and in the desktop app. It does not show `systemMessage`.
- The text keeps its bytes, but it shows as a blocked prompt with a fixed title. Claude Code does not render it as Markdown.
- In print mode, a reason of 1, 10 and 100 KiB was complete, byte for byte.
- In the interactive CLI, the screen does not always show the start of a reply that is longer than the screen. In 4 runs, the start of a 10 KiB or 100 KiB text was on the screen in 0, 0, 3 and 4 of 4 cases.
- In the CLI, the model did not get the hook text, in this turn or in the next turn. In the desktop app, I did not measure this, because I had no proxy there.
- In print mode, Claude Code sent the blocked prompt to the model API in a harness request with no tools and 1 message. This occurred in 9 of 9 cases. In the interactive CLI, it occurred in 0 of 9 cases. [#199](https://github.com/mohanraj00/verbatim-relay/issues/199) records this limit.

### Can a command hook show the reply? (Codex, #193)

Data: [`hook-display.json`](../../proofs/spikes/hook-display.json), part `codex`. Method: [`spike_hook_display.py`](../../scripts/spike_hook_display.py).

- In the interactive CLI and in the desktop app, Codex shows the block `reason`. In `codex exec`, it shows no reply field.
- The interactive CLI shows `systemMessage`. The desktop app does not show it.
- Codex shows the text with a fixed title. It does not render Markdown.
- In the desktop app, the largest tested reason was complete and byte for byte, when a person copied it. The maximum length is not known.
- The model did not get the hook text.
- In the desktop app, a separate request to the model API held the blocked prompt. The requests of the main turns did not hold it. The purpose of that request is not known.

### Codex plugin hooks and the trust step (#177)

Data: [`codex-plugin.json`](../../proofs/spikes/codex-plugin.json). Method: [`spike_codex_plugin.py`](../../scripts/spike_codex_plugin.py).

- `SessionStart`, `UserPromptSubmit` and `PreToolUse` ran from a plugin in the interactive CLI and in `codex exec`, when a person trusted the hooks. They also ran in the desktop app.
- If a person did not trust a changed hook, `codex exec` skipped it, and a blocked prompt reached the model. Thus the plugin alone fails open.
- A `SessionStart` hook of the same plugin was also skipped. It cannot check its own trust.
- A check outside the plugin can read the hook state with app-server `hooks/list`, and refuse a run if a required hook is missing, disabled, untrusted or modified.
- One plugin folder with `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, one `hooks/hooks.json` and one skills folder worked in Codex. Claude Code validated the manifest.
- Codex sets `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` to the same value.

### Can a plugin MCP server give the model the transcript? (#178, #194)

Data: [`plugin-mcp.json`](../../proofs/spikes/plugin-mcp.json). Method: [`spike_plugin_mcp.py`](../../scripts/spike_plugin_mcp.py).

- A plugin MCP server with only the Python standard library started in both harnesses, in the CLI and in the desktop app.
- A 10 KiB result got to the model with the same SHA-256 in both CLIs. I had no proxy in the desktop apps. In the Codex desktop app, the session kept the result with the same SHA-256. In the Claude desktop app, the model saw the start and end markers.
- At the default limits, a result of 50 KiB or more did not get to the model unchanged in either harness. Claude Code saves it to a file and gives a preview. Codex truncates it.
- A truncated result can keep its start and end markers. Only a hash shows the change.
- The tool name is `mcp__plugin_<plugin>_<server>__<tool>` in Claude Code, and `mcp__<server>__<tool>` in Codex.

### What a Codex plugin can show (#205)

Data: [`codex-display.json`](../../proofs/spikes/codex-display.json). Method: [`spike_codex_display.py`](../../scripts/spike_codex_display.py). Report: [Codex display spike](../codex-display.md).

- The tested plugin manifest and hook schema of Codex have no in-process handler like a Claude Code function hook. They also have no plugin footer, no status-line field and no command that runs without the model. This result comes from the schema, not from a test that injected code.
- A skill starts a model turn. Hook `additionalContext` goes to the model.
- The interactive CLI shows hook `systemMessage` warnings and short `statusMessage` texts. `codex exec` shows neither.
- In the desktop app, a toy MCP App rendered in a pane. A click in the app called a server tool with no new chat turn and no hook event. The person clicked more than one time, so this does not prove 1 call for each click.
- The desktop check ran before the probe checked its files and disabled other MCP servers. Thus it does not prove an isolated desktop run.

### Time that a Python hook process adds (#179)

Data: [`hook-latency.json`](../../proofs/spikes/hook-latency.json). Method: [`spike_hook_latency.py`](../../scripts/spike_hook_latency.py).

- A warm hook process takes 47 to 52 ms on macOS and 39 to 44 ms on Linux (median).
- An empty Python process takes 12.8 ms on macOS. A process that imports only the standard modules of a guard rule takes 18.1 ms.
- The import of `verbatim_relay.kit` is most of the rest. A lazy import in the kit can save up to about 29 ms on macOS for each event.
- 100 tool calls in one model turn add 5.2 s on macOS and 4.1 s on Linux.
- A loopback HTTP call needs a `curl` process, which takes 7.8 ms on macOS.

## Decision

- **Name.** The project becomes Nooku (Tamil நோக்கு: to look, observe, scrutinize). Tagline: "A test harness for developers of agent apps." [#181](https://github.com/mohanraj00/verbatim-relay/issues/181) does the rename.
- **One core.** One core in Python holds each rule and each text: the control words, the relay, the guard, the policy, the status, the start and end texts, and the scripted tests. No rule has a TypeScript copy.
- **One plugin.** One plugin folder serves Claude Code and Codex. It has a manifest for each harness, one command hook file, one MCP server and one skills folder. Each command hook runs `python -m nooku hook`.
- **Display layer.** Claude Code function hooks are an optional display layer: dim rows, a pane, a status line and slash commands. They hold no rule. If they break, the command hooks still work. In Codex, an optional MCP App can be the display layer of the desktop app, with its logic in the core. Before an MCP App shows a live reply, a spike must prove that it keeps the bytes, and that a click result does not go to the model. In the interactive CLI, hook warnings can give short notices. `codex exec` has no display layer, so it needs `nooku view`. A display layer never carries a tester reply in text that goes to the model, for example `additionalContext`.
- **Fallback.** `init` writes the same command hooks into a project, for a project that cannot install plugins.
- **Harnesses.** Claude Code and Codex only. A new harness needs an adapter for its hook events and a plugin manifest. It needs no change to the core.

The spikes give these rules for the design:

- **Reply display.** In both harnesses, the core can show the reply with the block `reason`, as an optional notice. Do not use `systemMessage`, because the desktop apps do not show it. Keep `nooku view` and the transcript tool, because `codex exec` shows no reply, and the interactive screen can lose the start of a long reply.
- **Trust gate.** In Codex, the core checks the hook state with `hooks/list` before the first relayed message. If a required hook is missing, disabled, untrusted or modified, the core refuses the test. The plugin's own `SessionStart` hook is not the gate. A person always does the trust step. The check is not a security boundary alone. If a hook changes after the check, Codex skips it, so the hook cannot detect the change. Thus the core starts Codex with the plugin files and the runtime configuration that it checked, and keeps them unchanged until the test ends. [#182](https://github.com/mohanraj00/verbatim-relay/issues/182) designs how.
- **Transcript tool.** The MCP server gives the model read-only tools: `transcript` and `status`. `transcript` returns pages, with an offset, a page count and a hash. The page size is configurable. The output limits count tokens, not bytes, so the core bounds each page by a token estimate, not by bytes. The only measured safe case is 10 KiB of repetitive English text, in both CLIs. Codex truncated that text at about 12 KiB, so token-dense text can be truncated below 10 KiB. Before [#182](https://github.com/mohanraj00/verbatim-relay/issues/182) sets the default, it measures a token-dense page, for example non-ASCII text and JSON, in both harnesses.
- **Tool names.** The core builds the allowed tool names from one constant for each harness, because the 2 harnesses use different prefixes.
- **Hook time.** Keep one Python process for each event. The hook path imports only the modules that its rule needs. A test fails if the hook path imports more. The target is less than 25 ms on macOS for a warm event. The guard does not call the bridge over loopback.
- **Blocked prompts.** A command hook alone does not keep a blocked prompt from the model API. `claude -p` and the Codex desktop app sent it in a side request. Until [#199](https://github.com/mohanraj00/verbatim-relay/issues/199) and [#203](https://github.com/mohanraj00/verbatim-relay/issues/203) close, the docs state this limit.

## Options that I did not take

- **Keep 2 relays.** Each rule needs 2 copies and conformance cases for both. The copies drift, and each guard issue must change both of them.
- **Move the rules to TypeScript.** The Codex plugin schema has no handler that runs code in the harness process ([#205](https://github.com/mohanraj00/verbatim-relay/issues/205)). Thus Codex would still need a second copy.
- **A long-running hook server.** A loopback call saves time only while a test runs, and a command hook still needs a `curl` process. The guard must also work outside a test. A second path adds a second way to fail.
- **Trust the plugin to check itself.** In Codex, an untrusted plugin skips all its hooks, also `SessionStart`. Only a check outside the plugin can refuse the test.
- **Send the full transcript in one tool result.** At the default limits, results of 50 KiB or more did not get to the model unchanged.

## Consequences

- Each guard rule, control word and display text has one copy. The issues that only make the 2 copies equal close with [#182](https://github.com/mohanraj00/verbatim-relay/issues/182).
- Codex gets the plugin, the MCP tools and the skills. It does not get the dim rows, the status line or the slash commands of Claude Code. Its desktop app can get an MCP App pane later.
- Claude Code users of the v0.3 plugin get the same look, because the function hooks stay as the display layer.
- Each event costs one Python process. With lazy imports, this is the floor that the hook-time rule gives.
- A Codex test needs the trust step after each change to a hook file. The upgrade docs must say this.
- The rename changes the CLI, the state folder, the variables and the plugin name. [#181](https://github.com/mohanraj00/verbatim-relay/issues/181) gives the upgrade steps from verbatim-relay 0.3.x.

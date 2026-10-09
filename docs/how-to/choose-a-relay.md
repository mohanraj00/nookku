# Choose a relay

A [relay](../reference/glossary.md#relay) carries each message to your agent and each reply back to you. There are [2 relays](../../SPEC.md#5-relays): the Claude Code plugin and the hook kit. Use this page to select one, and to select how the relay reaches your agent.

## Decision flow

```mermaid
flowchart TD
    harness{"Which harness do you use?"}
    harness -->|Codex| kit["Hook kit"]
    harness -->|Claude Code| chat{"Do you want each reply in the chat?"}
    chat -->|yes| plugin["Plugin"]
    chat -->|no| kit
    plugin -.->|"if the plugin fails"| kit
    plugin --> agent{"Is your agent an HTTP server, and do you need no trace and no evaluation?"}
    kit --> agent
    agent -->|yes| httptap["HTTP tap, with no entry"]
    agent -->|no| entry["Entry"]
```

1. Select the relay for your [harness](../reference/glossary.md#harness):
   - Codex uses the hook kit. Read [codex.md](codex.md).
   - In Claude Code, use the plugin or the hook kit. The plugin shows each reply in the chat. The hook kit shows each reply in a second terminal. Read [claude-code-plugin.md](claude-code-plugin.md) or [claude-code-hook-kit.md](claude-code-hook-kit.md).
2. Select how the relay reaches your agent:
   - If your agent is already an HTTP server, and you need no [trace](../reference/glossary.md#trace) and no [evaluation](../reference/glossary.md#evaluation), you can use the HTTP [tap](../reference/glossary.md#tap). Read [http-tap.md](http-tap.md).
   - Each other agent uses an [entry](../reference/glossary.md#entry). Read [connect-your-agent.md](connect-your-agent.md).

## Compare the relays

| | Plugin | Hook kit |
|---|---|---|
| What it installs, and where | The plugin, with `claude plugin install`. By default, Claude Code installs it in the user scope, for each of your projects. You write `.nooku/config.json`, or the `setup` skill writes it. | `nooku init` writes `.nooku/config.json`, `.nooku/mode` and [2 hooks](../../src/nooku/kit.py), in the project only. The hooks go in `.claude/settings.local.json` (Claude Code) or `.codex/hooks.json` (Codex). |
| The start and end commands | `/nooku start`. The prompt `nooku end` ends the test and starts the evaluation. `/nooku end` ends the test with no evaluation. | The prompt `nooku start`. The prompt `nooku end` ends the test and starts the evaluation. `nooku end` in a shell ends the test with no evaluation. |
| Where the reply shows | In the chat, as a dim row that the model does not receive, and in the Nooku pane. The status line shows when [relay mode](../reference/glossary.md#relay-mode) is on. | In `nooku view`, in a second terminal. The chat shows only the block text of the hook, for example "relayed to the agent". |
| How the model reads the transcript | With the read-only `transcript` tool. The tool runs `nooku transcript`. | With the command `nooku transcript`. |
| The harnesses | Claude Code. The proofs ran on Claude Code 2.1.290 ([data](../../proofs/claude-code/results.json)). | Claude Code and Codex. The proofs ran on Claude Code 2.1.290 ([data](../../proofs/hooks-claude-code/results.json)) and codex-cli 0.160.0 ([data](../../proofs/hooks-codex/results.json)). |
| The limits | It uses function hooks, which are early access and can change between releases. CI pins Claude Code 2.1.290 ([ci.yml](../../.github/workflows/ci.yml)). It stops at a relay record of [3.5 MiB](../../plugins/claude-code/hooks/register.tsx). | It cannot show text in the chat. Codex runs its hooks only after you trust them. |

Both relays need the `nooku` command: `uv tool install nooku`. Both give the model the same transcript text ([SPEC.md section 5](../../SPEC.md#5-relays)). Both relays fail closed: if a relay cannot send a message, the message does not go to the model. For both relays, the deny of model tool calls is best effort. [limits.md](../limits.md) gives each limit.

## Switch from one relay to the other

**Warning:** Never use both relays in one project. If both run, each message goes to the agent two times, and the [audit](../reference/glossary.md#audit) reports a `duplicate_send` break ([SPEC.md section 3.3](../../SPEC.md#33-break-classes)).

With an entry, the two relays use the same `.nooku/config.json` and the same [test folders](../reference/glossary.md#test-folder). A switch keeps your entry and your old tests. Codex has only the hook kit, so a switch applies to Claude Code only.

### From the plugin to the hook kit

1. End the running test. Type `/nooku end`.
2. Disable the plugin in this project only. Give `--scope local`. Without it, the command can disable the plugin at the user scope, and then the plugin stops in each project:

   ```bash
   claude plugin disable --scope local nooku@nooku
   ```

3. Install the hook kit. `init` keeps each key of an existing `.nooku/config.json`, also the entry:

   ```bash
   nooku init claude-code
   ```

4. Do the steps of [claude-code-hook-kit.md](claude-code-hook-kit.md) from the viewer step.

### From the hook kit to the plugin

1. End the running test. Run `nooku end` in a shell.
2. Remove the [2 hooks](../../src/nooku/kit.py) of the kit from `.claude/settings.local.json`. Their command contains `nooku hook`. Keep your other hooks.
3. If you disabled the plugin in this project before, enable it again in this project:

   ```bash
   claude plugin enable --scope local nooku@nooku
   ```

4. Do the steps of [claude-code-plugin.md](claude-code-plugin.md). Your `.nooku/config.json` stays.

With no entry, the plugin reads `tap_url` and the other options from its plugin options ([reference/config.md](../reference/config.md#plugin-options)). The hook kit reads them from `.nooku/config.json`. If you changed an option, set it again for the new relay.

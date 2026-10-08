# Remove verbatim-relay

This page removes verbatim-relay from a project and from your computer: the hooks of the kit, the plugin, the test files and the package.

The output on this page is the real output of each step. I used the toy shop project of [getting-started.md](../getting-started.md) with verbatim-relay 0.3.0, Claude Code 2.1.294 and jq 1.7.1 on macOS. I shortened the paths of the folders to `.../`. The test ids are different on your machine.

Do the steps in this order. Remove the hooks before you remove the CLI. The hooks run the Python of the CLI install. After `uv tool uninstall`, this program does not exist. Then each hook command fails with `No such file or directory`.

## 1. End each running test

```bash
verbatim-relay status
```

If the line names a test, end it:

```bash
verbatim-relay end
```

End the test before you remove anything. `end` stops the bridge and the entry of the test. Without `end`, they continue to run.

If `status` names no test but relay mode is on, follow [recover-a-stuck-test.md](recover-a-stuck-test.md).

## 2. Remove the hooks of the kit

`verbatim-relay init` adds 2 hook entries to one file ([kit.py](../../src/verbatim_relay/kit.py)):

| Harness | File |
|---|---|
| Claude Code | `.claude/settings.local.json` |
| Codex | `.codex/hooks.json` |

The 2 entries are:

- In `hooks.UserPromptSubmit`: a group with one hook, with `"timeout": 300`.
- In `hooks.PreToolUse`: a group with `"matcher": ".*"` and one hook, with `"timeout": 30`.

The `command` of each hook contains `verbatim_relay hook`. This is the file that `verbatim-relay init claude-code --entry "python3 agent.py"` wrote in a new project:

```json
{
 "hooks": {
  "UserPromptSubmit": [
   {
    "hooks": [
     {
      "type": "command",
      "command": ".../bin/python -m verbatim_relay hook --root .../toy-shop --harness claude-code",
      "timeout": 300
     }
    ]
   }
  ],
  "PreToolUse": [
   {
    "matcher": ".*",
    "hooks": [
     {
      "type": "command",
      "command": ".../bin/python -m verbatim_relay hook --root .../toy-shop --harness claude-code",
      "timeout": 30
     }
    ]
   }
  ]
 }
}
```

`.codex/hooks.json` has the same form, with `--harness codex`.

Count the hooks of the kit in the 2 files:

```bash
grep -c 'verbatim_relay hook' .claude/settings.local.json .codex/hooks.json
```

```text
.claude/settings.local.json:2
.codex/hooks.json:2
```

Remove each hook object whose `command` contains `verbatim_relay hook`. If its group then has no hook, remove the group too. Keep each other hook and each other key. You can edit the file by hand, or use [jq](https://jqlang.org/). This jq filter removes the hooks of the kit, then each empty group and each empty event:

```bash
jq '.hooks |= (with_entries(.value |= (map(.hooks |= map(select((.command // "") | tostring | contains("verbatim_relay hook") | not))) | map(select(.hooks | length > 0)))) | with_entries(select(.value | length > 0)))' .claude/settings.local.json > settings.tmp && mv settings.tmp .claude/settings.local.json
```

Do not delete `.claude/settings.local.json` to remove the hooks. The file can also hold your permissions and your own hooks. In my run, the file had a permission and an own hook before `init`. After the jq filter, it had these again:

```json
{
  "permissions": {
    "allow": [
      "Bash(pytest:*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "echo my own hook"
          }
        ]
      }
    ]
  }
}
```

For Codex, use the same filter on `.codex/hooks.json`:

```bash
jq '.hooks |= (with_entries(.value |= (map(.hooks |= map(select((.command // "") | tostring | contains("verbatim_relay hook") | not))) | map(select(.hooks | length > 0)))) | with_entries(select(.value | length > 0)))' .codex/hooks.json > hooks.tmp && mv hooks.tmp .codex/hooks.json
```

In my run, `.codex/hooks.json` had only the hooks of the kit, so the result was `{"hooks": {}}`.

Count again. Each file must show 0. `grep` exits with 1, because it found no line:

```bash
grep -c 'verbatim_relay hook' .claude/settings.local.json .codex/hooks.json
```

```text
.claude/settings.local.json:0
.codex/hooks.json:0
```

## 3. Uninstall the plugin

If you use the Claude Code plugin, uninstall it:

```bash
claude plugin uninstall verbatim-relay@verbatim-relay
```

```text
✔ Successfully uninstalled plugin: verbatim-relay (scope: user)
```

The default scope is `user`. If you installed the plugin in another scope, add `--scope project` or `--scope local`. If you added the marketplace only for verbatim-relay, remove it too:

```bash
claude plugin marketplace remove verbatim-relay
```

```text
✔ Successfully removed marketplace: verbatim-relay
```

## 4. Delete or keep the test files

verbatim-relay keeps the files of your tests in 2 places ([reference/records.md](../reference/records.md#the-state-folder)):

- `.verbatim-relay/` in the project: the configuration, the entry, relay mode and a folder for each test, with its records.
- `~/.verbatim-relay/seals/`, or `$VERBATIM_RELAY_HOME/seals/` if the variable is set: a copy of the seal of each test, as `<test-id>.json`. This folder holds the seals of each project on your computer.

To keep the records of your tests, keep both. If you keep a test folder, keep its seal copy too. With no copy, `verify` says that the seal is broken and exits with 2:

```text
Seal: BROKEN. the copy of the seal is missing. Do not trust these records.
```

To delete the files of this project, first delete the seal copies of its tests. Do this before you delete `.verbatim-relay/`, because the names of the test folders give the names of the copies:

```bash
for t in .verbatim-relay/tests/*/; do rm -f "${VERBATIM_RELAY_HOME:-$HOME/.verbatim-relay}/seals/$(basename "$t").json"; done
```

Then delete the state folder:

```bash
rm -rf .verbatim-relay
```

Do not delete all of `~/.verbatim-relay/seals/` if you keep tests in other projects. `verify` of those tests then says that the seal is broken.

## 5. Remove the package and the `.gitignore` line

Remove the CLI:

```bash
uv tool uninstall verbatim-relay
```

```text
Uninstalled 1 executable: verbatim-relay
```

If you added the package to your app's environment, for example for `serve()` ([connect-your-agent.md](connect-your-agent.md#in-python-use-serve)), remove it there too. With uv, run:

```bash
uv remove --dev verbatim-relay
```

The interpreter of your app then does not find the package:

```bash
.venv/bin/python -m verbatim_relay --version
```

```text
.../toy-shop/.venv/bin/python: No module named verbatim_relay
```

Last, remove the line for verbatim-relay from `.gitignore`, if you added one: `.verbatim-relay/` or `.verbatim-relay/tests/` ([SECURITY.md](../../SECURITY.md)). Do this only if you deleted `.verbatim-relay/`. If you keep the folder, keep the line, because the records contain the whole test conversation.

# Remove Nookku

This page removes Nookku from a project and from your computer: the project hooks, the plugin, the test files and the package.

The output on this page is the real output of each step. I used the toy shop project of [getting-started.md](../getting-started.md) with verbatim-relay 0.3.0 and Claude Code 2.1.294 on macOS. Section 2 has the output of the code of [#163](https://github.com/mohanraj00/nookku/issues/163), before the 0.4.0 release. I shortened the paths of the folders to `.../`. The test ids are different on your machine.

Do the steps in this order. Remove the hooks before you remove the CLI. The hooks run the Python of the CLI install. After `uv tool uninstall`, this program does not exist. Then each hook command fails with `No such file or directory`.

## 1. End each running test

```bash
nookku status
```

If the line names a test, end it:

```bash
nookku end
```

End the test before you remove anything. `end` stops the bridge and the entry of the test. Without `end`, they continue to run.

If `status` names no test but relay mode is on, follow [recover-a-stuck-test.md](recover-a-stuck-test.md).

## 2. Remove the project hooks

`nookku init` adds 2 hook entries to one file ([kit.py](../../src/nookku/kit.py)):

| Harness | File |
|---|---|
| Claude Code | `.claude/settings.local.json` |
| Codex | `.codex/hooks.json` |

The 2 entries are:

- In `hooks.UserPromptSubmit`: a group with one hook, with `"timeout": 300`.
- In `hooks.PreToolUse`: a group with `"matcher": ".*"` and one hook, with `"timeout": 30`.

The `command` of each hook contains `nookku hook`. This is the file that `nookku init claude-code --entry "python3 agent.py"` wrote in a new project:

```json
{
 "hooks": {
  "UserPromptSubmit": [
   {
    "hooks": [
     {
      "type": "command",
      "command": ".../bin/python -m nookku hook --root .../toy-shop --harness claude-code",
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
      "command": ".../bin/python -m nookku hook --root .../toy-shop --harness claude-code",
      "timeout": 30
     }
    ]
   }
  ]
 }
}
```

`.codex/hooks.json` has the same form, with `--harness codex`.

Remove the project hooks with `init --remove`. Give the harness:

```bash
nookku init --remove claude-code
nookku init --remove codex
```

It removes each hook whose `command` contains `nookku hook`, and also each hook of verbatim-relay 0.3, whose command contains `verbatim_relay hook`. If a group or an event then has no hook, it removes it too. It keeps each other hook and each other key, and `.nookku/`. If the file then has no key, it deletes the file, because `init` made it.

In my run, `.claude/settings.local.json` had a permission and an own hook before `init`. `.codex/hooks.json` did not exist before `init`:

```text
removed 2 hooks from .../toy-shop/.claude/settings.local.json
The state folder .nookku/ stays. It has the config and your tests.
removed 2 hooks from .../toy-shop/.codex/hooks.json, and deleted the file, because it is now empty
The state folder .nookku/ stays. It has the config and your tests.
```

After the command, `.claude/settings.local.json` had the same JSON as before `init`. Only the indent was different, because `init` writes the file again:

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

If the file has no hook of nookku, the command changes nothing and exits with 0:

```text
.../toy-shop/.codex/hooks.json has no hook of nookku. Nothing was changed.
```

The command changes nothing and exits with 1 in these 2 cases:

- A test runs or relay mode is on. Without the hooks, a message in relay mode goes to the model. End the test with `nookku end`, or switch relay mode off with `nookku mode off`.
- The file is not valid JSON, or its `hooks` key has a wrong form. Correct the file, then run the command again.

Do not delete `.claude/settings.local.json` yourself to remove the hooks. The file can also hold your permissions and your own hooks.

## 3. Uninstall the plugin

If you use the plugin in Claude Code, uninstall it:

```bash
claude plugin uninstall nookku@nookku
```

```text
✔ Successfully uninstalled plugin: nookku (scope: user)
```

The default scope is `user`. If you installed the plugin in another scope, add `--scope project` or `--scope local`. If you added the marketplace only for Nookku, remove it too:

```bash
claude plugin marketplace remove nookku
```

```text
✔ Successfully removed marketplace: nookku
```

If you use the plugin in Codex, remove the plugin and its local copy. If you added the marketplace only for Nookku, remove it too:

```bash
codex plugin remove nookku@nookku
codex plugin marketplace remove nookku
```

I did not record the output of these 2 commands. `codex plugin list` shows the plugins that stay.

## 4. Delete or keep the test files

Nookku keeps the files of your tests in 2 places ([reference/records.md](../reference/records.md#the-state-folder)):

- `.nookku/` in the project: the configuration, the entry, relay mode and a folder for each test, with its records.
- `~/.nookku/seals/`, or `$NOOKKU_HOME/seals/` if the variable is set: a copy of the seal of each test, as `<test-id>.json`. This folder holds the seals of each project on your computer.

To keep the records of your tests, keep both. If you keep a test folder, keep its seal copy too. With no copy, `verify` says that the seal is broken and exits with 2:

```text
Seal: BROKEN. the copy of the seal is missing. Do not trust these records.
```

To delete the files of this project, first delete the seal copies of its tests. Do this before you delete `.nookku/`, because the names of the test folders give the names of the copies:

```bash
for t in .nookku/tests/*/; do rm -f "${NOOKKU_HOME:-$HOME/.nookku}/seals/$(basename "$t").json"; done
```

Then delete the state folder:

```bash
rm -rf .nookku
```

Do not delete all of `~/.nookku/seals/` if you keep tests in other projects. `verify` of those tests then says that the seal is broken.

## 5. Remove the package and the `.gitignore` line

Remove the CLI:

```bash
uv tool uninstall nookku
```

```text
Uninstalled 1 executable: nookku
```

If you added the package to your app's environment, for example for `serve()` ([connect-your-agent.md](connect-your-agent.md#in-python-use-serve)), remove it there too. With uv, run:

```bash
uv remove --dev nookku
```

The interpreter of your app then does not find the package:

```bash
.venv/bin/python -m nookku --version
```

```text
.../toy-shop/.venv/bin/python: No module named nookku
```

Last, remove the line for Nookku from `.gitignore`, if you added one: `.nookku/` or `.nookku/tests/` ([SECURITY.md](../../SECURITY.md)). Do this only if you deleted `.nookku/`. If you keep the folder, keep the line, because the records contain the whole test conversation.

# Upgrade Nookku

This page upgrades the CLI, the package in your app's environment, the Claude Code plugin and the Codex hooks. Some releases need a special step. Read the section of each release from your version to the new version in [Releases with a special step](#releases-with-a-special-step). [CHANGELOG.md](../../CHANGELOG.md) lists all changes.

The output on this page is the real output of each step. I used the toy shop project of [getting-started.md](../getting-started.md) with verbatim-relay 0.3.0 and Claude Code 2.1.294 on macOS. I shortened the paths of the folders to `.../`. The test id and the times are different on your machine.

## 1. End each running test

End each running test before you upgrade. A new version can read the `current.json` of an old test as no test, and then it does not stop the old bridge (see [0.3.0](#030)).

In each project that uses Nookku, run:

```bash
nookku status
```

If the line names a test, end it:

```bash
nookku end
```

If the line names no test and relay mode is on, follow [recover-a-stuck-test.md](recover-a-stuck-test.md).

## 2. Upgrade the CLI and the package

If you installed the CLI from PyPI, run:

```bash
uv tool upgrade nookku
```

If you installed it from the repo, install it again:

```bash
uv tool install --force git+https://github.com/mohanraj00/nookku
```

Check the version:

```bash
nookku --version
```

```text
nookku 0.3.0
```

The hooks of the kit run the Python of the CLI install, for example `.../nookku/bin/python -m nookku hook ...`. Thus the hooks use the new version, and the hook file does not change. If you install the CLI in a new place, run `nookku init` again, so that the hooks name the new Python.

If your entry imports `nookku`, for example to use `serve()`, upgrade the package in your app's environment too ([connect-your-agent.md](connect-your-agent.md#in-python-use-serve)). With uv, run:

```bash
uv sync --upgrade-package nookku
```

If your version constraint excludes the new version, change the constraint first, for example with `uv add --dev "nookku>=0.3"`. Then check the version with the interpreter of the entry:

```bash
.venv/bin/python -m nookku --version
```

```text
nookku 0.3.0
```

## 3. Update the plugin

If you use the Claude Code plugin, update the marketplace and the plugin:

```bash
claude plugin marketplace update nookku
claude plugin update nookku@nookku
```

The second command names the new version, or says that the plugin is already at the latest version. Restart Claude Code to load the new version. `claude plugin list` shows the version of `nookku@nookku`.

The plugin runs the CLI to start and end a test, to show the status and to print the transcript (the plugin option `cli` in [reference/config.md](../reference/config.md#plugin-options)). Upgrade the CLI and the plugin to the same version.

## 4. Trust the Codex hooks again

If you use the hook kit in Codex, start `codex` in the project. If Codex shows the hooks prompt, accept it.

Do not skip this step. If Codex does not trust the hooks, it does not run them, and the model answers your test messages ([troubleshooting.md](../troubleshooting.md#in-codex-the-model-answers-my-test-messages)). Codex asks again after each change to `.codex/hooks.json`, for example after a new `nookku init` ([codex.md](codex.md#install)).

## 5. Run `check`

```bash
nookku check
```

```text
Test 20261007-224410-2171: .../toy-shop/.nookku/tests/20261007-224410-2171
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

`check` runs a short test with one message through the new version, and exits with 0 if it passes ([reference/cli.md](../reference/cli.md#nookku-check)). If it fails, each FAIL line gives the cause and the fix ([troubleshooting.md](../troubleshooting.md#end-a-test)).

## Releases with a special step

### 0.4.0

verbatim-relay is now Nookku ([#181](https://github.com/mohanraj00/nookku/issues/181)). The package, the CLI, the module and the plugin have new names, so the steps 2 and 3 above do not apply. Do these steps in their place.

1. End each running test with the old CLI:

   ```bash
   verbatim-relay end
   ```

2. Remove the old CLI and install the new CLI:

   ```bash
   uv tool uninstall verbatim-relay
   uv tool install nookku
   ```

3. In each project, run one `nookku` command, for example `nookku status`. The command moves `.verbatim-relay/` to `.nookku/`, with each test and each seal, and prints the 2 folders. If `config.json` has a `record` path in `.verbatim-relay/`, the command changes it to the same file in `.nookku/`.

4. If `.verbatim-relay/` and `.nookku/` both exist, each command stops with exit 1 and names the 2 folders. Each hook event is blocked. Keep one folder: move the tests that you need into `.nookku/tests/`, then remove `.verbatim-relay/`.

5. If you use the hook kit, run `nookku init` again with the same harness and flags. It replaces the hooks that verbatim-relay wrote. In Codex, trust the hooks again (step 4 above).

6. If you use the Claude Code plugin, remove the old plugin and its marketplace, then install the new plugin:

   ```bash
   claude plugin uninstall verbatim-relay@verbatim-relay
   claude plugin marketplace remove verbatim-relay
   claude plugin marketplace add mohanraj00/nookku
   claude plugin install nookku@nookku
   ```

7. If your entry imports the package, change `verbatim_relay` to `nookku` in the import, for example `from nookku.agent import serve`. Then change the package in your app's environment:

   ```bash
   uv remove --dev verbatim-relay
   uv add --dev nookku
   ```

8. If you set `VERBATIM_RELAY_HOME`, set `NOOKKU_HOME` in its place. `verify` still reads the seal copies of old tests from `~/.verbatim-relay/seals/`, or from `VERBATIM_RELAY_HOME` if it is set.

Then run `check` (step 5 above).

### 0.3.0

**A test that 0.2.0 started.** `current.json` now needs `pid_start`, the start time of the bridge ([#44](https://github.com/mohanraj00/nookku/issues/44)). 0.3.0 treats a test that 0.2.0 started as not running. `status` names no test, and `end` removes `current.json` but sends no signal to the old bridge. The old bridge and its entry continue to run.

I made this state with 0.3.0: I started a test and removed `pid_start` from its `current.json`. Then `status` and `end` printed:

```text
relay mode is on.
```

```text
No test runs. Relay mode is off.
```

Find the old bridge:

```bash
ps -A -o pid=,command= | grep '[v]erbatim_relay bridge'
```

```text
38282 .../bin/python -m verbatim_relay bridge --root .../toy-shop --test 20261007-224554-4b17
```

Stop it with SIGTERM, the default signal of `kill`:

```bash
kill 38282
```

On SIGTERM, the bridge ends the test as `end` does: it stops the entry, and writes the trace, the audit and the seal. The bridge of 0.2.0 does the same ([bridge.py of 0.2.0](https://github.com/mohanraj00/nookku/blob/v0.2.0/src/verbatim_relay/bridge.py#L514)). In my run, the test folder then had `audit.json` and `seal.json`:

```bash
nookku verify 20261007-224554-4b17
```

```text
Seal: intact. No record changed after the end of the test.
```

Do not use `kill -9` on the bridge. With SIGKILL, the bridge cannot write the audit and the seal ([recover-a-stuck-test.md](recover-a-stuck-test.md#4-learn-what-a-stale-currentjson-is)).

**Unknown keys in `config.json`.** `start`, `check` and `init` now stop at an unknown key, for example a key with a typo ([#89](https://github.com/mohanraj00/nookku/issues/89)). Before, `start` accepted it. With the key `evaluation` in place of `evaluate`, `check` printed this text and exited with 1:

```text
nookku: .nookku/config.json has unknown keys: ['evaluation']. Correct or remove them.
```

Correct the name of the key, or remove it. [reference/config.md](../reference/config.md) lists each key.

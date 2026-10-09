# Upgrade Nooku

This page upgrades the CLI, the package in your app's environment, the Claude Code plugin and the Codex hooks. Some releases need a special step. Read the section of each release from your version to the new version in [Releases with a special step](#releases-with-a-special-step). [CHANGELOG.md](../../CHANGELOG.md) lists all changes.

The output on this page is the real output of each step. I used the toy shop project of [getting-started.md](../getting-started.md) with Nooku 0.3.0 and Claude Code 2.1.294 on macOS. I shortened the paths of the folders to `.../`. The test id and the times are different on your machine.

## 1. End each running test

End each running test before you upgrade. A new version can read the `current.json` of an old test as no test, and then it does not stop the old bridge (see [0.3.0](#030)).

In each project that uses Nooku, run:

```bash
nooku status
```

If the line names a test, end it:

```bash
nooku end
```

If the line names no test and relay mode is on, follow [recover-a-stuck-test.md](recover-a-stuck-test.md).

## 2. Upgrade the CLI and the package

If you installed the CLI from PyPI, run:

```bash
uv tool upgrade nooku
```

If you installed it from the repo, install it again:

```bash
uv tool install --force git+https://github.com/mohanraj00/verbatim-relay
```

Check the version:

```bash
nooku --version
```

```text
nooku 0.3.0
```

The hooks of the kit run the Python of the CLI install, for example `.../nooku/bin/python -m nooku hook ...`. Thus the hooks use the new version, and the hook file does not change. If you install the CLI in a new place, run `nooku init` again, so that the hooks name the new Python.

If your entry imports `nooku`, for example to use `serve()`, upgrade the package in your app's environment too ([connect-your-agent.md](connect-your-agent.md#in-python-use-serve)). With uv, run:

```bash
uv sync --upgrade-package nooku
```

If your version constraint excludes the new version, change the constraint first, for example with `uv add --dev "nooku>=0.3"`. Then check the version with the interpreter of the entry:

```bash
.venv/bin/python -m nooku --version
```

```text
nooku 0.3.0
```

## 3. Update the plugin

If you use the Claude Code plugin, update the marketplace and the plugin:

```bash
claude plugin marketplace update nooku
claude plugin update nooku@nooku
```

The second command names the new version, or says that the plugin is already at the latest version. Restart Claude Code to load the new version. `claude plugin list` shows the version of `nooku@nooku`.

The plugin runs the CLI to start and end a test, to show the status and to print the transcript (the plugin option `cli` in [reference/config.md](../reference/config.md#plugin-options)). Upgrade the CLI and the plugin to the same version.

## 4. Trust the Codex hooks again

If you use the hook kit in Codex, start `codex` in the project. If Codex shows the hooks prompt, accept it.

Do not skip this step. If Codex does not trust the hooks, it does not run them, and the model answers your test messages ([troubleshooting.md](../troubleshooting.md#in-codex-the-model-answers-my-test-messages)). Codex asks again after each change to `.codex/hooks.json`, for example after a new `nooku init` ([codex.md](codex.md#install)).

## 5. Run `check`

```bash
nooku check
```

```text
Test 20261007-224410-2171: .../toy-shop/.nooku/tests/20261007-224410-2171
Reply: Which item is this about: the mug or the teapot?
Audit: exit 0
PASS
```

`check` runs a short test with one message through the new version, and exits with 0 if it passes ([reference/cli.md](../reference/cli.md#nooku-check)). If it fails, each FAIL line gives the cause and the fix ([troubleshooting.md](../troubleshooting.md#end-a-test)).

## Releases with a special step

### 0.3.0

**A test that 0.2.0 started.** `current.json` now needs `pid_start`, the start time of the bridge ([#44](https://github.com/mohanraj00/verbatim-relay/issues/44)). 0.3.0 treats a test that 0.2.0 started as not running. `status` names no test, and `end` removes `current.json` but sends no signal to the old bridge. The old bridge and its entry continue to run.

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
38282 .../bin/python -m nooku bridge --root .../toy-shop --test 20261007-224554-4b17
```

Stop it with SIGTERM, the default signal of `kill`:

```bash
kill 38282
```

On SIGTERM, the bridge ends the test as `end` does: it stops the entry, and writes the trace, the audit and the seal. The bridge of 0.2.0 does the same ([bridge.py of 0.2.0](https://github.com/mohanraj00/verbatim-relay/blob/v0.2.0/src/nooku/bridge.py#L514)). In my run, the test folder then had `audit.json` and `seal.json`:

```bash
nooku verify 20261007-224554-4b17
```

```text
Seal: intact. No record changed after the end of the test.
```

Do not use `kill -9` on the bridge. With SIGKILL, the bridge cannot write the audit and the seal ([recover-a-stuck-test.md](recover-a-stuck-test.md#4-learn-what-a-stale-currentjson-is)).

**Unknown keys in `config.json`.** `start`, `check` and `init` now stop at an unknown key, for example a key with a typo ([#89](https://github.com/mohanraj00/verbatim-relay/issues/89)). Before, `start` accepted it. With the key `evaluation` in place of `evaluate`, `check` printed this text and exited with 1:

```text
nooku: .nooku/config.json has unknown keys: ['evaluation']. Correct or remove them.
```

Correct the name of the key, or remove it. [reference/config.md](../reference/config.md) lists each key.

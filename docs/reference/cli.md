# CLI reference

Release: nookku 0.7.0.

This page lists each command of `nookku`. Each command has its own page in the folder `commands/`: the purpose, the form, each flag, each exit code and an example. The commands start and end a test, read its records, run the [evaluation](glossary.md#evaluation), the [audit](glossary.md#audit) and the [trace](glossary.md#trace) with its [findings](glossary.md#findings), and run the [tap](glossary.md#tap). The parser is in [src/nookku/cli.py](../../src/nookku/cli.py). The test `tests/test_docs.py` checks that each command of the parser has a page, and that each flag of the parser is on the page of its command. It also checks that each flag on a page is in the parser.

```text
nookku [-h] [--version] COMMAND ...
```

| Flag | Meaning |
|---|---|
| `--version` | Print the version and exit with 0. |
| `-h`, `--help` | Print the help of the program or of a command, and exit with 0. |

Each command that takes `--root` uses the current folder by default. The root is the project: the folder that holds `.nookku/`.

## The tests folder

Each command that reads or writes a test takes `--tests-dir PATH`: the folder that holds the folders of the tests. The command finds the folder in this order:

1. `--tests-dir PATH`. A relative path starts at the current folder.
2. The environment variable `NOOKKU_TESTS_DIR`, if it is not empty.
3. `.nookku/tests/` in the project.

Use it to keep the tests on a mounted volume, for example in a pod. The path must be absolute in `NOOKKU_TESTS_DIR`. It must not be in a state folder, and it must not be the project or a folder above it. If the path does not obey these rules, the command prints the cause and exits with 1, and the hook denies each tool call. The state files, for example `current.json`, stay in `.nookku/` ([SPEC.md section 7](../../SPEC.md#7-tests)).

The hooks of the [harness](glossary.md#harness) get no option. They read `NOOKKU_TESTS_DIR` of the harness. During a test, the guard also protects the folder of the running test. At the start of a test in a tests folder that is not `.nookku/tests`, nookku adds the folder to `.nookku/tests-dirs.json`. The hooks read this file, so the guard protects the folder after the end of the test too, also if the harness has no `NOOKKU_TESTS_DIR`. The file keeps each such folder, the newest last. Only nookku writes it, and the guard denies a model write to it. If the file is broken, the hook denies each tool call and no test starts. Remove the file to repair it ([SPEC.md section 7](../../SPEC.md#7-tests), [#507](https://github.com/mohanraj00/nookku/issues/507)).

`NOOKKU_TEST_DIR` is a different variable. The [bridge](glossary.md#bridge) gives it to the [entry](glossary.md#entry), and it is the folder of one test ([config.md](config.md#environment-variables)).

An unknown command or flag prints the usage and exits with 2. The error of an unknown command lists the commands, but not the [internal commands](#internal-commands). With no command, `nookku` prints the help and exits with 2.

## Commands of a test

### `nookku start`

Start a test. Page: [`nookku start`](commands/start.md).

### `nookku register`

Check an egress answer and keep it for the next start ([SPEC.md section 7.11](../../SPEC.md#711-egress-discovery)). Page: [`nookku register`](commands/register.md).

### `nookku end`

End the test. Page: [`nookku end`](commands/end.md).

### `nookku status`

Show [relay mode](glossary.md#relay-mode) and the running test, for example `relay mode is on. Page: [`nookku status`](commands/status.md).

### `nookku check`

Run a short test with one message, and check the entry and its model sessions ([SPEC.md section 7.1](../../SPEC.md#71-configuration)). Page: [`nookku check`](commands/check.md).

### `nookku run`

Run a [scripted test](glossary.md#scripted-test) ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)). Page: [`nookku run`](commands/run.md).

### `nookku script`

Save a test as a script ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)). Page: [`nookku script`](commands/script.md).

### `nookku replay`

Run a saved script again after a fix, and see which replies changed ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)). Page: [`nookku replay`](commands/replay.md).

### `nookku gate`

`nookku gate run` runs each test of a gate file, and writes one sealed result ([SPEC.md section 7.15](../../SPEC.md#715-gate-run)). Page: [`nookku gate`](commands/gate.md).

### `nookku adjudicate`

Record your decision about one mismatch of the [answer key](app-spec.md#answer-key) ([SPEC.md section 7.17](../../SPEC.md#717-answer-key)). Page: [`nookku adjudicate`](commands/adjudicate.md).

### `nookku evaluation`

Write the issue rows of an evaluation to `evaluation.json` in the [test folder](glossary.md#test-folder) ([SPEC.md section 9.4](../../SPEC.md#94-issue-rows)). Page: [`nookku evaluation`](commands/evaluation.md).

### `nookku mode`

Switch relay mode on or off. Page: [`nookku mode`](commands/mode.md).

### `nookku chat`

Serve the chat page. Page: [`nookku chat`](commands/chat.md).

## Commands that read a test

### `nookku dashboard`

Serve the read-only API of the runs and the gate runs of the project, and with `--site`, the static files of a dashboard ([api.md](api.md)). Page: [`nookku dashboard`](commands/dashboard.md).

### `nookku view`

Print each relayed turn. Page: [`nookku view`](commands/view.md).

### `nookku transcript`

Print the exact conversation for the model to evaluate ([SPEC.md section 5](../../SPEC.md#5-relays)). Page: [`nookku transcript`](commands/transcript.md).

### `nookku audit`

Compare the relay record with the [tap record](glossary.md#tap-record) ([SPEC.md section 3](../../SPEC.md#3-audit)). Page: [`nookku audit`](commands/audit.md).

### `nookku trace`

Build the trace of a test again, and show its findings ([SPEC.md section 8](../../SPEC.md#8-trace)). Page: [`nookku trace`](commands/trace.md).

### `nookku faults`

Run each check of the [trace](glossary.md#trace) on its seeded faults, with no model ([ADR 0002](../contributing/adr/0002-seeded-faults-personas-answer-keys-verifiers.md#nookku-faults), [#546](https://github.com/mohanraj00/nookku/issues/546)). Page: [`nookku faults`](commands/faults.md).

### `nookku verifier`

Measure a verifier on a declared claim set. Page: [`nookku verifier`](commands/verifier.md).

### `nookku export`

Write a test as one HTML file, so you can give it to a person who does not have the project or nookku. Page: [`nookku export`](commands/export.md).

### `nookku finding`

Export each confirmed defect of a test, or of a gate run, as a [finding record](glossary.md#finding-record). Page: [`nookku finding`](commands/finding.md).

### `nookku verify`

Check that no record of a test changed after its end ([SPEC.md section 7.4](../../SPEC.md#74-seal)). Page: [`nookku verify`](commands/verify.md).

## Commands that install or connect

### `nookku init`

Write the config, and the [project hooks](glossary.md#project-hooks) of a harness. Page: [`nookku init`](commands/init.md).

### `nookku policy`

Print each key of the [policy file](glossary.md#policy-file) `.nookku/policy.json` with its value, as JSON. Page: [`nookku policy`](commands/policy.md).

### `nookku setup`

Print the guide that connects a test to the app ([setup.md](../../src/nookku/setup.md)). Page: [`nookku setup`](commands/setup.md).

### `nookku tap`

Run the tap proxy in front of the agent ([SPEC.md section 4](../../SPEC.md#4-tap)). Page: [`nookku tap`](commands/tap.md).

## Internal commands

The relays and the bridge run these commands. You do not run them yourself. `nookku --help` does not show these commands.

### `nookku hook`

The hook command that `init` writes into the hook file. Page: [`nookku hook`](commands/hook.md).

### `nookku mcp`

The MCP server that gives the model the read-only tools `transcript` and `status`. Page: [`nookku mcp`](commands/mcp.md).

### `nookku mcp-stdio`

The wrapper of a stdio MCP server of the agent ([SPEC.md section 7.12](../../SPEC.md#712-mcp-proxies)). Page: [`nookku mcp-stdio`](commands/mcp-stdio.md).

### `nookku bridge`

The background process of a test ([architecture.md](../architecture.md#the-bridge)). Page: [`nookku bridge`](commands/bridge.md).

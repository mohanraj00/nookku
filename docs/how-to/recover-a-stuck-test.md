# Recover a stuck test

A test is stuck when its [bridge](../reference/glossary.md#bridge) stopped, but the project still says that a test runs. For example, the computer restarted, or a process killed the bridge. Then the [relay](../reference/glossary.md#relay) blocks each prompt with this text:

```text
nookku: relay mode is on, but no test runs. Start one with: nookku start. Nothing was sent.
```

The [plugin](../reference/glossary.md#plugin) shows the same text with `Type /nookku start`, or "the test stopped, and no test runs" ([claude-code-plugin.md](claude-code-plugin.md)). In both relays, the message does not go to the model.

The output on this page is the real output of each step. I used a toy shop project like the one of [getting-started.md](../getting-started.md), with the nookku code of the commit that added this output, on macOS. I started a test, gave one message to `nookku hook --harness claude-code`, as Claude Code does, and stopped the bridge with `kill -9`. I shortened the paths of the folders to `.../`. The test id, the pid and the times are different on your machine.

Run each command in the project root, in a shell.

## 1. Run `status`

```bash
nookku status
```

```text
relay mode is on. No test runs.
Test 20261013-192120-5c8c stopped with no end. Folder: .../toy-shop/.nookku/tests/20261013-192120-5c8c
To write its audit and its seal, run: nookku end
```

[Relay mode](../reference/glossary.md#relay-mode) is on, but no test runs. The second line names the test that stopped and its folder. If more than one test stopped, it names the one that started last. The third line gives the next step. If a test runs, the first line names it:

```text
relay mode is on. Test 20261011-185435-1c1b runs on http://127.0.0.1:49439/.
```

If the line names a test, the bridge runs. Then step 2 stops it.

`status` names a stopped test only 30 seconds or more after its start, because a test that started less than 30 seconds ago can still be in its start ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)).

## 2. Run `end` in a shell

```bash
nookku end
```

```text
Test 20261013-192120-5c8c ended: 1 turns, 0 model sessions.
Folder: .../toy-shop/.nookku/tests/20261013-192120-5c8c
The bridge stopped before the end, so end wrote the audit and the seal from the records. The test has no model sessions. See bridge.log in the folder.
Trace: 0 model items in 1 turns, no findings.
Audit: nookku audit --tap .../toy-shop/.nookku/tests/20261013-192120-5c8c/tap.jsonl --relay .../toy-shop/.nookku/tests/20261013-192120-5c8c/relay.jsonl
To evaluate the test, type this prompt in your harness: nookku end
```

`end` switches relay mode off. Then it finishes the folder of the stopped test. If the [entry](../reference/glossary.md#entry) of the test still runs, `end` stops it first. Then `end` writes `killed: true` and the end time into `manifest.json`, and writes the [trace](../reference/glossary.md#trace), `audit.json` and the [seal](../reference/glossary.md#seal) from the records that exist. It does not copy the model sessions of the app, because the bridge did not find them. If no test runs and no test stopped, `end` prints `No test runs. Relay mode is off.`

If the bridge runs but does not stop, `end` waits [120 seconds](../../src/nookku/bridge.py), and then stops the bridge with SIGKILL. It prints one line when it starts to wait. I made this case with `kill -STOP` on the bridge of a new test. `end` printed the first line at once, and the other lines after 120 seconds:

```text
Ending test 20261013-192152-322d. Waiting up to 120 s for the bridge to stop.
Test 20261013-192152-322d ended: 0 turns, 0 model sessions.
Folder: .../toy-shop/.nookku/tests/20261013-192152-322d
The bridge stopped before the end, so end wrote the audit and the seal from the records. The test has no model sessions. See bridge.log in the folder.
Trace: 0 model items in 0 turns, no findings.
Audit: nookku audit --tap .../toy-shop/.nookku/tests/20261013-192152-322d/tap.jsonl --relay .../toy-shop/.nookku/tests/20261013-192152-322d/relay.jsonl
To evaluate the test, type this prompt in your harness: nookku end
```

## 3. Run `mode off`

```bash
nookku mode off
```

```text
nookku: no test runs. Relay mode is off.
```

`end` already switched relay mode off, so this step only makes sure of it. Run `status` again to see the result:

```bash
nookku status
```

```text
relay mode is off. No test runs.
```

Now each prompt goes to the model again.

## 4. Learn what a stale `current.json` is

The bridge writes `.nookku/current.json` when a test starts, and removes it when the test ends. The file names the test, its folder, the [tap](../reference/glossary.md#tap) URL, the tap token `tap_token`, the pid of the bridge and `pid_start`, the start time of the bridge ([reference/records.md](../reference/records.md#the-state-folder)). If the bridge stops with no end, for example after `kill -9` or a restart, the file stays. This file is stale.

A pid and its start time identify the bridge, because the OS can give the pid of a stopped process to a new process. If no process has the pid, or if that process has another start time, no test runs ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)). Then `status`, `start` and `end` remove the file. The relays also do this check before each prompt.

To see a stale file, look before you run `status`, `start` or `end`, because they remove it. This example is from an earlier test:

```bash
cat .nookku/current.json
```

```text
{
 "v": 1,
 "test": "20261011-185432-0da0",
 "dir": ".../toy-shop/.nookku/tests/20261011-185432-0da0",
 "tap_url": "http://127.0.0.1:49413/",
 "tap_token": "<43 random characters>",
 "pid": 9220,
 "pid_start": "ps:Mon Oct 12 01:54:32 2026"
}
```

Then look for the process with this pid:

```bash
TZ=UTC0 LC_ALL=C ps -o lstart= -p 9220
```

This command printed nothing and exited with 1, because no process had this pid. Thus the file was stale. If `ps` prints a time, compare it with the time in `pid_start`. If the 2 times are different, another process has the pid, and the file is stale.

After `status`, the file does not exist:

```bash
cat .nookku/current.json
```

```text
cat: .nookku/current.json: No such file or directory
```

The folder of the stuck test stays. Before `end`, it has `relay.jsonl`, `tap.jsonl`, `app.log`, `bridge.log` and `manifest.json`, and the files that the app wrote in `app-state/`. It has no `audit.json` and no seal, because the bridge did not finish the test. `status` names the test (step 1), and `end` finishes the folder (step 2). After `end`, `verify` checks the seal:

```bash
nookku verify 20261013-192120-5c8c
```

```text
Test 20261013-192120-5c8c. Seal: intact. No record changed after the end of the test.
```

Use this seal with care. `end` wrote it after the bridge stopped, so it does not show a change to a record between the stop of the bridge and the run of `end`.

## 5. Start a new test

```bash
nookku start
```

```text
Test 20261011-185435-1c1b started on http://127.0.0.1:49439/. Relay mode is on.
To end the test and start the evaluation, type the prompt nookku end. To end the test with no evaluation, run nookku end in a shell.
```

You can also type the prompt `nookku start`, or `/nookku start` in the plugin. The new test is a new conversation. The agent does not get the turns of the stuck test.

## Related

- [Troubleshooting](../troubleshooting.md#during-a-test): each error text during a test.
- [CLI reference](../reference/cli.md#commands-of-a-test): `start`, `end`, `status` and `mode`.

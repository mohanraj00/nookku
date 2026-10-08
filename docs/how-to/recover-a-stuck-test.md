# Recover a stuck test

A test is stuck when its bridge stopped, but the project still says that a test runs. For example, the computer restarted, or a process killed the bridge. Then the hook kit blocks each prompt with this text:

```text
verbatim-relay: relay mode is on, but no test runs. Start one with: verbatim-relay start. Nothing was sent.
```

The plugin shows the same text with `Type /verbatim-relay start`, or "the test stopped, and no test runs" ([how-to/claude-code.md](claude-code.md#plugin)). In both relays, the message does not go to the model.

The output on this page is the real output of each step. I used the toy shop project of [getting-started.md](../getting-started.md) with verbatim-relay 0.3.0 on macOS. I started a test, sent one message, and stopped the bridge with `kill -9`. I shortened the paths of the folders to `.../`. The test id, the pid and the times are different on your machine.

Run each command in the project root, in a shell.

## 1. Run `status`

```bash
verbatim-relay status
```

```text
relay mode is on.
```

Relay mode is on, but the line names no test. Thus the bridge does not run. If a test runs, the line names it:

```text
relay mode is on. Test 20261007-224332-07f9 runs on http://127.0.0.1:52705/.
```

If the line names a test, the bridge runs. Then step 2 stops it.

## 2. Run `end` in a shell

```bash
verbatim-relay end
```

```text
No test runs. Relay mode is off.
```

`end` switches relay mode off. If no test runs, it does nothing more.

If the bridge runs but does not stop, `end` waits [120 seconds](../../src/verbatim_relay/bridge.py), and then stops the bridge with SIGKILL. I made this case with `kill -STOP` on the bridge. After 120 seconds, `end` printed:

```text
Test 20261007-224359-d00f ended: 1 turns, 0 model sessions.
Folder: .../toy-shop/.verbatim-relay/tests/20261007-224359-d00f
The bridge did not finish its collection. See bridge.log in the folder.
Audit: verbatim-relay audit --tap .../toy-shop/.verbatim-relay/tests/20261007-224359-d00f/tap.jsonl --relay .../toy-shop/.verbatim-relay/tests/20261007-224359-d00f/relay.jsonl
```

## 3. Run `mode off`

```bash
verbatim-relay mode off
```

```text
verbatim-relay: no test runs. Relay mode is off.
```

`end` already switched relay mode off, so this step only makes sure of it. Run `status` again to see the result:

```bash
verbatim-relay status
```

```text
relay mode is off.
```

Now each prompt goes to the model again.

## 4. Learn what a stale `current.json` is

The bridge writes `.verbatim-relay/current.json` when a test starts, and removes it when the test ends. The file names the test, its folder, the tap URL, the pid of the bridge and `pid_start`, the start time of the bridge ([reference/records.md](../reference/records.md#the-state-folder)). If the bridge stops with no end, for example after `kill -9` or a restart, the file stays. This file is stale.

A pid and its start time identify the bridge, because the OS can give the pid of a stopped process to a new process. If no process has the pid, or if that process has another start time, no test runs ([SPEC.md section 7.2](../../SPEC.md#72-start-and-end)). Then `status`, `start` and `end` remove the file. The relays also do this check before each prompt.

To see a stale file, look before you run `status`, `start` or `end`, because they remove it:

```bash
cat .verbatim-relay/current.json
```

```text
{
 "v": 1,
 "test": "20261007-224330-68e1",
 "dir": ".../toy-shop/.verbatim-relay/tests/20261007-224330-68e1",
 "tap_url": "http://127.0.0.1:52698/",
 "pid": 35287,
 "pid_start": "ps:Thu Oct 8 05:43:30 2026"
}
```

Then look for the process with this pid:

```bash
TZ=UTC0 LC_ALL=C ps -o lstart= -p 35287
```

This command printed nothing and exited with 1, because no process had this pid. Thus the file was stale. If `ps` prints a time, compare it with the time in `pid_start`. If the 2 times are different, another process has the pid, and the file is stale.

After `status`, the file does not exist:

```bash
cat .verbatim-relay/current.json
```

```text
cat: .verbatim-relay/current.json: No such file or directory
```

The folder of the stuck test stays. It has `relay.jsonl`, `tap.jsonl`, `app.log`, `bridge.log` and `manifest.json`. It has no `audit.json` and no seal, because the bridge did not finish the test. `verify` says so and exits with 2:

```bash
verbatim-relay verify 20261007-224330-68e1
```

```text
Seal: none. The records of this test have no seal.
```

You can still audit the 2 records by hand:

```bash
verbatim-relay audit --tap .verbatim-relay/tests/20261007-224330-68e1/tap.jsonl --relay .verbatim-relay/tests/20261007-224330-68e1/relay.jsonl
```

```text
1 turns, 1 exchanges, 0 blocked model calls, 0 model sessions, 0 breaks
Result: clean (exit 0)
```

Use this audit with care. The test has no seal, so nothing shows a change to a record after the bridge stopped.

## 5. Start a new test

```bash
verbatim-relay start
```

```text
Test 20261007-224332-07f9 started on http://127.0.0.1:52705/. Relay mode is on.
End it with: verbatim-relay end
```

You can also type the prompt `verbatim-relay start`, or `/verbatim-relay start` in the plugin. The new test is a new conversation. The agent does not get the turns of the stuck test.

## Related

- [Troubleshooting](../troubleshooting.md#during-a-test): each error text during a test.
- [CLI reference](../reference/cli.md#commands-of-a-test): `start`, `end`, `status` and `mode`.

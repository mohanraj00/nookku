import contextlib
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from nookku import bridge, evaluation, kit, mcp, policy, seal, state, stdio, trace
from nookku.audit import CHECKS, audit
from nookku.cli import main
from nookku.record import RecordError, Writer

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
CLAUDE_SID = "4f1c2a7e-0d3b-4c55-9a61-2b8e5d7c9f10"
APP_THREAD = "019a0b1c-2d3e-7f40-8a5b-6c7d8e9f0a1b"
TESTER_THREAD = "019a0b1c-0000-7000-8000-000000004471"

# A toy shop app that runs one Claude Code session and one Codex thread. It writes the files that
# the harness binaries write: the pid file and the transcript of Claude Code, and a Codex rollout.
# It also writes a rollout for the tester's own thread, which the bridge must not take.
FIXTURE_APP = f"""
import json, os, sys, time
from pathlib import Path

claude, codex = Path(os.environ["CLAUDE_CONFIG_DIR"]), Path(os.environ["CODEX_HOME"])
(claude / "sessions").mkdir(parents=True, exist_ok=True)
project = claude / "projects" / "-toy-shop"
project.mkdir(parents=True, exist_ok=True)
(project / "{CLAUDE_SID}.jsonl").write_text('{{"type": "user"}}\\n')
pid_file = claude / "sessions" / f"{{os.getpid()}}.json"
pid_file.write_text(json.dumps({{"pid": os.getpid(), "sessionId": "{CLAUDE_SID}"}}))
day = codex / "sessions" / time.strftime("%Y/%m/%d")
day.mkdir(parents=True, exist_ok=True)
for name, sid in (("app", "{APP_THREAD}"), ("tester", "{TESTER_THREAD}")):
    meta = {{"id": sid, "cwd": os.getcwd(), "originator": "toy-shop-" + name}}
    line = json.dumps({{"type": "session_meta", "payload": meta}})
    (day / f"rollout-{{name}}-{{sid}}.jsonl").write_text(line + "\\n")
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = {{"v": 1, "id": request["id"], "reply": "Toy shop: " + request["message"]}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\\n")
    sys.stdout.flush()
"""


def project(tmp_path: Path, entry: list[str], models: list[str] | None = None) -> Path:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": entry, "models": models or []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    return root


@pytest.fixture
def homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    claude, codex = tmp_path / "claude-home", tmp_path / "codex-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    return claude, codex


def test_a_test_relays_and_records_both_sides(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root, "tester-1")
    try:
        assert (root / ".nookku" / "current.json").exists()
        assert cur["pid_start"] == bridge.process_start(cur["pid"])
        said = "Do you ship to Chennai?\u2028Line two  "
        shown, ok = bridge.send(cur, said)
        Writer(Path(cur["dir"]) / "relay.jsonl").append(
            {"type": "turn", "harness": "codex", "said": said, "shown": shown, "ok": ok}
        )
        with pytest.raises(bridge.BridgeError, match="runs already"):
            bridge.start(root)
    finally:
        manifest = bridge.end(root)
    assert ok and shown.startswith("We ship to Chennai")
    assert manifest is not None and manifest["ended"] >= manifest["started"]
    assert manifest["tester_sessions"] == ["tester-1"]
    assert manifest["model_sessions"] == []
    assert "config.json" in manifest["config_sha256"]
    assert manifest["trace"] == trace.TRACE_KEYS
    folder = Path(cur["dir"])
    assert not (root / ".nookku" / "current.json").exists()
    assert "toy shop agent: ready" in (folder / "app.log").read_text()
    report = audit(folder / "tap.jsonl", folder / "relay.jsonl")
    assert (report.exit, report.turns, report.exchanges) == (0, 1, 1)
    # The last step of the end seals the folder, with a copy outside the project.
    assert seal.verify(folder)["intact"] and seal.verify(folder)["copy"] == "same"
    assert bridge.end(root) is None


def test_the_tap_of_a_test_takes_only_requests_with_its_token(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root)
    current = root / ".nookku" / "current.json"
    body = json.dumps({"v": 1, "id": "m-1", "session": "t", "message": "Hi", "history": []})
    good = state.tap_headers(cur[state.TOKEN_KEY])
    refused = [
        {"Content-Type": "application/json"},
        {**good, state.TOKEN_HEADER: "not-the-tap-token"},
        {**good, "Origin": "https://example.com"},
        {**good, "Content-Type": "text/plain"},
    ]
    try:
        # current.json holds the token, so only the owner can read it.
        assert len(cur[state.TOKEN_KEY]) >= 40 and current.stat().st_mode & 0o777 == 0o600
        statuses = []
        for headers in refused:
            req = urllib.request.Request(cur["tap_url"], body.encode(), headers, method="POST")
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=10)
            statuses.append(e.value.code)
        shown, ok = bridge.send(cur, "What is the refund policy?")
    finally:
        bridge.end(root)
    assert statuses == [403] * 4
    assert ok and shown.startswith("Our refund policy")
    rows = [json.loads(x) for x in (Path(cur["dir"]) / "tap.jsonl").read_text().splitlines()]
    # Only the relayed message reached the entry.
    assert [r["input"] for r in rows if r["type"] == "exchange"] == ["What is the refund policy?"]
    answers = Path(cur["dir"]) / "app-state" / "answers.jsonl"
    assert len(answers.read_text().splitlines()) == 1


def test_start_and_status_print_no_tap_token(tmp_path: Path, homes: tuple, capsys) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    try:
        assert main(["start", "--root", str(root), "--json"]) == 0
        started = json.loads(capsys.readouterr().out)
        assert main(["status", "--root", str(root), "--json"]) == 0
        status = json.loads(capsys.readouterr().out)
        cur = bridge.current(root)
    finally:
        main(["end", "--root", str(root)])
    assert cur is not None and cur[state.TOKEN_KEY]
    assert started == status["test"] == state.public(cur)
    assert state.TOKEN_KEY not in started


def test_a_relay_with_no_token_fails_closed(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root)
    try:
        shown, ok = bridge.send({k: v for k, v in cur.items() if k != state.TOKEN_KEY}, "Hi")
    finally:
        bridge.end(root)
    assert not ok and shown.startswith("nookku: HTTP 403: nookku tap:")


def test_the_entry_keeps_its_state_in_the_sealed_test_folder(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root)
    try:
        shown, ok = bridge.send(cur, "What is the refund policy?")
    finally:
        bridge.end(root)
    assert ok and shown.startswith("Our refund policy")
    folder = Path(cur["dir"])
    state = folder / "app-state" / "answers.jsonl"
    row = json.loads(state.read_text())
    # The toy shop got the test id and the absolute test folder from the bridge.
    assert row["test"] == cur["test"] and row["topic"] == "refund"
    assert Path(cur["dir"]).is_absolute()
    result = seal.verify(folder)
    assert result["intact"]
    state.write_text(state.read_text().replace("refund", "price"))
    assert not seal.verify(folder)["intact"]


@pytest.mark.parametrize("name", [bridge.TEST_DIR, bridge.TEST_ID])
def test_a_backend_may_not_use_a_test_variable(tmp_path: Path, name: str) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    config = root / ".nookku" / "config.json"
    shop = {"name": "shop", "env": name, "url": "http://127.0.0.1:9000"}
    config.write_text(json.dumps({**json.loads(config.read_text()), "backends": [shop]}))
    with pytest.raises(bridge.BridgeError, match=f"the variable {name} of nookku"):
        bridge.load_config(root)


def test_history_is_the_ok_turns_of_the_test(tmp_path: Path) -> None:
    relay = tmp_path / "relay.jsonl"
    w = Writer(relay)
    w.append({"type": "turn", "harness": "codex", "said": "a\u2028", "shown": "b", "ok": True})
    w.append({"type": "turn", "harness": "codex", "said": "c", "shown": "error", "ok": False})
    assert bridge.history(relay) == [("a\u2028", "b")]


def test_an_invalid_relay_record_is_an_error(tmp_path: Path) -> None:
    relay = tmp_path / "relay.jsonl"
    Writer(relay).append(
        {"type": "turn", "harness": "codex", "said": "a", "shown": "b", "ok": True}
    )
    relay.write_text(relay.read_text(encoding="utf-8").replace('"b"', '"c"'), encoding="utf-8")
    with pytest.raises(RecordError, match=r"relay\.jsonl: line 1: field shown_sha256"):
        bridge.history(relay)
    text = bridge.summary({"test": "t", "dir": str(tmp_path), "ended": 1.0})
    assert text.startswith("Test t ended: an invalid relay record (")
    assert bridge.history(tmp_path / "no-such.jsonl") == []


def test_a_stale_current_file_is_removed(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    current = root / ".nookku" / "current.json"
    current.write_text(json.dumps({"test": "x", "pid": dead.pid, "dir": "", "tap_url": ""}))
    assert bridge.current(root) is None
    assert not current.exists()


def _wait_dead(pid: int) -> None:
    deadline = time.monotonic() + 10
    while bridge.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)


def test_end_finishes_the_folder_of_a_killed_bridge(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    shown, ok = bridge.send(cur, "What is the refund policy?")
    Writer(folder / "relay.jsonl").append(
        {
            "type": "turn",
            "harness": "codex",
            "said": "What is the refund policy?",
            "shown": shown,
            "ok": ok,
        }
    )
    os.kill(cur["pid"], 9)
    _wait_dead(cur["pid"])
    # A test that started less than START_WAIT ago can still be in its start.
    assert bridge.stopped(root) is None
    monkeypatch.setattr(bridge, "START_WAIT", 0.0)
    assert main(["status", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert f"Test {cur['test']} stopped with no end. Folder: {folder}\n" in out
    assert "To write its audit and its seal, run: nookku end" in out
    assert not (root / ".nookku" / "current.json").exists()
    assert main(["end", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Test {cur['test']} ended: 1 turns, 0 model sessions.")
    assert "The bridge stopped before the end, so end wrote the audit and the seal" in out
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["killed"] is True and manifest["ended"] >= manifest["started"]
    assert json.loads((folder / "audit.json").read_text())["exit"] == 0
    assert seal.verify(folder)["intact"]
    assert "nookku end: Trace:" in (folder / "bridge.log").read_text()
    # The test is finished, so status names no stopped test, and end finds no test.
    assert bridge.stopped(root) is None
    assert bridge.end(root) is None


def test_end_finishes_the_folder_of_a_hung_bridge(
    tmp_path: Path, homes: tuple, capsys: pytest.CaptureFixture
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    os.kill(cur["pid"], signal.SIGSTOP)
    manifest = bridge.end(root, wait=0.5)
    _wait_dead(cur["pid"])
    assert manifest is not None and manifest["killed"] is True
    assert seal.verify(folder)["intact"]
    assert "stopped before the end" in bridge.summary(manifest)


def test_end_stops_the_entry_of_a_killed_bridge(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This entry does not stop at the end of its stdin.
    root = project(tmp_path, [sys.executable, "-c", "import time; time.sleep(600)"])
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    entry = json.loads((folder / "manifest.json").read_text())["entry_pid"]
    os.kill(cur["pid"], 9)
    _wait_dead(cur["pid"])
    assert bridge.alive(entry)
    monkeypatch.setattr(bridge, "START_WAIT", 0.0)
    manifest = bridge.end(root)
    assert manifest is not None and manifest["killed"] is True
    assert not bridge.alive(entry)
    assert seal.verify(folder)["intact"]


def test_an_older_stopped_test_stays_stopped_after_a_new_test(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    tests = root / ".nookku" / "tests"
    now = time.time()
    for name, started, ended in (("old", now - 100, None), ("new", now - 50, now - 40)):
        (tests / name).mkdir(parents=True)
        manifest = {"test": name, "started": started, "ended": ended}
        (tests / name / "manifest.json").write_text(json.dumps(manifest))
    assert bridge.stopped(root) == tests / "old"
    # Of 2 stopped tests, the one that started last is the stopped test.
    (tests / "older").mkdir()
    (tests / "older" / "manifest.json").write_text(json.dumps({"started": now - 200}))
    assert bridge.stopped(root) == tests / "old"


def test_end_stops_the_group_of_an_entry_that_stopped(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # The entry starts a helper in its group, then stops at the end of its stdin.
    shell = f"sleep 600 & exec {sys.executable} -c 'import sys; sys.stdin.read()'"
    root = project(tmp_path, ["sh", "-c", shell])
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    entry = json.loads((folder / "manifest.json").read_text())["entry_pid"]
    os.kill(cur["pid"], 9)
    _wait_dead(cur["pid"])
    _wait_dead(entry)
    assert not bridge.alive(entry) and bridge._group(entry)
    monkeypatch.setattr(bridge, "START_WAIT", 0.0)
    try:
        manifest = bridge.end(root)
        assert manifest is not None and manifest["killed"] is True
        if sys.platform.startswith("linux"):
            # The helper has the test id in its environment, so end stops it.
            assert not bridge._group(entry)
            assert seal.verify(folder)["intact"]
        else:
            # Only Linux lets nookku read the environment, so end sends no signal and warns.
            assert bridge._group(entry)
            err = capsys.readouterr().err
            assert f"have the process group id of the entry of test {cur['test']}" in err
            assert f"run: nookku verify {cur['test']}" in err
    finally:
        with contextlib.suppress(OSError):
            os.killpg(entry, 9)


def test_a_group_with_another_test_id_gets_no_signal() -> None:
    # The leader of the group exits, and a process with no test id stays in the group. This is
    # the group of a new process that got the pid of the entry after the entry stopped.
    shell = subprocess.Popen(["sh", "-c", "sleep 600 &"], start_new_session=True)
    shell.wait()
    try:
        members = bridge._members(shell.pid)
        assert members and shell.pid not in members
        manifest = {"test": "t-1", "entry_pid": shell.pid, "entry_pid_start": "ps:x"}
        assert bridge._stop_entry(manifest, grace=0.2) == members
        assert bridge._group(shell.pid)
    finally:
        with contextlib.suppress(OSError):
            os.killpg(shell.pid, 9)


def test_a_live_pid_with_another_start_time_is_not_the_entry() -> None:
    other = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        manifest = {"entry_pid": other.pid, "entry_pid_start": "ps:Thu Jan 1 00:00:00 1970"}
        bridge._stop_entry(manifest, grace=0.2)
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_check_does_not_finish_an_older_stopped_test(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    old = root / ".nookku" / "tests" / "old"
    old.mkdir(parents=True)
    (old / "manifest.json").write_text(json.dumps({"started": time.time() - 100}))
    assert bridge.end(root, find_stopped=False) is None
    assert "killed" not in json.loads((old / "manifest.json").read_text())


def test_end_finishes_a_bridge_that_hangs_after_it_wrote_the_end_time(
    tmp_path: Path, homes: tuple
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    os.kill(cur["pid"], signal.SIGSTOP)
    # The bridge wrote `ended`, then hung before the audit and the seal.
    manifest = json.loads((folder / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps({**manifest, "ended": time.time()}))
    ended = bridge.end(root, wait=0.5)
    _wait_dead(cur["pid"])
    assert ended is not None and ended["killed"] is True
    assert (folder / "audit.json").exists() and seal.verify(folder)["intact"]


def test_end_names_the_test_and_the_wait(
    tmp_path: Path, homes: tuple, capsys: pytest.CaptureFixture
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root)
    assert main(["end", "--root", str(root)]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first == f"Ending test {cur['test']}. Waiting up to 120 s for the bridge to stop."


def test_a_live_process_that_is_not_the_bridge_gets_no_signal(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    other = subprocess.Popen(["sleep", "60"])
    try:
        current = root / ".nookku" / "current.json"
        real = bridge.process_start(other.pid)
        assert real
        cur = {"test": "x", "pid": other.pid, "dir": str(tmp_path), "tap_url": ""}
        # A file of an earlier version has no pid_start. A pid that the OS gave again has a
        # different start time.
        for start in ({}, {"pid_start": "ps:Thu Jan 1 00:00:00 1970"}):
            current.write_text(json.dumps({**cur, **start}))
            assert bridge.end(root, wait=1) is None
            assert not current.exists()
            current.write_text(json.dumps({**cur, **start}))
            assert bridge.current(root) is None
            assert not current.exists()
        assert other.poll() is None
        # The same process with its own start time is a bridge for current().
        current.write_text(json.dumps({**cur, "pid_start": real}))
        assert bridge.current(root) is not None
    finally:
        other.kill()
        other.wait()


def test_a_pid_that_changes_owner_after_the_check_gets_no_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    other = subprocess.Popen(["sleep", "60"])
    try:
        # current() saw the bridge, and then the OS gave its pid to another process.
        cur = {"test": "x", "pid": other.pid, "pid_start": "ps:old", "dir": str(tmp_path)}
        monkeypatch.setattr(bridge, "current", lambda root: cur)
        bridge.end(root, wait=1)
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_an_entry_that_exits_at_start_is_reported(tmp_path: Path, homes: tuple) -> None:
    # A shell starts in milliseconds. A new Python process can need more than START_CHECK on a
    # busy CI runner, and then the test started with no error (#300).
    script = "echo 'no toy shop database' >&2; exit 1"
    root = project(tmp_path, ["/bin/sh", "-c", script])
    with pytest.raises(bridge.BridgeError, match="no toy shop database"):
        bridge.start(root)
    assert bridge.current(root) is None


def test_a_test_whose_entry_did_not_start_is_not_stopped_and_gets_no_evaluation(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nookku import evaluation

    root = project(tmp_path, ["/bin/sh", "-c", "exit 1"])
    with pytest.raises(bridge.BridgeError):
        bridge.start(root)
    folder = bridge.latest_test(root)
    assert folder is not None
    deadline = time.monotonic() + 10
    while json.loads((folder / "manifest.json").read_text())["ended"] is None:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["start_failed"] is True and manifest["ended"] >= manifest["started"]
    # The test is not a stopped test also after START_WAIT, so end does not finish it.
    monkeypatch.setattr(bridge, "START_WAIT", 0.0)
    assert bridge.stopped(root) is None
    assert bridge.end(root) is None
    assert evaluation.pending(root) is None


def test_end_finishes_a_stopped_test_with_an_entry_pid_larger_than_a_c_int(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    folder = root / ".nookku" / "tests" / "t-1"
    folder.mkdir(parents=True)
    manifest = {"test": "t-1", "started": time.time() - 100, "ended": None}
    manifest.update(entry_pid=2**70, entry_pid_start="ps:x")
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert not bridge.alive(2**70)
    monkeypatch.setattr(bridge, "START_WAIT", 0.0)
    ended = bridge.end(root)
    assert ended is not None and ended["killed"] is True
    assert seal.verify(folder)["intact"]


def test_end_of_a_test_with_a_manifest_that_is_not_an_object_does_not_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    folder = root / ".nookku" / "tests" / "t-1"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("[1, 2]")
    # A bridge pid that the OS cannot have does not run.
    cur = {"test": "t-1", "dir": str(folder), "pid": 2**70, "pid_start": "ps:x"}
    monkeypatch.setattr(bridge, "current", lambda root: cur)
    assert bridge.end(root, wait=0.2) == {"test": "t-1", "dir": str(folder)}


def test_the_start_check_does_not_wait_for_an_entry_that_exits() -> None:
    proc = subprocess.Popen(["/bin/sh", "-c", "exit 1"], stdout=subprocess.PIPE)
    began = time.monotonic()
    assert bridge._exits_at_start(proc, wait=60.0)
    assert time.monotonic() - began < 30.0
    assert proc.returncode == 1
    assert proc.stdout is not None
    proc.stdout.close()


def test_the_start_check_passes_an_entry_that_runs() -> None:
    proc = subprocess.Popen(["/bin/sh", "-c", "read line"], stdin=subprocess.PIPE)
    try:
        assert not bridge._exits_at_start(proc, wait=0.05)
        assert proc.poll() is None
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait()


def test_no_entry_is_an_error(tmp_path: Path) -> None:
    root = project(tmp_path, [])
    with pytest.raises(bridge.BridgeError, match="no 'entry'"):
        bridge.start(root)


def test_check_finds_the_model_sessions_of_the_app(tmp_path: Path, homes: tuple) -> None:
    script = tmp_path / "app.py"
    script.write_text(FIXTURE_APP)
    root = project(tmp_path, [sys.executable, str(script)], ["claude-code", "codex"])
    passed, lines = bridge.check(root)
    assert passed, lines
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    found = {(s["harness"], s["session"], s["inferred"]) for s in manifest["model_sessions"]}
    assert ("claude-code", CLAUDE_SID, False) in found
    assert ("codex", APP_THREAD, True) in found
    assert (folder / "sessions" / "claude-code" / f"{CLAUDE_SID}.jsonl").exists()
    rows = [json.loads(x) for x in (folder / "tap.jsonl").read_text().split("\n") if x]
    assert sum(r["type"] == "model_session" for r in rows) >= 2
    assert audit(folder / "tap.jsonl", folder / "relay.jsonl").exit == 0
    assert json.loads((folder / "audit.json").read_text())["exit"] == 0
    # The fixture files have no items and no version (SPEC.md section 8). `check` has no tester
    # session, so it also takes the tester rollout of the fixture.
    assert (folder / "trace.jsonl").read_text() == ""
    findings = json.loads((folder / "findings.json").read_text())
    assert findings["turns"] == 1
    assert {s["version"] for s in findings["sessions"]} == {"unknown"}
    assert findings["counts"]["version_untested"] == len(manifest["model_sessions"])
    assert findings["counts"]["session_inferred"] == len(manifest["model_sessions"]) - 1
    assert findings["counts"]["turn_without_model"] == 0


def test_check_finds_the_sessions_of_an_app_in_a_subfolder(tmp_path: Path, homes: tuple) -> None:
    # The work-around of docs/troubleshooting.md (#124): the app runs its harness in a subfolder,
    # so that its sessions stay out of the session list of the tester.
    script = tmp_path / "app.py"
    script.write_text(FIXTURE_APP)
    start = f"import os, runpy; os.chdir('.toy-shop-work'); runpy.run_path({str(script)!r})"
    root = project(tmp_path, [sys.executable, "-c", start], ["claude-code", "codex"])
    (root / ".toy-shop-work").mkdir()
    passed, lines = bridge.check(root)
    assert passed, lines
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    found = {(s["harness"], s["session"]) for s in manifest["model_sessions"]}
    assert {("claude-code", CLAUDE_SID), ("codex", APP_THREAD)} <= found
    assert (folder / "sessions" / "claude-code" / f"{CLAUDE_SID}.jsonl").exists()


def test_the_tester_thread_is_not_an_app_session(tmp_path: Path, homes: tuple) -> None:
    script = tmp_path / "app.py"
    script.write_text(FIXTURE_APP)
    root = project(tmp_path, [sys.executable, str(script)], ["codex"])
    # As with codex exec, the prompt that ends the test is a new session: the tester thread of
    # the fixture. The relay passes it to the bridge (SPEC.md section 7.2).
    events = [
        {"hook_event_name": "UserPromptSubmit", "prompt": p, "session_id": sid}
        for p, sid in (
            ("nookku start", "tester-start"),
            ("Is the teapot in stock?", "tester-start"),
            ("nookku end", TESTER_THREAD),
        )
    ]
    answers = [kit.handle(e, root, "codex") for e in events]
    assert all(a and a["decision"] == "block" for a in answers[:2])
    assert "started" in answers[0]["reason"]
    # The end prompt goes on to the model, with the evaluation.
    assert "Evaluate test" in answers[2]["hookSpecificOutput"]["additionalContext"]
    assert not (root / ".nookku" / bridge.ENDING).exists()
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    assert TESTER_THREAD in manifest["tester_sessions"]
    threads = [s["session"] for s in manifest["model_sessions"] if s["harness"] == "codex"]
    assert threads == [APP_THREAD]


def test_check_fails_without_a_model_session(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)], ["claude-code"])
    passed, lines = bridge.check(root)
    assert not passed
    assert any("No claude-code model session" in line for line in lines)


def own_end(root: Path, find_stopped: bool = True) -> dict:
    """An end for check and run_script: they must end only their own test (#164)."""
    assert find_stopped is False
    return {}


def test_check_gives_the_fix_for_logs_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The tap error of an entry that writes its logs on stdout (tests/test_contract.py makes it).
    error = (
        "the agent printed 3 lines on stdout but no reply line for m-1 in 240 s, so the tap "
        f"stopped it. {stdio.STRAY_HINT} The first line: 'toy shop: loading catalog'"
    )
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    folder = tmp_path / "test"
    folder.mkdir()
    monkeypatch.setattr(bridge, "start", lambda root, **_: {"test": "t-1", "dir": str(folder)})
    monkeypatch.setattr(bridge, "send", lambda cur, said: (f"nookku: HTTP 504: {error}", False))
    monkeypatch.setattr(bridge, "end", own_end)
    # The tap wrote an unparsed row for each stray line, so the audit exits with 2.
    detail = "line 1: STDIO stdout: a stray line on stdout: 'toy shop: loading catalog'"
    row = {"class": "tap_unparsed", "record": "tap", "detail": detail}
    (folder / "audit.json").write_text(json.dumps({"exit": 2, "breaks": [], "errors": [row]}))
    passed, lines = bridge.check(root)
    assert not passed
    # The fix shows one time (#118).
    assert lines[-2:] == [
        "FAIL: The entry printed lines on stdout, but no reply line. " + stdio.STRAY_HINT,
        f"FAIL: tap_unparsed: tap {detail}.",
    ]


def test_check_gives_one_line_for_the_stray_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    folder = tmp_path / "test"
    folder.mkdir()
    monkeypatch.setattr(bridge, "start", lambda root, **_: {"test": "t-1", "dir": str(folder)})
    monkeypatch.setattr(bridge, "send", lambda cur, said: ("Toy shop: hi", True))
    monkeypatch.setattr(bridge, "end", own_end)
    stray = [
        {
            "class": "tap_unparsed",
            "record": "tap",
            "detail": f"line {n}: STDIO stdout: a stray line on stdout: 'toy shop: log {n}'",
        }
        for n in range(1, 51)
    ]
    other = {"class": "tap_unparsed", "record": "tap", "detail": "line 51: not JSON"}
    errors = [*stray[:2], other, *stray[2:]]
    report = {"exit": 2, "breaks": [], "errors": errors}
    (folder / "audit.json").write_text(json.dumps(report))
    passed, lines = bridge.check(root)
    assert not passed
    first = "; ".join(e["detail"] for e in stray[:3])
    fix = "Send one contract line for each request (SPEC.md section 6)."
    assert [line for line in lines if line.startswith("FAIL")] == [
        f"FAIL: tap_unparsed: tap has 50 stray lines on stdout. The first 3: {first}. "
        + stdio.STRAY_HINT,
        f"FAIL: tap_unparsed: tap line 51: not JSON. {fix}",
    ]
    assert "\n".join(lines).count(stdio.STRAY_HINT) == 1


# An entry that prints a log line on stdout and then replies (#90). The reply comes, but the tap
# writes an unparsed row for the log line, so the audit of each real test exits with 2.
LOG_ON_STDOUT_APP = """
import json, sys
print("toy shop: loading catalog", flush=True)
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = {"v": 1, "id": request["id"], "reply": "Toy shop: " + request["message"]}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_check_fails_if_the_entry_logs_on_stdout_and_then_replies(
    tmp_path: Path, homes: tuple
) -> None:
    script = tmp_path / "app.py"
    script.write_text(LOG_ON_STDOUT_APP)
    root = project(tmp_path, [sys.executable, str(script)])
    passed, lines = bridge.check(root)
    assert not passed, lines
    assert "Reply: Toy shop: " + bridge.CHECK_MESSAGE in lines
    assert "Audit: exit 2" in lines
    stray = "a stray line on stdout: 'toy shop: loading catalog'. " + stdio.STRAY_HINT
    assert [line for line in lines if line.startswith("FAIL")] == [
        f"FAIL: tap_unparsed: tap line 1: STDIO stdout: {stray}"
    ]


ECHO_APP = LOG_ON_STDOUT_APP.replace('print("toy shop: loading catalog", flush=True)\n', "")


def test_check_sends_the_check_message_of_the_config(tmp_path: Path, homes: tuple) -> None:
    script = tmp_path / "app.py"
    script.write_text(ECHO_APP)
    root = project(tmp_path, [sys.executable, str(script)])
    conf = root / ".nookku" / "config.json"
    message = "Do you sell a red teapot?\nI need one for a gift."
    conf.write_text(json.dumps({**json.loads(conf.read_text()), "check_message": message}))
    passed, lines = bridge.check(root)
    assert passed, lines
    assert "Reply: Toy shop: " + message in lines
    folder = bridge.latest_test(root)
    assert folder is not None
    turns = [json.loads(x) for x in (folder / "relay.jsonl").read_text().splitlines() if x]
    assert [r["said"] for r in turns if r["type"] == "turn"] == [message]


REPLY_THEN_LOG_APP = """
import json, sys
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = {"v": 1, "id": request["id"], "reply": "Toy shop: " + request["message"]}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.write("toy shop: reply sent\\n")
    sys.stdout.flush()
"""


def test_check_fails_if_the_entry_replies_and_then_logs_on_stdout(
    tmp_path: Path, homes: tuple
) -> None:
    # The log line comes after the last reply. The end of the test records it as a stray line.
    script = tmp_path / "app.py"
    script.write_text(REPLY_THEN_LOG_APP)
    root = project(tmp_path, [sys.executable, str(script)])
    passed, lines = bridge.check(root)
    assert not passed, lines
    assert "Audit: exit 2" in lines
    stray = "a stray line on stdout: 'toy shop: reply sent'. " + stdio.STRAY_HINT
    assert [line for line in lines if line.startswith("FAIL")] == [
        f"FAIL: tap_unparsed: tap line 2: STDIO stdout: {stray}"
    ]


def test_a_clean_entry_passes_the_check(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    passed, lines = bridge.check(root)
    assert passed, lines
    assert lines[-2:] == ["Audit: exit 0", "PASS"]


def test_a_check_that_stops_before_the_reply_gets_no_evaluation(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ctrl-C during the send: the check ends its test with no turn (#297).
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])

    def stop(cur: dict, said: str) -> tuple[str, bool]:
        raise KeyboardInterrupt

    monkeypatch.setattr(bridge, "send", stop)
    with pytest.raises(KeyboardInterrupt):
        bridge.check(root)
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["check"] is True and manifest["ended"] is not None
    assert bridge.history(folder / "relay.jsonl") == []
    assert evaluation.pending(root) is None
    # A test of the tester is not a check test.
    bridge.start(root)
    assert bridge.end(root)["check"] is False
    assert evaluation.pending(root) == bridge.latest_test(root)


def test_check_fails_closed_without_a_valid_audit(tmp_path: Path) -> None:
    missing = "The audit.json of the test is missing. Read bridge.log in the test folder."
    assert bridge.audit_problems(tmp_path) == (None, [missing])
    for text in ("{", "[]", '{"exit": 0}', '{"exit": true, "breaks": [], "errors": []}'):
        (tmp_path / "audit.json").write_text(text)
        code, problems = bridge.audit_problems(tmp_path)
        assert code is None, text
        assert len(problems) == 1, text
        assert problems[0].startswith("The audit.json of the test is not valid"), text


def test_check_names_each_break_with_its_fix(tmp_path: Path) -> None:
    assert set(bridge.BREAK_FIX) == set(CHECKS)
    breaks = [
        {"class": "not_delivered", "relay_line": 1, "tap_line": None, "evidence": {}},
        {"class": "injected_input", "relay_line": None, "tap_line": 2, "evidence": {}},
    ]
    (tmp_path / "audit.json").write_text(json.dumps({"exit": 1, "breaks": breaks, "errors": []}))
    assert bridge.audit_problems(tmp_path) == (
        1,
        [
            "not_delivered break (relay line 1, tap line -). " + bridge.BREAK_FIX["not_delivered"],
            "injected_input break (relay line -, tap line 2). "
            + bridge.BREAK_FIX["injected_input"],
        ],
    )


def test_the_watcher_takes_only_processes_of_the_entry(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    parent = subprocess.Popen(
        [sys.executable, "-c", "import subprocess, sys; subprocess.run(['sleep', '30'])"]
    )
    try:
        child = None
        for _ in range(50):
            child = next(iter(bridge.descendants(parent.pid) - {parent.pid}), None)
            if child:
                break
            time.sleep(0.1)
        assert child is not None
        (sessions / f"{child}.json").write_text(json.dumps({"pid": child, "sessionId": "app"}))
        other = os.getpid()
        (sessions / f"{other}.json").write_text(json.dumps({"pid": other, "sessionId": "tester"}))
        (sessions / "partial.json").write_text('{"pid": ')
        watcher = bridge.ClaudeWatcher(parent.pid, Writer(tmp_path / "tap.jsonl"), sessions)
        watcher.poll()
        watcher.poll()
    finally:
        parent.kill()
    assert watcher.found == {"app": child}
    rows = (tmp_path / "tap.jsonl").read_text().split("\n")
    assert len([r for r in rows if r]) == 1


def test_codex_sessions_match_project_time_and_tester(tmp_path: Path) -> None:
    root = tmp_path / "shop"
    (root / "api").mkdir(parents=True)
    base = tmp_path / "sessions"
    day = base / time.strftime("%Y/%m/%d")
    day.mkdir(parents=True)

    def rollout(name: str, sid: str, cwd: Path, old: bool = False) -> None:
        f = day / f"rollout-{name}.jsonl"
        meta = {"type": "session_meta", "payload": {"id": sid, "cwd": str(cwd)}}
        f.write_text(json.dumps(meta) + "\n")
        if old:
            os.utime(f, (time.time() - 3600, time.time() - 3600))

    rollout("app", "app", root / "api")
    rollout("tester", "tester", root)
    rollout("elsewhere", "elsewhere", tmp_path)
    rollout("old", "old", root, old=True)
    (day / "rollout-broken.jsonl").write_text("not json\n")
    now = time.time()
    found = bridge.codex_sessions(root, now - 60, now + 1, {"tester"}, base)
    assert [meta["id"] for _, meta in found] == ["app"]


def test_kit_without_a_test_fails_closed(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    kit.set_mode(root, True)
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "Hi", "session_id": "s1"}
    answer = kit.handle(event, root, "claude-code")
    assert answer is not None and answer["decision"] == "block"
    assert "no test runs" in answer["reason"]


@pytest.mark.parametrize(
    ("tool", "tool_input", "denied"),
    [
        ("Write", {"file_path": ".nookku/entry.py", "content": "x"}, True),
        ("apply_patch", {"input": "*** Update File: .nookku/config.json"}, True),
        ("Bash", {"command": "cat .nookku/config.json"}, True),
        ("Read", {"file_path": ".nookku/config.json"}, False),
        ("Write", {"file_path": "shop/orders.py", "content": "x"}, False),
        ("Bash", {"command": "curl -s {tap_url}"}, True),
        ("Bash", {"command": "ls"}, False),
    ],
)
def test_kit_protects_the_test(
    tmp_path: Path, homes: tuple, tool: str, tool_input: dict, denied: bool
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    kit.init(root, "claude-code", {"entry": [sys.executable, str(TOY_SHOP)]})
    cur = bridge.start(root)
    try:
        text = json.loads(json.dumps(tool_input).replace("{tap_url}", cur["tap_url"]))
        event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": text}
        answer = kit.handle(event, root, "claude-code")
    finally:
        bridge.end(root)
    assert (answer is not None) == denied


def test_view_follows_the_latest_test(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    kit.init(root, "claude-code", {"entry": [sys.executable, str(TOY_SHOP)]})
    for prompt in ("nookku start", "Refund policy?", "nookku end"):
        event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "session_id": "s1"}
        kit.handle(event, root, "claude-code")
    out = io.StringIO()
    kit.view_tests(root, False, out)
    text = out.getvalue()
    assert text.startswith("════ test ")
    assert "Refund policy?\n──── agent ────\nOur refund policy:" in text


def test_view_finds_a_test_that_starts_after_the_view(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The view starts with no config.json. Then the tester writes a config with an entry and
    starts a test. The view shows the turn of that test (#312)."""
    root = tmp_path / "shop"
    root.mkdir()
    real_sleep, busy = time.sleep, [False]

    def write_config() -> None:
        kit.init(root, "claude-code", {"entry": [sys.executable, str(TOY_SHOP)]})

    def run_test() -> None:
        for prompt in ("nookku start", "Refund policy?", "nookku end"):
            event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "session_id": "s1"}
            kit.handle(event, root, "claude-code")

    todo = [write_config, run_test]

    def sleep(seconds: float) -> None:
        # A step can also sleep, for example when a test starts. That sleep is a real sleep.
        if busy[0]:
            return real_sleep(seconds)
        if not todo:
            raise KeyboardInterrupt  # the view stops as when the tester types Ctrl+C
        busy[0] = True
        try:
            todo.pop(0)()
        finally:
            busy[0] = False

    monkeypatch.setattr(kit.time, "sleep", sleep)
    assert main(["view", "--root", str(root)]) == 0
    assert not todo
    text = capsys.readouterr().out
    assert "════ test " in text
    assert "Refund policy?\n──── agent ────\nOur refund policy:" in text


def test_the_latest_test_is_the_one_that_started_last(tmp_path: Path) -> None:
    tests = tmp_path / ".nookku" / "tests"
    # The same second: the random part puts the older test last by name.
    for name, started in (("20261006-080000-ffff", 1.0), ("20261006-080000-0000", 2.0)):
        (tests / name).mkdir(parents=True)
        (tests / name / "manifest.json").write_text(json.dumps({"started": started}))
    assert bridge.latest_test(tmp_path) == tests / "20261006-080000-0000"
    # A folder with no manifest yet is a test that starts now.
    (tests / "20261006-075959-aaaa").mkdir()
    assert bridge.latest_test(tmp_path) == tests / "20261006-075959-aaaa"


# A toy shop app with OpenTelemetry: for each message, it sends one span to the endpoint that the
# bridge gives it, with a personal attribute that the receiver must remove.
OTEL_APP = """
import json, os, sys, time, urllib.request

url = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] + "/v1/traces"
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    now = time.time_ns()
    attrs = [
        {"key": "shop.sku", "value": {"stringValue": "teapot-set"}},
        {"key": "user.email", "value": {"stringValue": "tester@example.com"}},
    ]
    span = {"traceId": "0af7651916cd43dd8448eb211c80319c", "spanId": "b7ad6b7169203331",
            "name": "check_stock", "startTimeUnixNano": str(now), "endTimeUnixNano": str(now),
            "attributes": attrs}
    res = {"attributes": [{"key": "service.name", "value": {"stringValue": "toy-shop"}}]}
    body = {"resourceSpans": [{"resource": res, "scopeSpans": [{"spans": [span]}]}]}
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()
    out = {"v": 1, "id": request["id"], "reply": "3 teapot sets left."}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_the_receiver_records_the_app_spans(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, "-c", OTEL_APP])
    cur = bridge.start(root, "tester-1")
    try:
        shown, ok = bridge.send(cur, "Do you have the teapot set?")
    finally:
        bridge.end(root)
    assert ok and shown == "3 teapot sets left."
    folder = Path(cur["dir"])
    rows = [json.loads(x) for x in (folder / "otel.jsonl").read_text().splitlines()]
    assert [(r["type"], r["service"], r["name"]) for r in rows] == [
        ("span", "toy-shop", "check_stock")
    ]
    assert "example.com" not in (folder / "otel.jsonl").read_text()
    items = [json.loads(x) for x in (folder / "trace.jsonl").read_text().splitlines()]
    assert [(it["kind"], it["turn"], it["source"]["file"]) for it in items] == [
        ("span", 1, "otel.jsonl")
    ]
    assert seal.verify(folder)["intact"]


def test_otel_false_starts_no_receiver(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    config = root / ".nookku" / "config.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "otel": False}))
    cur = bridge.start(root, "tester-1")
    try:
        bridge.send(cur, "Hi")
    finally:
        bridge.end(root)
    assert not (Path(cur["dir"]) / "otel.jsonl").exists()
    assert "OTLP receiver" not in (Path(cur["dir"]) / "bridge.log").read_text()


# A toy shop app that asks its stock service for each message. It reads the URL from STOCK_URL.
STOCK_APP = """
import json, os, sys, urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    with urllib.request.urlopen(os.environ["STOCK_URL"] + "/stock?sku=teapot-set", timeout=5) as r:
        left = json.loads(r.read())["left"]
    out = {"v": 1, "id": request["id"], "reply": f"{left} teapot sets left."}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_the_proxy_records_the_backend_calls(tmp_path: Path, homes: tuple) -> None:
    from toy_stock_server import StockServer

    root = project(tmp_path, [sys.executable, "-c", STOCK_APP])
    config = root / ".nookku" / "config.json"
    with StockServer() as stock:
        backends = [{"name": "stock", "env": "STOCK_URL", "url": stock.url}]
        config.write_text(json.dumps({**json.loads(config.read_text()), "backends": backends}))
        cur = bridge.start(root, "tester-1")
        try:
            shown, ok = bridge.send(cur, "Do you have the teapot set?")
        finally:
            bridge.end(root)
    assert ok and shown == "3 teapot sets left."
    folder = Path(cur["dir"])
    items = [json.loads(x) for x in (folder / "trace.jsonl").read_text().splitlines()]
    assert [(it["kind"], it["turn"], it["name"], it["exit_code"]) for it in items] == [
        ("http", 1, "GET /stock", 200)
    ]
    assert seal.verify(folder)["intact"]


MODEL_APP = """
import json, os, sys, urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    ask = {"model": "claude-toy", "stream": True, "messages": [
        {"role": "user", "content": request["message"]}]}
    call = urllib.request.Request(
        os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", data=json.dumps(ask).encode(),
        headers={"x-api-key": "sk-toy-k3y", "content-type": "application/json"})
    with urllib.request.urlopen(call, timeout=5) as r:
        lines = r.read().decode().split("\\n")
    events = [json.loads(x[6:]) for x in lines if x.startswith("data: ")]
    deltas = [e["delta"] for e in events if e["type"] == "content_block_delta"]
    text = "".join(d.get("text", "") for d in deltas)
    sys.stdout.write(json.dumps({"v": 1, "id": request["id"], "reply": text}) + "\\n")
    sys.stdout.flush()
"""


def test_the_proxy_records_the_direct_model_calls(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_model_api import STREAM
    from toy_model_server import ModelServer

    root = project(tmp_path, [sys.executable, "-c", MODEL_APP])
    with ModelServer() as model:
        model.parts = STREAM
        monkeypatch.setenv("ANTHROPIC_BASE_URL", model.url)
        cur = bridge.start(root, "tester-1")
        try:
            shown, ok = bridge.send(cur, "Do you have the teapot set?")
        finally:
            bridge.end(root)
    assert ok and shown == "3 teapot sets € left."
    folder = Path(cur["dir"])
    assert "k3y" not in (folder / "model_api.jsonl").read_text()
    items = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    assert [(it["kind"], it["turn"], it["role"], it["output"]) for it in items] == [
        ("message", 1, "user", "Do you have the teapot set?"),
        ("message", 1, "assistant", "3 teapot sets € left."),
    ]
    assert seal.verify(folder)["intact"]


def test_a_bad_model_api_config_stops_the_start(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    config = root / ".nookku" / "config.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "model_api": ["toy"]}))
    with pytest.raises(bridge.BridgeError, match="'model_api' must be"):
        bridge.start(root)


def test_a_bad_backend_config_stops_the_start(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    config = root / ".nookku" / "config.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "backends": [{"name": "x"}]}))
    with pytest.raises(bridge.BridgeError, match="'name', 'env' and 'url'"):
        bridge.start(root)


def test_an_invalid_relay_record_infers_no_codex_session(tmp_path: Path, homes: tuple) -> None:
    # Without the tester sessions of relay.jsonl, a tester rollout looks like an app session.
    script = tmp_path / "app.py"
    script.write_text(FIXTURE_APP)
    root = project(tmp_path, [sys.executable, str(script)], ["codex"])
    cur = bridge.start(root, "tester-start")
    folder = Path(cur["dir"])
    (folder / "relay.jsonl").write_text("not json\n", encoding="utf-8")
    time.sleep(0.5)
    bridge.end(root, wait=10)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert [s for s in manifest["model_sessions"] if s["harness"] == "codex"] == []
    assert not (folder / "sessions" / "codex").exists()
    log = (folder / "bridge.log").read_text(encoding="utf-8")
    assert "the relay record is invalid, so the test infers no Codex session" in log


SCRIPT = ["Is the teapot in stock?", "Return order #4471, please.  ", "Thanks.\nBye €"]


def write_script(path: Path, form: str, messages: list[str]) -> Path:
    if form == "json":
        path.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    else:
        text = "".join(json.dumps({"said": m}, ensure_ascii=False) + "\n" for m in messages)
        path.write_text(text, encoding="utf-8")
    return path


def relay_turns(folder: Path) -> list[dict]:
    rows = [json.loads(x) for x in (folder / "relay.jsonl").read_text().splitlines() if x]
    return [r for r in rows if r["type"] == "turn"]


@pytest.mark.parametrize("form", ["jsonl", "json"])
def test_run_script_sends_each_message_of_the_script(
    tmp_path: Path, homes: tuple, form: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "app.py"
    app.write_text(ECHO_APP)
    root = project(tmp_path, [sys.executable, str(app)])
    path = write_script(tmp_path / f"turns.{form}", form, SCRIPT)
    real_end, calls = bridge.end, []
    monkeypatch.setattr(bridge, "end", lambda root, **kw: calls.append(kw) or real_end(root, **kw))
    passed, lines, folder = bridge.run_script(root, path)
    # run_script ends only its own test, never an older stopped test.
    assert calls == [{"find_stopped": False}]
    assert passed, lines
    assert lines[1:] == ["Turns: 3 of 3 messages", "Audit: exit 0", lines[3], "PASS"]
    # The output gives no reply: the evaluation reads the records.
    assert not any("Toy shop:" in line for line in lines)
    turns = relay_turns(folder)
    assert [(t["harness"], t["said"]) for t in turns] == [("script", m) for m in SCRIPT]
    assert (folder / f"script.{form}").read_bytes() == path.read_bytes()
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["entry_name"] is None
    assert manifest["script"] == {
        "source": str(path.resolve()),
        "file": f"script.{form}",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    assert seal.verify(folder)["intact"]
    assert not kit.is_on(root)
    prompt = evaluation.prompt(folder)
    assert prompt.startswith("This test is scripted.")
    assert manifest["script"]["sha256"] in prompt
    # A changed relay row gives script_mismatch.
    rows = [json.loads(x) for x in (folder / "relay.jsonl").read_text().splitlines() if x]
    rows[1] = {**rows[1], "said": "Return order #4472, please.  "}
    rows[1]["said_sha256"] = hashlib.sha256(rows[1]["said"].encode()).hexdigest()
    changed = tmp_path / "changed.jsonl"
    changed.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    report = audit(folder / "tap.jsonl", changed, folder / f"script.{form}")
    assert [b.kind for b in report.breaks] == ["altered_input", "script_mismatch"]


def test_run_script_starts_the_named_entry(tmp_path: Path, homes: tuple) -> None:
    app = tmp_path / "app.py"
    app.write_text(ECHO_APP)
    root = project(tmp_path, [sys.executable, str(tmp_path / "not-the-app.py")])
    conf = root / ".nookku" / "config.json"
    replay = [sys.executable, str(app)]
    conf.write_text(json.dumps({**json.loads(conf.read_text()), "entries": {"replay": replay}}))
    path = write_script(tmp_path / "turns.jsonl", "jsonl", SCRIPT[:1])
    passed, lines, folder = bridge.run_script(root, path, "replay")
    assert passed, lines
    manifest = json.loads((folder / "manifest.json").read_text())
    assert (manifest["entry_name"], manifest["entry"]) == ("replay", replay)
    assert "The entry is replay: " in evaluation.prompt(folder)


@pytest.mark.parametrize(
    "entry, text, error",
    [
        ("replay", '{"said": "Hi"}\n', "has no entry 'replay' in 'entries'. The names: none."),
        (None, "[]", "the script has no message"),
        (None, '{"said": "Hi", "x": 1}\n', 'line 1: a row must be {"said": "..."}'),
    ],
)
def test_run_script_starts_no_test_for_a_bad_entry_or_script(
    tmp_path: Path, homes: tuple, entry: str | None, text: str, error: str
) -> None:
    app = tmp_path / "app.py"
    app.write_text(ECHO_APP)
    root = project(tmp_path, [sys.executable, str(app)])
    path = tmp_path / "turns.jsonl"
    path.write_text(text)
    with pytest.raises(bridge.BridgeError) as info:
        bridge.run_script(root, path, entry)
    assert error in str(info.value)
    assert not (root / ".nookku" / "tests").exists()


ERROR_APP = """
import json, sys
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    if "fail" in request["message"]:
        out = {"v": 1, "id": request["id"], "error": "the toy shop is closed"}
    else:
        out = {"v": 1, "id": request["id"], "reply": "Toy shop: " + request["message"]}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_run_script_stops_at_a_turn_with_no_reply(tmp_path: Path, homes: tuple) -> None:
    app = tmp_path / "app.py"
    app.write_text(ERROR_APP)
    root = project(tmp_path, [sys.executable, str(app)])
    path = write_script(tmp_path / "turns.jsonl", "jsonl", ["Hi", "please fail", "Thanks"])
    passed, lines, folder = bridge.run_script(root, path)
    assert not passed
    assert lines[1] == "Turns: 2 of 3 messages"
    assert [t["ok"] for t in relay_turns(folder)] == [True, False]
    assert any(line.startswith("FAIL: script_mismatch break") for line in lines), lines
    assert "FAIL: The entry sent no reply to message 2 of the script." in lines


def test_run_script_fails_when_the_last_message_gets_no_reply(tmp_path: Path, homes: tuple) -> None:
    app = tmp_path / "app.py"
    app.write_text(ERROR_APP)
    root = project(tmp_path, [sys.executable, str(app)])
    path = write_script(tmp_path / "turns.jsonl", "jsonl", ["Hi", "please fail"])
    passed, lines, _ = bridge.run_script(root, path)
    assert not passed
    assert lines[1] == "Turns: 2 of 2 messages"
    assert lines[-1] == "FAIL: The entry sent no reply to message 2 of the script.", lines


def test_the_cli_runs_a_script_and_prints_the_evaluation_prompt(
    tmp_path: Path, homes: tuple, capsys: pytest.CaptureFixture[str]
) -> None:
    app = tmp_path / "app.py"
    app.write_text(ECHO_APP)
    root = project(tmp_path, [sys.executable, str(app)])
    path = write_script(tmp_path / "turns.jsonl", "jsonl", SCRIPT)
    assert main(["run", "--script", str(path), "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Turns: 3 of 3 messages" in out and "This test is scripted." in out
    assert main(["run", "--script", str(path), "--root", str(root), "--no-evaluate"]) == 0
    assert "This test is scripted." not in capsys.readouterr().out
    assert main(["run", "--script", str(path), "--root", str(root), "--entry", "x"]) == 1
    assert "has no entry 'x'" in capsys.readouterr().out


def test_the_mcp_tool_runs_a_script_only_if_the_policy_lets_the_model(
    tmp_path: Path, homes: tuple
) -> None:
    app = tmp_path / "app.py"
    app.write_text(ECHO_APP)
    root = project(tmp_path, [sys.executable, str(app)])
    write_script(root / "turns.jsonl", "jsonl", SCRIPT[:1])
    refused = mcp.call(root, "run_script", {"path": "turns.jsonl"})
    assert refused["isError"] is True
    assert "only a person runs a scripted test" in refused["content"][0]["text"]
    assert not (root / ".nookku" / "tests").exists()
    policy.set_key(root, "scripts", "model")
    outside = write_script(tmp_path / "outside.jsonl", "jsonl", SCRIPT[:1])
    (root / "link.jsonl").symlink_to(outside)
    for name in (str(outside), "../outside.jsonl", "link.jsonl"):
        away = mcp.call(root, "run_script", {"path": name})
        assert "the script file must be in the project folder" in away["content"][0]["text"]
    assert not (root / ".nookku" / "tests").exists()
    result = mcp.call(root, "run_script", {"path": "turns.jsonl"})
    text = result["content"][0]["text"]
    assert "isError" not in result, text
    assert "Turns: 1 of 1 messages" in text and "This test is scripted." in text
    (root / ".nookku" / "policy.json").write_text("{")
    broken = mcp.call(root, "run_script", {"path": "turns.jsonl"})
    assert "the policy file is not valid" in broken["content"][0]["text"]

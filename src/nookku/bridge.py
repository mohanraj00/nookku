"""Tests (SPEC.md section 7): start the entry through the tap, relay to it, then end and collect."""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nookku import (
    __version__,
    backend,
    db_proxy,
    discovery,
    mcp_proxy,
    model_api,
    otlp,
    policy,
    script,
    seal,
    trace,
)
from nookku.audit import audit
from nookku.config import CHECK_MESSAGE as CHECK_MESSAGE
from nookku.config import FILE as CONFIG_FILE
from nookku.config import HARNESSES as HARNESSES
from nookku.config import NO_ENTRY as NO_ENTRY
from nookku.config import STATE_DIR as STATE_DIR
from nookku.config import ConfigError, read_config
from nookku.config import has_entry as has_entry
from nookku.record import RecordError, Writer, turns

# The state functions are in nookku.state. These names keep the imports of bridge working.
from nookku.state import TIMEOUT as TIMEOUT
from nookku.state import TOKEN_KEY, lock_sends, manifest_of
from nookku.state import _children as _children
from nookku.state import _started as _started
from nookku.state import alive as alive
from nookku.state import current as current
from nookku.state import history as history
from nookku.state import is_bridge as is_bridge
from nookku.state import latest_test as latest_test
from nookku.state import mark as _mark
from nookku.state import process_start as process_start
from nookku.state import send as send
from nookku.state import state as state
from nookku.stdio import STRAY_HINT, Agent, StdioTap, start_in_thread
from nookku.stdio import TIMEOUT as AGENT_TIMEOUT

# The harness session that ends a test, for the bridge (SPEC.md section 7.2).
ENDING = "ending.json"
# The variables that give the entry its test folder and its test id (#145).
TEST_DIR = "NOOKKU_TEST_DIR"
TEST_ID = "NOOKKU_TEST_ID"
POLL = 0.5
# The harness of the one turn of `nookku check`. A test with only such turns gets no evaluation.
CHECK_HARNESS = "nookku-check"
# Files in the state folder that a test writes or that switch a mode. They are not configuration.
NOT_CONFIG = {"tests", "current.json", "mode", "relay.jsonl", "tap.jsonl", ENDING}
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", ".git"}
# The check names the first stray lines, and gives the count of all of them.
STRAY_SHOWN = 3
# For each break class of the audit (SPEC.md section 3.3): what occurred in the check, and the fix.
ONE_SENDER = "Make sure that only one relay sends messages to the tap."
BREAK_FIX = {
    "altered_input": f"The agent received a different message. {ONE_SENDER}",
    "injected_input": f"The agent received a message that the check did not send. {ONE_SENDER}",
    "duplicate_send": f"The agent received the check message more than one time. {ONE_SENDER}",
    "out_of_order": f"The agent received the messages in a different order. {ONE_SENDER}",
    "not_delivered": "The agent did not receive the check message. Read bridge.log and app.log.",
    "altered_reply": "The check got a different reply from the agent. Read bridge.log.",
    "unshown_reply": "The check did not get the reply of the agent. Read bridge.log.",
    "script_mismatch": "A turn of the relay record is not the script message at its position. "
    "Read relay.jsonl and the script copy in the test folder.",
}


class BridgeError(Exception):
    """A test cannot start or end."""


@dataclass
class TestConfig:
    entry: list[str]
    models: list[str]
    # False stops the OTLP receiver (SPEC.md section 7.5).
    otel: bool = True
    # Each key of the policy file with its value (SPEC.md section 7.9).
    policy: dict[str, Any] = field(default_factory=dict)
    # The one message of nookku check (SPEC.md section 7.1).
    check_message: str = CHECK_MESSAGE
    # The keys of the trace checks. The manifest records them (SPEC.md section 7.2).
    trace: dict[str, Any] = field(default_factory=dict)
    # The name of the entry in entries, or None for the default entry (SPEC.md section 7.10).
    entry_name: str | None = None


def load_config(root: Path, entry_name: str | None = None) -> TestConfig:
    """The test keys of `.nookku/config.json`. Raise BridgeError if the file breaks the
    rule of `config.read_config`, if there is no entry, or if the policy file is not valid. Also
    return the policy keys (SPEC.md section 7.9). With entry_name, the entry is that entry of
    entries, and an unknown name raises BridgeError (SPEC.md section 7.10)."""
    try:
        data = read_config(root)
        rules = policy.read(root)
    except (ConfigError, policy.PolicyError) as e:
        raise BridgeError(str(e)) from None
    entry, models = data.get("entry") or [], data.get("models") or []
    if entry_name is not None:
        entries = data.get("entries") or {}
        if entry_name not in entries:
            names = ", ".join(sorted(entries)) or "none"
            raise BridgeError(
                f"{CONFIG_FILE} has no entry {entry_name!r} in 'entries'. The names: {names}."
            )
        entry = entries[entry_name]
    if not (isinstance(entry, list) and entry and all(isinstance(a, str) for a in entry)):
        raise BridgeError(NO_ENTRY)
    otel = data.get("otel", True) is not False
    message = data.get("check_message", CHECK_MESSAGE)
    keys = {k: data.get(k, default) for k, default in trace.TRACE_KEYS.items()}
    return TestConfig(entry, models, otel, rules, message, keys, entry_name)


def egress_proxies(
    answer: dict[str, Any], environ: dict[str, str] | os._Environ[str]
) -> tuple[list[backend.Backend], list[backend.Backend]]:
    """The backend proxies and the model API proxies of a discovery answer (SPEC.md section
    7.11). Raise BridgeError if the URL of a model API is not valid."""
    try:
        apis = model_api.backends(answer["model_apis"], environ)
        db_proxy.databases(answer["databases"], environ)
    except ValueError as e:
        raise BridgeError(f"the egress answer: {e}") from None
    return backend.from_answer(answer["backends"]), apis


def _tail(path: Path, n: int = 20) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


# The time that start waits for the bridge (#164).
START_WAIT = 30.0
# The time that the bridge waits for an entry that exits at start. An entry that exits in this
# time stops the test. The bridge does not wait the full time for an entry that exits (#300).
START_CHECK = 0.3
# The time that end waits for the bridge to stop, before it sends SIGKILL.
END_WAIT = 120.0


def start(
    root: Path,
    tester_session: str | None = None,
    wait: float = START_WAIT,
    entry_name: str | None = None,
    script_path: Path | None = None,
    check: bool = False,
    egress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start a test in a background bridge process. Return the contents of current.json.

    The test uses the egress answer `egress`, else the pending answer of `nookku register`,
    which the start then removes (SPEC.md section 7.11). With no answer, no test starts.

    With script_path, the test is scripted: the script is read before the test starts, and its
    bytes are copied into the test folder, so that the seal covers them (SPEC.md section 7.10).
    With check, the test is a test of `nookku check`: the first manifest records this, so that no
    evaluation starts, also if the check stops before its turn (SPEC.md section 9.1).
    """
    load_config(root, entry_name)
    copy: tuple[str, bytes] | None = None
    if script_path is not None:
        try:
            _, form, data = script.read(script_path)
        except script.ScriptError as e:
            raise BridgeError(str(e)) from None
        copy = (script.COPIES[form], data)
    cur = current(root)
    if cur is not None:
        raise BridgeError(f"test {cur['test']} runs already. End it first.")
    from nookku import claude_gate, codex_gate

    both = claude_gate.problem(root)
    if both is not None:
        raise BridgeError(both)
    gate = codex_gate.check(root)
    if gate["problems"]:
        raise BridgeError(codex_gate.refusal(gate))
    pending = egress is None
    egress = discovery.pending(root) if egress is None else egress
    if egress is None:
        raise BridgeError(discovery.no_answer())
    # A given answer gets the same check as the pending answer.
    try:
        egress = {"registered": egress["registered"], "answer": discovery.parse(egress["answer"])}
    except (discovery.AnswerError, KeyError, TypeError) as e:
        raise BridgeError(f"the egress answer: {e}") from None
    egress_proxies(egress["answer"], os.environ)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    test = f"{stamp}-{secrets.token_hex(2)}"
    folder = state(root) / "tests" / test
    folder.mkdir(parents=True)
    _mark(state(root))
    # The bridge puts the result in the manifest, and removes this file.
    _write_json(folder / GATE_FILE, gate)
    _write_json(folder / EGRESS_FILE, egress)
    argv = [sys.executable, "-m", "nookku", "bridge", "--root", str(root), "--test", test]
    if tester_session:
        argv += ["--tester-session", tester_session]
    if entry_name is not None:
        argv += ["--entry-name", entry_name]
    if check:
        argv.append("--check")
    if copy is not None and script_path is not None:
        (folder / copy[0]).write_bytes(copy[1])
        argv += ["--script-source", str(script_path.resolve())]
    with (folder / "bridge.log").open("ab") as log:
        proc = subprocess.Popen(
            argv,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    _children[proc.pid] = proc
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        cur = current(root)
        if cur is not None and cur.get("test") == test:
            if pending:
                discovery.take(root)
            return cur
        if proc.poll() is not None:
            raise BridgeError(f"the test did not start:\n{_tail(folder / 'bridge.log')}")
        time.sleep(0.1)
    proc.terminate()
    raise BridgeError(f"the test did not start in {wait:g} s:\n{_tail(folder / 'bridge.log')}")


def stopped(root: Path) -> Path | None:
    """The folder of the latest test whose bridge stopped with no end, else None (#164).

    The caller makes sure that no test runs. A test that started less than START_WAIT ago can
    still be in its start, so it is not stopped. An older stopped test stays stopped after a new
    test, so this looks at each test folder, not only at the latest one."""
    tests = state(root) / "tests"
    found: list[tuple[float, str, Path]] = []
    for folder in tests.iterdir() if tests.is_dir() else []:
        try:
            manifest = json.loads((folder / "manifest.json").read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict) or manifest.get("ended") is not None:
            continue
        started = manifest.get("started")
        if isinstance(started, (int, float)) and time.time() - started >= START_WAIT:
            found.append((float(started), folder.name, folder))
    return max(found, default=(0.0, "", None))[2]


def _group(pid: int) -> bool:
    """True if a process group with the id `pid` has a process in it."""
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _members(pgid: int) -> list[int]:
    """The pids of the processes in the process group `pgid`, from ps."""
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,pgid="], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return []
    rows = [line.split() for line in out.splitlines()]
    return [int(r[0]) for r in rows if len(r) == 2 and r[1] == str(pgid) and r[0].isdigit()]


def _of_test(pid: int, test: str) -> bool:
    """True if the environment of `pid` gives the id of this test (TEST_ID). Only Linux lets
    nookku read it (/proc/<pid>/environ), so on other systems this is False (fail closed)."""
    try:
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False
    return f"{TEST_ID}={test}".encode() in env


def _stop_entry(manifest: dict[str, Any], grace: float = 5.0) -> list[int]:
    """Stop the process group of the entry of a stopped bridge, if a process of it still runs.
    Return the pids of the group that got no signal, because nookku cannot prove that they are
    processes of the test.

    The entry starts in its own process group, so its pid is the group id. The pid and its start
    time identify the entry, as for the bridge (SPEC.md section 7.2). If the entry stopped, other
    processes can have the group id, also after the OS gave the pid to a new process. Then each
    of them must have the id of this test in its environment, else no process gets a signal."""
    pid, start = manifest.get("entry_pid"), manifest.get("entry_pid_start")
    if type(pid) is not int or pid <= 0 or not isinstance(start, str):
        return []
    if alive(pid):
        if process_start(pid) != start:
            return []
    else:
        members = _members(pid)
        unproven = [m for m in members if not _of_test(m, str(manifest.get("test")))]
        if unproven or not members:
            return unproven
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(OSError):
            os.killpg(pid, sig)
        deadline = time.monotonic() + grace
        while _group(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
    return []


def finish_stopped(folder: Path) -> dict[str, Any]:
    """Finish the folder of a test whose bridge stopped with no end (SPEC.md section 7.2).
    Stop the entry and mark the test as killed. Then write the trace, the audit and the seal from
    the records."""
    path = folder / "manifest.json"
    manifest: dict[str, Any] = json.loads(path.read_text())

    def log(message: str) -> None:
        with (folder / "bridge.log").open("a", encoding="utf-8") as f:
            f.write(f"nookku end: {message}\n")

    unproven = _stop_entry(manifest)
    if unproven:
        pids = ", ".join(map(str, unproven))
        warning = (
            f"warning: the processes {pids} have the process group id of the entry of test "
            f"{manifest.get('test')}, but nookku cannot prove that they belong to the test, so "
            "it sent them no signal. If they belong to the test, stop them, then run: nookku "
            f"verify {manifest.get('test')}"
        )
        log(warning)
        print(f"nookku: {warning}", file=sys.stderr)
    # Wait for a send of the chat page, and keep each later send out until the seal (SPEC.md 5).
    # The test folder is <root>/.nookku/tests/<test>.
    sends = lock_sends(folder.parents[2])
    try:
        manifest.update(ended=time.time(), killed=True)
        _write_json(path, manifest)
        _collect(folder, script.copy_in(folder), log)
    finally:
        os.close(sends)
    return manifest


def end(
    root: Path,
    wait: float = END_WAIT,
    tester_session: str | None = None,
    find_stopped: bool = True,
    test: str | None = None,
) -> dict[str, Any] | None:
    """Stop the running test and wait for the bridge to collect. Return the manifest.

    If no test runs, but the bridge of a test stopped with no end, finish that test. A caller
    that ends only its own test turns this off with `find_stopped=False`. If `test` is set, end
    the running test only if it has this id, else return None (the "End test" button, #391).

    `tester_session` is the harness session that ends the test. It is not a session of the app,
    also if it starts after the last turn."""
    cur = current(root)
    if cur is None:
        folder = stopped(root) if find_stopped else None
        return None if folder is None else finish_stopped(folder)
    if test is not None and cur["test"] != test:
        return None
    if tester_session:
        _write_json(state(root) / ENDING, {"test": cur["test"], "tester_session": tester_session})
    pid = cur["pid"]
    # The OS can give the pid to a new process after the bridge stops. Check the start time again
    # before each signal and in the wait, so that no signal goes to that process.
    if is_bridge(cur):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait
    while is_bridge(cur) and time.monotonic() < deadline:
        time.sleep(0.2)
    killed = is_bridge(cur)
    if killed:
        os.kill(pid, signal.SIGKILL)
        (state(root) / "current.json").unlink(missing_ok=True)
    folder = Path(cur["dir"])
    data = manifest_of(folder)
    if data is None:
        return {"test": cur["test"], "dir": cur["dir"]}
    # The bridge writes `ended` before the trace, the audit and the seal. It can hang in them.
    unsealed = not (folder / "audit.json").exists() or not (folder / seal.SEAL).exists()
    if killed and (data.get("ended") is None or unsealed):
        return finish_stopped(folder)
    return data


GATE_FILE = "codex-gate.json"
# start writes the egress answer here, and the bridge moves it into the manifest.
EGRESS_FILE = "egress-answer.json"


def _start_gate(folder: Path) -> dict[str, Any] | None:
    """The gate result that start wrote, or None if start did not write one."""
    path = folder / GATE_FILE
    try:
        gate: dict[str, Any] = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    return gate


def _start_egress(folder: Path) -> dict[str, Any] | None:
    """The egress answer that start wrote, or None. The bridge checks it again."""
    path = folder / EGRESS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        answer = discovery.parse(data["answer"])
        registered = data["registered"]
    except (OSError, ValueError, TypeError, KeyError):
        return None
    path.unlink(missing_ok=True)
    return {"registered": registered, "answer": answer}


def egress_text(folder: Path) -> str:
    """The lines of the start text that name each egress part of the test (SPEC.md 7.11)."""
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        answer = discovery.parse(manifest["egress"]["answer"])
    except (OSError, ValueError, TypeError, KeyError):
        return "The manifest has no valid egress answer. See bridge.log in the test folder."
    text = "Egress of the agent:\n" + "\n".join(discovery.lines(answer))
    if discovery.unseen(answer):
        text += (
            "\nNo proxy sees a part with no proxy. The report recommends a way to see its calls, "
            "for example logs or OpenTelemetry spans."
        )
    return text


def gate_changed(manifest: dict[str, Any]) -> str | None:
    """Why the Codex hooks of the test are not the hooks that start checked, or None."""
    gate = manifest.get("codex_gate") or {}
    first, last = gate.get("start"), gate.get("end")
    if not first or not last or not first.get("codex"):
        return None
    if last.get("problems"):
        return "; ".join(last["problems"])
    if first.get("hooks") != last.get("hooks"):
        return "the hooks at the end differ from the hooks at the start"
    return None


def summary(manifest: dict[str, Any]) -> str:
    folder = Path(manifest.get("dir", ""))
    sessions = manifest.get("model_sessions", [])
    try:
        count = f"{len(turns(folder / 'relay.jsonl', missing_ok=True))} turns"
    except RecordError as e:
        count = f"an invalid relay record ({e})"
    lines = [
        f"Test {manifest.get('test')} ended: {count}, {len(sessions)} model sessions.",
        f"Folder: {folder}",
    ]
    if manifest.get("ended") is None:
        lines.append("The bridge did not finish its collection. See bridge.log in the folder.")
    if manifest.get("killed"):
        lines.append(
            "The bridge stopped before the end, so end wrote the audit and the seal from the "
            "records. The test has no model sessions. See bridge.log in the folder."
        )
    changed = gate_changed(manifest)
    if changed:
        lines.append(
            "The Codex hooks changed during the test, so Codex can have skipped a hook and given "
            f"a message to the model: {changed}. Do not trust this test."
        )
    with contextlib.suppress(OSError, ValueError, KeyError):
        lines.append(trace.summary(json.loads((folder / "findings.json").read_text())))
    lines.append(
        f"Audit: nookku audit --tap {folder / 'tap.jsonl'} --relay {folder / 'relay.jsonl'}"
    )
    return "\n".join(lines)


# The bridge process ------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def config_hashes(root: Path) -> dict[str, str]:
    out = {}
    base = state(root)
    for dirpath, dirnames, filenames in os.walk(base):
        rel = Path(dirpath).relative_to(base)
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not (rel == Path(".") and d in NOT_CONFIG)
        )
        for name in sorted(filenames):
            if rel == Path(".") and (name in NOT_CONFIG or name.endswith(".log")):
                continue
            out[str(rel / name)] = _sha256(Path(dirpath) / name)
    return out


def _version(cmd: str) -> str | None:
    if shutil.which(cmd) is None:
        return None
    try:
        p = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() or None


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def descendants(pid: int) -> set[int]:
    """The process and each process below it, from `ps`."""
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {pid}
    children: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = {pid}, [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


class ClaudeWatcher(threading.Thread):
    """Identify the Claude Code sessions that the entry's processes run (SPEC.md section 7.3)."""

    def __init__(self, pid: int, writer: Writer, base: Path | None = None) -> None:
        super().__init__(daemon=True)
        self.pid, self.writer = pid, writer
        self.base = base or claude_home() / "sessions"
        self.found: dict[str, int] = {}
        self._checked: set[tuple[int, str]] = set()
        self._mtimes: dict[str, int] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def poll(self) -> None:
        with self._lock:
            try:
                files = list(self.base.glob("*.json"))
            except OSError:
                return
            todo = []
            for f in files:
                try:
                    mtime = f.stat().st_mtime_ns
                except OSError:
                    continue
                if self._mtimes.get(f.name) == mtime:
                    continue
                try:
                    data = json.loads(f.read_text())
                except (OSError, ValueError):
                    continue  # a file in the middle of a write: read it at the next poll
                self._mtimes[f.name] = mtime
                pid, sid = data.get("pid"), data.get("sessionId")
                if (
                    isinstance(pid, int)
                    and isinstance(sid, str)
                    and (pid, sid) not in self._checked
                ):
                    todo.append((pid, sid))
            if not todo:
                return
            tree = descendants(self.pid)
            for pid, sid in todo:
                self._checked.add((pid, sid))
                if pid in tree and sid not in self.found:
                    self.found[sid] = pid
                    self.writer.append(
                        {
                            "type": "model_session",
                            "harness": "claude-code",
                            "session": sid,
                            "pid": pid,
                            "inferred": False,
                        }
                    )

    def run(self) -> None:
        while not self._stop.wait(POLL):
            self.poll()

    def stop(self) -> None:
        self._stop.set()


def _inside(path: str, root: Path) -> bool:
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return False
    return p == root or root in p.parents


def codex_sessions(
    root: Path, started: float, ended: float, exclude: set[str], base: Path | None = None
) -> list[tuple[Path, dict[str, Any]]]:
    """Rollout files that changed during the test, ran in the project and are not the tester's."""
    base = base or codex_home() / "sessions"
    root = root.resolve()
    day = datetime.date.fromtimestamp(started) - datetime.timedelta(days=1)
    last = datetime.date.fromtimestamp(ended) + datetime.timedelta(days=1)
    out = []
    while day <= last:
        folder = base / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
        day += datetime.timedelta(days=1)
        for f in sorted(folder.glob("rollout-*.jsonl")) if folder.is_dir() else []:
            try:
                if f.stat().st_mtime < started:
                    continue
                with f.open(encoding="utf-8") as fh:
                    meta = json.loads(fh.readline())
            except (OSError, ValueError):
                continue
            payload = meta.get("payload") if isinstance(meta, dict) else None
            if meta.get("type") != "session_meta" or not isinstance(payload, dict):
                continue
            sid, cwd = payload.get("id"), payload.get("cwd")
            if not (isinstance(sid, str) and isinstance(cwd, str)) or sid in exclude:
                continue
            if _inside(cwd, root):
                out.append((f, payload))
    return out


def _exits_at_start(proc: subprocess.Popen[bytes], wait: float = START_CHECK) -> bool:
    """True if the entry exits in `wait` seconds. The function returns when the entry exits."""
    try:
        proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        return False
    return True


def _log(message: str) -> None:
    """One progress line in bridge.log, so that a test that does not start shows its last step."""
    print(f"nookku bridge: {message}", file=sys.stderr, flush=True)


def _write_json(path: Path, data: dict[str, Any], mode: int | None = None) -> None:
    """Write the file in one step. With `mode`, only the file has that mode, from its start."""
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    if mode is None:
        tmp.write_text(text)
    else:
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "w") as f:
            f.write(text)
    tmp.replace(path)


def _start_failed(folder: Path, manifest: dict[str, Any]) -> int:
    """Mark a test whose entry did not start, and return the exit code of the bridge.

    The manifest gets `ended` and `start_failed: true` (SPEC.md section 7.2). Thus the test is
    not a stopped test, so `end` does not finish it, and it gets no evaluation."""
    manifest.update(ended=time.time(), start_failed=True)
    _write_json(folder / "manifest.json", manifest)
    return 1


def run(
    root: Path,
    test: str,
    tester_session: str | None,
    timeout: float = AGENT_TIMEOUT,
    entry_name: str | None = None,
    script_source: str | None = None,
    check: bool = False,
) -> int:
    """The bridge process: run the tap and the entry until SIGTERM, then collect."""
    root = root.resolve()
    folder = state(root) / "tests" / test
    config = load_config(root, entry_name)
    copy = script.copy_in(folder)
    pid_start = process_start(os.getpid())
    if pid_start is None:
        print("nookku bridge: cannot read the start time of its process", file=sys.stderr)
        return 1
    egress = _start_egress(folder)
    if egress is None:
        print("nookku bridge: the test folder has no valid egress answer", file=sys.stderr)
        return 1
    try:
        backends, model_apis = egress_proxies(egress["answer"], os.environ)
    except BridgeError as e:
        print(f"nookku bridge: {e}", file=sys.stderr)
        return 1
    started = time.time()
    manifest: dict[str, Any] = {
        "v": "0.2",
        "test": test,
        "dir": str(folder),
        "root": str(root),
        "entry": config.entry,
        "entry_name": entry_name,
        "script": None
        if copy is None
        else {
            "source": script_source,
            "file": copy.name,
            "sha256": script.sha256(copy.read_bytes()),
        },
        "models": config.models,
        "started": started,
        "ended": None,
        "versions": {"nookku": __version__, "claude-code": None, "codex": None},
        "config_sha256": config_hashes(root),
        "policy": config.policy,
        "trace": config.trace,
        "tester_sessions": [tester_session] if tester_session else [],
        "model_sessions": [],
        "codex_gate": {"start": _start_gate(folder), "end": None},
        "check": check,
        # The accepted answer, the parts that no proxy sees, and the URL of each proxy.
        "egress": {
            **egress,
            "unseen": discovery.unseen(egress["answer"]),
            "proxies": {},
            "receiver": None,
        },
    }
    _write_json(folder / "manifest.json", manifest)
    _log("manifest written")
    # A `--version` call can take seconds. The test must not wait for it to start.
    versions: dict[str, str | None] = {}
    lookup = threading.Thread(
        target=lambda: versions.update(claude=_version("claude"), codex=_version("codex")),
        daemon=True,
    )
    lookup.start()

    receiver = otlp.Receiver(("127.0.0.1", 0), folder / otlp.FILE) if config.otel else None
    env = otlp.environment(receiver.url) if receiver else {}
    if receiver:
        start_in_thread(receiver)
        _log(f"OTLP receiver on {receiver.url}")
        # The coverage check skips the calls to the receiver (SPEC.md section 8.6).
        manifest["egress"]["receiver"] = receiver.url
    proxies = backend.Proxies(backends, folder / backend.FILE)
    env.update(proxies.start())
    for p in proxies.proxies:
        _log(f"backend {p.backend.name}: {p.backend.env}={p.url} -> {p.backend.url}")
    apis = backend.Proxies(model_apis, folder / model_api.FILE, model_api.ModelProxy)
    env.update(apis.start())
    # The app can keep its state in the test folder, for example in app-state/, so that the seal
    # covers it (SPEC.md section 6.1).
    env.update({TEST_DIR: str(folder.resolve()), TEST_ID: test})
    for p in apis.proxies:
        _log(f"model API {p.backend.name}: {p.backend.env}={p.url} -> {p.backend.url}")
    # The MCP servers that have a variable (SPEC.md section 7.12).
    servers = egress["answer"]["mcp_servers"]
    mcp = backend.Proxies(
        mcp_proxy.http_servers(servers), folder / mcp_proxy.FILE, mcp_proxy.HttpProxy
    )
    env.update(mcp.start())
    for p in mcp.proxies:
        _log(f"MCP server {p.backend.name}: {p.backend.env}={p.url} -> {p.backend.url}")
    wrappers = mcp_proxy.stdio_environment(servers, folder)
    env.update(wrappers)
    for name in wrappers:
        _log(f"MCP server wrapper: {name}")
    # The Postgres databases that have a variable (SPEC.md section 7.13). egress_proxies checked
    # each value.
    db_lock = threading.Lock()
    dbs = [
        db_proxy.Proxy(d, folder / db_proxy.FILE, db_lock)
        for d in db_proxy.databases(egress["answer"]["databases"], os.environ)
    ]
    for d in dbs:
        start_in_thread(d)
        # The log line has no value of the variable: the URL can hold a password.
        _log(f"database {d.database.name}: {d.database.env} -> {d.url}")
    env.update(db_proxy.environment(dbs, os.environ))
    every = proxies.proxies + apis.proxies + mcp.proxies
    manifest["egress"]["proxies"] = {p.backend.name: p.url for p in every}
    manifest["egress"]["proxies"].update({d.database.name: d.url for d in dbs})
    # A stdio server has no address. Its value is STDIO (SPEC.md section 7.12).
    manifest["egress"]["proxies"].update(
        {p["name"]: mcp_proxy.STDIO for p in servers if p["env"] in wrappers}
    )
    agent = Agent(config.entry, root, folder / "app.log", timeout=timeout, env=env)
    tap = StdioTap(("127.0.0.1", 0), agent, folder / "tap.jsonl")
    _log(f"tap bound to {tap.url}")
    try:
        agent.start()
    except OSError as e:
        print(f"nookku bridge: cannot start the entry {config.entry}: {e}", file=sys.stderr)
        return _start_failed(folder, manifest)
    _log(f"entry started: {config.entry}")
    assert agent.proc is not None
    if _exits_at_start(agent.proc):
        print(f"nookku bridge: the entry exited at start:\n{agent.tail()}", file=sys.stderr)
        return _start_failed(folder, manifest)
    # end can stop the entry if the bridge stops with no end (#164).
    manifest.update(entry_pid=agent.proc.pid, entry_pid_start=process_start(agent.proc.pid))
    _write_json(folder / "manifest.json", manifest)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    watcher = ClaudeWatcher(agent.proc.pid, tap.writer)
    watcher.start()
    start_in_thread(tap)
    _write_json(
        state(root) / "current.json",
        {
            "v": 1,
            "test": test,
            "dir": str(folder),
            "tap_url": tap.url,
            # A relay or a page server sends this token with each message (SPEC.md 4.2).
            TOKEN_KEY: tap.token,
            "pid": os.getpid(),
            "pid_start": pid_start,
        },
        # The file holds the tap token, so only the owner can read it.
        mode=0o600,
    )
    _log(f"test {test} on {tap.url}")
    stop.wait()

    _log("ending")
    # Wait for a send of the chat page, and keep each later send out until the seal (SPEC.md 5).
    sends = lock_sends(root)
    tap.shutdown()
    watcher.stop()
    watcher.poll()
    agent.stop()
    # A line after the last reply waits in the queue. It is a stray line too (SPEC.md 4.2).
    tap.record_rest()
    if receiver:
        # The app can export its last spans when it exits. Then no request comes after it.
        receiver.quiet()
        receiver.shutdown()
        receiver.server_close()
    proxies.stop()
    apis.stop()
    mcp.stop()
    mcp_proxy.close(folder)
    for d in dbs:
        d.stop()
    ended = time.time()
    relay = folder / "relay.jsonl"
    tester = set(manifest["tester_sessions"])
    ending = state(root) / ENDING
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(ending.read_text())
        if data.get("test") == test and isinstance(data.get("tester_session"), str):
            tester.add(data["tester_session"])
    ending.unlink(missing_ok=True)
    infer = True
    try:
        tester |= {t.session for t in turns(relay, missing_ok=True) if t.session is not None}
    except RecordError as e:  # the test must still end
        # Without the tester sessions, an inferred Codex session can be a tester session.
        infer = False
        _log(f"the relay record is invalid, so the test infers no Codex session: {e}")
    sessions: list[dict[str, Any]] = []
    copies = folder / "sessions"
    for sid, pid in watcher.found.items():
        files = sorted((claude_home() / "projects").glob(f"*/{sid}.jsonl"))
        for f in files:
            (copies / "claude-code").mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, copies / "claude-code" / f.name)
        sessions.append(
            {
                "harness": "claude-code",
                "session": sid,
                "pid": pid,
                "inferred": False,
                "file": f"sessions/claude-code/{sid}.jsonl" if files else None,
            }
        )
    for f, meta in codex_sessions(root, started, ended, tester) if infer else []:
        row: dict[str, Any] = {
            "type": "model_session",
            "harness": "codex",
            "session": meta["id"],
            "pid": None,
            "inferred": True,
        }
        if isinstance(meta.get("originator"), str):
            row["originator"] = meta["originator"]
        tap.writer.append(row)
        (copies / "codex").mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, copies / "codex" / f.name)
        sessions.append(
            {**{k: v for k, v in row.items() if k != "type"}, "file": f"sessions/codex/{f.name}"}
        )
    lookup.join(timeout=40)
    manifest["versions"].update(
        {"claude-code": versions.get("claude"), "codex": versions.get("codex")}
    )
    manifest.update(ended=ended, tester_sessions=sorted(tester), model_sessions=sessions)
    try:
        from nookku import codex_gate

        manifest["codex_gate"]["end"] = codex_gate.check(root)
    except Exception as e:  # the test must still end
        manifest["codex_gate"]["end"] = {"codex": None, "hooks": [], "problems": [repr(e)]}
    _write_json(folder / "manifest.json", manifest)
    _collect(folder, copy)
    (state(root) / "current.json").unlink(missing_ok=True)
    os.close(sends)
    tap.server_close()
    _log(f"test {test} ended")
    return 0


def _collect(folder: Path, copy: Path | None, log: Callable[[str], None] | None = None) -> None:
    """Write the trace, the audit and the seal of a test folder (SPEC.md section 7.2, steps 5
    to 7). Each step writes its error to the log, and the test still ends."""
    log = log or _log
    try:
        log(trace.summary(trace.build(folder)))
    except Exception as e:
        log(f"the trace failed: {e!r}")
    try:
        report = audit(folder / "tap.jsonl", folder / "relay.jsonl", copy).as_dict()
        _write_json(folder / "audit.json", report)
    except Exception as e:
        log(f"the audit failed: {e!r}")
    try:
        error = seal.write(folder)
        if error:
            log(f"the seal has no copy outside the project: {error}")
    except Exception as e:
        log(f"the seal failed: {e!r}")


def audit_problems(folder: Path) -> tuple[int | None, list[str]]:
    """Read audit.json of a test folder. Return (the exit code, a problem for each break or error).

    If the file is missing or invalid, the exit code is None and the check fails (fail closed).
    """
    try:
        report = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
        code, breaks, errors = report["exit"], report["breaks"], report["errors"]
        if type(code) is not int or not isinstance(breaks, list) or not isinstance(errors, list):
            raise ValueError("wrong types")
        problems = _audit_errors(errors) + [_audit_break(b) for b in breaks]
    except (OSError, ValueError, TypeError, KeyError) as e:
        why = "is missing" if isinstance(e, FileNotFoundError) else f"is not valid ({e})"
        return None, [f"The audit.json of the test {why}. Read bridge.log in the test folder."]
    if code != 0 and not problems:
        problems = [f"The audit exits with {code}. Read audit.json in the test folder."]
    return code, problems


def _is_stray(error: dict[str, Any]) -> bool:
    return bool(error["class"] == "tap_unparsed" and "a stray line on stdout" in error["detail"])


def _audit_errors(errors: list[dict[str, Any]]) -> list[str]:
    """A problem for each audit error. The errors of stray lines give one problem, at the place
    of the first one, with the count, the first lines and the fix one time (#118)."""
    stray = [e for e in errors if _is_stray(e)]
    if len(stray) < 2:
        return [_audit_error(e) for e in errors]
    first = "; ".join(e["detail"] for e in stray[:STRAY_SHOWN])
    grouped = (
        f"tap_unparsed: tap has {len(stray)} stray lines on stdout. "
        f"The first {min(len(stray), STRAY_SHOWN)}: {first}. {STRAY_HINT}"
    )
    out = []
    for e in errors:
        if e is stray[0]:
            out.append(grouped)
        elif not _is_stray(e):
            out.append(_audit_error(e))
    return out


def _hint_once(problems: list[str]) -> list[str]:
    """Keep the fix for stray lines only in the first problem that gives it (#118)."""
    hint = f" {STRAY_HINT}"
    seen, out = False, []
    for p in problems:
        if hint in p and seen:
            p = p.replace(hint, "")
        seen = seen or hint in p
        out.append(p)
    return out


def _audit_error(error: dict[str, Any]) -> str:
    kind, detail = error["class"], error["detail"]
    if _is_stray(error):
        return f"tap_unparsed: tap {detail}. {STRAY_HINT}"
    if kind == "tap_unparsed":
        fix = "Send one contract line for each request (SPEC.md section 6)."
        return f"tap_unparsed: tap {detail}. {fix}"
    return f"{kind}: the {error['record']} record: {detail}. Read bridge.log in the test folder."


def _audit_break(found: dict[str, Any]) -> str:
    kind = found["class"]
    where = f"relay line {found['relay_line'] or '-'}, tap line {found['tap_line'] or '-'}"
    fix = BREAK_FIX.get(kind, "Read audit.json in the test folder.")
    return f"{kind} break ({where}). {fix}"


def run_script(
    root: Path,
    script_path: Path,
    entry_name: str | None = None,
    egress: dict[str, Any] | None = None,
) -> tuple[bool, list[str], Path]:
    """Run a scripted test (SPEC.md section 7.10). Return (passed, the report lines, the test
    folder).

    Each message of the script goes to the entry byte for byte, as a relay row with the harness
    script. The lines name the test, the count of turns, the audit and the trace. They do not
    give the replies: the evaluation reads the records. The run stops at the first turn with no
    reply, and the audit then reports each message that was not sent."""
    try:
        messages = script.read(script_path)[0]
    except script.ScriptError as e:
        raise BridgeError(str(e)) from None
    cur = start(root, entry_name=entry_name, script_path=script_path, egress=egress)
    folder = Path(cur["dir"])
    relay = folder / "relay.jsonl"
    sent, failed = 0, None
    try:
        for said in messages:
            shown, ok = send(cur, said)
            Writer(relay).append(
                {"type": "turn", "harness": "script", "said": said, "shown": shown, "ok": ok}
            )
            sent += 1
            if not ok:
                failed = sent
                break
        time.sleep(2 * POLL)
    finally:
        manifest = end(root, find_stopped=False) or {}
    lines = [f"Test {cur['test']}: {cur['dir']}", f"Turns: {sent} of {len(messages)} messages"]
    code, problems = audit_problems(folder)
    if failed is not None:
        # The audit can be clean when the last message got no reply, so name the turn here.
        problems.insert(0, f"The entry sent no reply to message {failed} of the script.")
    lines.append(f"Audit: exit {code}" if code is not None else "Audit: no valid audit.json")
    try:
        findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))
        lines.append(trace.summary(findings))
    except (OSError, ValueError, KeyError) as e:
        lines.append(f"Trace: no valid findings.json ({e})")
    changed = gate_changed(manifest)
    if changed is not None:
        problems.append(f"The Codex hooks changed during the test: {changed}")
    lines += [f"FAIL: {p}" for p in _hint_once(problems)] or ["PASS"]
    return not problems, lines, folder


def check(root: Path) -> tuple[bool, list[str]]:
    """Run a test with one message. Return (passed, the report lines).

    The check passes only if the audit of its own test is clean (SPEC.md section 7.1)."""
    config = load_config(root)
    # A check uses the fresh answer and keeps it, so the test after the check can use it.
    egress = discovery.pending(root)
    if egress is None:
        raise BridgeError(discovery.no_answer())
    cur = start(root, check=True, egress=egress)
    relay = Path(cur["dir"]) / "relay.jsonl"
    try:
        shown, ok = send(cur, config.check_message)
        Writer(relay).append(
            {
                "type": "turn",
                "harness": CHECK_HARNESS,
                "said": config.check_message,
                "shown": shown,
                "ok": ok,
            }
        )
        time.sleep(2 * POLL)
    finally:
        manifest = end(root, find_stopped=False) or {}
    lines = [f"Test {cur['test']}: {cur['dir']}", f"Reply: {shown}"]
    problems = [] if ok else ["The entry sent no reply."]
    if not ok and STRAY_HINT in shown:
        problems = [f"The entry printed lines on stdout, but no reply line. {STRAY_HINT}"]
    code, audited = audit_problems(Path(cur["dir"]))
    lines.append(f"Audit: exit {code}" if code is not None else "Audit: no valid audit.json")
    problems += audited
    found = manifest.get("model_sessions", [])
    for harness in config.models:
        mine = [s for s in found if s["harness"] == harness]
        if not mine:
            problems.append(
                f"No {harness} model session was identified. Check that the app uses {harness}, "
                "and that it does not turn off its session files."
            )
        for s in mine:
            how = "by its directory and time" if s["inferred"] else f"by its process {s['pid']}"
            lines.append(f"{harness} session {s['session']} found {how}: {s['file']}")
            if s["file"] is None:
                problems.append(
                    f"The {harness} session {s['session']} has no session file. The app can turn "
                    "the files off (persistSession: false in the Agent SDK)."
                )
    lines += [f"FAIL: {p}" for p in _hint_once(problems)] or ["PASS"]
    return not problems, lines

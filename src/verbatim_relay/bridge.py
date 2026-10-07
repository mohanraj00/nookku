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
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verbatim_relay import __version__, backend, contract, model_api, otlp, seal, trace
from verbatim_relay.adapters import History
from verbatim_relay.audit import audit
from verbatim_relay.record import Writer
from verbatim_relay.stdio import TIMEOUT as AGENT_TIMEOUT
from verbatim_relay.stdio import Agent, StdioTap, start_in_thread

STATE_DIR = ".verbatim-relay"
# The harness session that ends a test, for the bridge (SPEC.md section 7.2).
ENDING = "ending.json"
HARNESSES = ("claude-code", "codex")
# Longer than the tap's wait for the agent, shorter than the hook deadline (kit.HOOK_DEADLINE).
TIMEOUT = 270
POLL = 0.5
# Files in the state folder that a test writes or that switch a mode. They are not configuration.
NOT_CONFIG = {"tests", "current.json", "mode", "relay.jsonl", "tap.jsonl", ENDING}
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", ".git"}
CHECK_MESSAGE = "Hello from verbatim-relay check. What can you help me with?"


class BridgeError(Exception):
    """A test cannot start or end."""


@dataclass
class TestConfig:
    entry: list[str]
    models: list[str]
    # False stops the OTLP receiver (SPEC.md section 7.5).
    otel: bool = True
    # The backend proxies (SPEC.md section 7.6).
    backends: list[backend.Backend] = field(default_factory=list)
    # The model APIs to record, with their URLs (SPEC.md section 7.7).
    model_apis: list[backend.Backend] = field(default_factory=list)


def state(root: Path) -> Path:
    return root / STATE_DIR


def load_config(root: Path) -> TestConfig:
    """The test keys of `.verbatim-relay/config.json`. Raise BridgeError if there is no entry."""
    try:
        data = json.loads((state(root) / "config.json").read_text())
    except (OSError, ValueError) as e:
        raise BridgeError(f"cannot read {STATE_DIR}/config.json: {e}") from None
    entry, models = data.get("entry") or [], data.get("models") or []
    if not (isinstance(entry, list) and entry and all(isinstance(a, str) for a in entry)):
        raise BridgeError(f"{STATE_DIR}/config.json has no 'entry' command")
    if not (isinstance(models, list) and all(m in HARNESSES for m in models)):
        raise BridgeError(f"'models' must be a list of {', '.join(HARNESSES)}")
    try:
        backends = backend.parse(data.get("backends"))
        apis = model_api.backends(model_api.parse(data.get("model_api")), os.environ)
    except ValueError as e:
        raise BridgeError(f"{STATE_DIR}/config.json: {e}") from None
    if {b.env for b in backends} & {a.env for a in apis}:
        raise BridgeError(f"{STATE_DIR}/config.json: a backend uses the variable of a model API")
    return TestConfig(entry, models, data.get("otel", True) is not False, backends, apis)


def has_entry(root: Path) -> bool:
    try:
        load_config(root)
    except BridgeError:
        return False
    return True


# Bridge processes that this process started, so that alive() can reap them.
_children: dict[int, subprocess.Popen[bytes]] = {}


def alive(pid: int) -> bool:
    if pid in _children:
        return _children[pid].poll() is None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_start(pid: int) -> str | None:
    """The start time of a process as the OS gives it, or None if it is not known.

    The OS can give the pid of a stopped process to a new process. The new process has a
    different start time, so the pid and this value together identify one process."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        pass
    else:
        # Field 2 is the command name in parentheses. It can hold spaces and ")".
        fields = stat.rsplit(")", 1)[-1].split()
        return f"proc:{fields[19]}" if len(fields) > 19 else None
    # UTC and the C locale give the same text in each shell.
    env = {**os.environ, "LC_ALL": "C", "TZ": "UTC0"}
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = " ".join(out.stdout.split())
    return f"ps:{text}" if out.returncode == 0 and text else None


def is_bridge(cur: dict[str, Any]) -> bool:
    """True if the process of `pid` runs and has the start time `pid_start` of current.json."""
    pid, start = cur.get("pid"), cur.get("pid_start")
    if type(pid) is not int or pid <= 0 or not isinstance(start, str) or not alive(pid):
        return False
    return process_start(pid) == start


def current(root: Path) -> dict[str, Any] | None:
    """The running test, from current.json. Remove the file if its bridge does not run."""
    path = state(root) / "current.json"
    try:
        cur = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(cur, dict) or not is_bridge(cur):
        path.unlink(missing_ok=True)
        return None
    return cur


def _started(folder: Path) -> float:
    """The start time in the manifest. A folder with no manifest yet is a test that starts now."""
    try:
        return float(json.loads((folder / "manifest.json").read_text())["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return float("inf")


def latest_test(root: Path) -> Path | None:
    """The test that started last. 2 test ids of the same second differ only by a random part."""
    tests = state(root) / "tests"
    dirs = [p for p in tests.iterdir() if p.is_dir()] if tests.is_dir() else []
    return max(dirs, key=lambda d: (_started(d), d.name), default=None)


def _tail(path: Path, n: int = 20) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def start(root: Path, tester_session: str | None = None, wait: float = 30.0) -> dict[str, Any]:
    """Start a test in a background bridge process. Return the contents of current.json."""
    load_config(root)
    cur = current(root)
    if cur is not None:
        raise BridgeError(f"test {cur['test']} runs already. End it first.")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    test = f"{stamp}-{secrets.token_hex(2)}"
    folder = state(root) / "tests" / test
    folder.mkdir(parents=True)
    argv = [sys.executable, "-m", "verbatim_relay", "bridge", "--root", str(root), "--test", test]
    if tester_session:
        argv += ["--tester-session", tester_session]
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
            return cur
        if proc.poll() is not None:
            raise BridgeError(f"the test did not start:\n{_tail(folder / 'bridge.log')}")
        time.sleep(0.1)
    proc.terminate()
    raise BridgeError(f"the test did not start in {wait:g} s:\n{_tail(folder / 'bridge.log')}")


def end(
    root: Path, wait: float = 120.0, tester_session: str | None = None
) -> dict[str, Any] | None:
    """Stop the running test and wait for the bridge to collect. Return the manifest.

    `tester_session` is the harness session that ends the test. It is not a session of the app,
    also if it starts after the last turn."""
    cur = current(root)
    if cur is None:
        return None
    if tester_session:
        _write_json(state(root) / ENDING, {"test": cur["test"], "tester_session": tester_session})
    pid = cur["pid"]
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    # The OS can give the pid to a new process after the bridge stops. Do not kill that process.
    if is_bridge(cur):
        os.kill(pid, signal.SIGKILL)
        (state(root) / "current.json").unlink(missing_ok=True)
    manifest = Path(cur["dir"]) / "manifest.json"
    try:
        data: dict[str, Any] = json.loads(manifest.read_text())
    except (OSError, ValueError):
        data = {"test": cur["test"], "dir": cur["dir"]}
    return data


def summary(manifest: dict[str, Any]) -> str:
    folder = Path(manifest.get("dir", ""))
    turns = _rows(folder / "relay.jsonl", "turn")
    sessions = manifest.get("model_sessions", [])
    lines = [
        f"Test {manifest.get('test')} ended: {len(turns)} turns, {len(sessions)} model sessions.",
        f"Folder: {folder}",
    ]
    if manifest.get("ended") is None:
        lines.append("The bridge did not finish its collection. See bridge.log in the folder.")
    with contextlib.suppress(OSError, ValueError, KeyError):
        lines.append(trace.summary(json.loads((folder / "findings.json").read_text())))
    lines.append(
        f"Audit: verbatim-relay audit --tap {folder / 'tap.jsonl'} --relay {folder / 'relay.jsonl'}"
    )
    return "\n".join(lines)


def _rows(path: Path, kind: str) -> list[dict[str, Any]]:
    """The rows of one type in a JSONL record. Split on \\n only: a text can hold U+2028."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [r for r in (json.loads(x) for x in text.split("\n") if x) if r.get("type") == kind]


def history(relay: Path) -> History:
    """The turns of the test that showed the agent's reply (SPEC.md section 5)."""
    return [
        (r["said"], r["shown"])
        for r in _rows(relay, "turn")
        if r.get("ok") is True and isinstance(r.get("shown"), str)
    ]


def send(cur: dict[str, Any], said: str, timeout: float = TIMEOUT) -> tuple[str, bool]:
    """Relay one message to the running test. Return (the text to show, whether it is the reply)."""
    rid = uuid.uuid4().hex
    body = contract.request(rid, cur["test"], said, history(Path(cur["dir"]) / "relay.jsonl"))
    req = urllib.request.Request(
        cur["tap_url"], data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = resp.read()
    except urllib.error.HTTPError as e:
        text = e.read()
        if e.code == 500:
            try:
                error = contract.parse_reply(text, rid)[1]
                return f"verbatim-relay: the agent sent an error:\n{error}", False
            except contract.ContractError:
                pass
        try:
            message = json.loads(text)["error"]
        except (ValueError, KeyError, TypeError):
            message = text.decode("utf-8", errors="replace")
        return f"verbatim-relay: HTTP {e.code}: {message}", False
    except (OSError, ValueError) as e:
        return f"verbatim-relay: cannot reach the tap at {cur['tap_url']}: {e}", False
    try:
        reply, _ = contract.parse_reply(out, rid)
    except contract.ContractError as e:
        return f"verbatim-relay: cannot read the reply: {e}", False
    assert reply is not None
    return reply, True


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


def _log(message: str) -> None:
    """One progress line in bridge.log, so that a test that does not start shows its last step."""
    print(f"verbatim-relay bridge: {message}", file=sys.stderr, flush=True)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)


def run(root: Path, test: str, tester_session: str | None, timeout: float = AGENT_TIMEOUT) -> int:
    """The bridge process: run the tap and the entry until SIGTERM, then collect."""
    root = root.resolve()
    folder = state(root) / "tests" / test
    config = load_config(root)
    pid_start = process_start(os.getpid())
    if pid_start is None:
        print("verbatim-relay bridge: cannot read the start time of its process", file=sys.stderr)
        return 1
    started = time.time()
    manifest: dict[str, Any] = {
        "v": "0.2",
        "test": test,
        "dir": str(folder),
        "root": str(root),
        "entry": config.entry,
        "models": config.models,
        "started": started,
        "ended": None,
        "versions": {"verbatim-relay": __version__, "claude-code": None, "codex": None},
        "config_sha256": config_hashes(root),
        "tester_sessions": [tester_session] if tester_session else [],
        "model_sessions": [],
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
    proxies = backend.Proxies(config.backends, folder / backend.FILE)
    env.update(proxies.start())
    for p in proxies.proxies:
        _log(f"backend {p.backend.name}: {p.backend.env}={p.url} -> {p.backend.url}")
    apis = backend.Proxies(config.model_apis, folder / model_api.FILE, model_api.ModelProxy)
    env.update(apis.start())
    for p in apis.proxies:
        _log(f"model API {p.backend.name}: {p.backend.env}={p.url} -> {p.backend.url}")
    agent = Agent(config.entry, root, folder / "app.log", timeout=timeout, env=env)
    tap = StdioTap(("127.0.0.1", 0), agent, folder / "tap.jsonl")
    _log(f"tap bound to {tap.url}")
    try:
        agent.start()
    except OSError as e:
        print(f"verbatim-relay bridge: cannot start the entry {config.entry}: {e}", file=sys.stderr)
        return 1
    _log(f"entry started: {config.entry}")
    time.sleep(0.3)
    assert agent.proc is not None
    if agent.proc.poll() is not None:
        print(f"verbatim-relay bridge: the entry exited at start:\n{agent.tail()}", file=sys.stderr)
        return 1
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
            "pid": os.getpid(),
            "pid_start": pid_start,
        },
    )
    _log(f"test {test} on {tap.url}")
    stop.wait()

    _log("ending")
    tap.shutdown()
    watcher.stop()
    watcher.poll()
    agent.stop()
    if receiver:
        # The app can export its last spans when it exits. Then no request comes after it.
        receiver.quiet()
        receiver.shutdown()
        receiver.server_close()
    proxies.stop()
    apis.stop()
    ended = time.time()
    relay = folder / "relay.jsonl"
    tester = set(manifest["tester_sessions"])
    ending = state(root) / ENDING
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(ending.read_text())
        if data.get("test") == test and isinstance(data.get("tester_session"), str):
            tester.add(data["tester_session"])
    ending.unlink(missing_ok=True)
    tester |= {r["session"] for r in _rows(relay, "turn") if isinstance(r.get("session"), str)}
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
    for f, meta in codex_sessions(root, started, ended, tester):
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
    _write_json(folder / "manifest.json", manifest)
    try:
        _log(trace.summary(trace.build(folder)))
    except Exception as e:  # the test must still end
        _log(f"the trace failed: {e!r}")
    try:
        report = audit(folder / "tap.jsonl", relay).as_dict()
        _write_json(folder / "audit.json", report)
    except Exception as e:  # the test must still end
        _log(f"the audit failed: {e!r}")
    try:
        error = seal.write(folder)
        if error:
            _log(f"the seal has no copy outside the project: {error}")
    except Exception as e:  # the test must still end
        _log(f"the seal failed: {e!r}")
    (state(root) / "current.json").unlink(missing_ok=True)
    tap.server_close()
    _log(f"test {test} ended")
    return 0


def check(root: Path) -> tuple[bool, list[str]]:
    """Run a test with one message. Return (passed, the report lines)."""
    config = load_config(root)
    cur = start(root)
    relay = Path(cur["dir"]) / "relay.jsonl"
    try:
        shown, ok = send(cur, CHECK_MESSAGE)
        Writer(relay).append(
            {
                "type": "turn",
                "harness": "verbatim-relay-check",
                "said": CHECK_MESSAGE,
                "shown": shown,
                "ok": ok,
            }
        )
        time.sleep(2 * POLL)
    finally:
        manifest = end(root) or {}
    lines = [f"Test {cur['test']}: {cur['dir']}", f"Reply: {shown}"]
    problems = [] if ok else ["The entry sent no reply."]
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
    lines += [f"FAIL: {p}" for p in problems] or ["PASS"]
    return not problems, lines

"""The state of a test that a hook reads on each event: relay mode's test, the latest test, and
the relay of one message. This module imports little, so that a hook event stays fast (#214)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import subprocess

from nookku import contract, seal
from nookku.adapters import History
from nookku.config import STATE_DIR as STATE_DIR
from nookku.record import RecordError, loads, turns

# Longer than the tap's wait for the agent, shorter than the hook deadline (kit.HOOK_DEADLINE).
TIMEOUT = 270
# The harness of the turn of `nookku check`. bridge.CHECK_HARNESS has the same value, and a test
# checks it. This module does not import bridge, so that a hook event stays fast (#214).
CHECK_HARNESS = "nookku-check"

# The header of the tap token (SPEC.md section 4.2). A browser cannot send this header to the tap
# without a preflight, and the tap refuses a preflight.
TOKEN_HEADER = "X-Nookku-Token"
# The key of the tap token in current.json.
TOKEN_KEY = "tap_token"


# The page file in the state folder: the port, the pid and the pid start time of the chat page
# server (SPEC.md section 5, "Chat page"). It never holds the page token, because a model tool
# call can read it.
PAGE_FILE = "page.json"


def page_info(root: Path) -> dict[str, Any] | None:
    """The page file of the project, or None if it does not exist or is not valid."""
    try:
        data = json.loads((state(root) / PAGE_FILE).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or type(data.get("port")) is not int:
        return None
    return data


# The page lock in the state folder. The chat page server holds it for its whole life, so that
# only one page server runs for each project.
PAGE_LOCK = "page.lock"
# The send lock in the state folder. A send of the hook relay or of the page holds it from its
# checks to its turn row. The end of a test holds it from the tap shutdown to the seal (SPEC.md
# section 5, "Chat page").
SEND_LOCK = "send.lock"


def lock_sends(root: Path) -> int:
    """Take the send lock of the project, and wait for it if necessary. Return its file
    descriptor. `os.close` of the descriptor gives the lock back."""
    import fcntl

    folder = state(root)
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(folder / SEND_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def page_port(root: Path) -> int | None:
    """The port of the chat page of the project, or None. The guard denies a call to it."""
    info = page_info(root)
    return info["port"] if info else None


def public(cur: dict[str, Any]) -> dict[str, Any]:
    """current.json with no tap token, for output that a log or a tool result can keep."""
    return {k: v for k, v in cur.items() if k != TOKEN_KEY}


def tap_headers(token: str) -> dict[str, str]:
    """The headers of a POST to the stdio tap. A page server of the bridge, or a process that
    reads current.json, sends each message with these headers."""
    return {"Content-Type": "application/json", TOKEN_HEADER: token}


def state(root: Path) -> Path:
    return root / STATE_DIR


# The variable that names the folder of the tests (SPEC.md section 7). The option --tests-dir of
# a command sets it for that command and its child processes. NOOKKU_TEST_DIR is another
# variable: the bridge gives it to the entry, and it names the folder of one test.
TESTS_ENV = "NOOKKU_TESTS_DIR"
# The name of a test folder. It has no path separator and no drive, on each system.
TEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class TestsDirError(ValueError):
    """The value of NOOKKU_TESTS_DIR or of --tests-dir breaks the rule of SPEC.md section 7."""


def is_test_id(name: str) -> bool:
    return TEST_ID.fullmatch(name) is not None


def tests_dir(root: Path) -> Path:
    """The folder of the tests of the project (SPEC.md section 7): the absolute path in
    NOOKKU_TESTS_DIR, else <root>/.nookku/tests. An empty variable counts as no variable. A
    value that breaks the rule raises TestsDirError, so that no command reads or writes a test
    in another folder."""
    default = state(root) / "tests"
    value = os.environ.get(TESTS_ENV)
    if not value:
        return default
    hint = f"Give the absolute path of a folder for the tests in {TESTS_ENV} or --tests-dir."
    if not os.path.isabs(value):
        raise TestsDirError(f"{TESTS_ENV} is not an absolute path: {value!r}. {hint}")
    folder = Path(os.path.normpath(value))
    if folder == Path(os.path.normpath(default)):
        return default
    if any(part.casefold() == STATE_DIR.casefold() for part in folder.parts):
        raise TestsDirError(f"{TESTS_ENV} names a folder in a state folder: {value!r}. {hint}")
    project = Path(os.path.normpath(root.absolute()))
    for top, real in ((folder, project), (folder.resolve(), root.resolve())):
        if top == real or top in real.parents:
            raise TestsDirError(
                f"{TESTS_ENV} names the project or a folder above it: {value!r}. Then each "
                f"folder of the project looks like a test. {hint}"
            )
    return folder


# The file in the state folder that names each tests folder outside the state folder that a test
# used, the newest last (SPEC.md section 7, #507). The relay in the harness reads it. Thus it
# protects such a folder after the test ends, also if the harness has no NOOKKU_TESTS_DIR. The
# list only becomes longer: a later test in another folder does not remove the protection of a
# folder before it.
TESTS_DIRS = "tests-dirs.json"


def known_tests_dirs(root: Path) -> list[Path]:
    """The tests folders of the file TESTS_DIRS, or [] if the file does not exist. A file that
    breaks its rule raises TestsDirError, so that the relay denies each tool call (fail closed)."""
    path = state(root) / TESTS_DIRS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise TestsDirError(_known_error(path, str(e))) from None
    folders = data.get("folders") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("v") != 1
        or not isinstance(folders, list)
        or not all(isinstance(f, str) and f and os.path.isabs(f) for f in folders)
    ):
        raise TestsDirError(
            _known_error(path, 'it must be {"v": 1, "folders": [<absolute path>, ...]}')
        )
    return [Path(os.path.normpath(f)) for f in folders]


def _known_error(path: Path, cause: str) -> str:
    return (
        f"{path} is not valid: {cause}. Only nookku writes this file. A person can remove it. "
        "Then the relay protects only the tests folder of NOOKKU_TESTS_DIR and of a running test."
    )


def remember_tests_dir(root: Path, folder: Path) -> None:
    """Add the tests folder of a new test to the file TESTS_DIRS, as its newest folder, if the
    folder is not `.nookku/tests`. A file that breaks its rule raises TestsDirError. The write
    makes a new file and then replaces the old one, so a link that a model makes in the state
    folder does not get the text."""
    path = Path(os.path.normpath(folder.absolute()))
    if path == Path(os.path.normpath(state(root).absolute() / "tests")):
        return
    known = [str(f) for f in known_tests_dirs(root) if f != path]
    text = json.dumps({"v": 1, "folders": [*known, str(path)]}, indent=1) + "\n"
    target = state(root) / TESTS_DIRS
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.replace(target)


def set_tests_dir(value: str) -> None:
    """Keep the value of --tests-dir in NOOKKU_TESTS_DIR, as an absolute path, so that the
    command and each child process, for example the bridge, use the same folder."""
    if not value:
        raise TestsDirError("--tests-dir needs the path of a folder.")
    os.environ[TESTS_ENV] = os.path.abspath(value)


# A file that marks a state folder, also when a symlink with another name points to it. init
# refuses a root in a marked folder (#148). No app has a file with this name.
MARKER = "nookku-state"
MARKER_TEXT = "This folder is the state folder of nookku. Do not run nookku init in it.\n"


def mark(folder: Path) -> None:
    """Write the marker of a state folder, if it does not exist."""
    path = folder / MARKER
    if not path.exists():
        path.write_text(MARKER_TEXT, encoding="utf-8")


# Bridge processes that this process started, so that alive() can reap them.
_children: dict[int, subprocess.Popen[bytes]] = {}


def alive(pid: int) -> bool:
    """True if a process with this pid runs. A pid that the OS cannot have, for example one
    larger than a C int in a manifest, is not a running process."""
    if pid in _children:
        return _children[pid].poll() is None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError, ValueError):
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
    import subprocess

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


def same_process(pid: object, start: object) -> bool:
    """True if a process with `pid` runs and has the start time `start` (see process_start).
    A value of the wrong type, for example no start time in an older file, is False."""
    if type(pid) is not int or pid <= 0 or not isinstance(start, str) or not alive(pid):
        return False
    return process_start(pid) == start


def is_bridge(cur: dict[str, Any]) -> bool:
    """True if the process of `pid` runs and has the start time `pid_start` of current.json."""
    return same_process(cur.get("pid"), cur.get("pid_start"))


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
        return float(loads((folder / "manifest.json").read_text())["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return float("inf")


def tests_newest_first(root: Path) -> list[Path]:
    """The test folders, the test that started last first. 2 test ids of the same second differ
    only by a random part. A folder whose name is not a test id is not a test, for example
    `lost+found` on a mounted volume (SPEC.md section 7)."""
    tests = tests_dir(root)
    dirs = (
        [p for p in tests.iterdir() if p.is_dir() and is_test_id(p.name)] if tests.is_dir() else []
    )
    return sorted(dirs, key=lambda d: (_started(d), d.name), reverse=True)


def latest_test(root: Path) -> Path | None:
    """The test that started last."""
    found = tests_newest_first(root)
    return found[0] if found else None


def manifest_of(folder: Path) -> dict[str, Any] | None:
    """The manifest of a test, or None if it cannot be read or is not a JSON object."""
    try:
        manifest = loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def closed(folder: Path) -> bool:
    """True if the test ended, or its end wrote the audit or the seal. Then its records must not
    change. A test with a manifest that cannot be read is also closed (fail closed). A send of
    the hook relay or of the chat page, and a note, use this one rule (SPEC.md section 5)."""
    if (folder / "audit.json").exists() or (folder / seal.SEAL).exists():
        return True
    manifest = manifest_of(folder)
    return manifest is None or manifest.get("ended") is not None


def is_check(folder: Path, manifest: dict[str, Any]) -> bool:
    """True if the test is a test of `nookku check` (SPEC.md section 9.1). If the manifest has the
    key `check`, the key decides. A manifest of an older Nookku version has no such key: then
    the test has turns, and each one has the harness `nookku-check`. A relay record that cannot
    be read is not a check test."""
    if "check" in manifest:
        return manifest["check"] is True
    try:
        found = turns(folder / "relay.jsonl", missing_ok=True)
    except RecordError:
        return False
    return bool(found) and all(t.harness == CHECK_HARNESS for t in found)


def tester_test(root: Path) -> Path | None:
    """The latest test that is not a check test that ended (SPEC.md section 9.1). A check test
    with no end time, or a test with a manifest that cannot be read, stops the search: it is
    the result. The evaluation, its denies and the default test of `transcript` use this test."""
    for folder in tests_newest_first(root):
        manifest = manifest_of(folder)
        ended = manifest is not None and manifest.get("ended") is not None
        if not (ended and manifest is not None and is_check(folder, manifest)):
            return folder
    return None


def history(relay: Path) -> History:
    """The turns of the test that showed the agent's reply (SPEC.md section 5). An invalid line
    in the relay record raises a RecordError."""
    return [
        (t.said, t.shown)
        for t in turns(relay, missing_ok=True)
        if t.ok is True and isinstance(t.shown, str)
    ]


def send(cur: dict[str, Any], said: str, timeout: float = TIMEOUT) -> tuple[str, bool]:
    """Relay one message to the running test. Return (the text to show, whether it is the reply)."""
    # Imported here, so that an event that does not relay stays fast (#214).
    import urllib.error
    import urllib.request
    import uuid

    rid = uuid.uuid4().hex
    body = contract.request(rid, cur["test"], said, history(Path(cur["dir"]) / "relay.jsonl"))
    # A current.json with no token gets a 403 from the tap, so the relay fails closed.
    token = cur.get(TOKEN_KEY)
    headers = tap_headers(token if isinstance(token, str) else "")
    req = urllib.request.Request(cur["tap_url"], data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = resp.read()
    except urllib.error.HTTPError as e:
        text = e.read()
        if e.code == 500:
            try:
                error = contract.parse_reply(text, rid)[1]
                return f"nookku: the agent sent an error:\n{error}", False
            except contract.ContractError:
                pass
        try:
            message = json.loads(text)["error"]
        except (ValueError, KeyError, TypeError):
            message = text.decode("utf-8", errors="replace")
        return f"nookku: HTTP {e.code}: {message}", False
    except (OSError, ValueError) as e:
        return f"nookku: cannot reach the tap at {cur['tap_url']}: {e}", False
    try:
        reply, _ = contract.parse_reply(out, rid)
    except contract.ContractError as e:
        return f"nookku: cannot read the reply: {e}", False
    assert reply is not None
    return reply, True

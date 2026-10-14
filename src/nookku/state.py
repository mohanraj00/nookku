"""The state of a test that a hook reads on each event: relay mode's test, the latest test, and
the relay of one message. This module imports little, so that a hook event stays fast (#214)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import subprocess

from nookku import contract
from nookku.adapters import History
from nookku.config import STATE_DIR as STATE_DIR
from nookku.record import turns

# Longer than the tap's wait for the agent, shorter than the hook deadline (kit.HOOK_DEADLINE).
TIMEOUT = 270
# The header of the tap token (SPEC.md section 4.2). A browser cannot send this header to the tap
# without a preflight, and the tap refuses a preflight.
TOKEN_HEADER = "X-Nookku-Token"
# The key of the tap token in current.json.
TOKEN_KEY = "tap_token"


# The page file in the state folder: the port and the pid of the chat page server (SPEC.md section
# 5, "Chat page"). It never holds the page token, because a model tool call can read it.
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

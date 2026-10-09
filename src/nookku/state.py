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
from nookku.config import FILE as CONFIG_FILE
from nookku.config import STATE_DIR as STATE_DIR
from nookku.record import turns

# Longer than the tap's wait for the agent, shorter than the hook deadline (kit.HOOK_DEADLINE).
TIMEOUT = 270


def state(root: Path) -> Path:
    return root / STATE_DIR


def has_entry(root: Path) -> bool:
    """True if config.json has a list `entry` with at least one item. The plugin's `hasEntry`
    uses the same rule. A file with an entry and an error still has an entry, so that `start`
    shows the error."""
    try:
        data = json.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    entry = data.get("entry") if isinstance(data, dict) else None
    return isinstance(entry, list) and len(entry) > 0


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

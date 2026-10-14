"""The dashboard of the chat page: one row for each test of the project (#349).

The dashboard reads only the files of the test folders, and it changes no file. It does not
remove a stale `current.json`, as `state.current` does. The page server serves it behind the
same token, `Host` and `Origin` checks as the chat page (SPEC.md section 5, "Dashboard").
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from nookku import seal, state
from nookku.record import RecordError, turns

# The values of each filter, in the order of the page. The first value of each is the default.
STATES = ("all", "running", "ended", "stopped", "unknown")
HAS = ("all", "break", "finding")
ORDERS = ("newest", "oldest")


def running_id(root: Path) -> str | None:
    """The id of the running test, from current.json, or None. Change no file."""
    try:
        cur = json.loads((state.state(root) / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cur, dict) or not isinstance(cur.get("dir"), str) or not state.is_bridge(cur):
        return None
    return Path(cur["dir"]).name


def find(root: Path, test_id: str) -> Path | None:
    """The folder of the test with this id, or None. The id must be the name of a test folder,
    so a path from the request never leaves the test folders."""
    return next((f for f in state.tests_newest_first(root) if f.name == test_id), None)


def _json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The JSON object in the file, and an error. A missing file gives no object and no error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return None, f"{path.name}: {e}"
    if not isinstance(data, dict):
        return None, f"{path.name}: not a JSON object"
    return data, None


def _count(data: dict[str, Any] | None, key: str, name: str) -> tuple[int | None, str | None]:
    """The length of the list `key` of the file, or None if the file is missing or wrong."""
    if data is None:
        return None, None
    found = data.get(key)
    if not isinstance(found, list):
        return None, f"{name}: no list {key}"
    return len(found), None


def _seal_state(folder: Path) -> tuple[str, str | None]:
    """intact, broken or none, with the rule of `nookku verify` (SPEC.md section 7.4), and an
    error. If a file cannot be read, the state is unknown, and only this row shows the error."""
    try:
        result = seal.verify(folder)
    except OSError as e:
        return "unknown", f"seal: cannot read a file: {e.strerror or type(e).__name__}"
    if not result["sealed"] and result["copy"] == "none":
        return "none", None
    return ("intact" if result["intact"] else "broken"), None


def _time(manifest: dict[str, Any], key: str) -> tuple[float | None, str | None]:
    """A time of the manifest, or None. A time that is not a finite number gives an error, because
    the JSON of the answer cannot hold NaN or Infinity (SPEC.md section 2)."""
    value = manifest.get(key)
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None, f"manifest.json: {key} is not a finite number"
    return float(value), None


def row(folder: Path, running: str | None) -> dict[str, Any]:
    """The row of one test folder."""
    errors: list[str] = []
    manifest, error = _json_object(folder / "manifest.json")
    if error is None and manifest is None:
        error = "manifest.json: missing"
    if folder.name == running:
        test_state = "running"
    elif manifest is None:
        test_state = "unknown"
    else:
        test_state = "stopped" if manifest.get("ended") is None else "ended"
    if error is not None and test_state != "running":
        errors.append(error)
    manifest = manifest or {}
    started, start_error = _time(manifest, "started")
    ended, end_error = _time(manifest, "ended")
    errors += [e for e in (start_error, end_error) if e]
    try:
        turn_count: int | None = len(turns(folder / "relay.jsonl", missing_ok=True))
    except RecordError as e:
        turn_count = None
        errors.append(str(e))
    audit, error = _json_object(folder / "audit.json")
    breaks, count_error = _count(audit, "breaks", "audit.json")
    if audit is not None and audit.get("exit") == 2:
        # A record that is not valid gives no breaks (SPEC.md section 3.1).
        breaks, count_error = None, "audit.json: a record is missing or not valid (exit 2)"
    errors += [e for e in (error, count_error) if e]
    findings_data, error = _json_object(folder / "findings.json")
    findings, count_error = _count(findings_data, "findings", "findings.json")
    errors += [e for e in (error, count_error) if e]
    # The files of a running test still change, and it has no seal yet.
    seal_state, error = ("none", None) if test_state == "running" else _seal_state(folder)
    errors += [error] if error else []
    return {
        "id": folder.name,
        "started": started,
        "ended": ended,
        "state": test_state,
        "turns": turn_count,
        "breaks": breaks,
        "findings": findings,
        "seal": seal_state,
        "errors": errors,
    }


def _is_text(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def rows(
    root: Path, test_state: str = "all", has: str = "all", order: str = "newest"
) -> list[dict[str, Any]]:
    """The rows of the tests that pass the filters, sorted by the start time."""
    running = running_id(root)
    # A folder name that is not UTF-8 text is not a test id, and the answer cannot hold it.
    folders = [f for f in state.tests_newest_first(root) if _is_text(f.name)]
    found = [row(folder, running) for folder in folders]
    if test_state != "all":
        found = [r for r in found if r["state"] == test_state]
    if has == "break":
        found = [r for r in found if r["breaks"]]
    elif has == "finding":
        found = [r for r in found if r["findings"]]
    return found[::-1] if order == "oldest" else found


def answer(root: Path, rest: str) -> tuple[int, dict[str, Any]]:
    """The answer to `api/tests` or `api/tests/<state>/<has>/<order>`: the status and the data."""
    parts = rest.split("/")[2:] if rest != "api/tests" else []
    if parts and (
        len(parts) != 3 or parts[0] not in STATES or parts[1] not in HAS or parts[2] not in ORDERS
    ):
        return 404, {"error": "nookku page: not found"}
    test_state, has, order = parts or (STATES[0], HAS[0], ORDERS[0])
    return 200, {"tests": rows(root, test_state, has, order), "error": None}

"""The seal of a test folder (SPEC.md section 7.4).

At the end of a test, the bridge writes the SHA-256 of each file of the test folder to seal.json,
and a copy to ~/.verbatim-relay/seals/<test-id>.json. `verify` finds each file that changed after
the end. A model that changes a record must also change both seals.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

SEAL = "seal.json"
DENIED = "denied.jsonl"
# Files that change after the end: the evaluation, the bridge log, the seal and the denies.
UNSEALED = {"report.md", "bridge.log", SEAL, DENIED}
VERSION = 1


def home() -> Path:
    return Path(os.environ.get("VERBATIM_RELAY_HOME") or Path.home() / ".verbatim-relay")


def copy_path(test: str, base: Path | None = None) -> Path:
    return (base or home()) / "seals" / f"{test}.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def hashes(folder: Path) -> dict[str, str]:
    """The SHA-256 of each sealed file of the folder, by its path in the folder."""
    out = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if path.is_file() and rel not in UNSEALED:
            out[rel] = _sha256(path)
    return out


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write(folder: Path, base: Path | None = None) -> str | None:
    """Seal the folder. Return the error of the copy, or None if the copy was written."""
    data: dict[str, Any] = {
        "v": VERSION,
        "test": folder.name,
        "sealed": time.time(),
        "files": hashes(folder),
    }
    error = None
    try:
        _write(copy_path(folder.name, base), {**data, "copy": True})
    except OSError as e:
        error = f"{type(e).__name__}: {e}"
    _write(folder / SEAL, {**data, "copy": error is None})
    return error


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = isinstance(data, dict) and isinstance(data.get("files"), dict)
    return data if ok else None


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(a.get(k) == b.get(k) for k in ("v", "test", "sealed", "files"))


def verify(folder: Path, base: Path | None = None) -> dict[str, Any]:
    """Compare the folder with its seal and the seal with its copy.

    `copy` is "same", "different", "missing" (the seal names a copy that does not exist) or
    "none" (the bridge could not write a copy). Without seal.json, the copy is the seal.
    """
    seal = _read(folder / SEAL)
    copy = _read(copy_path(folder.name, base))
    ref = seal or copy
    out: dict[str, Any] = {
        "test": folder.name,
        "sealed": seal is not None,
        "intact": False,
        "changed": [],
        "missing": [],
        "added": [],
        "copy": "none",
    }
    if ref is None:
        return out
    if seal is None or seal.get("copy"):
        out["copy"] = "missing" if copy is None else "same" if _same(ref, copy) else "different"
    now = hashes(folder)
    files: dict[str, Any] = ref["files"]
    out["changed"] = sorted(k for k in files if k in now and now[k] != files[k])
    out["missing"] = sorted(k for k in files if k not in now)
    out["added"] = sorted(k for k in now if k not in files)
    broken = out["changed"] or out["missing"] or out["added"]
    out["intact"] = seal is not None and not broken and out["copy"] in ("same", "none")
    return out


def update(folder: Path, names: list[str], base: Path | None = None) -> None:
    """Put the new hashes of the named files into both seals, after a rebuild of the trace."""
    seal = _read(folder / SEAL)
    if seal is None:
        return
    files = {**seal["files"]}
    for name in names:
        path = folder / name
        if path.is_file():
            files[name] = _sha256(path)
    data = {**seal, "files": files}
    if seal.get("copy"):
        _write(copy_path(folder.name, base), {**data, "copy": True})
    _write(folder / SEAL, data)


def summary(result: dict[str, Any]) -> str:
    """One line for the transcript and the CLI."""
    if not result["sealed"] and result["copy"] == "none":
        return "Seal: none. The records of this test have no seal."
    if result["intact"]:
        extra = " (no copy outside the project)" if result["copy"] == "none" else ""
        return f"Seal: intact{extra}. No record changed after the end of the test."
    parts = [] if result["sealed"] else ["seal.json is missing"]
    for key, word in (("changed", "changed"), ("missing", "missing"), ("added", "new")):
        if result[key]:
            parts.append(f"{word}: {', '.join(result[key])}")
    if result["copy"] in ("different", "missing"):
        parts.append(f"the copy of the seal is {result['copy']}")
    return f"Seal: BROKEN. {'; '.join(parts)}. Do not trust these records."

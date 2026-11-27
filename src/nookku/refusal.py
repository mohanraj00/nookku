"""The sealed record of a refused start (SPEC.md section 7.8, #628).

If the hook check of Claude Code or the Codex hook gate refuses a start, no test starts. The
start then writes a folder `refused-<time>-<random>` in the tests folder with `refusal.json`, and
seals it as a test folder (SPEC.md section 7.4). Thus `nookku verify <id>` shows if the record
changed. The readers of the tests folder do not read the folder as a test.
"""

from __future__ import annotations

import datetime
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from nookku import __version__, seal, state

RECORD = "refusal.json"
VERSION = 1


def new_id() -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{state.REFUSAL_PREFIX}{stamp}-{secrets.token_hex(4)}"


def record(
    refusal: str, root: Path, harness: str, problems: list[str], versions: dict[str, Any]
) -> dict[str, Any]:
    """The content of refusal.json."""
    return {
        "v": VERSION,
        "refusal": refusal,
        "refused": time.time(),
        "command": "start",
        "harness": harness,
        "root": str(root),
        "problems": list(problems),
        "versions": {"nookku": __version__, **versions},
    }


def write(root: Path, harness: str, problems: list[str], versions: dict[str, Any]) -> Path:
    """Write and seal the record of a refused start. Return its folder.

    The tests folder goes into the file state.TESTS_DIRS first, so the relay protects the record
    also in a tests folder outside the state folder. The folder and refusal.json must be new: the
    write never goes into a folder or through a link that exists. Raise OSError or
    state.TestsDirError if the record cannot be written."""
    tests = state.tests_dir(root)
    state.remember_tests_dir(root, tests)
    tests.mkdir(parents=True, exist_ok=True)
    refusal = new_id()
    folder = tests / refusal
    folder.mkdir()
    data = record(refusal, root, harness, problems, versions)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(folder / RECORD, flags, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    seal.write(folder)
    return folder

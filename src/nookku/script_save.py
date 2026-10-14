"""Save a test as a script (SPEC.md section 7.10, "Save a test as a script").

`nookku script save` and the "Save as script" button of the chat page write the `said` text of
each `turn` row of a test into a JSONL script, byte for byte. `nookku run --script` reads the
file with no change. The file name is the source test id, because the form of a script has no
other field for it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nookku import kit, script, state
from nookku.record import RecordError, turns

# The folder of the saved scripts, in the state folder of the project. The guard protects it.
FOLDER = kit.SCRIPTS
# The path of the page request that saves a script, after the token.
ROUTE = "api/save-script"


class SaveError(ValueError):
    """The test cannot be saved as a script. Nothing was written."""


def path_of(root: Path, test: str) -> Path:
    """The path of the script of a test: `.nookku/scripts/<test id>.jsonl`."""
    return state.state(root) / FOLDER / f"{test}.jsonl"


def script_bytes(folder: Path) -> bytes:
    """The JSONL script of the turns of a test folder. Raise SaveError if the relay record is
    not valid or has no turn. The reader refuses a `said` with a lone surrogate, so a script
    never holds a changed message."""
    try:
        found = turns(folder / "relay.jsonl", missing_ok=True)
    except RecordError as e:
        raise SaveError(str(e)) from None
    if not found:
        raise SaveError(f"test {folder.name} has no turn, and a script needs one message")
    saids = [t.said for t in found]
    # json.dumps escapes each control character, also a line feed, so each row is one line.
    # ensure_ascii=False keeps each other character as it is, also U+2028.
    data = "".join(json.dumps({"said": s}, ensure_ascii=False) + "\n" for s in saids).encode()
    # Fail closed: the reader of `nookku run` must give each message back, byte for byte.
    try:
        messages, _ = script.parse(data)
    except script.ScriptError as e:
        raise SaveError(f"the script does not read back: {e}") from None
    if messages != saids:
        raise SaveError("the script does not give back each message byte for byte")
    return data


def save(root: Path, test: str) -> tuple[Path, int]:
    """Write the script of a test id. Return its path and its count of messages. Raise
    SaveError. The id must name a folder in the tests folder of the project (kit.existing_test),
    so a page request cannot reach another folder."""
    try:
        folder = kit.existing_test(root, test)
    except kit.TranscriptError as e:
        raise SaveError(str(e)) from None
    data = script_bytes(folder)
    path = path_of(root, folder.name)
    # Write a new file, then replace, so a reader never gets a part of the script.
    new = path.with_name(f".{path.name}.{os.getpid()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new.write_bytes(data)
        os.replace(new, path)
    except OSError as e:
        new.unlink(missing_ok=True)
        raise SaveError(f"cannot write the script {path}: {e}") from None
    # json.dumps escapes each line end in a message, so each line is one message.
    return path, data.count(b"\n")


def run_text(root: Path, path: Path) -> str:
    """The command that runs a saved script, with the path from the project folder."""
    return f"nookku run --script {path.relative_to(root)}"


def answer(root: Path, body: Any) -> tuple[int, dict[str, Any]]:
    """The status and the answer of a page request to save a script. The body must be a JSON
    object with the text `test`, the id of the test that the page shows."""
    test = body.get("test") if isinstance(body, dict) else None
    if not isinstance(test, str):
        return 400, {"saved": False, "error": 'nookku page: the body needs the text "test"'}
    try:
        path, count = save(root, test)
    except SaveError as e:
        return 200, {"saved": False, "error": f"nookku: {e}"}
    text = f"Saved {count} messages of test {test} to {path}. Run it with: {run_text(root, path)}"
    return 200, {"saved": True, "path": str(path), "messages": count, "text": text}

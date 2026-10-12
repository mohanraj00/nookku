"""The script file of a scripted test (SPEC.md section 7.10).

A script holds the messages of a test, in order. The relay sends each message byte for byte, so
the model never retypes a message. A script has one of 2 forms: JSONL with one {"said": "..."}
row for each turn, or one JSON array of strings.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nookku.record import lone_surrogate

# The name of the copy in the test folder, for each form. The seal covers the copy.
COPIES = {"json": "script.json", "jsonl": "script.jsonl"}


class ScriptError(ValueError):
    """A script file that cannot be read or that breaks the rule of its form. The attribute
    unreadable is True if the file cannot be read."""

    def __init__(self, text: str, unreadable: bool = False) -> None:
        super().__init__(text)
        self.unreadable = unreadable


def _message(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ScriptError(f"{where}: a message must be a string")
    found = lone_surrogate(value)
    if found:
        raise ScriptError(f"{where}: the message has {found}")
    return value


def parse(data: bytes) -> tuple[list[str], str]:
    """The messages of a script and its form, "json" or "jsonl". Raise ScriptError if the bytes
    are not UTF-8, break the rule of the form, have a lone surrogate, or hold no message."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ScriptError(f"the script is not UTF-8: {e}") from None
    if text.lstrip().startswith("["):
        form = "json"
        try:
            values = json.loads(text)
        except ValueError as e:
            raise ScriptError(f"the script is not a JSON array: {e}") from None
        if not isinstance(values, list):
            raise ScriptError("the script is not a JSON array")
        messages = [_message(v, f"item {n}") for n, v in enumerate(values, 1)]
    else:
        form = "jsonl"
        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        messages = []
        for n, line in enumerate(lines, 1):
            try:
                row = json.loads(line)
            except ValueError as e:
                raise ScriptError(f"line {n}: not a JSON object: {e}") from None
            if not isinstance(row, dict) or set(row) != {"said"}:
                raise ScriptError(f'line {n}: a row must be {{"said": "..."}} with no other key')
            messages.append(_message(row["said"], f"line {n}"))
    if not messages:
        raise ScriptError("the script has no message")
    return messages, form


def read(path: Path) -> tuple[list[str], str, bytes]:
    """The messages, the form and the bytes of a script file. Raise ScriptError."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ScriptError(f"cannot read the script {path}: {e}", unreadable=True) from None
    messages, form = parse(data)
    return messages, form, data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_in(folder: Path) -> Path | None:
    """The script copy of a test folder, or None if the test is not scripted."""
    found = [folder / name for name in COPIES.values() if (folder / name).exists()]
    return found[0] if found else None

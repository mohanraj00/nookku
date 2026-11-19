"""The script file of a scripted test (SPEC.md section 7.10).

A script holds the messages of a test, in order. The relay sends each message byte for byte, so
the model never retypes a message. A script has one of 2 forms: JSONL with one {"said": "..."}
row for each turn, or one JSON array of strings.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from nookku.record import loads, lone_surrogate

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


# The most seconds of the key `during` of a row (SPEC.md section 7.10). It is a chosen value.
MAX_DURING = 60


def _during(row: dict[str, object], n: int, before: list[float | None]) -> float | None:
    """The key `during` of row n of a JSONL script, or None. `before` holds the key of each row
    before it."""
    if "during" not in row:
        return None
    value = row["during"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScriptError(f'line {n}: "during" must be a number of seconds')
    if not 0 <= value <= MAX_DURING:
        raise ScriptError(f'line {n}: "during" must be from 0 to {MAX_DURING}')
    if not before:
        raise ScriptError(f'line {n}: the first message cannot have "during"')
    if before[-1] is not None:
        raise ScriptError(f'line {n}: the row before a row with "during" cannot have it')
    return float(value)


def parse(data: bytes) -> tuple[list[str], str]:
    """The messages of a script and its form, "json" or "jsonl". Raise ScriptError if the bytes
    are not UTF-8, break the rule of the form, have a lone surrogate, or hold no message."""
    messages, form, _ = _parse(data)
    return messages, form


def timing(data: bytes) -> list[float | None]:
    """The key `during` of each message of a script (SPEC.md section 7.10): the seconds after
    the send of the message before it, or None for a message that waits for the reply before
    it. Raise ScriptError as parse does."""
    return _parse(data)[2]


def _parse(data: bytes) -> tuple[list[str], str, list[float | None]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ScriptError(f"the script is not UTF-8: {e}") from None
    if text.lstrip().startswith("["):
        form = "json"
        try:
            values = loads(text)
        except ValueError as e:
            raise ScriptError(f"the script is not a JSON array: {e}") from None
        if not isinstance(values, list):
            raise ScriptError("the script is not a JSON array")
        messages = [_message(v, f"item {n}") for n, v in enumerate(values, 1)]
        during: list[float | None] = [None] * len(messages)
    else:
        form = "jsonl"
        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        messages, during = [], []
        for n, line in enumerate(lines, 1):
            try:
                row = loads(line)
            except ValueError as e:
                raise ScriptError(f"line {n}: not a JSON object: {e}") from None
            if not isinstance(row, dict) or "said" not in row or set(row) - {"said", "during"}:
                raise ScriptError(
                    f'line {n}: a row must be {{"said": "..."}}, with no other key than "during"'
                )
            messages.append(_message(row["said"], f"line {n}"))
            during.append(_during(row, n, during))
    if not messages:
        raise ScriptError("the script has no message")
    return messages, form, during


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

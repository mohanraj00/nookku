"""The file .nookku/policy.json (SPEC.md section 7.9): the keys that control the guard.

Only a person changes this file, with `nookku policy set` in a shell. The relay denies each model
write to it, also when no test runs (SPEC.md section 5). If the file does not exist, each key has
its default, and each default is the strict value.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nookku.commands import SHELL_TOOLS

STATE_DIR = ".nookku"
NAME = "policy.json"
FILE = f"{STATE_DIR}/{NAME}"
REASON = f"nookku: only a person changes {FILE}, with nookku policy set in a shell."
# Text that names the file or the command that writes it. The match ignores case, because the
# file system of macOS and Windows ignores case.
NAMES_FILE = re.compile(re.escape(NAME), re.IGNORECASE)
NAMES_STATE = re.compile(re.escape(STATE_DIR), re.IGNORECASE)
NAMES_COMMAND = re.compile(r"nookku\W+policy\b", re.IGNORECASE)
# The input fields of a file tool that give its target path.
PATH_FIELDS = ("file_path", "notebook_path", "path")


class PolicyError(ValueError):
    """The policy file cannot be read, or a key or a value is not known."""


@dataclass(frozen=True)
class Key:
    default: Any
    # Parse the text of `nookku policy set`. Raise ValueError if the text is not a valid value.
    parse: Callable[[str], Any]
    # True if a value of the file is valid.
    valid: Callable[[Any], bool]
    meaning: str


# The keys of policy.json. Each other key is an error. The issue that adds a guard rule adds its
# key here, with SPEC.md section 7.9 and docs/reference/config.md.
KEYS: dict[str, Key] = {}


def path(root: Path) -> Path:
    return root / STATE_DIR / NAME


def read(root: Path) -> dict[str, Any]:
    """Each key with its value: the value of the file, else the default. Raise PolicyError if the
    file is not a JSON object, or has a key or a value that is not known."""
    try:
        text = path(root).read_text(encoding="utf-8")
    except FileNotFoundError:
        data: Any = {}
    except OSError as e:
        raise PolicyError(f"cannot read {FILE}: {e}") from None
    else:
        try:
            data = json.loads(text)
        except ValueError as e:
            raise PolicyError(f"cannot read {FILE}: {e}") from None
    if not isinstance(data, dict):
        raise PolicyError(f"{FILE} is not a JSON object")
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise PolicyError(f"{FILE} has unknown keys: {unknown}. Correct or remove them.")
    for name, value in data.items():
        if not KEYS[name].valid(value):
            raise PolicyError(f"{FILE}: {name!r} has a value that is not valid: {value!r}")
    return {name: data.get(name, key.default) for name, key in KEYS.items()}


def set_key(root: Path, name: str, text: str) -> dict[str, Any]:
    """Write one key into the file. Return each key with its new value."""
    if name not in KEYS:
        known = ", ".join(KEYS) or "none"
        raise PolicyError(f"{name!r} is not a policy key. The keys are: {known}.")
    try:
        value = KEYS[name].parse(text)
    except ValueError as e:
        raise PolicyError(f"{name!r}: {e}") from None
    read(root)
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    data[name] = value
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write a new file and replace the old one, so a failed write leaves the old file whole.
    tmp = target.with_name(NAME + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return read(root)


def _target(value: Any, base: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return (base / value).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def touches(
    root: Path, tool: str, tool_input: Any, text: str, writes: bool, reads: bool, cwd: Path
) -> bool:
    """True if a model tool call can change the policy file (SPEC.md section 5).

    `writes` is True for a file write tool, and `reads` is True if the call passes the read check.
    The caller does not ask for a file tool that only reads. Best effort, like each deny of the
    relay. `cwd` is the folder of the call, so that a relative path finds its file.
    """
    if NAMES_FILE.search(text) and NAMES_STATE.search(text) and (writes or not reads):
        return True
    if writes and isinstance(tool_input, dict):
        own = str(path(root).resolve()).casefold()
        for name in PATH_FIELDS:
            target = _target(tool_input.get(name), cwd)
            if target is not None and str(target).casefold() == own:
                return True
    if writes or reads:
        return False
    if NAMES_COMMAND.search(text):
        return True
    # A tool that is not a shell, for example write_stdin of a persistent Codex shell, does not
    # show the folder where its text runs. So it must not name the file at all.
    if tool not in SHELL_TOOLS and NAMES_FILE.search(text):
        return True
    # A command in the state folder can name the file without the folder.
    state = str((root / STATE_DIR).resolve()).casefold()
    here = str(cwd.resolve()).casefold()
    in_state = here == state or here.startswith(state + os.sep)
    return in_state and bool(NAMES_FILE.search(text))

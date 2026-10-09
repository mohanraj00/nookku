"""The file .nooku/config.json (SPEC.md section 7.1): its keys and its one reader.

The hook kit, `start`, `check` and `init` read the file with `read_config`, so one rule applies
to its keys. Each part then checks the values that it uses.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

STATE_DIR = ".nooku"
FILE = f"{STATE_DIR}/config.json"
# The state folder of verbatim-relay 0.3.x and earlier. The first run of nooku moves it.
OLD_STATE_DIR = ".verbatim-relay"


class ConfigError(ValueError):
    """The config file cannot be read, or it breaks the rule for its keys."""


def move_old_state(root: Path) -> str | None:
    """Move the state folder of verbatim-relay 0.3.x to STATE_DIR. Return an error, or None.

    The move is one rename, so each test, record and seal stays as it is. If both folders exist,
    nothing moves: the person must choose which one to keep.
    """
    old, new = root / OLD_STATE_DIR, root / STATE_DIR
    if not old.is_dir():
        return None
    if new.exists():
        return (
            f"{old} and {new} both exist. Keep one: move the tests that you need into {new}, "
            f"then remove {old}."
        )
    # Change the config first. If that fails, the old folder stays, and the next run tries again.
    error = _move_record_key(old / "config.json")
    if error:
        return error
    try:
        old.rename(new)
    except FileNotFoundError:
        return None  # Another nooku process moved it first.
    except OSError as error:
        return f"cannot move {old} to {new}: {error}"
    print(f"nooku: moved {old} to {new}", file=sys.stderr)
    return None


def _move_record_key(path: Path) -> str | None:
    """Change a `record` key in the old state folder to the same file in STATE_DIR. Without this
    change, the first prompt writes the record into the old folder again, and then both folders
    exist. A record path outside the old folder stays as it is."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        return f"cannot read {path}: {error}"
    record = data.get("record") if isinstance(data, dict) else None
    if not isinstance(record, str) or not record.startswith(f"{OLD_STATE_DIR}/"):
        return None
    data["record"] = STATE_DIR + record[len(OLD_STATE_DIR) :]
    try:
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    except OSError as error:
        return f"cannot write {path}: {error}"
    print(f"nooku: changed 'record' in {path} to {data['record']}", file=sys.stderr)
    return None


@dataclass
class Config:
    tap_url: str = "http://127.0.0.1:8800/"
    agent_url: str = ""
    adapter: str = "json"
    message_field: str = "text"
    reply_field: str = "reply"
    openai_model: str = ""
    # True: the openai adapter sends "stream": true in each request (SPEC.md section 5).
    openai_stream: bool = False
    record: str = f"{STATE_DIR}/relay.jsonl"
    entry: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    # False stops the evaluation at the end of a test (SPEC.md section 9).
    evaluate: bool = True
    # False stops the OTLP receiver of a test (SPEC.md section 7.5).
    otel: bool = True
    # The backend proxies of a test (SPEC.md section 7.6).
    backends: list[dict[str, str]] = field(default_factory=list)
    # The model APIs to record: true, false, a list of names, or names with URLs (SPEC.md 7.7).
    model_api: bool | list[str] | dict[str, str | None] = True

    @classmethod
    def load(cls, root: Path) -> Config:
        return cls(**read_config(root))

    def record_path(self, root: Path) -> Path:
        return root / self.record


# The known keys of config.json. Each other key is an error.
KEYS = tuple(f.name for f in fields(Config))


def check(data: Any) -> dict[str, Any]:
    """Apply the rule for the keys to the parsed file. Return it, or raise ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError(f"{FILE} is not a JSON object")
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"{FILE} has unknown keys: {unknown}. Correct or remove them.")
    if not isinstance(data.get("openai_stream", False), bool):
        raise ConfigError(f"{FILE}: 'openai_stream' must be true or false")
    return data


def read_config(root: Path) -> dict[str, Any]:
    """The keys of config.json as the file gives them. Raise ConfigError if the file cannot be
    read or breaks the rule for its keys."""
    try:
        data = json.loads((root / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"cannot read {FILE}: {e}") from None
    return check(data)

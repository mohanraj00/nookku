"""The file .verbatim-relay/config.json (SPEC.md section 7.1): its keys and its one reader.

The hook kit, `start`, `check` and `init` read the file with `read_config`, so one rule applies
to its keys. Each part then checks the values that it uses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

STATE_DIR = ".verbatim-relay"
FILE = f"{STATE_DIR}/config.json"


class ConfigError(ValueError):
    """The config file cannot be read, or it breaks the rule for its keys."""


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

"""The file .nookku/config.json (SPEC.md section 7.1): its keys and its one reader.

The relay (`nookku hook`), `start`, `check` and `init` read the file with `read_config`, so
one rule applies to its keys. Each part then checks the values that it uses.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from nookku.record import lone_surrogate

STATE_DIR = ".nookku"
NAME = "config.json"
FILE = f"{STATE_DIR}/{NAME}"
# The state folder of verbatim-relay 0.3.x and earlier. The first run of nookku moves it.
OLD_STATE_DIR = ".verbatim-relay"
# The message of nookku check if config.json has no check_message (SPEC.md section 7.1).
CHECK_MESSAGE = "Hello from nookku check. What can you help me with?"
# The values of model_reply_match (SPEC.md section 8.6).
MATCHES = ("exact", "normalized", "off")


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
    error = _move_record_key(old / NAME)
    if error:
        return error
    try:
        old.rename(new)
    except FileNotFoundError:
        return None  # Another nookku process moved it first.
    except OSError as error:
        return f"cannot move {old} to {new}: {error}"
    print(f"nookku: moved {old} to {new}", file=sys.stderr)
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
    # Write a new file and replace the old one, so a failed write leaves the old file whole.
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as error:
        tmp.unlink(missing_ok=True)
        return f"cannot write {path}: {error}"
    print(f"nookku: changed 'record' in {path} to {data['record']}", file=sys.stderr)
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
    # The one message of nookku check (SPEC.md section 7.1).
    check_message: str = CHECK_MESSAGE
    # The count of consecutive turns with the same reply that gives a repeated_reply finding.
    # 0 turns the check off (SPEC.md section 8.6).
    repeated_reply: int = 2
    # The dot path of the client text in the JSON of a model output, or empty for the full text.
    # model_reply_match: exact, normalized or off (SPEC.md section 8.6).
    model_reply_field: str = ""
    model_reply_match: str = "normalized"
    # True: nookku transcript --trace shows a repeated text one time (SPEC.md section 9.2).
    transcript_compact: bool = False
    # False: start does not start the chat page with the test (SPEC.md section 5, #328).
    page: bool = True
    # More entries of a scripted test, by name (SPEC.md section 7.10). entry stays the default.
    entries: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Config:
        return cls(**read_config(root))

    @classmethod
    def load_or_default(cls, root: Path) -> Config:
        """The config of the project, or the defaults if config.json does not exist. The plugin
        has no config file. Raise ConfigError if the file exists and cannot be read or breaks
        the rule for its keys."""
        if not (root / FILE).exists():
            return cls()
        return cls.load(root)

    def record_path(self, root: Path) -> Path:
        return root / self.record


# The rule for the name of an entry in entries.
ENTRY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

# The known keys of config.json. Each other key is an error.
KEYS = tuple(f.name for f in fields(Config))
# The harnesses that the app can use for its model sessions (the key models).
HARNESSES = ("claude-code", "codex")
# The model APIs of the key model_api. model_api.APIS gives the variable and the URL of each.
MODEL_APIS = ("anthropic", "openai")
# The keys with a string value and no other rule here. check_message and model_reply_field
# have their own rules below.
STRING_KEYS = (
    "tap_url",
    "agent_url",
    "adapter",
    "message_field",
    "reply_field",
    "openai_model",
    "record",
)
BOOLEAN_KEYS = ("openai_stream", "evaluate", "otel", "transcript_compact", "page")
# The keys whose parser takes None for a key that is not there, and the value of an explicit null.
NULL_KEYS = ("backends", "model_api")
_NULL = object()


def _check_types(data: dict[str, Any]) -> None:
    """Check the type of each value that has its own rule here (SPEC.md section 7.1). Each key
    has one error text, so init, start, check, mode on and the relay give the same error (#121).
    """
    for key in STRING_KEYS:
        if not isinstance(data.get(key, ""), str):
            raise ConfigError(f"{FILE}: '{key}' must be a string")
    for key in BOOLEAN_KEYS:
        if not isinstance(data.get(key, False), bool):
            raise ConfigError(f"{FILE}: '{key}' must be true or false")
    entry = data.get("entry", [])
    if not (isinstance(entry, list) and all(isinstance(a, str) for a in entry)):
        raise ConfigError(f"{FILE}: 'entry' must be a list of strings")
    models = data.get("models", [])
    if not (isinstance(models, list) and all(m in HARNESSES for m in models)):
        raise ConfigError(f"{FILE}: 'models' must be a list of {', '.join(HARNESSES)}")
    # The parsers take None for a key that is not there. An explicit null is a wrong type, so it
    # goes in as a value that each parser refuses, and gives the same error text.
    given = {k: _NULL if k in data and data[k] is None else data.get(k) for k in NULL_KEYS}
    try:
        parse_backends(given["backends"])
        parse_model_api(given["model_api"])
    except ValueError as e:
        raise ConfigError(f"{FILE}: {e}") from None


def is_http_url(url: str) -> bool:
    """True if url is an http or https URL with a host and a valid port, or no port: the rule for
    the URL of a backend and of a model API (SPEC.md sections 7.6 and 7.7)."""
    parts = urlsplit(url)
    try:
        parts.port  # noqa: B018 - the property raises ValueError for a bad port
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def parse_backends(raw: Any) -> list[tuple[str, str, str]]:
    """The `backends` key: the name, the variable and the URL of each backend (SPEC.md section
    7.6). Raise ValueError if it is not valid. The proxy module uses it too, so one rule applies.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("'backends' must be a list")
    out: list[tuple[str, str, str]] = []
    for b in raw:
        if not isinstance(b, dict) or not all(
            isinstance(b.get(k), str) for k in ("name", "env", "url")
        ):
            raise ValueError("each backend needs the strings 'name', 'env' and 'url'")
        if not is_http_url(b["url"]):
            raise ValueError(f"backend {b['name']}: 'url' must be an http or https URL")
        out.append((b["name"], b["env"], b["url"].rstrip("/")))
    names = [name for name, _, _ in out]
    if len(set(names)) != len(names) or len({env for _, env, _ in out}) != len(out):
        raise ValueError("each backend needs its own 'name' and 'env'")
    return out


def parse_model_api(raw: Any) -> dict[str, str | None]:
    """The `model_api` key: the APIs to record, each with the URL from the configuration, or
    None for the URL from its variable (SPEC.md section 7.7). Raise ValueError if it is not
    valid."""
    if raw is None or raw is True:
        return dict.fromkeys(MODEL_APIS)
    if raw is False:
        return {}
    if isinstance(raw, list) and all(isinstance(x, str) and x in MODEL_APIS for x in raw):
        return dict.fromkeys(raw)
    if isinstance(raw, dict) and all(
        k in MODEL_APIS and (v is None or isinstance(v, str)) for k, v in raw.items()
    ):
        return dict(raw)
    raise ValueError(
        f"'model_api' must be true, false, a list of: {', '.join(MODEL_APIS)}, "
        "or an object from these names to a URL or null"
    )


def check(data: Any) -> dict[str, Any]:
    """Apply the rule for the keys to the parsed file. Return it, or raise ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError(f"{FILE} is not a JSON object")
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"{FILE} has unknown keys: {unknown}. Correct or remove them.")
    _check_types(data)
    message = data.get("check_message", CHECK_MESSAGE)
    if not isinstance(message, str) or not message.strip():
        raise ConfigError(f"{FILE}: 'check_message' must be a string with text")
    bad = lone_surrogate(message)
    if bad is not None:
        raise ConfigError(f"{FILE}: 'check_message' has {bad}")
    count = data.get("repeated_reply", 2)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count == 1:
        raise ConfigError(
            f"{FILE}: 'repeated_reply' must be 0 (off) or a whole number of 2 or more"
        )
    path = data.get("model_reply_field", "")
    if not isinstance(path, str) or (path and not all(path.split("."))):
        raise ConfigError(
            f"{FILE}: 'model_reply_field' must be empty or a dot path such as output.client_text"
        )
    if data.get("model_reply_match", "normalized") not in MATCHES:
        raise ConfigError(f"{FILE}: 'model_reply_match' must be exact, normalized or off")
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        raise ConfigError(f"{FILE}: 'entries' must be an object from a name to a command")
    for name, argv in entries.items():
        if not ENTRY_NAME.fullmatch(name):
            raise ConfigError(
                f"{FILE}: the entry name {name!r} must be letters, digits, '_', '.' or '-'"
            )
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
            raise ConfigError(f"{FILE}: the entry {name!r} must be a list of strings")
    return data


def _load(root: Path) -> Any:
    """The JSON value of config.json, with no check of its keys. Raise ConfigError if the file
    cannot be read or is not JSON."""
    try:
        return json.loads((root / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"cannot read {FILE}: {e}") from None


def read_config(root: Path) -> dict[str, Any]:
    """The keys of config.json as the file gives them. Raise ConfigError if the file cannot be
    read or breaks the rule for its keys."""
    return check(_load(root))


def has_entry(root: Path) -> bool:
    """True if config.json has a list `entry` with at least one item. This does not check the
    other keys. A file with an entry and an error still has an entry, so that `start` shows the
    error."""
    try:
        data = _load(root)
    except ConfigError:
        return False
    entry = data.get("entry") if isinstance(data, dict) else None
    return isinstance(entry, list) and len(entry) > 0

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
# The keys of nookku 0.5.1 and earlier that discovery replaces (SPEC.md section 7.11).
OLD_KEYS = ("backends", "model_api")
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


# The variable of an egress part: the entry gets it, and Popen refuses a name with "=" or NUL.
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def is_http_url(url: str) -> bool:
    """True if url is an http or https URL with a host and a valid port, or no port: the rule for
    the URL of a backend and of a model API (SPEC.md sections 7.6, 7.7 and 7.11)."""
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - the property raises ValueError for a bad port
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def check(data: Any) -> dict[str, Any]:
    """Apply the rule for the keys to the parsed file. Return it, or raise ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError(f"{FILE} is not a JSON object")
    old = [k for k in OLD_KEYS if k in data]
    if old:
        raise ConfigError(
            f"{FILE} has the keys {old} of nookku 0.5.1 and earlier. Nookku now finds the "
            "egress of the agent at each start (SPEC.md section 7.11). Remove the keys."
        )
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


def entry_command(relay: str = "<relay>", command: str = "<command>") -> str:
    """The command that writes the key entry. The note of init and the start refusal use it."""
    return f'nookku init {relay} --entry "{command}"'


# The refusal of a test with no entry (SPEC.md section 7.1). `start`, `check`, `run`, the prompt
# nookku start and the run_script tool of `nookku mcp` all get it from `bridge.load_config`.
NO_ENTRY = (
    f"{FILE} has no 'entry' command, so the test cannot start. Write the command that starts "
    f"your agent with: {entry_command()}. <relay> is plugin, claude-code or codex."
)


def no_entry_note(relay: str) -> str:
    """The note of `nookku init <relay>` if the config has nothing that starts or reaches an
    agent (`needs_entry`)."""
    return (
        f"Note: {FILE} has no entry, so a test cannot start yet. Write the command that starts "
        f"your agent with: {entry_command(relay, 'python3 agent.py')}. Replace python3 agent.py "
        "with your command."
    )


def needs_entry(root: Path) -> bool:
    """True if config.json has no entry (the rule of `has_entry`, which start uses) and no
    `agent_url`. Then nothing starts or reaches an agent."""
    if has_entry(root):
        return False
    try:
        data = _load(root)
    except ConfigError:
        return True
    url = data.get("agent_url") if isinstance(data, dict) else None
    return not (isinstance(url, str) and url)


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

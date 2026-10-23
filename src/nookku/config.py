"""The file .nookku/config.json (SPEC.md section 7.1): its keys and its one reader.

The relay (`nookku hook`), `start`, `check` and `init` read the file with `read_config`, so
one rule applies to its keys. Each part then checks the values that it uses.
"""

from __future__ import annotations

import errno
import json
import os
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
    # The most bytes of a body that a backend or model API proxy keeps in the record (SPEC.md
    # section 7.6). The app always gets all of the bytes.
    record_limit: int = 1024 * 1024
    # The files of the app spec, relative to the project root. The evaluation reads them first
    # (SPEC.md section 9.2, docs/reference/app-spec.md).
    spec: list[str] = field(default_factory=list)

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
    spec = data.get("spec", [])
    if not (
        isinstance(spec, list)
        and all(isinstance(p, str) and p.strip() and "\x00" not in p for p in spec)
    ):
        raise ConfigError(f"{FILE}: 'spec' must be a list of file paths")
    if len(spec) > SPEC_COUNT:
        raise ConfigError(f"{FILE}: 'spec' must have {SPEC_COUNT} paths or fewer")
    twice = sorted({p for p in spec if spec.count(p) > 1})
    if twice:
        raise ConfigError(f"{FILE}: 'spec' has the path {twice[0]!r} more than one time")


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
    limit = data.get("record_limit", 1)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ConfigError(f"{FILE}: 'record_limit' must be a whole number of bytes, 1 or more")
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


# The most bytes of one spec file (SPEC.md section 7.1). A spec is text for a model, so 1 MiB is
# a chosen bound, not a measurement.
SPEC_LIMIT = 1024 * 1024
# The most paths of the config key spec. A spec has 5 parts, so 20 files is a chosen bound.
SPEC_COUNT = 20


def spec_file(root: Path, path: str) -> Path:
    """The resolved file of one path of the config key spec. The tester or the model writes the
    path, so it must be a file in the project after symlinks resolve, and not in the state
    folder (SPEC.md section 7.1). Raise ConfigError if it breaks this rule."""
    top = root.resolve()
    try:
        file = (top / path).resolve()
    # Python 3.10 to 3.12 raise RuntimeError for a symlink loop.
    except (OSError, ValueError, RuntimeError):
        raise ConfigError(f"{FILE}: the spec file {path!r} is not a file") from None
    if not file.is_relative_to(top):
        raise ConfigError(f"{FILE}: the spec file {path!r} is not in the project folder")
    parts = file.relative_to(top).parts
    if parts and parts[0].casefold() in (STATE_DIR, OLD_STATE_DIR):
        raise ConfigError(f"{FILE}: the spec file {path!r} is in the state folder {STATE_DIR}")
    if not file.is_file():
        raise ConfigError(f"{FILE}: the spec file {path!r} is not a file")
    return file


def spec_bytes(root: Path, path: str) -> bytes:
    """The bytes of one spec file. The file is opened with no follow of a last symlink and
    must be a regular file of SPEC_LIMIT bytes or less, so a file that changes after the check
    cannot make the read follow a symlink, block or take all of the memory. Raise ConfigError."""
    return _regular_bytes(spec_file(root, path), f"{FILE}: ", f"the spec file {path!r}")


def _regular_bytes(file: Path, prefix: str, what: str) -> bytes:
    """The bytes of a regular file of SPEC_LIMIT bytes or less, read with no follow of a last
    symlink. Raise ConfigError with `prefix` and `what`, the name of the file in the error."""
    import stat

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        checked = os.stat(file)
        fd = os.open(file, flags)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise ConfigError(f"{prefix}{what} is not a file") from None
        raise ConfigError(f"{prefix}cannot read {what}: {e.strerror}") from None
    with os.fdopen(fd, "rb") as f:
        try:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ConfigError(f"{prefix}{what} is not a file")
            # A folder of the path can change between the check and the open.
            if (info.st_dev, info.st_ino) != (checked.st_dev, checked.st_ino):
                raise ConfigError(f"{prefix}{what} changed during the check")
            if info.st_size > SPEC_LIMIT:
                raise ConfigError(f"{prefix}{what} has more than {SPEC_LIMIT} bytes")
            blocks, size = [], 0
            for block in iter(lambda: f.read(1 << 16), b""):
                size += len(block)
                if size > SPEC_LIMIT:
                    raise ConfigError(f"{prefix}{what} has more than {SPEC_LIMIT} bytes")
                blocks.append(block)
        except OSError as e:
            raise ConfigError(f"{prefix}cannot read {what}: {e.strerror}") from None
    return b"".join(blocks)


# The folder of the spec copies in a test folder (SPEC.md section 7.2).
SPEC_COPIES = "spec"
# The suffix of a spec path that its copy keeps: a dot and 1 to 16 ASCII letters and digits.
_COPY_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,16}")


def spec_copy(n: int, path: str) -> str:
    """The path in the test folder of the copy of spec file `n` (from 1) with the config path
    `path`: `spec/<n>`, with the suffix of the path if it is a plain suffix (SPEC.md 7.2)."""
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    suffix = name[dot:] if dot > 0 else ""
    return f"{SPEC_COPIES}/{n}{suffix if _COPY_SUFFIX.fullmatch(suffix) else ''}"


def spec_copy_bytes(folder: Path, n: int, path: str) -> bytes:
    """The bytes of the copy of spec file `n` in a test folder, with the rule of spec_bytes.
    The copy and its folder must not be a symlink. Raise ConfigError with the cause (SPEC.md
    section 9.2)."""
    name = spec_copy(n, path)
    copy = folder / name
    if copy.parent.is_symlink() or copy.is_symlink():
        raise ConfigError(f"the copy {name} is not a file")
    if not copy.exists():
        raise ConfigError(f"the test folder has no copy {name}")
    return _regular_bytes(copy, "", f"the copy {name}")


def spec_hashes(root: Path, spec: list[str]) -> list[dict[str, str]]:
    """The path and the SHA-256 of each file of the config key spec, as the manifest records
    them (SPEC.md section 7.2). Raise ConfigError for the first path that breaks the rule."""
    return [h for h, _ in spec_contents(root, spec)]


def spec_contents(root: Path, spec: list[str]) -> list[tuple[dict[str, str], bytes]]:
    """For each file of the config key spec: its path and SHA-256 (spec_hashes) and the bytes
    that give the SHA-256, from one read. Raise ConfigError for the first path that breaks the
    rule."""
    import hashlib

    seen: dict[Path, str] = {}
    for path in spec:
        file = spec_file(root, path)
        if file in seen:
            raise ConfigError(
                f"{FILE}: the spec paths {seen[file]!r} and {path!r} name the same file"
            )
        seen[file] = path
    out = []
    for path in spec:
        data = spec_bytes(root, path)
        out.append(({"path": path, "sha256": hashlib.sha256(data).hexdigest()}, data))
    return out


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

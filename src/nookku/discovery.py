"""Egress discovery (SPEC.md section 7.11): the answer of the harness model that names each egress
part of the agent, and the pending file that keeps it until the next start.

The harness model reads the code of the agent and runs `nookku register` with the answer. The
next start takes the answer, writes it into the manifest of the test, and starts one proxy for
each part that has a proxy. The answer holds the names of the variables, never their values.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from nookku.config import ENV_NAME, STATE_DIR, is_http_url
from nookku.record import lone_surrogate

VERSION = 1
# The pending answer, until the next start takes it.
NAME = "discovery.json"
# The file of the answer that the discovery task tells the model to write (discover.md).
ANSWER_FILE = "egress.json"
# A start takes only an answer that is newer than this. It is a design value, not a measurement:
# the code of the agent can change after the answer, so an old answer must not start a test.
FRESH = 30 * 60
# The lists of an answer, in the order of the start text.
LISTS = ("model_apis", "backends", "mcp_servers", "databases", "other")
# The model APIs that a proxy can read (SPEC.md section 7.7).
MODEL_APIS = ("anthropic", "openai")
MCP_TRANSPORTS = ("stdio", "http")
# How the test records the calls of a database (SPEC.md section 7.11): the Postgres proxy, or the
# OpenTelemetry spans of the driver in the app process.
RECORDS = ("proxy", "driver")
# The database system of the semantic conventions for a `kind` that is not the same word.
# A kind of the answer that is not the system name of OpenTelemetry, for example the name of a
# Python module.
SYSTEMS = {"postgres": "postgresql", "sqlite3": "sqlite", "mongo": "mongodb"}
# An address that the coverage check can compare with a span: host:port or host:port/database.
HOST_PORT = re.compile(
    r"(?:\[(?P<v6>[^\]]+)\]|(?P<host>[^\s:/\[\]]+)):(?P<port>\d{1,5})(?:/(?P<db>[^\s/?;&]+))?"
)
# The variables that the bridge gives the entry. A part must not use one of them.
RESERVED = frozenset(
    {
        "NOOKKU_TEST_DIR",
        "NOOKKU_TEST_ID",
        "NOOKKU_TESTS_DIR",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_TRACES_EXPORTER",
        "OTEL_LOGS_EXPORTER",
        "OTEL_METRICS_EXPORTER",
        "OTEL_BSP_SCHEDULE_DELAY",
        "OTEL_BLRP_SCHEDULE_DELAY",
        "OTEL_LOGS_EXPORT_INTERVAL",
        "OTEL_TRACES_EXPORT_INTERVAL",
        "CLAUDE_CODE_ENABLE_TELEMETRY",
        "OTEL_LOG_USER_PROMPTS",
        "OTEL_LOG_TOOL_DETAILS",
    }
)
# The keys of each part. Each key is required: a value can be null only where the table says so.
PART_KEYS = {
    "model_apis": ("api", "env", "url"),
    "backends": ("name", "env", "url"),
    "mcp_servers": ("name", "transport", "env", "command", "url"),
    "databases": ("name", "kind", "env", "address", "record"),
    "other": ("name", "kind", "detail"),
}

NO_ANSWER = (
    "no test started: nookku has no egress answer from the last {minutes} minutes. Type the "
    "prompt nookku start in the harness, so that the model finds the egress of the agent. Or run "
    "nookku register with the answer (SPEC.md section 7.11)."
)


class AnswerError(ValueError):
    """The answer breaks the rule of SPEC.md section 7.11."""


@dataclass
class Part:
    """One egress part of an answer, as the start text shows it."""

    kind: str
    name: str
    line: str
    proxy: bool
    # True for a database with `record: driver`: its driver spans record its calls.
    driver: bool = False

    @property
    def seen_by(self) -> str:
        return "proxy" if self.proxy else "driver trace" if self.driver else "no proxy"


def path(root: Path) -> Path:
    return root / STATE_DIR / NAME


def _secret_free_url(where: str, url: str) -> None:
    """Refuse a URL with a user or a password, or with a value of a secret query parameter. The
    answer goes into the manifest, which the evaluation model reads."""
    from nookku.backend import secret

    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None:
        raise AnswerError(f"{where}: the URL has a user or a password. Give the variable only.")
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if value and secret(key):
            raise AnswerError(f"{where}: the URL has a value of the secret parameter {key!r}.")


def _string(where: str, value: Any, null: bool = False) -> str | None:
    if value is None and null:
        return None
    if not isinstance(value, str) or not value.strip() or lone_surrogate(value):
        raise AnswerError(f"{where} must be a text" + (" or null" if null else ""))
    return value


def _env(where: str, value: Any, null: bool = False) -> str | None:
    env = _string(f"{where} 'env'", value, null)
    if env is None:
        return None
    if not ENV_NAME.fullmatch(env):
        raise AnswerError(f"{where} 'env' must be a variable name of letters, digits and '_'")
    if env in RESERVED:
        raise AnswerError(f"{where} 'env' is the variable {env} of nookku")
    return env


def _secret_free_address(where: str, address: str) -> None:
    """Refuse a database address with a user, or with a value of a secret key: in a query after
    `?`, or in a `key=value` word."""
    from nookku.backend import secret

    if "@" in address:
        raise AnswerError(f"{where}: the address has a user or a password. Give host:port.")
    words = [w for w in re.split(r"[\s;&?]+", address) if "=" in w]
    for word in words:
        key, _, value = word.partition("=")
        key = unquote(key)
        if value and secret(key):
            raise AnswerError(f"{where}: the address has a value of the secret key {key!r}.")


def _secret_free_command(where: str, command: list[str]) -> None:
    """Refuse a command with a value of a secret key: a `key=value` or `--key=value` word, or a
    `--key` option with a next word. A word with a space, for example the program of `sh -c`, is
    split into its shell words first."""
    from nookku.backend import secret

    words = []
    for arg in command:
        words.append(arg)
        if any(c.isspace() for c in arg):
            try:
                words.extend(shlex.split(arg))
            except ValueError:
                words.extend(arg.split())
    for n, word in enumerate(words):
        key, eq, value = word.partition("=")
        name = key.lstrip("-")
        given = bool(value) if eq else key.startswith("-") and n + 1 < len(words)
        if name and given and secret(name):
            raise AnswerError(
                f"{where}: the command has a value of the secret key {name!r}. "
                "Give the value in a variable of the server."
            )


def _url(where: str, value: Any, null: bool = False) -> str | None:
    url = _string(f"{where} 'url'", value, null)
    if url is None:
        return None
    if not is_http_url(url):
        raise AnswerError(f"{where} 'url' must be an http or https URL with a host")
    _secret_free_url(where, url)
    return url


def _part(kind: str, n: int, raw: Any) -> dict[str, Any]:
    where = f"{kind}[{n}]"
    if not isinstance(raw, dict):
        raise AnswerError(f"{where} must be an object")
    keys = PART_KEYS[kind]
    if set(raw) != set(keys):
        raise AnswerError(f"{where} must have the keys {', '.join(keys)}, and no other key")
    if kind == "model_apis":
        if raw["api"] not in MODEL_APIS:
            raise AnswerError(f"{where} 'api' must be one of: {', '.join(MODEL_APIS)}")
        _env(where, raw["env"])
        _url(where, raw["url"], null=True)
    elif kind == "backends":
        _string(f"{where} 'name'", raw["name"])
        _env(where, raw["env"])
        _url(where, raw["url"])
    elif kind == "mcp_servers":
        _string(f"{where} 'name'", raw["name"])
        if raw["transport"] not in MCP_TRANSPORTS:
            raise AnswerError(f"{where} 'transport' must be one of: {', '.join(MCP_TRANSPORTS)}")
        _env(where, raw["env"], null=True)
        stdio = raw["transport"] == "stdio"
        command = raw["command"]
        if stdio != (command is not None) or stdio != (raw["url"] is None):
            raise AnswerError(
                f"{where}: a stdio server needs 'command' and a null 'url', "
                "an http server needs 'url' and a null 'command'"
            )
        if stdio and not (
            isinstance(command, list)
            and command
            and all(isinstance(a, str) and a and not lone_surrogate(a) for a in command)
        ):
            raise AnswerError(f"{where} 'command' must be a list of texts")
        if stdio:
            _secret_free_command(where, command)
        if not stdio:
            _url(where, raw["url"])
    elif kind == "databases":
        _string(f"{where} 'name'", raw["name"])
        _string(f"{where} 'kind'", raw["kind"])
        _env(where, raw["env"], null=True)
        address = _string(f"{where} 'address'", raw["address"], null=True)
        if address is not None:
            _secret_free_address(where, address)
        if raw["record"] not in RECORDS:
            raise AnswerError(f"{where} 'record' must be one of: {', '.join(RECORDS)}")
        # Only a Postgres database with a variable can have a proxy (SPEC.md section 7.13).
        if raw["record"] == "proxy" and (raw["kind"] != "postgres" or raw["env"] is None):
            raise AnswerError(
                f"{where}: only a postgres database with a variable has a proxy. "
                "Give 'record' driver."
            )
    else:
        for key in keys:
            _string(f"{where} '{key}'", raw[key])
    return dict(raw)


def parse(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """Check an answer (SPEC.md section 7.11). Return it, or raise AnswerError."""
    if not isinstance(raw, dict):
        raise AnswerError("the answer must be a JSON object")
    if set(raw) != set(LISTS):
        raise AnswerError(f"the answer must have the lists {', '.join(LISTS)}, and no other key")
    out: dict[str, list[dict[str, Any]]] = {}
    for kind in LISTS:
        if not isinstance(raw[kind], list):
            raise AnswerError(f"{kind!r} must be a list")
        out[kind] = [_part(kind, n, p) for n, p in enumerate(raw[kind])]
    names = [p["api"] for p in out["model_apis"]]
    names += [p["name"] for kind in LISTS[1:] for p in out[kind]]
    if len(set(names)) != len(names):
        raise AnswerError("each part needs its own name (a model API uses its 'api' as its name)")
    envs = [p["env"] for kind in LISTS[:4] for p in out[kind] if p["env"] is not None]
    if len(set(envs)) != len(envs):
        raise AnswerError("each part needs its own 'env'")
    # The coverage check can tell a driver call from a call around a proxy of the same system
    # only by the address of the driver database (SPEC.md section 8.6).
    proxied = {db_system(p["kind"]) for p in out["databases"] if p["record"] == "proxy"}
    for n, p in enumerate(out["databases"]):
        shared = p["record"] == "driver" and db_system(p["kind"]) in proxied
        if shared and driver_address(p["address"]) is None:
            raise AnswerError(
                f"databases[{n}]: a proxy database has the same kind, so a driver database "
                "needs the address host:port or host:port/database"
            )
    return out


def db_system(name: str) -> str:
    """The database system of a `kind` of the answer or of a span attribute, in lowercase."""
    return SYSTEMS.get(name.lower(), name.lower())


def driver_address(address: Any) -> tuple[str, int, str | None] | None:
    """The host in lowercase, the port and the database of an address `host:port` or
    `host:port/database`, else None (SPEC.md section 8.6)."""
    m = HOST_PORT.fullmatch(address) if isinstance(address, str) else None
    if m is None or not 0 < int(m["port"]) < 65536:
        return None
    return (m["v6"] or m["host"]).lower(), int(m["port"]), m["db"]


def make(**given: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """An answer with an empty list for each list that `given` does not name. parse checks it."""
    return {**{kind: [] for kind in LISTS}, **given}


def both_apis() -> list[dict[str, Any]]:
    """Both model APIs, each with the URL of its usual variable: a part list for the scripts."""
    envs = {"anthropic": "ANTHROPIC_BASE_URL", "openai": "OPENAI_BASE_URL"}
    return [{"api": api, "env": envs[api], "url": None} for api in MODEL_APIS]


def parts(answer: dict[str, list[dict[str, Any]]]) -> list[Part]:
    """Each part of an answer, with its line of the start text and True if a proxy sees it."""
    out = []
    for p in answer["model_apis"]:
        url = p["url"] or f"the URL in {p['env']} or the default"
        out.append(Part("model API", p["api"], f"{p['env']} -> {url}", True))
    for p in answer["backends"]:
        out.append(Part("backend", p["name"], f"{p['env']} -> {p['url']}", True))
    for p in answer["mcp_servers"]:
        target = " ".join(p["command"]) if p["transport"] == "stdio" else p["url"]
        # A proxy needs the variable: nookku cannot change a command or a URL in the code.
        where = f"{p['env']} -> " if p["env"] else ""
        line = f"{p['transport']} {where}{target}"
        out.append(Part("MCP server", p["name"], line, p["env"] is not None))
    for p in answer["databases"]:
        where = p["env"] or p["address"] or "no variable"
        # parse lets `proxy` only for a Postgres database with a variable (SPEC.md section 7.13).
        proxy = p["record"] == "proxy"
        out.append(Part("database", p["name"], f"{p['kind']}, {where}", proxy, not proxy))
    for p in answer["other"]:
        out.append(Part("other", p["name"], f"{p['kind']}, {p['detail']}", False))
    return out


def lines(answer: dict[str, list[dict[str, Any]]]) -> list[str]:
    """One line for each part: its kind, its name, its target, and if a proxy sees it."""
    if not any(answer.values()):
        return ["- no egress part: the agent calls no service"]
    return [f"- {p.kind} {p.name}: {p.line} ({p.seen_by})" for p in parts(answer)]


def unseen(answer: dict[str, list[dict[str, Any]]]) -> list[str]:
    """The names of the parts that no proxy and no driver trace sees. The report recommends a way
    to see their calls."""
    return [p.name for p in parts(answer) if p.seen_by == "no proxy"]


def drivers(answer: dict[str, list[dict[str, Any]]]) -> list[str]:
    """The names of the databases that the driver trace records (SPEC.md section 7.11)."""
    return [p["name"] for p in answer["databases"] if p["record"] == "driver"]


def register(root: Path, raw: Any, now: float | None = None) -> dict[str, Any]:
    """Check the answer and write it as the pending answer. Return the pending file data."""
    answer = parse(raw)
    data = {"v": VERSION, "registered": time.time() if now is None else now, "answer": answer}
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{NAME}.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return data


def pending(root: Path, now: float | None = None) -> dict[str, Any] | None:
    """The pending answer if it is valid and fresh, else None. A start checks the answer again,
    because a tool call of the model can write the file."""
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != VERSION:
        return None
    registered = data.get("registered")
    if isinstance(registered, bool) or not isinstance(registered, (int, float)):
        return None
    age = (time.time() if now is None else now) - registered
    if not 0 <= age <= FRESH:
        return None
    try:
        answer = parse(data.get("answer"))
    except AnswerError:
        return None
    return {"v": VERSION, "registered": registered, "answer": answer}


def take(root: Path) -> None:
    """Remove the pending answer and the answer file after a start used it. The next test needs
    a new answer, and a failed write of the model must not leave the old answer file."""
    path(root).unlink(missing_ok=True)
    (root / STATE_DIR / ANSWER_FILE).unlink(missing_ok=True)


def no_answer() -> str:
    return NO_ANSWER.format(minutes=FRESH // 60)


def task(root: Path) -> str:
    """The discovery task for the harness model: src/nookku/discover.md."""
    text = (Path(__file__).parent / "discover.md").read_text(encoding="utf-8")
    return text.replace("{root}", str(root)).replace("{minutes}", str(FRESH // 60))

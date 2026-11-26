"""The approvals of a test (SPEC.md section 7.18): the `Approvals` section of the app spec, the
interrupt and resume items of the tap record, and the check for an action with no approval.
The check uses no model."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any

from . import app_spec
from .adapters import AdapterError, pick
from .config import ConfigError
from .structured import structured

SECTION = "approvals"
# The key of the manifest with the rows (SPEC.md section 7.18).
KEY = "approvals"
COLUMNS = ("action", "source", "approval", "by")
# The sources of an action: the sources of a trace point, and a tool call of an MCP proxy.
SOURCES = (*app_spec.SOURCES, "mcp")
# What gives an approval: an accepted MCP elicitation, the message after an interrupt, or an
# item of the trace.
ELICITATION, MESSAGE = "elicitation", "message"
BY = (ELICITATION, MESSAGE, "session", "backend", "otel", "mcp")
# The most rows of the section. This is a chosen value, as for the trace points.
MAX_ROWS = 200
KEYS = ("action", "source", "approval", "by", "interrupt", "bind")
# A row of a test of Nookku 0.6.1 or older has no key `bind`.
OLD_KEYS = KEYS[:-1]
# A Bind is 2 dot paths: `<approval path> = <action path>`.
BIND_SPLIT = " = "
# The By kinds with an item that can hold a field of the action.
NO_BIND = (ELICITATION, MESSAGE)
# The harness and the file of an interrupt or a resume item.
TAP, TAP_FILE = "tap", "tap.jsonl"
# The most characters of the value of an interrupt in its item.
SHOWN = 200
ACCEPT, FORM = "accept", "form"


class _RowReader(app_spec.Reader):
    def __init__(self) -> None:
        super().__init__(SECTION, COLUMNS, "approvals")
        self.rows: list[tuple[str, int, dict[str, str]]] = []

    def take(self, path: str, n: int, row: dict[str, str]) -> None:
        self.rows.append((path, n, row))


def _plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def read(files: list[tuple[str, str]]) -> list[dict[str, str]]:
    """The rows of the `Approvals` sections of the spec files, for the manifest key `approvals`.
    `files` holds the path and the text of each spec file. Raise ConfigError if a part of a
    section is not valid, so the test does not start with a rule that the check cannot use."""
    reader = _RowReader()
    for path, text in files:
        reader.file(path, text)
    for p in reader.records():
        raise ConfigError(f"{p['file']} line {p['line']}: {p['problem']}")
    out: list[dict[str, str]] = []
    for path, n, cells in reader.rows:
        where = f"{path} line {n}: "
        row = {k: _plain(cells.get(k, "")) for k in KEYS}
        row["source"], row["by"] = row["source"].lower(), row["by"].lower()
        if row["bind"]:
            row["bind"] = BIND_SPLIT.join(p.strip() for p in row["bind"].split("=", 1))
        if len(out) >= MAX_ROWS:
            raise ConfigError(where + f"the app spec has more than {MAX_ROWS} Approvals rows")
        problem = row_problem(row)
        if problem is not None:
            raise ConfigError(where + problem)
        if any((r["action"], r["source"]) == (row["action"], row["source"]) for r in out):
            raise ConfigError(where + "the action has an earlier Approvals row")
        out.append(row)
    return out


def row_problem(row: Any) -> str | None:
    """The reason that a value is not a row of the manifest key `approvals`, or None."""
    if not isinstance(row, dict) or set(row) not in (set(KEYS), set(OLD_KEYS)):
        return "the row does not have the keys " + ", ".join(KEYS)
    if not all(isinstance(row[k], str) for k in row):
        return "a value of the row is not a text"
    if not row["action"]:
        return "the Approvals row has no Action"
    if row["source"] not in SOURCES:
        return "the Source must be " + ", ".join(SOURCES)
    if not row["approval"]:
        return "the Approvals row has no Approval"
    if row["by"] not in BY:
        return "the By must be " + ", ".join(BY)
    path = row["interrupt"]
    if row["by"] == MESSAGE and not (path and all(path.split("."))):
        return "the By message needs an Interrupt: a dot path such as interrupt"
    if row["by"] != MESSAGE and path:
        return "only the By message takes an Interrupt"
    return _bind_problem(row["by"], row.get("bind", ""))


def _bind_problem(by: str, bind: str) -> str | None:
    if not bind:
        return None
    if by in NO_BIND:
        return f"the By {by} cannot take a Bind: its item holds no field of the action"
    paths = bind.split(BIND_SPLIT)
    if len(paths) != 2 or not all(p and all(p.split(".")) for p in paths):
        return "the Bind must be 2 dot paths with = between them, such as order = body.order"
    return None


def _bound(it: dict[str, Any], path: str) -> str | int | Decimal | None:
    """The value at a dot path of a Bind in an item of the trace, or None (SPEC.md section
    7.18). If the path gets to a string before its last part, the walk reads the string as
    JSON, with each number exact. Only a string or a finite number is a value."""
    data: Any = it
    for key in path.split("."):
        if isinstance(data, str):
            data = structured(data, exact=True)
        try:
            data = pick(data, key)
        except AdapterError:
            return None
    if isinstance(data, float):
        # A number of the item itself is a float. Its shortest text gives the same value as the
        # text of the same number in a JSON body, so 0.1 matches 0.1.
        return Decimal(repr(data)) if math.isfinite(data) else None
    if isinstance(data, Decimal):
        return data if data.is_finite() else None
    if isinstance(data, bool) or not isinstance(data, (str, int)):
        return None
    return data


def _same(a: str | int | Decimal, b: str | int | Decimal) -> bool:
    """True if 2 values of a Bind are equal: 2 strings byte for byte, or 2 numbers in value."""
    return isinstance(a, str) == isinstance(b, str) and a == b


def of_manifest(manifest: dict[str, Any]) -> list[dict[str, str]] | None:
    """The rows of the approvals of a manifest, or None if its key `approvals` is not valid. A
    manifest with no key, from a test before the key, has no rows. A key with the value null
    is a key, and null is not valid (#640)."""
    return valid(manifest[KEY]) if KEY in manifest else []


def valid(rows: Any) -> list[dict[str, str]] | None:
    """The rows of a value of the manifest key `approvals`, or None if the value does not have
    the form of SPEC.md section 7.18."""
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        return None
    if any(row_problem(r) is not None for r in rows):
        return None
    return [dict(r) for r in rows]


def _shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= SHOWN else text[:SHOWN] + "..."


def tap_items(
    rows: list[dict[str, str]],
    exchanges: list[tuple[int, dict[str, Any]]],
    value_at: Any,
    new_item: Any,
) -> list[dict[str, Any]]:
    """The interrupt and the resume items of the tap record (SPEC.md section 7.18). `exchanges`
    holds the line and the row of each exchange. `value_at(reply, path)` gives the value at a
    dot path in the JSON of a reply, or None. `new_item(line, ts)` gives a new item of
    tap.jsonl.

    An exchange is an interrupt if its reply has a value that is not null at the Interrupt path
    of a row. The next exchange is its resume: the message of the tester after the interrupt."""
    paths = sorted({r["interrupt"] for r in rows if r["by"] == MESSAGE})
    out: list[dict[str, Any]] = []
    before: list[str] = []
    for n, (line, r) in enumerate(exchanges, 1):
        if before:
            started = r.get("started")
            ts = started if isinstance(started, (int, float)) else exchanges[n - 2][1].get("ts")
            it = new_item(line, ts)
            it.update(kind="resume", turn=n, input={"interrupts": before}, output=r.get("input"))
            out.append(it)
        before = []
        reply = r.get("reply")
        for path in paths if isinstance(reply, str) else []:
            value = value_at(reply, path)
            if value is None:
                continue
            before.append(path)
            it = new_item(line, r.get("ts"))
            it.update(kind="interrupt", turn=n, name=path, output=_shown(value))
            out.append(it)
    return out


def _approval_keys(it: dict[str, Any], succeeded: Any) -> list[tuple[str, ...]]:
    """The (by, approval, interrupt) of each row that an item of the trace approves. A failed
    item of the trace, for example a call with the status 403, approves no row."""
    kind = it["kind"]
    if kind == "elicitation":
        return [(ELICITATION, str(it["server"]), "")] if _accepted(it) else []
    if kind == "resume":
        paths = it["input"]["interrupts"] if isinstance(it["input"], dict) else []
        text = it["output"]
        return [(MESSAGE, text, p) for p in paths] if isinstance(text, str) else []
    if not succeeded(it):
        return []
    return [(source, name, "") for source, name in _keys(it) if source in BY]


def _accepted(it: dict[str, Any]) -> bool:
    """True for an elicitation that gives an approval: the mode is `form`, and the app answered
    `accept`. An `accept` of the mode `url` says only that the user agreed to open a page."""
    return bool(it["kind"] == "elicitation" and it["output"] == ACCEPT and it["name"] == FORM)


def _during(it: dict[str, Any]) -> list[tuple[Any, Any]]:
    """The (line, tool) of each tool call that had no result when the app answered an
    elicitation."""
    calls = it["input"].get("during") if isinstance(it["input"], dict) else None
    return [(c.get("line"), c.get("tool")) for c in calls or [] if isinstance(c, dict)]


def _keys(it: dict[str, Any]) -> list[tuple[str, str]]:
    """The (source, name) of an item: the keys of a trace point, and `mcp` with the name
    `mcp__<server>__<tool>` for a tool call of an MCP proxy."""
    if it["harness"] == "mcp":
        if it["kind"] == "tool_call" and it["name"] is not None:
            return [("mcp", f"mcp__{it['server']}__{it['name']}")]
        return []
    if it["harness"] == TAP:
        return []
    return app_spec.item_keys(it)


def _in_call(it: dict[str, Any], server: str, asked: set[tuple[Any, ...]]) -> bool:
    """True if the action is a tool call of an MCP proxy, and its server got an accepted
    elicitation of the same turn before the result of the call."""
    if it["harness"] != "mcp" or it["kind"] != "tool_call" or it["session"] != server:
        return False
    return (server, it["source"]["line"], it["name"], it["turn"]) in asked


def _covers(approval: dict[str, Any], path: str, value: str | int | Decimal | None) -> bool:
    """True if an approval item has the value of the action at the path of a Bind. With no
    Bind, the value is None, and each approval covers the action."""
    if value is None:
        return True
    other = _bound(approval, path)
    return other is not None and _same(other, value)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check(
    rows: list[dict[str, str]], items: list[dict[str, Any]], succeeded: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The actions with no approval (SPEC.md section 7.18), and the count of the actions of
    each row for findings.json. A found action is a dict with `turn`, `detail` and `item`.

    An action of a row has an approval if an approval of the row is in the same turn, with a
    `ts` that is the `ts` of the action or less. An action in no turn has no approval.
    `succeeded(item)` is False for a failed item of the trace."""
    given: dict[tuple[Any, ...], list[tuple[float, dict[str, Any]]]] = {}
    # The tool calls that a server asked an approval for: server, line, tool and turn.
    asked: set[tuple[Any, ...]] = set()
    for it in items:
        if it["turn"] is None or not _number(it["ts"]):
            continue
        for key in _approval_keys(it, succeeded):
            given.setdefault((*key, it["turn"]), []).append((it["ts"], it))
        if _accepted(it):
            asked.update((it["server"], line, tool, it["turn"]) for line, tool in _during(it))
    found: list[dict[str, Any]] = []
    counts: list[dict[str, Any]] = []
    for row in rows:
        want = (row["source"], row["action"])
        text = f"Approval: {row['approval']} ({row['by']})"
        paths = row.get("bind", "").split(BIND_SPLIT) if row.get("bind") else []
        actions = without = 0
        for it in items:
            if want not in _keys(it):
                continue
            actions += 1
            turn, ts = it["turn"], it["ts"]
            name = f"{row['action']} ({row['source']}): "
            value = _bound(it, paths[1]) if paths else None
            if turn is None:
                detail = f"{name}the action is in no turn, so it has no approval. {text}"
            elif paths and value is None:
                detail = f"{name}the action has no value at {paths[1]}, so it has no approval. "
                detail += text
            else:
                times = given.get((row["by"], row["approval"], row["interrupt"], turn), [])
                path = paths[0] if paths else ""
                if _number(ts) and any(t <= ts and _covers(by, path, value) for t, by in times):
                    continue
                # A row with the By elicitation has no Bind (SPEC.md section 7.18).
                if row["by"] == ELICITATION and _in_call(it, row["approval"], asked):
                    continue
                same = f"of the same {paths[1]} " if paths else ""
                detail = f"{name}no approval {same}before it in this turn. {text}"
            without += 1
            found.append({"turn": turn, "detail": detail, "item": it})
        counts.append({**row, "actions": actions, "without_approval": without})
    return found, counts

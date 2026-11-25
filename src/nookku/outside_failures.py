"""Calls that failed for a cause outside the app (SPEC.md section 8.13).

A model provider that is at its rate limit, and a service of the test that refuses each
connection, make a test fail when the app did not change. The trace counts these calls in the key
`outside_failures` of findings.json. A gate run gives a test with such a call, and no good call
after it, the verdict `inconclusive` (section 7.15). The checks use no model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nookku.player import NO_ANSWER

KEY = "outside_failures"
PROVIDER_LIMIT, LOCAL_SERVICE = "provider_limit", "local_service"
# The reasons, in the order of the rows of the key.
REASONS = (PROVIDER_LIMIT, LOCAL_SERVICE)
# The verdict of a test, and of a gate run, that a person must run again.
INCONCLUSIVE = "inconclusive"
# The HTTP status of a provider that is at a rate limit or a quota.
LIMIT_STATUS = 429
MODEL_APIS = ("model_api", "gateway")
# The harness of the items of the HTTP proxies. NO_ANSWER starts the error of a call that the
# service did not answer (section 7.6).
PROXIES = ("backend", "model_api", "mcp")
DATABASE = "database"
DATABASE_FILE = "database.jsonl"
# The start of the error of a `connect` row of a Postgres proxy with no connection (7.13).
NO_CONNECTION = "no connection: "
# The text of the OS error of a refused connection, on Linux and on macOS.
REFUSED = "Connection refused"
CALLS = ("http", "message", "tool_call", "query")
MAX_COUNT = 999_999_999


def _refused(error: Any, start: str) -> bool:
    return isinstance(error, str) and error.startswith(start) and REFUSED in error


def _reason(item: dict[str, Any]) -> str | None:
    """The reason of an item of the trace that is an outside failure, or None."""
    model = item["harness"] in MODEL_APIS and item["role"] == "assistant"
    if model and item["exit_code"] == LIMIT_STATUS:
        return PROVIDER_LIMIT
    if item["harness"] in PROXIES and _refused(item["error"], NO_ANSWER):
        return LOCAL_SERVICE
    return None


def _good(item: dict[str, Any]) -> bool:
    """A call of a proxy record that ended with no error and with a status below 400."""
    if item["harness"] in MODEL_APIS and item["role"] != "assistant":
        return False
    ok = item["error"] is None and (item["exit_code"] or 0) < 400
    return item["kind"] in CALLS and ok


def refused_connections(folder: Path, turn_of: Callable[[Any], int | None]) -> list[dict[str, Any]]:
    """Each `connect` row of database.jsonl whose connection the database refused, as a call
    with its database and its turn. The reader of the queries keeps no `connect` row (section
    8.4), so the trace has no item for it."""
    try:
        lines = (folder / DATABASE_FILE).read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        connect = isinstance(row, dict) and row.get("type") == "connect"
        if connect and _refused(row.get("error"), NO_CONNECTION):
            call = {"session": str(row.get("database") or ""), "ts": row.get("ts")}
            found.append({**call, "turn": turn_of(row.get("ts"))})
    return found


def found(
    items: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    connections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The value of the key `outside_failures`: one row for each reason with a call, or an
    empty list. `items` holds the items of the trace in their order, `errors` the model errors
    of the Codex session files, and `connections` the refused connections of the databases.

    A call is retried if a later good call of the same record and the same name is in its
    turn. A call in no turn is never retried."""
    calls: dict[str, list[tuple[int | None, bool]]] = {reason: [] for reason in REASONS}
    for n, item in enumerate(items):
        reason = _reason(item)
        if reason is None:
            continue
        same = (item["harness"], item["session"], item["turn"])
        later = (x for x in items[n + 1 :] if (x["harness"], x["session"], x["turn"]) == same)
        retried = item["turn"] is not None and any(_good(x) for x in later)
        calls[reason].append((item["turn"], retried))
    for error in errors:
        if error.get("status") == LIMIT_STATUS:
            # A model error ends the turn of the harness, so no later call is its retry.
            calls[PROVIDER_LIMIT].append((error.get("turn"), False))
    for call in connections:
        good = (
            x
            for x in items
            if x["harness"] == DATABASE
            and (x["session"], x["turn"]) == (call["session"], call["turn"])
            and isinstance(x["ts"], (int, float))
            and isinstance(call["ts"], (int, float))
            and x["ts"] >= call["ts"]
        )
        retried = call["turn"] is not None and any(_good(x) for x in good)
        calls[LOCAL_SERVICE].append((call["turn"], retried))
    rows = []
    for reason in REASONS:
        if calls[reason]:
            lost = {turn for turn, retried in calls[reason] if not retried}
            turns: list[int | None] = [*sorted(t for t in lost if t is not None)]
            rows.append(
                {
                    "reason": reason,
                    "calls": len(calls[reason]),
                    "retried": sum(1 for _, retried in calls[reason] if retried),
                    "turns": turns + ([None] if None in lost else []),
                }
            )
    return rows


def of_trace(
    folder: Path,
    items: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    turn_of: Callable[[Any], int | None],
) -> list[dict[str, Any]]:
    """The rows of the key for the trace of a test folder. `turn_of` gives the turn of a time."""
    timed = [{**e, "turn": turn_of(e.get("ts"))} for e in errors]
    return found(items, timed, refused_connections(folder, turn_of))


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_COUNT


def problem(rows: Any) -> str | None:
    """The reason that a value is not the key `outside_failures` of findings.json, or None."""
    if not isinstance(rows, list) or not rows:
        return "it is not a list with 1 row or more"
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"reason", "calls", "retried", "turns"}:
            return "a row does not have the keys reason, calls, retried and turns"
        if row["reason"] not in REASONS:
            return "a reason is not " + " or ".join(REASONS)
        if not _count(row["calls"]) or not _count(row["retried"]) or row["calls"] < 1:
            return "a count is not a whole number"
        if row["retried"] > row["calls"]:
            return "a row has more retried calls than calls"
        turns = row["turns"]
        if not isinstance(turns, list) or not all(t is None or _count(t) for t in turns):
            return "the turns of a row are not a list of turns"
        if bool(turns) != (row["retried"] < row["calls"]):
            return "the turns of a row do not agree with its counts"
    reasons = [row["reason"] for row in rows]
    if len(set(reasons)) != len(reasons):
        return "a reason has 2 rows"
    return None


def open_reasons(rows: list[dict[str, Any]]) -> list[str]:
    """Each reason of valid rows with a call that no good call followed."""
    return [row["reason"] for row in rows if row["retried"] < row["calls"]]


def of_findings(data: bytes | None) -> tuple[list[dict[str, Any]] | None, str | None]:
    """The rows of the key in the bytes of findings.json, or None if the file has no key. With
    a key that is not valid, the result is None and the problem."""
    try:
        report = json.loads(data.decode("utf-8")) if data is not None else None
    except (ValueError, RecursionError):
        return None, None
    if not isinstance(report, dict) or KEY not in report:
        return None, None
    why = problem(report[KEY])
    if why is not None:
        return None, f"The key {KEY} of findings.json is not valid: {why}."
    return report[KEY], None


def judge(test: dict[str, Any], proof: dict[str, Any] | None) -> None:
    """Put the outside failures of a test into its object of a gate result (SPEC.md section
    7.15). The check reads findings.json only after the check `evidence` passed, so it reads
    only bytes that the seal covers. A key that is not valid fails the test. A valid key with
    a call that no good call followed gives the verdict `inconclusive`."""
    checks = test["checks"]
    if not any(c["check"] == "evidence" and c["verdict"] == "pass" for c in checks):
        return
    rows, why = of_findings(((proof or {}).get("files") or {}).get("findings.json"))
    if why is not None:
        checks.append({"check": KEY, "verdict": "fail", "text": why})
        test["verdict"] = "fail"
    if rows is not None:
        test[KEY] = rows
        if open_reasons(rows):
            test["verdict"] = INCONCLUSIVE


def waiting(tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One object for each reason of each inconclusive test of a gate result, in the order of
    the tests: the test, the reason, the calls and the retried calls."""
    return [
        {
            "test": t["name"],
            "reason": row["reason"],
            "calls": row["calls"],
            "retried": row["retried"],
        }
        for t in tests
        if t["verdict"] == INCONCLUSIVE
        for row in t[KEY]
        if row["retried"] < row["calls"]
    ]


def summary(report: dict[str, Any]) -> list[str]:
    """The lines of the outside failures of a gate result, for `nookku gate`."""
    lines = []
    for test in report["tests"]:
        for row in test.get(KEY, []):
            text = f"{row['reason']}, {row['calls']} calls, {row['retried']} retried"
            lines.append(f"Outside failure in {test['name']}: {text}.")
    names = {w["test"] for w in report.get(INCONCLUSIVE, [])}
    if names:
        lines.append(f"Inconclusive tests: {len(names)}. Run the gate again.")
    return lines

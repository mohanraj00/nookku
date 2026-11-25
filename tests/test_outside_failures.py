"""Calls that failed for a cause outside the app: a provider limit and a refused service (#671)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nookku import outside_failures, trace

REFUSED = "the backend did not answer: [Errno 111] Connection refused"


def _item(harness: str, session: str, turn: int | None, **fields: Any) -> dict[str, Any]:
    """An item of the trace with the fields that the check reads."""
    kind = {"backend": "http", "mcp": "tool_call", "database": "query"}.get(harness, "message")
    role = "assistant" if kind == "message" else None
    base = {"harness": harness, "session": session, "turn": turn, "kind": kind, "role": role}
    return {**base, "ts": 1.0, "error": None, "exit_code": None, **fields}


def _model(turn: int | None, status: int, **fields: Any) -> dict[str, Any]:
    error = "Rate limit reached" if status == 429 else None
    return _item("model_api", "openai", turn, **{"exit_code": status, "error": error, **fields})


def _test(findings: dict[str, Any] | None) -> dict[str, Any]:
    """The object of a test of a gate result after the check of its outside failures."""
    checks = [{"check": "evidence", "verdict": "pass", "text": None}]
    test = {"name": "stock", "verdict": "pass", "checks": checks}
    data = None if findings is None else json.dumps(findings).encode()
    outside_failures.judge(test, {"files": {"findings.json": data}})
    return test


def test_a_429_on_each_call_gives_inconclusive_with_provider_limit() -> None:
    # Each call of the app to the model API gets status 429, in 2 turns.
    items = [_model(1, 429), _model(1, 429), _model(2, 429)]
    rows = outside_failures.found(items, [], [])
    assert rows == [{"reason": "provider_limit", "calls": 3, "retried": 0, "turns": [1, 2]}]
    test = _test({"outside_failures": rows})
    assert test["verdict"] == "inconclusive" and test["outside_failures"] == rows
    assert outside_failures.waiting([test]) == [
        {"test": "stock", "reason": "provider_limit", "calls": 3, "retried": 0}
    ]


def test_one_429_with_a_good_call_after_it_keeps_the_verdict() -> None:
    # The app tries again in the same turn, and the second call gives the answer.
    items = [_model(1, 200), _model(2, 429), _model(2, 200)]
    rows = outside_failures.found(items, [], [])
    assert rows == [{"reason": "provider_limit", "calls": 1, "retried": 1, "turns": []}]
    test = _test({"outside_failures": rows})
    # The result records the retried call, and the test keeps the verdict of its checks.
    assert test["verdict"] == "pass" and test["outside_failures"] == rows
    assert outside_failures.waiting([test]) == []


def test_a_refused_local_port_gives_inconclusive_with_local_service(tmp_path: Path) -> None:
    items = [_item("backend", "stock", 2, error=REFUSED)]
    rows = outside_failures.found(items, [], [])
    assert rows == [{"reason": "local_service", "calls": 1, "retried": 0, "turns": [2]}]
    assert _test({"outside_failures": rows})["verdict"] == "inconclusive"
    # A Postgres proxy writes a `connect` row for a refused connection, and the trace has no
    # item for it (#660).
    connects = [
        {"type": "connect", "database": "orders", "ts": 5.0, "error": None},
        {"type": "connect", "database": "orders", "ts": 15.0},
        {"type": "connect", "database": "orders", "ts": 16.0, "error": "no connection: timed out"},
        {
            "type": "connect",
            "database": "orders",
            "ts": 17.0,
            "error": "no connection: [Errno 61] Connection refused",
        },
    ]
    text = "".join(json.dumps(row) + "\n" for row in connects) + "not JSON\n"
    (tmp_path / "database.jsonl").write_text(text)
    rows = outside_failures.of_trace(tmp_path, [], [], lambda ts: 2 if ts > 10 else 1)
    assert rows == [{"reason": "local_service", "calls": 1, "retried": 0, "turns": [2]}]
    # A later query of the same database in the same turn shows that the next connection came.
    later = _item("database", "orders", 2, ts=18.0)
    rows = outside_failures.of_trace(tmp_path, [later], [], lambda ts: 2 if ts > 10 else 1)
    assert rows == [{"reason": "local_service", "calls": 1, "retried": 1, "turns": []}]


def test_a_refused_mcp_call_with_no_item_is_a_refused_service(tmp_path: Path) -> None:
    # The reader of mcp.jsonl gives an item for a tool call only. A refused `initialize` or
    # `tools/list` call has no item, so the check reads the rows of the record.
    def call(server: str, started: Any, status: int | None, error: str | None = None) -> str:
        row = {"type": "call", "server": server, "started": started, "ts": None}
        return json.dumps({**row, "status": status, "error": error}) + "\n"

    rows = [
        call("tickets", 12.0, None, REFUSED),
        # The next call of the same server in the same turn gets an answer.
        call("tickets", 13.0, 200),
        call("tickets", 32.0, None, REFUSED),
        # None of these rows is a good call of the server tickets after the refused call.
        call("orders", 33.0, 200),
        call("tickets", 34.0, 500),
        call("tickets", 35.0, None, "the backend did not answer: timed out"),
        json.dumps({"type": "message", "server": "tickets", "ts": 36.0}) + "\n",
        "not JSON\n",
    ]
    (tmp_path / "mcp.jsonl").write_text("".join(rows))

    def turn_of(ts: Any) -> int | None:
        return None if ts is None else 2 if ts > 20 else 1

    want = [{"reason": "local_service", "calls": 2, "retried": 1, "turns": [2]}]
    assert outside_failures.of_trace(tmp_path, [], [], turn_of) == want
    # A refused tool call has an item of the trace, so its row does not count 2 times.
    source = {"file": "mcp.jsonl", "line": 3}
    item = _item("mcp", "tickets", 2, error=REFUSED, source=source)
    assert outside_failures.of_trace(tmp_path, [item], [], turn_of) == want
    # A call in no turn is never retried.
    (tmp_path / "mcp.jsonl").write_text(call("tickets", None, None, REFUSED) + rows[1])
    assert outside_failures.of_trace(tmp_path, [], [], turn_of) == [
        {"reason": "local_service", "calls": 1, "retried": 0, "turns": [None]}
    ]


def test_only_a_good_call_of_the_same_api_in_the_same_turn_is_a_retry() -> None:
    user = _item("model_api", "openai", 1, role="user")
    other_api = _item("model_api", "claude", 1, exit_code=200)
    next_turn = _model(2, 200)
    failed = _model(1, 500, error="Server error")
    rows = outside_failures.found([_model(1, 429), user, other_api, failed, next_turn], [], [])
    assert rows == [{"reason": "provider_limit", "calls": 1, "retried": 0, "turns": [1]}]
    # A call in no turn is never retried, and its turn is null.
    rows = outside_failures.found([_model(None, 429), _model(None, 200), _model(3, 429)], [], [])
    assert rows == [{"reason": "provider_limit", "calls": 2, "retried": 0, "turns": [3, None]}]
    # A gateway call and a model API call have the same rule. The 2 reasons give 2 rows.
    gateway = _item("gateway", "kd-1", 1, exit_code=429)
    mcp = _item("mcp", "orders", 1, error=REFUSED)
    rows = outside_failures.found([gateway, mcp], [], [])
    assert [(r["reason"], r["calls"]) for r in rows] == [
        ("provider_limit", 1),
        ("local_service", 1),
    ]


@pytest.mark.parametrize(
    "item",
    [
        _model(1, 500, error="Server error"),
        _model(1, 200),
        _item("backend", "stock", 1, exit_code=429),
        _item("backend", "stock", 1, error="the backend did not answer: timed out"),
        _item("backend", "stock", 1, error="the proxy refused the request: Connection refused"),
        _item("otel", "t1", 1, kind="span", error=REFUSED),
    ],
)
def test_another_failure_is_not_an_outside_failure(item: dict[str, Any]) -> None:
    assert outside_failures.found([item], [], []) == []
    assert "outside_failures" not in _test({"counts": {}})


def test_a_codex_model_error_with_status_429_is_a_provider_limit(tmp_path: Path) -> None:
    def row(info: Any) -> str:
        error = {"message": "The model is at its limit.", "codex_error_info": info}
        payload = {"type": "task_complete", "error": error}
        line = {"type": "event_msg", "timestamp": "2026-11-20T10:15:00Z", "payload": payload}
        return json.dumps(line) + "\n"

    path = tmp_path / "rollout.jsonl"
    path.write_text(
        row({"http_connection_failed": {"http_status_code": 429}})
        + row({"http_connection_failed": {"http_status_code": 503}})
        + row("server_overloaded")
    )
    errors = trace.read_codex_errors(path)
    assert [e["status"] for e in errors] == [429, 503, None]
    assert errors[0]["detail"].startswith("http_connection_failed (status 429): ")
    rows = outside_failures.of_trace(tmp_path, [], errors, lambda ts: 1)
    assert rows == [{"reason": "provider_limit", "calls": 1, "retried": 0, "turns": [1]}]


@pytest.mark.parametrize(
    "rows, problem",
    [
        ([], "it is not a list with 1 row or more"),
        ({}, "it is not a list with 1 row or more"),
        ([{"reason": "provider_limit"}], "a row does not have the keys"),
        ([{"reason": "tone", "calls": 1, "retried": 0, "turns": [1]}], "a reason is not"),
        ([{"reason": "local_service", "calls": 0, "retried": 0, "turns": []}], "a count is not"),
        ([{"reason": "local_service", "calls": True, "retried": 0, "turns": [1]}], "a count is"),
        ([{"reason": "local_service", "calls": 1, "retried": 2, "turns": []}], "more retried"),
        ([{"reason": "local_service", "calls": 1, "retried": 0, "turns": ["1"]}], "the turns"),
        ([{"reason": "local_service", "calls": 1, "retried": 0, "turns": []}], "do not agree"),
        ([{"reason": "local_service", "calls": 1, "retried": 1, "turns": [1]}], "do not agree"),
        ([{"reason": "local_service", "calls": 1, "retried": 0, "turns": [1]}] * 2, "has 2 rows"),
    ],
)
def test_a_key_that_is_not_valid_fails_the_test(rows: Any, problem: str) -> None:
    found = outside_failures.problem(rows)
    assert found is not None and problem in found
    test = _test({"outside_failures": rows})
    # The gate never reads counts that break the rule, so the test fails closed.
    assert test["verdict"] == "fail" and "outside_failures" not in test
    assert test["checks"][-1] == {
        "check": "outside_failures",
        "verdict": "fail",
        "text": f"The key outside_failures of findings.json is not valid: {found}.",
    }


def test_the_check_reads_findings_only_after_the_evidence_check() -> None:
    rows = [{"reason": "provider_limit", "calls": 1, "retried": 0, "turns": [1]}]
    data = json.dumps({"outside_failures": rows}).encode()
    for checks in (
        [{"check": "missing_test", "verdict": "fail", "text": "The test did not run."}],
        [{"check": "evidence", "verdict": "fail", "text": "The seal is not intact."}],
    ):
        test = {"name": "stock", "verdict": "fail", "checks": checks}
        outside_failures.judge(test, {"files": {"findings.json": data}})
        assert test["verdict"] == "fail" and "outside_failures" not in test

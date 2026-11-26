"""The approvals of a test (SPEC.md section 7.18)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nookku import approvals, bridge, trace
from nookku.config import ConfigError

SECTION = """# Toy shop

## Approvals

| Action | Source | Approval | By | Interrupt |
|---|---|---|---|---|
{rows}
"""
REFUND = "| `shop POST /refund` | Backend | `payments` | Elicitation | |"
CANCEL = "| `shop POST /orders/cancel` | backend | yes | message | `interrupt.action` |"


def _read(rows: str) -> list[dict[str, str]]:
    return approvals.read([("APP_SPEC.md", SECTION.format(rows=rows))])


def _read_bind(rows: str) -> list[dict[str, str]]:
    head = "| Action | Source | Approval | By | Interrupt | Bind |\n|---|---|---|---|---|---|"
    return approvals.read([("APP_SPEC.md", f"## Approvals\n\n{head}\n{rows}\n")])


def _row(
    action: str, source: str, approval: str, by: str, interrupt: str = "", bind: str = ""
) -> dict[str, str]:
    return {
        "action": action,
        "source": source,
        "approval": approval,
        "by": by,
        "interrupt": interrupt,
        "bind": bind,
    }


REFUND_ROW = _row("shop POST /refund", "backend", "payments", "elicitation")
CREDIT_ROW = _row("shop POST /credit", "backend", "shop POST /approvals", "backend")
CANCEL_ROW = _row("shop POST /orders/cancel", "backend", "yes", "message", "interrupt.action")


def test_the_section_gives_the_rows_of_the_manifest() -> None:
    assert _read(REFUND + "\n" + CANCEL) == [REFUND_ROW, CANCEL_ROW]


def test_a_spec_with_no_section_has_no_row() -> None:
    assert approvals.read([("APP_SPEC.md", "# Toy shop\n")]) == []


def test_the_interrupt_column_is_optional() -> None:
    text = "## Approvals\n\n| By | Approval | Action | Source |\n|---|---|---|---|\n"
    text += "| otel | `approval.given` | `mcp__refunds__refund` | mcp |\n"
    assert approvals.read([("APP_SPEC.md", text)]) == [
        _row("mcp__refunds__refund", "mcp", "approval.given", "otel")
    ]


def test_the_bind_column_gives_2_paths_with_one_space_at_each_side() -> None:
    rows = "| `shop POST /credit` | backend | `shop POST /approvals` | backend | | "
    rows += "`input.body.order`=  `input.body.order` |"
    bind = "input.body.order = input.body.order"
    assert _read_bind(rows) == [
        _row("shop POST /credit", "backend", "shop POST /approvals", "backend", bind=bind)
    ]


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        ("| | backend | `payments` | elicitation | |", "line 7: the Approvals row has no Action"),
        ("| `a` | file | `payments` | elicitation | |", "line 7: the Source must be session,"),
        ("| `a` | backend | | elicitation | |", "line 7: the Approvals row has no Approval"),
        ("| `a` | backend | `payments` | person | |", "line 7: the By must be elicitation,"),
        ("| `a` | backend | yes | message | |", "line 7: the By message needs an Interrupt"),
        ("| `a` | backend | yes | message | `a..b` |", "line 7: the By message needs an Interrupt"),
        ("| `a` | backend | `p` | elicitation | `x` |", "only the By message takes an Interrupt"),
        (REFUND + "\n" + REFUND, "line 8: the action has an earlier Approvals row"),
        ("| `a` | backend | `p` | elicitation | | `x = y` |", "the By elicitation cannot take"),
        ("| `a` | backend | yes | message | `i` | `x = y` |", "the By message cannot take a Bind"),
        ("| `a` | backend | `p` | backend | | `x` |", "the Bind must be 2 dot paths"),
        ("| `a` | backend | `p` | backend | | `x = ` |", "the Bind must be 2 dot paths"),
        ("| `a` | backend | `p` | backend | | `x..y = z` |", "the Bind must be 2 dot paths"),
        ("| `a` | backend | `p` | backend | | `x = y = z` |", "the Bind must be 2 dot paths"),
        ("| `a` | backend | `payments` |", "line 7: "),
    ],
)
def test_a_section_that_is_not_valid_stops_the_start(rows: str, error: str) -> None:
    with pytest.raises(ConfigError) as e:
        _read_bind(rows) if rows.count("|") == 7 else _read(rows)
    assert str(e.value).startswith("APP_SPEC.md ") and error in str(e.value)


def test_a_section_with_no_table_stops_the_start() -> None:
    with pytest.raises(ConfigError, match="line 1: The section has no table"):
        approvals.read([("APP_SPEC.md", "## Approvals\n\nA refund needs an approval.\n")])


def test_more_rows_than_the_limit_stop_the_start() -> None:
    rows = "\n".join(
        f"| `shop POST /refund/{n}` | backend | `payments` | elicitation | |"
        for n in range(approvals.MAX_ROWS + 1)
    )
    with pytest.raises(ConfigError, match="more than 200 Approvals rows"):
        _read(rows)


def test_the_bridge_records_the_rows_and_refuses_a_bad_section(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    config = {"entry": ["python3", "agent.py"], "spec": ["APP_SPEC.md"]}
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps(config))
    (tmp_path / "APP_SPEC.md").write_text(SECTION.format(rows=REFUND))
    assert bridge.load_config(tmp_path).approvals == [REFUND_ROW]
    (tmp_path / "APP_SPEC.md").write_text(SECTION.format(rows="| `a` | file | `p` | mcp | |"))
    with pytest.raises(bridge.BridgeError, match="line 7: the Source must be"):
        bridge.load_config(tmp_path)


@pytest.mark.parametrize(
    "rows",
    [
        {},
        "rows",
        None,
        [{"action": "a", "source": "backend"}],
        [{**REFUND_ROW, "more": ""}],
        [{**REFUND_ROW, "by": 1}],
        [{**REFUND_ROW, "source": "Backend"}],
        [{**CANCEL_ROW, "interrupt": ""}],
        [{**REFUND_ROW, "bind": "x = y"}],
        [{**CANCEL_ROW, "bind": "x = y"}],
        [{**CREDIT_ROW, "bind": "x"}],
        [{**CREDIT_ROW, "bind": "x=y"}],
        [{**CREDIT_ROW, "bind": None}],
        [REFUND_ROW] * (approvals.MAX_ROWS + 1),
    ],
)
def test_a_manifest_key_that_is_not_valid_has_no_rows(rows: Any) -> None:
    assert approvals.valid(rows) is None


def test_a_row_of_an_older_test_with_no_key_bind_is_valid() -> None:
    old = {k: v for k, v in REFUND_ROW.items() if k != "bind"}
    assert approvals.valid([old]) == [old]
    assert _found([old], [_accept(1, 5.0), _refund(1, 6.0)]) == []


def test_a_manifest_with_no_key_has_no_rows_and_no_finding() -> None:
    assert approvals.of_manifest({"test": "t1"}) == []
    assert approvals.of_manifest({"approvals": [REFUND_ROW]}) == [REFUND_ROW]
    assert approvals.valid([REFUND_ROW]) == [REFUND_ROW]
    # A key with the value null is a key that is not valid, not a manifest with no key (#640).
    assert approvals.of_manifest({"approvals": None}) is None
    assert approvals.of_manifest({"approvals": {}}) is None
    assert trace.actions_without_approval([], []) == []


def _item(
    kind: str, harness: str, turn: int | None, ts: float | None, **more: Any
) -> dict[str, Any]:
    it = trace._item(harness, more.pop("session", ""), f"{harness}.jsonl", more.pop("line", 1), ts)
    it.update(kind=kind, turn=turn, **more)
    return it


def _refund(turn: int | None, ts: float | None, line: int = 1) -> dict[str, Any]:
    return _item("http", "backend", turn, ts, session="shop", name="POST /refund", line=line)


def _accept(
    turn: int | None, ts: float | None, output: str | None = "accept", **more: Any
) -> dict[str, Any]:
    more.setdefault("input", {"message": "Refund?", "during": []})
    more.setdefault("name", "form")
    return _item(
        "elicitation", "mcp", turn, ts, session="payments", server="payments", output=output, **more
    )


def _found(rows: list[dict[str, str]], items: list[dict[str, Any]]) -> list[tuple[int | None, str]]:
    return [(f["turn"], f["detail"]) for f in trace.actions_without_approval(items, rows)]


NONE = "shop POST /refund (backend): no approval before it in this turn. "
NONE += "Approval: payments (elicitation)"


def test_an_approval_at_the_time_of_the_action_or_before_it_counts() -> None:
    assert _found([REFUND_ROW], [_accept(1, 5.0), _refund(1, 5.0)]) == []
    assert _found([REFUND_ROW], [_accept(1, 5.1), _refund(1, 5.0)]) == [(1, NONE)]


def test_an_approval_of_another_turn_does_not_count() -> None:
    assert _found([REFUND_ROW], [_accept(1, 5.0), _refund(2, 25.0)]) == [(2, NONE)]


def test_one_approval_covers_each_later_action_of_its_row_in_the_turn() -> None:
    items = [_accept(1, 5.0), _refund(1, 6.0), _refund(1, 7.0, line=2)]
    assert _found([REFUND_ROW], items) == []


@pytest.mark.parametrize(
    "approval",
    [
        _accept(1, 5.0, output="decline"),
        _accept(1, 5.0, output="cancel"),
        _accept(1, 5.0, output=None, error="no answer in mcp.jsonl"),
        _accept(1, 5.0, name="url"),
        _accept(1, 5.0, name=None),
        _accept(None, 5.0),
        _accept(1, None),
        {**_accept(1, 5.0), "session": "stock", "server": "stock"},
    ],
)
def test_an_item_that_is_not_an_accepted_elicitation_of_the_server_approves_nothing(
    approval: dict[str, Any],
) -> None:
    assert _found([REFUND_ROW], [approval, _refund(1, 6.0)]) == [(1, NONE)]


def test_an_action_in_no_turn_or_with_no_time_has_no_approval() -> None:
    found = _found([REFUND_ROW], [_accept(1, 5.0), _refund(None, 45.0), _refund(1, None)])
    assert found == [
        (
            None,
            "shop POST /refund (backend): the action is in no turn, so it has no approval. "
            "Approval: payments (elicitation)",
        ),
        (1, NONE),
    ]


def _tool(turn: int, ts: float, line: int, server: str = "refunds") -> dict[str, Any]:
    return _item(
        "tool_call", "mcp", turn, ts, session=server, server=server, name="refund", line=line
    )


TOOL_ROW = _row("mcp__refunds__refund", "mcp", "refunds", "elicitation")


def test_an_accept_before_the_result_of_a_tool_call_approves_that_call_only() -> None:
    during = {"message": "Refund?", "during": [{"line": 4, "tool": "refund"}]}
    accept = {**_accept(1, 6.0, input=during), "session": "refunds", "server": "refunds"}
    assert _found([TOOL_ROW], [_tool(1, 5.0, 4), accept]) == []
    found = _found([TOOL_ROW], [_tool(1, 5.0, 3), _tool(1, 5.5, 4), accept])
    assert [turn for turn, _ in found] == [1]
    # An accept of another turn does not approve the call.
    assert len(_found([TOOL_ROW], [_tool(1, 5.0, 4), {**accept, "turn": 2}])) == 1
    # A decline does not approve the call.
    assert len(_found([TOOL_ROW], [_tool(1, 5.0, 4), {**accept, "output": "decline"}])) == 1


def test_a_failed_item_of_the_trace_is_not_an_approval() -> None:
    row = _row("shop POST /refund", "backend", "shop POST /approvals", "backend")
    ok = _item("http", "backend", 1, 4.0, session="shop", name="POST /approvals", exit_code=200)
    assert _found([row], [ok, _refund(1, 5.0)]) == []
    for bad in ({"exit_code": 403}, {"error": "the backend did not answer"}):
        assert len(_found([row], [{**ok, **bad}, _refund(1, 5.0)])) == 1


def test_a_session_tool_call_can_be_the_action_and_the_approval() -> None:
    row = _row("mcp__shop__refund", "session", "ask_approval", "session")

    def call(ts: float, name: str, server: str | None) -> dict[str, Any]:
        return _item("tool_call", "claude-code", 1, ts, session="s1", name=name, server=server)

    assert _found([row], [call(4.0, "ask_approval", None), call(5.0, "refund", "shop")]) == []
    assert len(_found([row], [call(5.0, "refund", "shop"), call(6.0, "ask_approval", None)])) == 1


def test_the_resume_must_have_the_text_and_the_interrupt_of_the_row() -> None:
    cancel = _item("http", "backend", 2, 32.0, session="shop", name="POST /orders/cancel")

    def resume(text: str, paths: list[str]) -> dict[str, Any]:
        return _item("resume", "tap", 2, 30.0, input={"interrupts": paths}, output=text)

    assert _found([CANCEL_ROW], [resume("yes", ["interrupt.action"]), cancel]) == []
    for item in (resume("Yes", ["interrupt.action"]), resume("yes", ["interrupt"])):
        assert len(_found([CANCEL_ROW], [item, cancel])) == 1


def _exchange(
    n: int, message: str, reply: str | None, started: bool = True
) -> tuple[int, dict[str, Any]]:
    row: dict[str, Any] = {"type": "exchange", "input": message, "reply": reply, "ts": 20.0 * n}
    if started:
        row["started"] = 20.0 * n - 10
    return n, row


def _tap_items(exchanges: list[tuple[int, dict[str, Any]]]) -> list[tuple[Any, ...]]:
    def value_at(reply: str, path: str) -> Any:
        return trace._at(trace._structured(reply), path)

    def new_item(line: int, ts: Any) -> dict[str, Any]:
        return trace._item("tap", "", "tap.jsonl", line, ts)

    items = approvals.tap_items([CANCEL_ROW], exchanges, value_at, new_item)
    return [
        (it["kind"], it["turn"], it["ts"], it["name"], it["input"], it["output"]) for it in items
    ]


def test_the_tap_gives_the_interrupt_and_the_resume_items() -> None:
    ask = '{"reply": "Do I cancel?", "interrupt": {"action": {"order": "5120"}}}'
    exchanges = [
        _exchange(1, "Cancel order 5120.", ask),
        _exchange(2, "yes", '{"interrupt": null}', started=False),
        _exchange(3, "Thanks.", "not JSON"),
        _exchange(4, "Hello.", None),
    ]
    paths = {"interrupts": ["interrupt.action"]}
    assert _tap_items(exchanges) == [
        ("interrupt", 1, 20.0, "interrupt.action", None, '{"order": "5120"}'),
        # An exchange with no `started` has the time of the reply before it.
        ("resume", 2, 20.0, None, paths, "yes"),
    ]


def test_a_long_value_of_an_interrupt_is_cut() -> None:
    reply = json.dumps({"interrupt": {"action": "x" * 300}})
    (item,) = _tap_items([_exchange(1, "Cancel.", reply)])
    assert item[5] == '"' + "x" * 199 + "..."


def test_approvals_that_are_not_valid_give_one_finding() -> None:
    found = trace.actions_without_approval([_refund(1, 5.0)], None)
    assert [(f["check"], f["turn"], f["detail"]) for f in found] == [
        ("action_without_approval", None, trace.APPROVALS_UNUSABLE)
    ]


def _call(ts: float, name: str, given: Any) -> dict[str, Any]:
    """A tool call of a session: `refund` of the MCP server `shop`, or the tool `ask_approval`."""
    server = "shop" if name == "refund" else None
    return _item(
        "tool_call", "claude-code", 1, ts, session="s1", name=name, server=server, input=given
    )


def test_a_bind_reads_a_dict_and_the_json_of_a_text_in_a_code_fence() -> None:
    row = _row(
        "mcp__shop__refund", "session", "ask_approval", "session", bind="output.order = input.order"
    )
    ask = {**_call(4.0, "ask_approval", {}), "output": 'Approved:\n```json\n{"order": "4471"}\n```'}
    assert _found([row], [ask, _call(5.0, "refund", {"order": "4471"})]) == []
    detail = "mcp__shop__refund (session): no approval of the same input.order before it in this "
    detail += "turn. Approval: ask_approval (session)"
    assert _found([row], [ask, _call(5.0, "refund", {"order": "9999"})]) == [(1, detail)]


@pytest.mark.parametrize(
    ("approved", "action"),
    [(True, 1), (1, True), ("1", 1), (None, None), ([1], [1]), ({"a": 1}, {"a": 1})],
)
def test_a_bind_matches_only_2_equal_strings_or_2_equal_numbers(approved: Any, action: Any) -> None:
    row = _row("mcp__shop__refund", "session", "ask_approval", "session", bind="input.o = input.o")
    items = [_call(4.0, "ask_approval", {"o": approved}), _call(5.0, "refund", {"o": action})]
    assert len(_found([row], items)) == 1
    items = [_call(4.0, "ask_approval", {"o": 2.0}), _call(5.0, "refund", {"o": 2})]
    assert _found([row], items) == []

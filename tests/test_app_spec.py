"""The trace points of the app spec (SPEC.md sections 7.2 and 8.6)."""

import json
import time
from pathlib import Path

import pytest

from nookku import app_spec, bridge, trace

CASES = sorted(
    (Path(__file__).resolve().parent.parent / "conformance" / "trace_points").glob("*.json")
)


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_each_case_gives_its_trace_points(case: Path) -> None:
    data = json.loads(case.read_text(encoding="utf-8"))
    points, unread = app_spec.read([(path, text) for path, text in data["files"]])
    assert {"points": points, "unread": unread} == data["expect"]


def test_a_long_heading_line_is_read_in_linear_time() -> None:
    # A regex with three white space parts takes 15 s for 2000 spaces. The parse must not.
    line = "# a" + " " * 200_000 + "x\n"
    start = time.monotonic()
    assert app_spec.read([("APP_SPEC.md", line * 5)]) == ([], [])
    assert time.monotonic() - start < 2


def test_a_closing_heading_mark_is_not_part_of_the_text() -> None:
    texts = ["## Trace points ##", "## Trace points#", "##", "#Trace points", "   # a", "    # a"]
    assert [app_spec._heading(t) for t in texts] == [
        "Trace points",
        "Trace points#",
        "",
        None,
        "a",
        None,
    ]


@pytest.mark.parametrize(
    ("source", "when", "form"),
    [
        ("otel", "Each turn", ("each_turn", None)),
        ("backend", " each TURN. ", ("each_turn", None)),
        ("session", "Turn 3.", ("turn", 3)),
        ("backend", "Each `check_stock` tool call.", ("each_call", "check_stock")),
        ("model_api", "Each turn that asks about stock.", None),
        ("session", "Turn 0", None),
        ("session", "Turn 999999999", ("turn", 999999999)),
        ("session", "Turn " + "9" * 10, None),
        ("session", "Turn " + "9" * 5000, None),
        ("session", "Each turn, after the reply", None),
        ("database", "Each turn", None),
        ("mcp", "Each turn", None),
    ],
)
def test_only_a_known_source_and_when_form_is_checked(source: str, when: str, form: object) -> None:
    assert app_spec.rule({"name": "x", "source": source, "when": when}) == form


def _item(turn: int | None, harness: str, kind: str, name: str | None, **more: object) -> dict:
    it = {"turn": turn, "harness": harness, "kind": kind, "name": name, "role": None}
    return {"session": "s", "harness_internal": False, **it, **more}


def test_a_tool_call_needs_one_item_for_each_call_in_its_turn() -> None:
    point = {
        "name": "stock GET /stock",
        "source": "backend",
        "when": "Each `check_stock` tool call",
    }
    items = [
        _item(1, "claude-code", "tool_call", "check_stock"),
        _item(1, "claude-code", "tool_call", "check_stock"),
        _item(1, "backend", "http", "GET /stock", session="stock"),
        _item(2, "codex", "tool_call", "check_stock"),
        _item(2, "backend", "http", "GET /stock", session="stock"),
        # A call with no turn needs nothing, and a harness tool is not a tool of the app.
        _item(None, "claude-code", "tool_call", "check_stock"),
        _item(3, "claude-code", "tool_call", "check_stock", harness_internal=True),
    ]
    assert app_spec.missing([point], items, 3) == [
        (
            1,
            "stock GET /stock (backend): 1 of 2 items for 2 check_stock tool calls in this "
            "turn. When: Each check_stock tool call",
        ),
    ]


def test_an_item_of_another_source_does_not_count() -> None:
    points = [
        {"name": "openai", "source": "model_api", "when": "Each turn"},
        {"name": "lookup_order", "source": "session", "when": "Turn 1"},
        {"name": "user", "source": "session", "when": "Turn 2"},
        {"name": "shop.reply", "source": "otel", "when": "Turn 1"},
    ]
    items = [
        # The user message of a model API call is not the call: its assistant message is.
        _item(1, "model_api", "message", None, role="user", session="openai"),
        _item(1, "mcp", "tool_call", "lookup_order"),
        _item(2, "model_api", "message", None, role="user", session="openai"),
        _item(1, "claude-code", "span", "shop.reply"),
    ]
    found = app_spec.missing(points, items, 2)
    assert [(turn, detail.split(" (")[0]) for turn, detail in found] == [
        (1, "openai"),
        (2, "openai"),
        (1, "lookup_order"),
        (2, "user"),
        (1, "shop.reply"),
    ]


def test_a_full_mcp_tool_name_matches_the_short_name() -> None:
    points = [
        {
            "name": "stock GET /stock",
            "source": "backend",
            "when": "Each mcp__shop__check_stock tool call",
        },
        {"name": "mcp__shop__check_stock", "source": "session", "when": "Turn 1"},
    ]
    items = [_item(1, "claude-code", "tool_call", "check_stock", server="shop")]
    assert [turn for turn, _ in app_spec.missing(points, items, 1)] == [1]
    assert [p["needed"] for p in app_spec.summary(points, items, 1) or []] == [1, 1]


def test_a_point_that_no_turn_needs_is_not_checked() -> None:
    points = [
        {"name": "stock GET /stock", "source": "backend", "when": "Each check_stok tool call"},
        {"name": "x", "source": "otel", "when": "Turn 4"},
        {"name": "y", "source": "otel", "when": "Each turn after the reply"},
    ]
    items = [_item(1, "claude-code", "tool_call", "check_stock")]
    assert app_spec.missing(points, items, 3) == []
    assert [(p["checked"], p["needed"]) for p in app_spec.summary(points, items, 3) or []] == [
        (False, 0),
        (False, 0),
        (False, None),
    ]


@pytest.mark.parametrize("points", [None, "x", {}, 3, [], [{"name": "a"}]])
def test_a_manifest_with_no_valid_point_has_no_trace_points(points: object) -> None:
    assert app_spec.summary(points, [], 1) is None
    assert app_spec.valid(points) == []


def test_a_point_with_a_field_that_is_not_text_is_dropped() -> None:
    good = {"name": "a", "source": "otel", "when": "Each turn", "more": 1}
    points = [good, {"name": "b", "source": "otel"}, {"name": 1, "source": "otel", "when": "x"}, 5]
    assert app_spec.summary(points, [], 1) == [
        {"name": "a", "source": "otel", "when": "Each turn", "checked": True, "needed": 1}
    ]


def test_each_unread_record_gives_one_detail() -> None:
    records = [
        {"file": "APP_SPEC.md", "line": 5, "problem": "The row has no Name."},
        {"file": "APP_SPEC.md", "problem": "x"},
        {"file": 3, "problem": "x"},
        "x",
    ]
    assert app_spec.unread(records) == [
        "APP_SPEC.md line 5: The row has no Name. The trace does not check it.",
        "APP_SPEC.md: x The trace does not check it.",
    ]
    assert app_spec.unread(None) == []


def test_the_trace_gives_200_unread_details_at_most() -> None:
    records = [{"file": "APP_SPEC.md", "line": n, "problem": "x"} for n in range(1, 302)]
    details = app_spec.unread(records)
    assert len(details) == 200
    assert details[-1] == "102 more records of trace_points_unread."


def test_a_spec_with_many_bad_parts_gives_200_records_at_most() -> None:
    text = "## Trace points\n" * 1_000_000
    start = time.monotonic()
    points, unread = app_spec.read([("APP_SPEC.md", text)] * 3)
    assert points == []
    assert len(unread) == 200
    assert unread[-1]["problem"] == (
        "This part and 2999800 more parts of the sections are not trace points."
    )
    assert time.monotonic() - start < 30


def test_a_failure_of_the_check_gives_a_finding_and_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_: object) -> list[tuple[int, str]]:
        raise ValueError("bad row")

    monkeypatch.setattr(app_spec, "missing", fail)
    points = [{"name": "a", "source": "otel", "when": "Each turn"}]
    found = trace.check([], [], [], [], points=points)
    assert [(f["check"], f["detail"]) for f in found] == [
        ("trace_points_unread", "The trace could not check the trace points: ValueError.")
    ]


def test_the_start_records_the_trace_points_of_the_spec(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    spec = "## Trace points\n\n| Name | Source | When |\n|---|---|---|\n"
    spec += "| `x` | `otel` | Turn 1 |\n| | otel | Turn 2 |\n"
    (tmp_path / "APP_SPEC.md").write_bytes(spec.encode() + b"\xff\n")
    (tmp_path / "RULES.md").write_text("# Rules\n")
    config = {"entry": ["python3", "agent.py"], "spec": ["APP_SPEC.md", "RULES.md"]}
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps(config))
    loaded = bridge.load_config(tmp_path)
    assert loaded.trace_points == [{"name": "x", "source": "otel", "when": "Turn 1"}]
    assert loaded.trace_points_unread == [
        {"file": "APP_SPEC.md", "line": 6, "problem": "The row has no Name."}
    ]
    assert [f["path"] for f in loaded.spec] == ["APP_SPEC.md", "RULES.md"]

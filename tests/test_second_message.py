"""A second message during a turn (SPEC.md sections 4.2 and 7.10)."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_bridge import homes, project, relay_turns  # noqa: F401
from test_contract import post, wait_for

from nookku import bridge, contract, script, stdio, trace
from nookku.audit import audit
from nookku.record import Writer
from nookku.stdio import DURING_HEADER, Agent, StdioTap, start_in_thread

# A toy shop agent that reads stdin during a turn. It writes the time of each input line to
# got.jsonl. `slow` takes 1 second. The mode says what a message during a slow turn does:
# `queue` (it waits for its turn), `refuse` (it gets the reply `busy` at once) or `stop` (the
# slow turn ends at once with an error, and the message gets its reply).
AGENT = """
import json, queue, sys, threading, time
mode, got = sys.argv[1], open(sys.argv[2], "a")
lines, out = queue.Queue(), threading.Lock()
busy, stop = threading.Event(), threading.Event()

def say(rid, **fields):
    with out:
        sys.stdout.write(json.dumps({"v": 1, "id": rid, **fields}) + "\\n")
        sys.stdout.flush()

def read():
    for raw in sys.stdin:
        r = json.loads(raw)
        got.write(json.dumps({"message": r["message"], "ts": time.time()}) + "\\n")
        got.flush()
        if busy.is_set() and mode == "refuse":
            say(r["id"], reply="busy")
        elif busy.is_set() and mode == "stop":
            stop.set()
            lines.put(r)
        else:
            lines.put(r)

threading.Thread(target=read, daemon=True).start()
while True:
    r = lines.get()
    if r["message"] == "slow":
        busy.set()
        stopped = stop.wait(1)
        busy.clear()
        stop.clear()
        if stopped:
            say(r["id"], error="stopped")
        else:
            say(r["id"], reply="slow is done")
    else:
        say(r["id"], reply="ok: " + r["message"])
"""


def _run(
    tmp_path: Path,
    mode: str,
    second: dict[str, str] | None,
    delay: float = 0.3,
    timeout: float = 10,
    plant: Callable[[StdioTap], None] | None = None,
) -> tuple[list[tuple[int, bytes]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Send `slow`, and send `stock` after `delay` seconds with the headers `second`. Return
    the 2 HTTP results, the rows of the tap record and the lines that the agent got. `plant`
    can change the tap before the first send."""
    script, got = tmp_path / "agent.py", tmp_path / "got.jsonl"
    script.write_text(AGENT)
    argv = [sys.executable, str(script), mode, str(got)]
    agent = Agent(argv, tmp_path, tmp_path / "app.log", timeout=timeout)
    tap = StdioTap(("127.0.0.1", 0), agent, tmp_path / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    results: list[tuple[int, bytes]] = [(0, b""), (0, b"")]

    def send(n: int, message: str, headers: dict[str, str] | None) -> None:
        body = contract.request(f"m-{n + 1}", "t1", message, []).decode()
        results[n] = post(tap, body, dict(headers or {}))

    try:
        wait_for(got)
        if plant is not None:
            plant(tap)
        first = threading.Thread(target=send, args=(0, "slow", None))
        first.start()
        time.sleep(delay)
        send(1, "stock", second)
        first.join(timeout=15)
    finally:
        tap.shutdown()
        agent.stop(grace=1)
    rows = [json.loads(x) for x in (tmp_path / "tap.jsonl").read_text().split("\n") if x]
    lines = [json.loads(x) for x in got.read_text().split("\n") if x]
    return results, rows, lines


# The header names the request id of the first message.
DURING = {DURING_HEADER: "m-1"}


def test_the_agent_gets_a_second_message_during_the_turn(tmp_path: Path) -> None:
    results, rows, lines = _run(tmp_path, "queue", DURING)
    assert [r[0] for r in results] == [200, 200]
    # The row of the second message comes after the row of the first one.
    assert [(r["type"], r["input"], r["reply"]) for r in rows] == [
        ("exchange", "slow", "slow is done"),
        ("exchange", "stock", "ok: stock"),
    ]
    first, second = rows
    assert first["started"] < second["started"] < first["ts"] <= second["ts"]
    # The agent got the line before the reply of the first message.
    assert [x["message"] for x in lines] == ["slow", "stock"]
    assert lines[1]["ts"] < first["ts"]
    # The reply came in the turn of the second message, so the row has no `replied`.
    assert "replied" not in second and "replied" not in first


def test_a_reply_during_the_first_turn_is_kept_with_its_time(tmp_path: Path) -> None:
    results, rows, _ = _run(tmp_path, "refuse", DURING)
    assert [r[0] for r in results] == [200, 200]
    assert json.loads(results[1][1])["reply"] == "busy"
    # The early reply line is not a stray line: the record has 2 exchange rows only.
    assert [(r["type"], r["input"], r["reply"]) for r in rows] == [
        ("exchange", "slow", "slow is done"),
        ("exchange", "stock", "busy"),
    ]
    first, second = rows
    assert second["started"] < second["replied"] < first["ts"] <= second["ts"]


def test_the_agent_can_stop_the_first_turn(tmp_path: Path) -> None:
    results, rows, _ = _run(tmp_path, "stop", DURING)
    assert [r[0] for r in results] == [500, 200]
    assert [(r["input"], r["status"], r["reply"], r.get("error")) for r in rows] == [
        ("slow", 500, None, "stopped"),
        ("stock", 200, "ok: stock", None),
    ]
    first, second = rows
    # The first turn ended because of the second message, before its 1 second.
    assert first["ts"] - first["started"] < 0.9
    assert first["started"] < second["started"] < first["ts"]


def test_a_message_with_no_header_waits_for_the_reply_of_the_first_turn(tmp_path: Path) -> None:
    results, rows, lines = _run(tmp_path, "refuse", None)
    assert [r[0] for r in results] == [200, 200]
    first, second = rows
    # The tap sends one request at a time: the agent got the line after the first reply.
    assert second["reply"] == "ok: stock" and "replied" not in second and "replied" not in first
    assert first["ts"] <= second["started"] and first["ts"] <= lines[1]["ts"]


def test_the_header_with_no_turn_in_flight_changes_nothing(tmp_path: Path) -> None:
    # The second message comes after the reply of the first one.
    results, rows, _ = _run(tmp_path, "refuse", DURING, delay=1.5)
    assert [r[0] for r in results] == [200, 200]
    first, second = rows
    assert second["reply"] == "ok: stock" and "replied" not in second and "replied" not in first
    assert first["ts"] <= second["started"]


def test_a_message_after_the_reply_is_not_during_a_slow_record_write(tmp_path: Path) -> None:
    # Gap 1 of #656. The slow turn takes 1 second, and the write of its row takes 1 second more.
    # The second message comes after the reply and before the end of that write.
    def plant(tap: StdioTap) -> None:
        append = tap.writer.append

        def slow(row: dict[str, Any]) -> None:
            if row.get("input") == "slow":
                time.sleep(1.0)
            append(row)

        tap.writer.append = slow  # type: ignore[method-assign]

    results, rows, lines = _run(tmp_path, "refuse", DURING, delay=1.4, plant=plant)
    assert [r[0] for r in results] == [200, 200]
    first, second = rows
    # The agent got the line after its reply, so the line is not a second message.
    assert second["reply"] == "ok: stock" and "replied" not in second and "replied" not in first
    assert first["ts"] <= second["started"] and first["ts"] <= lines[1]["ts"]
    assert trace.second_messages(rows) == []


def test_a_second_message_reaches_the_agent_after_the_first_one(tmp_path: Path) -> None:
    # Gap 2 of #656. The second message comes at once (`during: 0`), and the first one is slow
    # to get to the agent: the tap reads the waiting stdout lines for 0.3 seconds first.
    def plant(tap: StdioTap) -> None:
        stray = tap.agent.stray

        def slow() -> list[bytes]:
            time.sleep(0.3)
            return stray()

        tap.agent.stray = slow  # type: ignore[method-assign]

    results, rows, lines = _run(tmp_path, "queue", DURING, delay=0, plant=plant)
    assert [r[0] for r in results] == [200, 200]
    assert [x["message"] for x in lines] == ["slow", "stock"]
    assert [(r["input"], r["reply"]) for r in rows] == [
        ("slow", "slow is done"),
        ("stock", "ok: stock"),
    ]
    first, second = rows
    assert first["started"] < second["started"] < first["ts"]
    assert [m["turn"] for m in trace.second_messages(rows)] == [2]


def test_a_second_message_for_an_unknown_request_waits_and_goes_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No request `m-9` comes, so the message goes after its wait, as a message with no header.
    monkeypatch.setattr(stdio, "DURING_WAIT", 0.2)
    results, rows, _ = _run(tmp_path, "refuse", {DURING_HEADER: "m-9"}, delay=1.5)
    assert [r[0] for r in results] == [200, 200]
    first, second = rows
    assert second["reply"] == "ok: stock" and "replied" not in second
    assert first["ts"] <= second["started"]


def test_a_timeout_of_the_first_turn_gives_the_second_message_no_reply(tmp_path: Path) -> None:
    results, rows, _ = _run(tmp_path, "queue", DURING, delay=0.1, timeout=0.5)
    assert [r[0] for r in results] == [504, 502]
    assert [(r["input"], r["status"], r["reply"]) for r in rows] == [
        ("slow", None, None),
        ("stock", None, None),
    ]
    assert "the tap stopped it" in rows[1]["error"]


def test_the_audit_reads_a_record_with_a_second_message(tmp_path: Path) -> None:
    _, rows, _ = _run(tmp_path, "refuse", DURING)
    assert "replied" in rows[1]
    relay = Writer(tmp_path / "relay.jsonl")
    for said, shown in (("slow", "slow is done"), ("stock", "busy")):
        relay.append({"type": "turn", "harness": "script", "said": said, "shown": shown})
    report = audit(tmp_path / "tap.jsonl", tmp_path / "relay.jsonl").as_dict()
    assert report["exit"] == 0 and report["breaks"] == []


@pytest.mark.parametrize(
    ("data", "want"),
    [
        (b'{"said": "a"}\n{"said": "b", "during": 0.5}\n{"said": "c"}\n', [None, 0.5, None]),
        (b'{"said": "a"}\n{"during": 0, "said": "b"}\n', [None, 0.0]),
        (b'{"said": "a"}\n{"said": "b", "during": 60}\n', [None, 60.0]),
        (b'["a", "b"]', [None, None]),
    ],
)
def test_the_key_during_of_a_script_row(data: bytes, want: list[float | None]) -> None:
    assert script.timing(data) == want
    assert script.parse(data)[0] == ["a", "b", "c"][: len(want)]


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b'{"said": "a", "during": 1}\n', 'line 1: the first message cannot have "during"'),
        (
            b'{"said": "a"}\n{"said": "b", "during": 1}\n{"said": "c", "during": 1}\n',
            'line 3: the row before a row with "during" cannot have it',
        ),
        (b'{"said": "a"}\n{"said": "b", "during": "1"}\n', 'line 2: "during" must be a number'),
        (b'{"said": "a"}\n{"said": "b", "during": true}\n', 'line 2: "during" must be a number'),
        (b'{"said": "a"}\n{"said": "b", "during": null}\n', 'line 2: "during" must be a number'),
        (b'{"said": "a"}\n{"said": "b", "during": -1}\n', 'line 2: "during" must be from 0 to 60'),
        (b'{"said": "a"}\n{"said": "b", "during": 61}\n', 'line 2: "during" must be from 0 to 60'),
        (b'{"said": "a"}\n{"said": "b", "after": 1}\n', 'with no other key than "during"'),
        (b'{"during": 1}\n', 'line 1: a row must be {"said": "..."}'),
    ],
)
def test_a_row_with_a_wrong_during_is_refused(data: bytes, error: str) -> None:
    with pytest.raises(script.ScriptError, match=re.escape(error)):
        script.timing(data)
    with pytest.raises(script.ScriptError, match=re.escape(error)):
        script.parse(data)


def _exchange(started: float | None, ts: float, **more: Any) -> dict[str, Any]:
    row = {"type": "exchange", "ts": ts, **more}
    return row if started is None else {**row, "started": started}


def test_a_second_message_starts_in_the_window_of_the_turn_before_it() -> None:
    exchanges = [
        _exchange(10, 20),
        _exchange(12.5, 26),
        _exchange(30, 40),
        _exchange(32, 41, replied=33),
        _exchange(50, 60),
        _exchange(60, 70),  # at the end of the turn before it: not during the turn
        _exchange(None, 80),  # a 0.1 row has no `started`
        _exchange(75, 90),
    ]
    assert trace.windows(exchanges)[3] == (32.0, 33.0)
    assert trace.second_messages(exchanges) == [
        {"turn": 2, "during": 1, "after": 2.5, "reply_first": False},
        {"turn": 4, "during": 3, "after": 2.0, "reply_first": True},
    ]
    # An item at a time in 2 windows is in the first of the 2 turns.
    spans = trace.windows(exchanges)
    assert [trace._turn(t, spans) for t in (11, 13, 21, 32.5, 40.5)] == [1, 1, 2, 3, None]


def _call(harness: str, kind: str, turn: int, ts: float, **more: Any) -> dict[str, Any]:
    it = trace._item(harness, more.pop("session", "s1"), f"{harness}.jsonl", 1, ts)
    it.update(kind=kind, turn=turn, name=more.pop("name", "refund"), **more)
    return it


def test_a_call_with_no_result_before_the_second_message_is_cut() -> None:
    exchanges = [_exchange(10, 20), _exchange(12, 26)]
    done = _call("claude-code", "tool_call", 1, 11)
    done["source"]["result_line"] = 9
    items = [
        _call("claude-code", "tool_call", 1, 11),
        done,
        _call("claude-code", "tool_call", 1, 12.5),  # it started after the second message
        _call("claude-code", "tool_call", 2, 21),  # it is in the turn of the second message
        _call("codex", "tool_call", 1, 11),  # a Codex item has no result_line in each case
        _call("driver", "query", 1, 11),
        _call("database", "query", 1, 11.5, session="orders", name="UPDATE"),
        _call("backend", "http", 1, 12, session="shop", name="POST /refund"),
        _call("backend", "http", 1, 11, session="shop", name="POST /refund", exit_code=200),
        _call("mcp", "elicitation", 1, 11),
    ]
    text = "no result. The call started before the message of turn 2, which came during this turn"
    assert [(f["turn"], f["detail"], f["harness"]) for f in trace.calls_cut(items, exchanges)] == [
        (1, f"refund: {text}", "claude-code"),
        (1, f"orders: UPDATE: {text}", "database"),
        (1, f"shop: POST /refund: {text}", "backend"),
    ]
    # With no second message, no call is cut.
    assert trace.calls_cut(items, [_exchange(10, 20), _exchange(20, 26)]) == []


def _script(path: Path, during: float) -> Path:
    rows = [{"said": "slow"}, {"said": "stock", "during": during}, {"said": "thanks"}]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


@pytest.mark.parametrize(
    ("mode", "replies", "reply_first"),
    [
        ("queue", ["slow is done", "ok: stock", "ok: thanks"], False),
        ("refuse", ["slow is done", "busy", "ok: thanks"], True),
    ],
)
@pytest.mark.usefixtures("homes")
def test_a_scripted_test_sends_a_second_message_during_a_turn(
    tmp_path: Path, mode: str, replies: list[str], reply_first: bool
) -> None:
    app = tmp_path / "agent.py"
    app.write_text(AGENT)
    root = project(tmp_path, [sys.executable, str(app), mode, str(tmp_path / "got.jsonl")])
    passed, lines, folder = bridge.run_script(root, _script(tmp_path / "turns.jsonl", 0.3))
    assert passed, lines
    assert lines[1] == "Turns: 3 of 3 messages" and lines[-1] == "PASS"
    # The relay rows are in the order of the script, and the audit is clean.
    turns = relay_turns(folder)
    assert [(t["said"], t["shown"]) for t in turns] == list(
        zip(["slow", "stock", "thanks"], replies, strict=True)
    )
    findings = json.loads((folder / "findings.json").read_text())
    (second,) = findings["second_messages"]
    assert (second["turn"], second["during"], second["reply_first"]) == (2, 1, reply_first)
    assert 0.25 < second["after"] < 0.9 and second["calls_cut"] == 0
    assert findings["counts"]["call_cut"] == 0


@pytest.mark.usefixtures("homes")
def test_a_second_message_after_the_reply_fails_the_run(tmp_path: Path) -> None:
    app = tmp_path / "agent.py"
    app.write_text(AGENT)
    root = project(tmp_path, [sys.executable, str(app), "queue", str(tmp_path / "got.jsonl")])
    # The slow turn takes 1 second, and the second message comes after 1.6 seconds.
    passed, lines, folder = bridge.run_script(root, _script(tmp_path / "turns.jsonl", 1.6))
    assert not passed
    assert lines[1] == "Turns: 3 of 3 messages"
    problem = "FAIL: Message 2 of the script has `during`, but the entry did not get it during "
    problem += "turn 1: the reply of turn 1 came first."
    assert any(line.startswith(problem) for line in lines), lines
    assert "second_messages" not in json.loads((folder / "findings.json").read_text())


@pytest.mark.usefixtures("homes")
def test_a_second_message_with_during_0_comes_after_the_first_one(tmp_path: Path) -> None:
    app, got = tmp_path / "agent.py", tmp_path / "got.jsonl"
    app.write_text(AGENT)
    root = project(tmp_path, [sys.executable, str(app), "queue", str(got)])
    passed, lines, folder = bridge.run_script(root, _script(tmp_path / "turns.jsonl", 0))
    assert passed, lines
    # The send of the second message names the first one, so the agent gets them in order.
    assert [json.loads(x)["message"] for x in got.read_text().split("\n") if x] == [
        "slow",
        "stock",
        "thanks",
    ]
    (second,) = json.loads((folder / "findings.json").read_text())["second_messages"]
    assert (second["turn"], second["during"]) == (2, 1)

"""Write the conformance cases. Each expectation here is written by hand from SPEC.md.

`cases/` holds the audit cases (SPEC.md section 3). `contract/` holds the stdio cases (sections 4.2
and 6): the requests that the relay posts, what a scripted agent does with each one, and the rows
and HTTP statuses that the tap must give. `trace/` holds the trace cases (section 8). `seal/` holds
the seal cases (section 7.4). `otlp/` holds the receiver cases (section 7.5).

Never fill an expectation by running the audit. CI runs this script and fails if the files change.

usage: python conformance/build.py
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import shutil
import struct
import unicodedata
from pathlib import Path
from typing import Any

CASES = Path(__file__).parent / "cases"
CONTRACT = Path(__file__).parent / "contract"
TRACE = Path(__file__).parent / "trace"
SEAL = Path(__file__).parent / "seal"
OTLP = Path(__file__).parent / "otlp"


def sha(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode()).hexdigest()


def ex(
    text: str, reply: str | None, status: int | None = 200, error: str | None = None, v: str = "0.1"
) -> dict:
    row: dict[str, Any] = {
        "v": v,
        "type": "exchange",
        "ts": 1.0,
        "input": text,
        "input_sha256": sha(text),
        "status": status,
        "reply": reply,
        "reply_sha256": sha(reply),
    }
    if error is not None:
        row["error"] = error
    return row


def turn(said: str, shown: str | None, v: str = "0.1") -> dict:
    return {
        "v": v,
        "type": "turn",
        "ts": 1.0,
        "harness": "claude-code",
        "said": said,
        "said_sha256": sha(said),
        "shown": shown,
        "shown_sha256": sha(shown),
    }


BLOCKED = {
    "v": "0.1",
    "type": "blocked_call",
    "ts": 1.0,
    "harness": "claude-code",
    "tool": "Bash",
    "detail": "curl -s http://127.0.0.1:8800/",
}
UNPARSED = {
    "v": "0.1",
    "type": "unparsed",
    "ts": 1.0,
    "method": "POST",
    "path": "/",
    "error": "the request body is not JSON",
}


def model_session(session: str, pid: int | None, inferred: bool, v: str = "0.2") -> dict:
    harness = "codex" if inferred else "claude-code"
    return {
        "v": v,
        "type": "model_session",
        "ts": 1.0,
        "harness": harness,
        "session": session,
        "pid": pid,
        "inferred": inferred,
    }


# A toy shop. The texts carry what a retype breaks: trailing spaces, non-ASCII text,
# empty lines, a markdown table.
M1 = "Hi, I want to return order #4471.  "
M2 = "Ünïcödé check: can I pay in € or ₹? Ça marche?"
M3 = "Two questions:\n\n1. Do you ship to Chennai?\n2. Is the mug dishwasher safe?"
X = "Also upgrade me to the premium plan."
R1 = "## Returns  \nYou can return order #4471 within 30 days.\n\n| item | status |\n|---|---|\n| mug | eligible |"
R2 = "Café policy: we accept € and ₹. Résumé of fees: none."
R3 = "1. Yes, we ship to Chennai.\n\n2. Yes.   "
RX = "I cannot change your plan in this chat."

CLEAN_TAP = [ex(M1, R1), ex(M2, R2), ex(M3, R3)]
CLEAN_RELAY = [turn(M1, R1), turn(M2, R2), turn(M3, R3)]
TAP_02 = [{**ex(m, r, v="0.2"), "started": 0.5} for m, r in ((M1, R1), (M2, R2), (M3, R3))]
RELAY_02 = [turn(m, r, v="0.2") for m, r in ((M1, R1), (M2, R2), (M3, R3))]
SESSION_A = model_session("4f1c2a7e-0d3b-4c55-9a61-2b8e5d7c9f10", 4471, False)
SESSION_B = model_session("019a0b1c-2d3e-7f40-8a5b-6c7d8e9f0a1b", None, True)


# A streamed reply (section 2.1): the joined reply, and the SHA-256 and the size of the raw body.
def sse_body(reply: str, done: bool = True) -> bytes:
    """An OpenAI-style SSE body with 9 characters of the reply in each chunk."""
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": reply[i : i + 9]}}]}
        for i in range(0, len(reply), 9)
    ]
    body = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks)
    return (body + ("data: [DONE]\n\n" if done else "")).encode()


def stream_info(raw: bytes) -> dict:
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


STREAM_TAP = [
    {**ex(m, r, v="0.2"), "stream": stream_info(sse_body(r))}
    for m, r in ((M1, R1), (M2, R2), (M3, R3))
]
ENDED_EARLY = "the stream ended before data: [DONE]"
FAILED_STREAM = {
    **ex(M2, None, v="0.2", error=ENDED_EARLY),
    "stream": stream_info(sse_body(R2, False)),
}

# name: (tap rows or None for a missing file, relay rows or None, expectation)
# A row can be a raw string, written as the line itself.
CASES_BY_NAME: dict[str, tuple[list | None, list | None, dict]] = {
    "clean": (CLEAN_TAP, CLEAN_RELAY, {"exit": 0, "breaks": []}),
    "clean_repeated_message": (
        [ex(M1, R1), ex(M1, R1)],
        [turn(M1, R1), turn(M1, R1)],
        {"exit": 0, "breaks": []},
    ),
    "empty_records": ([], [], {"exit": 0, "breaks": []}),
    "blocked_call_is_counted": (
        CLEAN_TAP,
        [CLEAN_RELAY[0], BLOCKED, *CLEAN_RELAY[1:]],
        {"exit": 0, "breaks": [], "blocked_calls": 1},
    ),
    "agent_error_is_a_note": (
        [ex(M1, None, status=500, error="HTTP 500")],
        [turn(M1, "The agent returned an error.")],
        {"exit": 0, "breaks": [], "notes": [["agent_error", 1, 1]]},
    ),
    "agent_unreachable_is_a_note": (
        [ex(M1, None, status=None, error="connection refused")],
        [turn(M1, None)],
        {"exit": 0, "breaks": [], "notes": [["agent_error", 1, 1]]},
    ),
    "altered_input_trailing_space": (
        [ex(M1.rstrip(), R1), *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 1, "breaks": [["altered_input", 1, 1]]},
    ),
    "altered_input_trailing_newline": (
        [CLEAN_TAP[0], ex(M2 + "\n", R2), CLEAN_TAP[2]],
        CLEAN_RELAY,
        {"exit": 1, "breaks": [["altered_input", 2, 2]]},
    ),
    "altered_input_unicode_nfd": (
        [CLEAN_TAP[0], ex(unicodedata.normalize("NFD", M2), R2), CLEAN_TAP[2]],
        CLEAN_RELAY,
        {"exit": 1, "breaks": [["altered_input", 2, 2]]},
    ),
    "altered_input_empty_line_lost": (
        [*CLEAN_TAP[:2], ex(M3.replace("\n\n", "\n"), R3)],
        CLEAN_RELAY,
        {"exit": 1, "breaks": [["altered_input", 3, 3]]},
    ),
    "altered_reply_word": (
        CLEAN_TAP,
        [CLEAN_RELAY[0], turn(M2, R2.replace("Café", "Care")), CLEAN_RELAY[2]],
        {"exit": 1, "breaks": [["altered_reply", 2, 2]]},
    ),
    "altered_reply_blank_line_added": (
        CLEAN_TAP,
        [turn(M1, R1 + "\n"), *CLEAN_RELAY[1:]],
        {"exit": 1, "breaks": [["altered_reply", 1, 1]]},
    ),
    "altered_reply_trailing_space_lost": (
        CLEAN_TAP,
        [*CLEAN_RELAY[:2], turn(M3, R3.rstrip())],
        {"exit": 1, "breaks": [["altered_reply", 3, 3]]},
    ),
    "unshown_reply": (
        CLEAN_TAP,
        [*CLEAN_RELAY[:2], turn(M3, None)],
        {"exit": 1, "breaks": [["unshown_reply", 3, 3]]},
    ),
    "injected_input": (
        [*CLEAN_TAP[:2], ex(X, RX), CLEAN_TAP[2]],
        CLEAN_RELAY,
        {"exit": 1, "breaks": [["injected_input", None, 3]]},
    ),
    "duplicate_send": (
        [CLEAN_TAP[0], CLEAN_TAP[0], *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 1, "breaks": [["duplicate_send", None, 2]]},
    ),
    "out_of_order": (
        [CLEAN_TAP[1], CLEAN_TAP[0]],
        CLEAN_RELAY[:2],
        {"exit": 1, "breaks": [["out_of_order", 1, 2]]},
    ),
    "not_delivered": (
        [CLEAN_TAP[0], CLEAN_TAP[2]],
        CLEAN_RELAY,
        {"exit": 1, "breaks": [["not_delivered", 2, None]]},
    ),
    # A greedy forward search would anchor turn 1 on exchange 3. The subsequence must not.
    "repeat_after_alteration": (
        [ex(M1.rstrip(), R1), ex(M2, R2), ex(M1, R1)],
        [turn(M1, R1), turn(M2, R2), turn(M1, R1)],
        {"exit": 1, "breaks": [["altered_input", 1, 1]]},
    ),
    # An injected exchange and an undelivered turn in the same gap pair up as one change.
    "several_breaks": (
        [ex(M1.rstrip(), R1), ex(M2, R2), ex(X, RX)],
        [turn(M1, R1), turn(M2, R2.replace("Café", "Care")), turn(M3, None)],
        {
            "exit": 1,
            "breaks": [
                ["altered_input", 1, 1],
                ["altered_reply", 2, 2],
                ["altered_input", 3, 3],
                ["unshown_reply", 3, 3],
            ],
        },
    ),
    "optional_turn_fields": (
        CLEAN_TAP,
        [{**t, "ok": True, "session": "s1"} for t in CLEAN_RELAY],
        {"exit": 0, "breaks": []},
    ),
    "optional_field_wrong_type": (
        CLEAN_TAP,
        [{**CLEAN_RELAY[0], "ok": "yes"}, *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "relay_record_missing": (CLEAN_TAP, None, {"exit": 2, "errors": ["record_missing"]}),
    "tap_record_missing": (None, CLEAN_RELAY, {"exit": 2, "errors": ["record_missing"]}),
    "invalid_json_line": (
        CLEAN_TAP,
        [CLEAN_RELAY[0], '{"v": "0.1", "type": "turn"', *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "blank_line": (
        CLEAN_TAP,
        [CLEAN_RELAY[0], "", *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "hash_mismatch": (
        [{**CLEAN_TAP[0], "input_sha256": sha(M1.rstrip())}, *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "wrong_version": (
        CLEAN_TAP,
        [{**CLEAN_RELAY[0], "v": "0.3"}, *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    # Version 0.2: a test adds `started` and `model_session` rows. The matching does not change.
    "v02_model_sessions_are_counted": (
        [TAP_02[0], SESSION_A, *TAP_02[1:], SESSION_B],
        RELAY_02,
        {"exit": 0, "breaks": [], "model_sessions": 2},
    ),
    "v02_breaks_are_the_same": (
        [{**TAP_02[0], **ex(M1.rstrip(), R1, v="0.2"), "started": 0.5}, SESSION_A, *TAP_02[1:]],
        RELAY_02,
        {"exit": 1, "breaks": [["altered_input", 1, 1]], "model_sessions": 1},
    ),
    "v01_and_v02_rows_mix": (
        [*CLEAN_TAP[:2], TAP_02[2], SESSION_A],
        CLEAN_RELAY,
        {"exit": 0, "breaks": [], "model_sessions": 1},
    ),
    "model_session_in_a_v01_row": (
        [*CLEAN_TAP, model_session("s-1", 4471, False, v="0.1")],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "started_in_a_v01_row": (
        [{**CLEAN_TAP[0], "started": 0.5}, *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "model_session_wrong_field_type": (
        [*TAP_02, {**SESSION_A, "inferred": "no"}],
        RELAY_02,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "model_session_in_the_relay_record": (
        TAP_02,
        [*RELAY_02, SESSION_A],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "unknown_type": (
        [*CLEAN_TAP, {"v": "0.1", "type": "note", "ts": 1.0}],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "missing_field": (
        CLEAN_TAP,
        [{k: v for k, v in CLEAN_RELAY[0].items() if k != "shown"}, *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "wrong_field_type": (
        [{**CLEAN_TAP[0], "status": "200"}, *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "reply_missing_on_success": (
        [ex(M1, None), *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "tap_unparsed": ([*CLEAN_TAP, UNPARSED], CLEAN_RELAY, {"exit": 2, "errors": ["tap_unparsed"]}),
    # Streamed replies (0.2). The audit compares the joined reply, the same as any reply.
    "streamed_reply_clean": (STREAM_TAP, RELAY_02, {"exit": 0, "breaks": []}),
    # The relay showed the first part of a complete stream as the reply.
    "streamed_reply_part_shown": (
        STREAM_TAP,
        [RELAY_02[0], turn(M2, R2[:18], v="0.2"), RELAY_02[2]],
        {"exit": 1, "breaks": [["altered_reply", 2, 2]]},
    ),
    # A failed stream has a 2xx status, no reply and an error. It is an agent error.
    "streamed_reply_failed_is_a_note": (
        [STREAM_TAP[0], FAILED_STREAM, STREAM_TAP[2]],
        [
            RELAY_02[0],
            turn(M2, f"verbatim-relay: cannot read the reply: {ENDED_EARLY}", v="0.2"),
            RELAY_02[2],
        ],
        {"exit": 0, "breaks": [], "notes": [["agent_error", 2, 2]]},
    ),
    "streamed_reply_failed_without_error": (
        [STREAM_TAP[0], {k: v for k, v in FAILED_STREAM.items() if k != "error"}, STREAM_TAP[2]],
        RELAY_02,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "stream_in_a_v01_row": (
        [{**CLEAN_TAP[0], "stream": STREAM_TAP[0]["stream"]}, *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "stream_wrong_field_type": (
        [{**STREAM_TAP[0], "stream": {"sha256": "abc", "bytes": 120}}, *STREAM_TAP[1:]],
        RELAY_02,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
}


# The stdio cases. Each request is the body that the relay posts. Each agent step says what the
# scripted agent does with one input line: write `lines`, `exit` with a code, or `sleep` seconds.
# `forwarded` is the index of each request that the agent must receive, byte for byte.
# A row lists only the fields to compare. The tap's timeout is 1 second in these cases.
def req(message: str, history: list | None = None, rid: str = "m-1") -> str:
    body = {"v": 1, "id": rid, "session": "t-1", "message": message, "history": history or []}
    return json.dumps(body, ensure_ascii=False)


def out(rid: str = "m-1", **fields: Any) -> str:
    return json.dumps({"v": 1, "id": rid, **fields}, ensure_ascii=False)


# A message with what a line protocol breaks: CR LF, U+2028 (a line end for some readers),
# a tab, trailing spaces and text that is not ASCII.
TRICKY = "Hi, return order #4471 please.  \r\nLine two\u2028line three\t€ ₹  "
HISTORY = [{"message": M1, "reply": R1}]
EXCHANGE_OK = {"type": "exchange", "input": TRICKY, "status": 200, "reply": R1}
UNPARSED_POST = {"type": "unparsed", "method": "POST", "path": "/"}

CONTRACT_CASES: dict[str, dict] = {
    "reply_is_exact": {
        "requests": [req(TRICKY, HISTORY)],
        "agent": [{"lines": [out(reply=R1)]}],
        "forwarded": [0],
        "http": [200],
        "rows": [EXCHANGE_OK],
    },
    "error_is_status_500": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(error="The order service is down.")]}],
        "forwarded": [0],
        "http": [500],
        "rows": [
            {
                "type": "exchange",
                "input": TRICKY,
                "status": 500,
                "reply": None,
                "error": "The order service is down.",
            }
        ],
    },
    "other_fields_are_ignored": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(reply=R1, latency_ms=12)]}],
        "forwarded": [0],
        "http": [200],
        "rows": [EXCHANGE_OK],
    },
    "reply_not_json": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": ["Loading the toy shop catalog..."]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    "reply_wrong_id": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out("m-0", reply=R1)]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    "reply_and_error": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(reply=R1, error="also an error")]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    "reply_not_a_string": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(reply=4471)]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    "reply_wrong_contract_version": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [json.dumps({"v": 2, "id": "m-1", "reply": R1})]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    # The tap does not restart the agent. The next request gets the same error.
    "crash_is_not_restarted": {
        "requests": [req(TRICKY), req(M2, rid="m-2")],
        "agent": [{"exit": 3}],
        "forwarded": [0],
        "http": [502, 502],
        "rows": [
            {"type": "exchange", "input": TRICKY, "status": None, "reply": None},
            {"type": "exchange", "input": M2, "status": None, "reply": None},
        ],
    },
    "timeout_stops_the_agent": {
        "requests": [req(TRICKY), req(M2, rid="m-2")],
        "agent": [{"sleep": 5}],
        "forwarded": [0],
        "http": [504, 502],
        "rows": [
            {"type": "exchange", "input": TRICKY, "status": None, "reply": None},
            {"type": "exchange", "input": M2, "status": None, "reply": None},
        ],
    },
    "request_not_a_contract_input": {
        "requests": [json.dumps({"text": M1})],
        "agent": [],
        "forwarded": [],
        "http": [400],
        "rows": [UNPARSED_POST],
    },
    "request_with_a_raw_line_end": {
        "requests": [req(TRICKY).replace(", ", ",\n", 1)],
        "agent": [],
        "forwarded": [],
        "http": [400],
        "rows": [UNPARSED_POST],
    },
    # A line that arrives after its request is done belongs to no request.
    "stray_line_is_unparsed": {
        "requests": [req(TRICKY), req(M2, rid="m-2")],
        "agent": [
            {"lines": [out(reply=R1), "debug: cache warm"]},
            {"lines": [out("m-2", reply=R2)]},
        ],
        "forwarded": [0, 1],
        "http": [200, 200],
        "rows": [
            EXCHANGE_OK,
            {"type": "unparsed", "method": "STDIO", "path": "stdout"},
            {"type": "exchange", "input": M2, "status": 200, "reply": R2},
        ],
    },
}


# Trace cases (SPEC.md section 8). Each case has a tap record, a manifest, the session files and
# the expected trace.jsonl and findings.json. The session lines copy the shapes of real session
# files of Claude Code 2.1.286 and codex-cli 0.160.0, with toy shop content.
T0 = 1791273600.0  # 2026-10-06T08:00:00Z
CC = "4f1c2a7e-0d3b-4c55-9a61-2b8e5d7c9f10"
CX = "019a0b1c-2d3e-7f40-8a5b-6c7d8e9f0a1b"
CC_FILE = f"sessions/claude-code/{CC}.jsonl"
CX_FILE = f"sessions/codex/rollout-2026-10-06T08-00-00-{CX}.jsonl"


def iso(t: float) -> str:
    stamp = datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc)
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def window(started: float | None, ts: float, status: int | None = 200, v: str = "0.2") -> dict:
    """An exchange of a trace case: only its times and its status matter."""
    row = ex("toy shop message", "toy shop reply" if status == 200 else None, status, v=v)
    row["ts"] = T0 + ts
    if started is not None:
        row["started"] = T0 + started
    if status != 200:
        row["error"] = "the agent failed"
    return row


def cc_line(kind: str, t: float, content: Any, **more: Any) -> dict:
    """One user or assistant line of a Claude Code session file."""
    row = {
        "type": kind,
        "sessionId": CC,
        "timestamp": iso(T0 + t),
        "version": more.pop("version", "2.1.286"),
        "isSidechain": False,
        "message": {"role": kind, "content": content},
    }
    return {**row, **more}


def use(tid: str, name: str, args: dict) -> dict:
    return {
        "type": "tool_use",
        "id": tid,
        "name": name,
        "input": args,
        "caller": {"type": "direct"},
    }


def result(tid: str, content: Any, error: bool = False) -> dict:
    row = {"type": "tool_result", "tool_use_id": tid, "content": content}
    return {**row, "is_error": True} if error else row


def cx_line(t: float, item: dict, at: bool = True) -> dict:
    """One item_completed line of a Codex rollout file."""
    payload: dict[str, Any] = {
        "type": "item_completed",
        "thread_id": CX,
        "turn_id": "t",
        "item": item,
    }
    if at:
        payload |= {"started_at_ms": int((T0 + t) * 1000), "completed_at_ms": int((T0 + t) * 1000)}
    return {"timestamp": iso(T0 + t), "type": "event_msg", "payload": payload}


def item(turn: int | None, harness: str, ts: float, kind: str, line: int, **fields: Any) -> dict:
    """An expected trace row. Each field that `fields` does not set has its SPEC.md default."""
    session, file = (CC, CC_FILE) if harness == "claude-code" else (CX, CX_FILE)
    row: dict[str, Any] = {
        "v": "0.3",
        "type": "model_item",
        "turn": turn,
        "harness": harness,
        "session": session,
        "ts": T0 + ts,
        "kind": kind,
        "role": None,
        "server": None,
        "name": None,
        "input": None,
        "output": None,
        "error": None,
        "exit_code": None,
        "harness_internal": False,
        "service": None,
        "source": {"file": file, "line": line},
    }
    if "result_line" in fields:
        row["source"]["result_line"] = fields.pop("result_line")
    return {**row, **fields}


def where(harness: str, line: int, result_line: int | None = None) -> dict:
    session, file = (CC, CC_FILE) if harness == "claude-code" else (CX, CX_FILE)
    source: dict[str, Any] = {"file": file, "line": line}
    if result_line is not None:
        source["result_line"] = result_line
    return {"harness": harness, "session": session, "source": source}


def counts(**n: int) -> dict:
    checks = (
        "agent_error",
        "tool_error",
        "command_failed",
        "span_error",
        "backend_error",
        "model_api_error",
        "turn_without_model",
        "item_between_turns",
        "otel_tool_not_in_session",
        "session_inferred",
        "version_untested",
    )
    return {c: n.get(c, 0) for c in checks}


CC_SESSION = {
    "harness": "claude-code",
    "session": CC,
    "pid": 4471,
    "inferred": False,
    "file": CC_FILE,
}
CX_SESSION = {
    "harness": "codex",
    "session": CX,
    "pid": None,
    "inferred": True,
    "originator": "toy-shop",
    "file": CX_FILE,
}
NO_RESULT = "no tool_result in the session file"
TOOL_REFERENCE = {"type": "tool_reference", "tool_name": "mcp__shop__lookup_order"}

# Claude Code: an app start before turn 1, a harness tool, an MCP tool with a result, an agent
# error, 2 failed tools, a thinking block, a meta line, items between turns, a tool call with no
# result, a line that is not JSON and a turn with no model item.
CLAUDE_CASE = {
    "tap": [window(10, 20), window(30, 40, status=500), window(50, 60)],
    "manifest": {"test": "20261006-080000-cc01", "model_sessions": [CC_SESSION]},
    "sessions": {
        CC_FILE: [
            {"type": "queue-operation", "operation": "enqueue", "sessionId": CC},
            cc_line("user", 5, "Warm up."),
            cc_line("assistant", 6, [{"type": "text", "text": "Ready."}]),
            cc_line("user", 11, "Where is my order 4471?"),
            cc_line("assistant", 12, [{"type": "thinking", "thinking": "", "signature": "x"}]),
            cc_line("assistant", 12.5, [use("t1", "ToolSearch", {"query": "select:shop"})]),
            cc_line("user", 12.6, [result("t1", [TOOL_REFERENCE])]),
            cc_line("assistant", 13, [use("t2", "mcp__shop__lookup_order", {"order": "4471"})]),
            cc_line(
                "user", 13.5, [result("t2", [{"type": "text", "text": '{"status": "delivered"}'}])]
            ),
            cc_line("assistant", 14, [{"type": "text", "text": "Order 4471 was delivered."}]),
            cc_line("user", 15, "A line that the harness adds.", isMeta=True),
            cc_line("user", 31, [{"type": "text", "text": "Where is my order 9999?"}]),
            cc_line("assistant", 32, [use("t3", "mcp__shop__lookup_order", {"order": "9999"})]),
            cc_line("user", 32.5, [result("t3", "no such order", error=True)]),
            cc_line("assistant", 33, [use("t4", "Bash", {"command": "cat returns.txt"})]),
            cc_line("user", 33.5, [result("t4", "cat: returns.txt: No such file", error=True)]),
            cc_line("assistant", 45, [{"type": "text", "text": "Anything else?"}]),
            "this line is not JSON",
            {"type": "cost-state", "sessionId": CC},
            cc_line("assistant", 46, [use("t5", "mcp__shop__lookup_order", {"order": "1"})]),
        ]
    },
    "trace": [
        item(None, "claude-code", 5, "message", 2, role="user", output="Warm up."),
        item(None, "claude-code", 6, "message", 3, role="assistant", output="Ready."),
        item(1, "claude-code", 11, "message", 4, role="user", output="Where is my order 4471?"),
        item(
            1,
            "claude-code",
            12.5,
            "tool_call",
            6,
            name="ToolSearch",
            input={"query": "select:shop"},
            output=json.dumps(TOOL_REFERENCE),
            harness_internal=True,
            result_line=7,
        ),
        item(
            1,
            "claude-code",
            13,
            "tool_call",
            8,
            server="shop",
            name="lookup_order",
            input={"order": "4471"},
            output='{"status": "delivered"}',
            result_line=9,
        ),
        item(
            1,
            "claude-code",
            14,
            "message",
            10,
            role="assistant",
            output="Order 4471 was delivered.",
        ),
        item(2, "claude-code", 31, "message", 12, role="user", output="Where is my order 9999?"),
        item(
            2,
            "claude-code",
            32,
            "tool_call",
            13,
            server="shop",
            name="lookup_order",
            input={"order": "9999"},
            error="no such order",
            result_line=14,
        ),
        item(
            2,
            "claude-code",
            33,
            "tool_call",
            15,
            name="Bash",
            input={"command": "cat returns.txt"},
            error="cat: returns.txt: No such file",
            result_line=16,
        ),
        item(None, "claude-code", 45, "message", 17, role="assistant", output="Anything else?"),
        item(
            None,
            "claude-code",
            46,
            "tool_call",
            20,
            server="shop",
            name="lookup_order",
            input={"order": "1"},
            error=NO_RESULT,
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-cc01",
        "turns": 3,
        "items": 11,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.286",
                "items": 11,
                "ignored": {
                    "assistant.thinking": 1,
                    "cost-state": 1,
                    "invalid_json": 1,
                    "queue-operation": 1,
                    "user.meta": 1,
                },
            }
        ],
        "otel": None,
        "backend": None,
        "model_api": None,
        "counts": counts(agent_error=1, tool_error=3, turn_without_model=1, item_between_turns=2),
        "findings": [
            {"check": "agent_error", "turn": 2, "detail": "the agent gave status 500"},
            {
                "check": "tool_error",
                "turn": 2,
                "detail": "lookup_order: no such order",
                **where("claude-code", 13, 14),
            },
            {
                "check": "tool_error",
                "turn": 2,
                "detail": "Bash: cat: returns.txt: No such file",
                **where("claude-code", 15, 16),
            },
            {
                "check": "tool_error",
                "turn": None,
                "detail": f"lookup_order: {NO_RESULT}",
                **where("claude-code", 20),
            },
            {"check": "turn_without_model", "turn": 3, "detail": "no model item in this turn"},
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a message item",
                **where("claude-code", 17),
            },
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a tool_call item",
                **where("claude-code", 20),
            },
        ],
    },
}

APPROVAL = "MCP tool call requires approval, but approval policy is never"
NO_FILE = "cat: returns.txt: No such file or directory\n"

# Codex: 0.1 exchanges without `started`, a dynamic tool, an MCP tool with no completed_at_ms, a
# failed command, an MCP error, a failed dynamic tool, an MCP result with isError, a declined
# command, item types that the trace skips, an item after the last turn and a turn with no item.
CODEX_CASE = {
    "tap": [window(None, 20, v="0.1"), window(None, 40, v="0.1"), window(50, 60)],
    "manifest": {"test": "20261006-080000-cx01", "model_sessions": [CX_SESSION]},
    "sessions": {
        CX_FILE: [
            {
                "timestamp": iso(T0 + 1),
                "type": "session_meta",
                "payload": {
                    "id": CX,
                    "cwd": "/toy-shop",
                    "originator": "toy-shop",
                    "cli_version": "0.160.0",
                },
            },
            {"timestamp": iso(T0 + 10), "type": "event_msg", "payload": {"type": "task_started"}},
            {"timestamp": iso(T0 + 10), "type": "response_item", "payload": {"type": "message"}},
            cx_line(
                11,
                {
                    "type": "UserMessage",
                    "id": "u1",
                    "content": [
                        {"type": "text", "text": "Where is my order 4471?", "text_elements": []}
                    ],
                },
            ),
            cx_line(
                12,
                {
                    "type": "DynamicToolCall",
                    "id": "d1",
                    "tool": "lookup_order",
                    "arguments": {"order": "4471"},
                    "status": "completed",
                    "content_items": [{"type": "inputText", "text": '{"status": "delivered"}'}],
                    "success": True,
                },
            ),
            cx_line(
                13,
                {
                    "type": "McpToolCall",
                    "id": "m1",
                    "server": "stock",
                    "tool": "check_stock",
                    "arguments": {"product": "mug"},
                    "status": "completed",
                    "result": {"content": [{"type": "text", "text": '{"in_stock": 12}'}]},
                },
                at=False,
            ),
            cx_line(
                14,
                {
                    "type": "AgentMessage",
                    "id": "a1",
                    "content": [{"type": "Text", "text": "Delivered, and 12 mugs are in stock."}],
                    "phase": "final_answer",
                },
            ),
            cx_line(15, {"type": "Reasoning", "id": "r1", "summary_text": [], "raw_content": []}),
            cx_line(
                31,
                {
                    "type": "UserMessage",
                    "id": "u2",
                    "content": [
                        {"type": "text", "text": "Can I return a mug?", "text_elements": []}
                    ],
                },
            ),
            cx_line(
                32,
                {
                    "type": "CommandExecution",
                    "id": "c1",
                    "command": ["/bin/zsh", "-lc", "cat returns.txt"],
                    "status": "failed",
                    "aggregated_output": NO_FILE,
                    "exit_code": 1,
                },
            ),
            cx_line(
                33,
                {
                    "type": "McpToolCall",
                    "id": "m2",
                    "server": "stock",
                    "tool": "check_stock",
                    "arguments": {"product": "kite"},
                    "status": "failed",
                    "error": {"message": APPROVAL},
                },
            ),
            cx_line(
                34,
                {
                    "type": "DynamicToolCall",
                    "id": "d2",
                    "tool": "lookup_order",
                    "arguments": {"order": "9999"},
                    "status": "failed",
                    "content_items": [{"type": "inputText", "text": "no such order"}],
                    "success": False,
                },
            ),
            cx_line(
                35,
                {
                    "type": "McpToolCall",
                    "id": "m3",
                    "server": "stock",
                    "tool": "check_stock",
                    "arguments": {"product": "kite"},
                    "status": "completed",
                    "result": {
                        "content": [{"type": "text", "text": "no such product"}],
                        "isError": True,
                    },
                },
            ),
            cx_line(
                36,
                {
                    "type": "CommandExecution",
                    "id": "c2",
                    "command": ["/bin/zsh", "-lc", "rm stock.txt"],
                    "status": "declined",
                    "aggregated_output": None,
                    "exit_code": None,
                },
            ),
            cx_line(
                37,
                {
                    "type": "AgentMessage",
                    "id": "a2",
                    "content": [{"type": "Text", "text": "I cannot check that."}],
                    "phase": "final_answer",
                },
            ),
            cx_line(38, {"type": "FileChange", "id": "f1", "changes": [], "status": "completed"}),
            cx_line(
                70,
                {
                    "type": "AgentMessage",
                    "id": "a3",
                    "content": [{"type": "Text", "text": "Goodbye."}],
                    "phase": "final_answer",
                },
            ),
            {"timestamp": iso(T0 + 71), "type": "world_state", "payload": {}},
        ]
    },
    "trace": [
        item(1, "codex", 11, "message", 4, role="user", output="Where is my order 4471?"),
        item(
            1,
            "codex",
            12,
            "tool_call",
            5,
            name="lookup_order",
            input={"order": "4471"},
            output='{"status": "delivered"}',
        ),
        item(
            1,
            "codex",
            13,
            "tool_call",
            6,
            server="stock",
            name="check_stock",
            input={"product": "mug"},
            output='{"in_stock": 12}',
        ),
        item(
            1,
            "codex",
            14,
            "message",
            7,
            role="assistant",
            output="Delivered, and 12 mugs are in stock.",
        ),
        item(2, "codex", 31, "message", 9, role="user", output="Can I return a mug?"),
        item(
            2,
            "codex",
            32,
            "command",
            10,
            input=["/bin/zsh", "-lc", "cat returns.txt"],
            output=NO_FILE,
            exit_code=1,
        ),
        item(
            2,
            "codex",
            33,
            "tool_call",
            11,
            server="stock",
            name="check_stock",
            input={"product": "kite"},
            error=APPROVAL,
        ),
        item(
            2,
            "codex",
            34,
            "tool_call",
            12,
            name="lookup_order",
            input={"order": "9999"},
            error="no such order",
        ),
        item(
            2,
            "codex",
            35,
            "tool_call",
            13,
            server="stock",
            name="check_stock",
            input={"product": "kite"},
            error="no such product",
        ),
        item(
            2,
            "codex",
            36,
            "command",
            14,
            input=["/bin/zsh", "-lc", "rm stock.txt"],
            error="status declined",
        ),
        item(2, "codex", 37, "message", 15, role="assistant", output="I cannot check that."),
        item(None, "codex", 70, "message", 17, role="assistant", output="Goodbye."),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-cx01",
        "turns": 3,
        "items": 12,
        "sessions": [
            {
                "harness": "codex",
                "session": CX,
                "file": CX_FILE,
                "inferred": True,
                "version": "0.160.0",
                "items": 12,
                "ignored": {
                    "event_msg.task_started": 1,
                    "item_completed.FileChange": 1,
                    "item_completed.Reasoning": 1,
                    "response_item.message": 1,
                    "session_meta": 1,
                    "world_state": 1,
                },
            }
        ],
        "otel": None,
        "backend": None,
        "model_api": None,
        "counts": counts(
            tool_error=3,
            command_failed=2,
            turn_without_model=1,
            item_between_turns=1,
            session_inferred=1,
        ),
        "findings": [
            {
                "check": "tool_error",
                "turn": 2,
                "detail": f"check_stock: {APPROVAL}",
                **where("codex", 11),
            },
            {
                "check": "tool_error",
                "turn": 2,
                "detail": "lookup_order: no such order",
                **where("codex", 12),
            },
            {
                "check": "tool_error",
                "turn": 2,
                "detail": "check_stock: no such product",
                **where("codex", 13),
            },
            {"check": "command_failed", "turn": 2, "detail": "exit code 1", **where("codex", 10)},
            {
                "check": "command_failed",
                "turn": 2,
                "detail": "status declined",
                **where("codex", 14),
            },
            {"check": "turn_without_model", "turn": 3, "detail": "no model item in this turn"},
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a message item",
                **where("codex", 17),
            },
            {
                "check": "session_inferred",
                "turn": None,
                "detail": "found by directory and time",
                "harness": "codex",
                "session": CX,
            },
        ],
    },
}

# Versions: a Claude Code file from an untested version, a Codex file from an untested version
# with no items, and a session that has no file. Turn 1 has items, so no turn_without_model.
UNTESTED_FILE = f"sessions/codex/rollout-2026-10-06T08-00-00-{CX}.jsonl"
VERSION_CASE = {
    "tap": [window(10, 20)],
    "manifest": {
        "test": "20261006-080000-vv01",
        "model_sessions": [
            CC_SESSION,
            {**CX_SESSION, "inferred": False, "pid": 4472},
            {
                "harness": "claude-code",
                "session": "gone",
                "pid": 4473,
                "inferred": False,
                "file": None,
            },
        ],
    },
    "sessions": {
        CC_FILE: [
            cc_line("user", 11, "Hi.", version="2.1.999"),
            cc_line("assistant", 12, [{"type": "text", "text": "Hello."}], version="2.1.999"),
        ],
        UNTESTED_FILE: [
            {
                "timestamp": iso(T0 + 1),
                "type": "session_meta",
                "payload": {"id": CX, "cwd": "/toy-shop", "cli_version": "0.161.0"},
            }
        ],
    },
    "trace": [
        item(1, "claude-code", 11, "message", 1, role="user", output="Hi."),
        item(1, "claude-code", 12, "message", 2, role="assistant", output="Hello."),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-vv01",
        "turns": 1,
        "items": 2,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.999",
                "items": 2,
                "ignored": {},
            },
            {
                "harness": "codex",
                "session": CX,
                "file": CX_FILE,
                "inferred": False,
                "version": "0.161.0",
                "items": 0,
                "ignored": {"session_meta": 1},
            },
            {
                "harness": "claude-code",
                "session": "gone",
                "file": None,
                "inferred": False,
                "version": None,
                "items": 0,
                "ignored": {},
            },
        ],
        "otel": None,
        "backend": None,
        "model_api": None,
        "counts": counts(version_untested=2),
        "findings": [
            {
                "check": "version_untested",
                "turn": None,
                "detail": "version 2.1.999, tested: 2.1.286, 2.1.292",
                "harness": "claude-code",
                "session": CC,
            },
            {
                "check": "version_untested",
                "turn": None,
                "detail": "version 0.161.0, tested: 0.160.0",
                "harness": "codex",
                "session": CX,
            },
        ],
    },
}

# No model sessions, as with an agent that calls no model: an empty trace and no
# turn_without_model findings.
NO_MODEL_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {"test": "20261006-080000-nm01", "model_sessions": []},
    "sessions": {},
    "trace": [],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-nm01",
        "turns": 2,
        "items": 0,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": None,
        "counts": counts(),
        "findings": [],
    },
}

# OpenTelemetry (SPEC.md sections 7.5 and 8.4): the rows of otel.jsonl as the receiver writes them.
# A harness tool_result that the session file has, one that it does not have, app spans with and
# without an error, an app log, a receiver error row, and a span after the last turn.
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
CC_RESOURCE = {"service.name": "claude-code", "service.version": "2.1.286"}
APP_RESOURCE = {"service.name": "toy-shop"}


def tool_event(t: float, tool: str, args: dict) -> dict:
    """A tool_result event of the Agent SDK, as otel.jsonl holds it."""
    attrs = {
        "session.id": CC,
        "event.name": "tool_result",
        "tool_name": "mcp_tool",
        "tool_parameters": json.dumps({"mcp_server_name": "shop", "mcp_tool_name": tool}),
        "tool_input": json.dumps(args),
        "success": "true",
    }
    return {
        "v": 1,
        "type": "log",
        "received": T0 + t + 0.4,
        "service": "claude-code",
        "resource": CC_RESOURCE,
        "scope": "com.anthropic.claude_code.events",
        "time": T0 + t,
        "event_name": "claude_code.tool_result",
        "severity": None,
        "body": "claude_code.tool_result",
        "attributes": attrs,
        "trace_id": None,
        "span_id": None,
    }


def app_span(
    t: float, name: str, attrs: dict, code: int = 0, message: str | None = None, **more: Any
) -> dict:
    return {
        "v": 1,
        "type": "span",
        "received": T0 + t + 0.5,
        "service": "toy-shop",
        "resource": APP_RESOURCE,
        "scope": "toy-shop",
        "trace_id": TRACE_ID,
        "span_id": "b7ad6b7169203331",
        "parent_span_id": None,
        "name": name,
        "start": T0 + t,
        "end": T0 + t + 0.1,
        "attributes": attrs,
        "events": more.pop("events", []),
        "status": {"code": code, "message": message},
    }


def oitem(
    turn: int | None, harness: str, session: str, ts: float, kind: str, line: int, **fields: Any
) -> dict:
    """An expected trace row from otel.jsonl."""
    row = item(turn, "claude-code", ts, kind, line)
    row.update(harness=harness, session=session, source={"file": "otel.jsonl", "line": line})
    return {**row, **fields}


LOOKUP_EVENT = tool_event(12.6, "lookup_order", {"order": "4471"})
REFUND_EVENT = tool_event(32, "refund", {"order": "5120", "amount_eur": 80})
TIMEOUT = {"name": "exception", "time": T0 + 45.1, "attributes": {"exception.message": "timeout"}}
APP_LOG = {
    "v": 1,
    "type": "log",
    "received": T0 + 12,
    "service": "toy-shop",
    "resource": APP_RESOURCE,
    "scope": "toy-shop",
    "time": T0 + 11.6,
    "event_name": None,
    "severity": "INFO",
    "body": "stock checked: 3 left",
    "attributes": {"shop.sku": "teapot-set"},
    "trace_id": None,
    "span_id": None,
}
OTEL_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {"test": "20261006-080000-ot01", "model_sessions": [CC_SESSION]},
    "sessions": {
        CC_FILE: [
            cc_line("user", 11, "Where is my order 4471?"),
            cc_line("assistant", 12, [use("t1", "mcp__shop__lookup_order", {"order": "4471"})]),
            cc_line(
                "user", 12.5, [result("t1", [{"type": "text", "text": '{"status": "delivered"}'}])]
            ),
            cc_line("assistant", 13, [{"type": "text", "text": "Order 4471 was delivered."}]),
            cc_line("user", 31, "Refund my teapot set from order 5120."),
            cc_line("assistant", 33, [{"type": "text", "text": "Your refund is done."}]),
        ]
    },
    "otel": [
        LOOKUP_EVENT,
        REFUND_EVENT,
        app_span(11.5, "check_stock", {"shop.sku": "teapot-set"}, code=1),
        app_span(32.2, "POST /payments", {"http.response.status_code": 402}, 2, "card declined"),
        {"v": 1, "type": "error", "received": T0 + 33, "path": "/v1/traces", "detail": "JSON: x"},
        APP_LOG,
        app_span(45, "GET /stock", {}, 2, None, events=[TIMEOUT]),
    ],
    "trace": [
        item(1, "claude-code", 11, "message", 1, role="user", output="Where is my order 4471?"),
        oitem(
            1,
            "otel",
            TRACE_ID,
            11.5,
            "span",
            3,
            name="check_stock",
            input={"shop.sku": "teapot-set"},
            service="toy-shop",
        ),
        oitem(
            1,
            "otel",
            "",
            11.6,
            "log",
            6,
            input={"shop.sku": "teapot-set"},
            output="stock checked: 3 left",
            service="toy-shop",
        ),
        item(
            1,
            "claude-code",
            12,
            "tool_call",
            2,
            server="shop",
            name="lookup_order",
            input={"order": "4471"},
            output='{"status": "delivered"}',
            result_line=3,
        ),
        oitem(
            1,
            "claude-code",
            CC,
            12.6,
            "log",
            1,
            name="tool_result",
            input=LOOKUP_EVENT["attributes"],
            service="claude-code",
        ),
        item(
            1, "claude-code", 13, "message", 4, role="assistant", output="Order 4471 was delivered."
        ),
        item(
            2,
            "claude-code",
            31,
            "message",
            5,
            role="user",
            output="Refund my teapot set from order 5120.",
        ),
        oitem(
            2,
            "claude-code",
            CC,
            32,
            "log",
            2,
            name="tool_result",
            input=REFUND_EVENT["attributes"],
            service="claude-code",
        ),
        oitem(
            2,
            "otel",
            TRACE_ID,
            32.2,
            "span",
            4,
            name="POST /payments",
            input={"http.response.status_code": 402},
            error="card declined",
            service="toy-shop",
        ),
        item(2, "claude-code", 33, "message", 6, role="assistant", output="Your refund is done."),
        oitem(
            None,
            "otel",
            TRACE_ID,
            45,
            "span",
            7,
            name="GET /stock",
            input={},
            error="timeout",
            service="toy-shop",
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-ot01",
        "turns": 2,
        "items": 11,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.286",
                "items": 5,
                "ignored": {},
            }
        ],
        "otel": {"file": "otel.jsonl", "rows": 7, "items": 6, "ignored": {"error": 1}},
        "backend": None,
        "model_api": None,
        "counts": counts(span_error=2, item_between_turns=1, otel_tool_not_in_session=1),
        "findings": [
            {
                "check": "span_error",
                "turn": 2,
                "detail": "toy-shop: POST /payments: card declined",
                "harness": "otel",
                "session": TRACE_ID,
                "source": {"file": "otel.jsonl", "line": 4},
            },
            {
                "check": "span_error",
                "turn": None,
                "detail": "toy-shop: GET /stock: timeout",
                "harness": "otel",
                "session": TRACE_ID,
                "source": {"file": "otel.jsonl", "line": 7},
            },
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a span item",
                "harness": "otel",
                "session": TRACE_ID,
                "source": {"file": "otel.jsonl", "line": 7},
            },
            {
                "check": "otel_tool_not_in_session",
                "turn": 2,
                "detail": "refund: a tool_result event with no tool call in the session file",
                "harness": "claude-code",
                "session": CC,
                "source": {"file": "otel.jsonl", "line": 2},
            },
        ],
    },
}


# Backend calls (SPEC.md sections 7.6 and 8.4): the rows of backend.jsonl as the proxy writes them.
# A call in turn 1, a 500 status and a call with no answer in turn 2, a binary response between
# the turns, and a row that is not a call.
def body(text: str | None = None, data: bytes | None = None) -> dict:
    raw = data if data is not None else (text or "").encode()
    out: dict[str, Any] = {
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "cut": False,
    }
    if data is not None:
        out["base64"] = base64.b64encode(data).decode()
    else:
        out["text"] = text
    return out


SENT = [["Content-Type", "application/json"], ["X-Api-Key", "<removed>"]]


def call(t: float, name: str, method: str, path: str, status: int | None, **more: Any) -> dict:
    return {
        "v": 1,
        "type": "call",
        "backend": name,
        "started": T0 + t,
        "ts": T0 + t + 0.2,
        "method": method,
        "path": path,
        "query": more.get("query"),
        "request_headers": SENT,
        "request_body": more.get("request", body()),
        "status": status,
        "response_headers": None if status is None else [["Content-Type", "application/json"]],
        "response_body": more.get("response"),
        "error": more.get("error"),
    }


def bitem(turn: int | None, name: str, ts: float, line: int, call_name: str, **fields: Any) -> dict:
    """An expected trace row from backend.jsonl."""
    row = item(turn, "claude-code", ts, "http", line)
    row.update(
        harness="backend",
        session=name,
        name=call_name,
        source={"file": "backend.jsonl", "line": line},
    )
    return {**row, **fields}


REFUSED = "the backend did not answer: [Errno 61] Connection refused"
PAY = '{"order": "5120", "amount_eur": 80}'
BACKEND_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {"test": "20261006-080000-bk01", "model_sessions": []},
    "sessions": {},
    "backend": [
        call(
            12,
            "stock",
            "GET",
            "/stock",
            200,
            query="sku=teapot-set",
            response=body('{"sku": "teapot-set", "left": 3}'),
        ),
        call(
            32,
            "payments",
            "POST",
            "/payments",
            500,
            request=body(PAY),
            response=body('{"error": "card service down"}'),
        ),
        call(33, "payments", "POST", "/payments", None, request=body(PAY), error=REFUSED),
        call(45, "stock", "GET", "/stock/image", 200, response=body(data=b"\x89PNG\x00\xff")),
        {"v": 1, "type": "note", "detail": "a row that is not a call"},
    ],
    "trace": [
        bitem(
            1,
            "stock",
            12,
            1,
            "GET /stock",
            input={"query": "sku=teapot-set", "headers": SENT, "body": None},
            output='{"sku": "teapot-set", "left": 3}',
            exit_code=200,
        ),
        bitem(
            2,
            "payments",
            32,
            2,
            "POST /payments",
            input={"query": None, "headers": SENT, "body": PAY},
            output='{"error": "card service down"}',
            exit_code=500,
        ),
        bitem(
            2,
            "payments",
            33,
            3,
            "POST /payments",
            input={"query": None, "headers": SENT, "body": PAY},
            error=REFUSED,
        ),
        bitem(
            None,
            "stock",
            45,
            4,
            "GET /stock/image",
            input={"query": None, "headers": SENT, "body": None},
            output="(6 bytes that are not UTF-8: base64 in backend.jsonl)",
            exit_code=200,
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-bk01",
        "turns": 2,
        "items": 4,
        "sessions": [],
        "otel": None,
        "backend": {"file": "backend.jsonl", "rows": 5, "items": 4, "ignored": {"note": 1}},
        "model_api": None,
        "counts": counts(backend_error=2, item_between_turns=1),
        "findings": [
            {
                "check": "backend_error",
                "turn": 2,
                "detail": "payments: POST /payments: status 500",
                "harness": "backend",
                "session": "payments",
                "source": {"file": "backend.jsonl", "line": 2},
            },
            {
                "check": "backend_error",
                "turn": 2,
                "detail": f"payments: POST /payments: {REFUSED}",
                "harness": "backend",
                "session": "payments",
                "source": {"file": "backend.jsonl", "line": 3},
            },
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a http item",
                "harness": "backend",
                "session": "stock",
                "source": {"file": "backend.jsonl", "line": 4},
            },
        ],
    },
}


# Direct model API calls (SPEC.md sections 7.7 and 8.4): the rows of model_api.jsonl as the proxy
# writes them. In turn 1, a streamed Anthropic call with a tool call, and a JSON call with the tool
# result. In turn 2, an OpenAI call with status 429, a harness call, a streamed OpenAI call with a
# tool call that has no result, a call to a path that is not a model call, and a row that is not
# a call.
def sse(events: list[dict], named: bool = True) -> str:
    out = ""
    for e in events:
        out += (f"event: {e['type']}\n" if named else "") + f"data: {json.dumps(e)}\n\n"
    return out


MSENT = [["Content-Type", "application/json"], ["x-api-key", "<removed>"]]
ASK = "Is the teapot set in stock?"
REFUND_ASK = "Refund order 5120."
TOOLS = [{"name": "check_stock", "input_schema": {"type": "object"}}]
STOCK_CALL = {"id": "toolu_1", "name": "check_stock", "input": {"sku": "teapot-set"}}
ANTHROPIC_STREAM = sse(
    [
        {
            "type": "message_start",
            "message": {"id": "msg_1", "model": "claude-toy", "usage": {"input_tokens": 40}},
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Let me "},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "check."},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "check_stock",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"sku": "tea'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": 'pot-set"}'},
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 20},
        },
        {"type": "message_stop"},
    ]
)
ANTHROPIC_JSON = json.dumps(
    {
        "id": "msg_2",
        "type": "message",
        "model": "claude-toy",
        "content": [{"type": "text", "text": "Yes, 3 teapot sets are in stock."}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 70, "output_tokens": 12},
    }
)
LIMIT = json.dumps({"error": {"message": "Rate limit reached", "type": "rate_limit"}})


def chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "chatcmpl-1",
        "model": "gpt-toy",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


OPENAI_STREAM = (
    sse(
        [
            chunk(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "refund", "arguments": ""},
                        }
                    ],
                }
            ),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"order": "5120", '}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"amount_eur": 80}'}}]}),
            chunk({}, "tool_calls"),
        ],
        named=False,
    )
    + "data: [DONE]\n\n"
)


def result(**more: Any) -> dict:
    out = {"model": None, "text": "", "tool_calls": [], "stop_reason": None, "usage": None}
    return {**out, "error": None, **more}


def mcall(t: float, api: str, path: str, status: int, request: Any, **more: Any) -> dict:
    kind = "text/event-stream" if more.get("stream") else "application/json"
    return {
        "v": 1,
        "type": "call",
        "api": api,
        "harness": more.get("harness"),
        "started": T0 + t,
        "ts": T0 + t + more.get("took", 1.0),
        "method": "POST",
        "path": path,
        "query": None,
        "request_headers": MSENT,
        "request_body": more.get("request_body") or body(json.dumps(request)),
        "status": status,
        "response_headers": [["Content-Type", kind]],
        "response_body": more.get("response_body") or body(more.get("response", "")),
        "error": None,
        "stream": bool(more.get("stream")),
        "result": more.get("result"),
    }


def omitted(text: str) -> dict:
    raw = text.encode()
    return {
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "cut": False,
        "omitted": True,
    }


def mitem(turn: int, api: str, ts: float, line: int, kind: str, **fields: Any) -> dict:
    """An expected trace row from model_api.jsonl."""
    row = item(turn, "claude-code", ts, kind, line)
    row.update(harness="model_api", session=api, source={"file": "model_api.jsonl", "line": line})
    return {**row, **fields}


def info(path: str, model: str | None, stop: str | None, usage: Any) -> dict:
    return {"path": path, "model": model, "stop_reason": stop, "usage": usage}


MESSAGES = "/v1/messages"
COMPLETIONS = "/chat/completions"
ASKED = [{"role": "user", "content": ASK}]
ANSWERED = [
    *ASKED,
    {
        "role": "assistant",
        "content": [{"type": "text", "text": "Let me check."}, {"type": "tool_use", **STOCK_CALL}],
    },
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": [{"type": "text", "text": "3 left"}],
            }
        ],
    },
]
REFUND_MESSAGES = [
    {"role": "system", "content": "You are the toy shop agent."},
    {"role": "user", "content": REFUND_ASK},
]
REFUND_INPUT = {"order": "5120", "amount_eur": 80}
STREAM_USAGE = {"input_tokens": 40, "output_tokens": 20}
JSON_USAGE = {"input_tokens": 70, "output_tokens": 12}
HARNESS_REQUEST = '{"model": "claude-toy", "system": "harness instructions"}'
MODEL_API_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {"test": "20261006-080000-ma01", "model_sessions": []},
    "sessions": {},
    "model_api": [
        mcall(
            11,
            "anthropic",
            MESSAGES,
            200,
            {"model": "claude-toy", "stream": True, "tools": TOOLS, "messages": ASKED},
            stream=True,
            took=2,
            response=ANTHROPIC_STREAM,
            result=result(
                model="claude-toy",
                text="Let me check.",
                tool_calls=[STOCK_CALL],
                stop_reason="tool_use",
                usage=STREAM_USAGE,
            ),
        ),
        mcall(
            14,
            "anthropic",
            MESSAGES,
            200,
            {"model": "claude-toy", "tools": TOOLS, "messages": ANSWERED},
            took=2,
            response=ANTHROPIC_JSON,
            result=result(
                model="claude-toy",
                text="Yes, 3 teapot sets are in stock.",
                stop_reason="end_turn",
                usage=JSON_USAGE,
            ),
        ),
        mcall(
            31,
            "openai",
            COMPLETIONS,
            429,
            {"model": "gpt-toy", "messages": REFUND_MESSAGES},
            response=LIMIT,
            result=result(error="Rate limit reached"),
        ),
        mcall(
            32,
            "anthropic",
            MESSAGES,
            200,
            None,
            harness="claude-code",
            stream=True,
            request_body=omitted(HARNESS_REQUEST),
            response_body=omitted(ANTHROPIC_STREAM),
        ),
        mcall(
            34,
            "openai",
            COMPLETIONS,
            200,
            {"model": "gpt-toy", "stream": True, "messages": REFUND_MESSAGES},
            stream=True,
            response=OPENAI_STREAM,
            result=result(
                model="gpt-toy",
                tool_calls=[{"id": "call_1", "name": "refund", "input": REFUND_INPUT}],
                stop_reason="tool_calls",
            ),
        ),
        {
            **mcall(36, "anthropic", "/api/hello", 200, None),
            "method": "HEAD",
            "request_body": body(),
            "result": None,
        },
        {"v": 1, "type": "note", "detail": "a row that is not a call"},
    ],
    "trace": [
        mitem(1, "anthropic", 11, 1, "message", role="user", output=ASK),
        mitem(
            1,
            "anthropic",
            13,
            1,
            "message",
            role="assistant",
            input=info(MESSAGES, "claude-toy", "tool_use", STREAM_USAGE),
            output="Let me check.",
            exit_code=200,
        ),
        mitem(
            1,
            "anthropic",
            13,
            1,
            "tool_call",
            name="check_stock",
            input={"sku": "teapot-set"},
            output="3 left",
        ),
        mitem(
            1,
            "anthropic",
            16,
            2,
            "message",
            role="assistant",
            input=info(MESSAGES, "claude-toy", "end_turn", JSON_USAGE),
            output="Yes, 3 teapot sets are in stock.",
            exit_code=200,
        ),
        mitem(2, "openai", 31, 3, "message", role="user", output=REFUND_ASK),
        mitem(
            2,
            "openai",
            32,
            3,
            "message",
            role="assistant",
            input=info(COMPLETIONS, None, None, None),
            error="Rate limit reached",
            exit_code=429,
        ),
        mitem(2, "openai", 34, 5, "message", role="user", output=REFUND_ASK),
        mitem(
            2,
            "openai",
            35,
            5,
            "message",
            role="assistant",
            input=info(COMPLETIONS, "gpt-toy", "tool_calls", None),
            exit_code=200,
        ),
        mitem(2, "openai", 35, 5, "tool_call", name="refund", input=REFUND_INPUT),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-ma01",
        "turns": 2,
        "items": 9,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": {
            "file": "model_api.jsonl",
            "rows": 7,
            "items": 9,
            "ignored": {"note": 1},
            "harness_calls": {"claude-code": 1},
            "other_calls": 1,
        },
        "counts": counts(model_api_error=1),
        "findings": [
            {
                "check": "model_api_error",
                "turn": 2,
                "detail": "openai: /chat/completions: Rate limit reached",
                "harness": "model_api",
                "session": "openai",
                "source": {"file": "model_api.jsonl", "line": 3},
            },
        ],
    },
}

TRACE_CASES = {
    "claude_code_toy_shop": CLAUDE_CASE,
    "codex_toy_shop": CODEX_CASE,
    "untested_versions": VERSION_CASE,
    "no_model_sessions": NO_MODEL_CASE,
    "otel_toy_shop": OTEL_CASE,
    "backend_toy_shop": BACKEND_CASE,
    "model_api_toy_shop": MODEL_API_CASE,
}


# Seal cases (SPEC.md section 7.4). Each case is a test folder after its end, the copy of the seal in
# `home/seals/`, and the result that `verbatim-relay verify --json` must give.
SEAL_TEST = "20261006-120000-se01"
SEALED_AT = 1791316800.0
SEAL_FILES = {
    "manifest.json": '{"test": "20261006-120000-se01", "ended": 1791316800.0}\n',
    "tap.jsonl": '{"v": "0.2", "type": "exchange", "input": "Hi, where is my order 5120?"}\n',
    "relay.jsonl": '{"v": "0.2", "type": "turn", "said": "Hi, where is my order 5120?"}\n',
    "trace.jsonl": '{"v": "0.1", "type": "model_item", "name": "lookup_order"}\n',
    "findings.json": '{"findings": []}\n',
    "audit.json": '{"exit": 0}\n',
    "sessions/claude-code/s1.jsonl": '{"type": "user"}\n',
    "report.md": "# Test 20261006-120000-se01: evaluation\n",
    "bridge.log": "test 20261006-120000-se01 ended\n",
}
UNSEALED_FILES = {"report.md", "bridge.log"}


def seal_of(files: dict[str, str], copy: bool) -> dict:
    sealed = {k: sha(v) for k, v in sorted(files.items()) if k not in UNSEALED_FILES}
    return {"v": 1, "test": SEAL_TEST, "sealed": SEALED_AT, "files": sealed, "copy": copy}


def verified(intact: bool, copy: str, sealed: bool = True, **lists: list[str]) -> dict:
    out = {"test": SEAL_TEST, "sealed": sealed, "intact": intact, "copy": copy}
    return {**out, **{k: lists.get(k, []) for k in ("changed", "missing", "added")}}


SEAL_CASES: dict[str, dict] = {
    "intact": {"verify": verified(True, "same")},
    # report.md, bridge.log and denied.jsonl change after the end. They are not in the seal.
    "files_that_change_after_the_end": {
        "after": {
            "report.md": "# Test 20261006-120000-se01: evaluation\n\nNo issue.\n",
            "bridge.log": "test 20261006-120000-se01 ended\ntrace rebuilt\n",
            "denied.jsonl": '{"v": "0.2", "type": "blocked_call", "tool": "Bash"}\n',
        },
        "verify": verified(True, "same"),
    },
    "changed_record": {
        "after": {"trace.jsonl": '{"v": "0.1", "type": "model_item", "name": "refund"}\n'},
        "verify": verified(False, "same", changed=["trace.jsonl"]),
    },
    "missing_record": {
        "remove": ["findings.json"],
        "verify": verified(False, "same", missing=["findings.json"]),
    },
    "new_file": {
        "after": {"sessions/codex/extra.jsonl": '{"type": "session_meta"}\n'},
        "verify": verified(False, "same", added=["sessions/codex/extra.jsonl"]),
    },
    "copies_differ": {
        "copy_files": {"tap.jsonl": '{"v": "0.2", "type": "exchange", "input": "Hi"}\n'},
        "verify": verified(False, "different"),
    },
    "copy_missing": {"no_copy_file": True, "verify": verified(False, "missing")},
    # The bridge could not write the copy, for example in a sandbox. The seal says so.
    "no_copy": {"copy": False, "no_copy_file": True, "verify": verified(True, "none")},
    # A changed record, with a seal.json that has the new hash and says `copy: false`. The copy
    # outside the project still exists, so verify compares it.
    "copy_flag_cleared": {
        "after": {"trace.jsonl": '{"v": "0.1", "type": "model_item", "name": "refund"}\n'},
        "seal_files": {"trace.jsonl": '{"v": "0.1", "type": "model_item", "name": "refund"}\n'},
        "copy": False,
        "verify": verified(False, "different"),
    },
    "seal_missing": {"no_seal_file": True, "verify": verified(False, "same", sealed=False)},
    "no_seal": {
        "no_seal_file": True,
        "no_copy_file": True,
        "verify": verified(False, "none", sealed=False),
    },
}


def write_seal_case(d: Path, case: dict) -> None:
    folder = d / "test" / SEAL_TEST
    files = {**SEAL_FILES, **case.get("after", {})}
    for name in case.get("remove", []):
        del files[name]
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    seal = seal_of({**SEAL_FILES, **case.get("seal_files", {})}, case.get("copy", True))
    if not case.get("no_seal_file"):
        (folder / "seal.json").write_text(json.dumps(seal, indent=1, sort_keys=True) + "\n")
    if not case.get("no_copy_file"):
        copy = seal_of({**SEAL_FILES, **case.get("copy_files", {})}, True)
        (d / "home" / "seals").mkdir(parents=True)
        (d / "home" / "seals" / f"{SEAL_TEST}.json").write_text(
            json.dumps(copy, indent=1, sort_keys=True) + "\n"
        )
    (d / "expect_verify.json").write_text(json.dumps(case["verify"], indent=1) + "\n")


# Receiver cases (SPEC.md section 7.5). This small protobuf writer follows the public OTLP .proto
# files. Each case is a request body and the otel.jsonl rows that the receiver must write for it.
def pb_varint(n: int) -> bytes:
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def pb(number: int, value: Any) -> bytes:
    """One field: an int or a bool is a varint, a float is a double, bytes or str are
    length-delimited."""
    if isinstance(value, int):
        return pb_varint(number << 3) + pb_varint(int(value) & ((1 << 64) - 1))
    if isinstance(value, float):
        return pb_varint(number << 3 | 1) + struct.pack("<d", value)
    data = value.encode() if isinstance(value, str) else value
    return pb_varint(number << 3 | 2) + pb_varint(len(data)) + data


def pb_fixed64(number: int, n: int) -> bytes:
    return pb_varint(number << 3 | 1) + struct.pack("<Q", n)


def pb_kv(key: str, any_value: bytes) -> bytes:
    return pb(1, key) + pb(2, any_value)


RECEIVED = T0 + 100
NS = 1_000_000_000


def ns(t: float) -> int:
    """T0 + t in nanoseconds, with no float error."""
    return int(T0) * NS + round(t * NS)


SPAN_ATTRS = [
    pb_kv("shop.sku", pb(1, "teapot-set")),
    pb_kv("shop.count", pb(3, -2)),
    pb_kv("shop.gift", pb(2, True)),
    pb_kv("shop.price", pb(4, 80.5)),
    pb_kv("shop.tags", pb(5, pb(1, pb(1, "fragile")) + pb(1, pb(3, 3)))),
    pb_kv(
        "shop.box", pb(6, pb(1, pb_kv("size", pb(1, "M"))) + pb(1, pb_kv("user.id", pb(1, "u-1"))))
    ),
    pb_kv("shop.raw", pb(7, b"\x01\x02")),
    pb_kv("user.email", pb(1, "tester@example.com")),
    pb_kv("customer_email", pb(1, "buyer@example.com")),
]
SPAN_PB = (
    pb(1, bytes.fromhex(TRACE_ID))
    + pb(2, bytes.fromhex("b7ad6b7169203331"))
    + pb(4, bytes.fromhex("00f067aa0ba902b7"))
    + pb(5, "POST /payments")
    + pb(6, 3)
    + pb_fixed64(7, ns(32))
    + pb_fixed64(8, ns(32.25))
    + b"".join(pb(9, kv) for kv in SPAN_ATTRS)
    + pb(
        11,
        pb_fixed64(1, ns(32.2))
        + pb(2, "exception")
        + pb(3, pb_kv("exception.message", pb(1, "card declined"))),
    )
    + pb(15, pb(2, "payment failed") + pb(3, 2))
    + pb(99, "a field that the receiver does not know")
)
APP_RESOURCE_PB = pb(1, pb_kv("service.name", pb(1, "toy-shop"))) + pb(
    1, pb_kv("user.account_id", pb(1, "a-1"))
)
TRACES_PB = pb(
    1, pb(1, APP_RESOURCE_PB) + pb(2, pb(1, pb(1, "toy-shop") + pb(2, "1.0")) + pb(2, SPAN_PB))
)
SPAN_ROW = {
    "v": 1,
    "type": "span",
    "received": RECEIVED,
    "service": "toy-shop",
    "resource": {"service.name": "toy-shop"},
    "scope": "toy-shop",
    "trace_id": TRACE_ID,
    "span_id": "b7ad6b7169203331",
    "parent_span_id": "00f067aa0ba902b7",
    "name": "POST /payments",
    "start": T0 + 32,
    "end": T0 + 32.25,
    "attributes": {
        "shop.sku": "teapot-set",
        "shop.count": -2,
        "shop.gift": True,
        "shop.price": 80.5,
        "shop.tags": ["fragile", 3],
        "shop.box": {"size": "M"},
        "shop.raw": "AQI=",
    },
    "events": [
        {
            "time": T0 + 32.2,
            "name": "exception",
            "attributes": {"exception.message": "card declined"},
        }
    ],
    "status": {"code": 2, "message": "payment failed"},
}


def js_kv(key: str, v: dict) -> dict:
    return {"key": key, "value": v}


TRACES_JSON = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [
                    js_kv("service.name", {"stringValue": "toy-shop"}),
                    js_kv("user.account_id", {"stringValue": "a-1"}),
                ]
            },
            "scopeSpans": [
                {
                    "scope": {"name": "toy-shop", "version": "1.0"},
                    "spans": [
                        {
                            "traceId": TRACE_ID,
                            "spanId": "b7ad6b7169203331",
                            "parentSpanId": "00f067aa0ba902b7",
                            "name": "POST /payments",
                            "kind": 3,
                            "startTimeUnixNano": str(ns(32)),
                            "endTimeUnixNano": str(ns(32.25)),
                            "attributes": [
                                js_kv("shop.sku", {"stringValue": "teapot-set"}),
                                js_kv("shop.count", {"intValue": "-2"}),
                                js_kv("shop.gift", {"boolValue": True}),
                                js_kv("shop.price", {"doubleValue": 80.5}),
                                js_kv(
                                    "shop.tags",
                                    {
                                        "arrayValue": {
                                            "values": [
                                                {"stringValue": "fragile"},
                                                {"intValue": "3"},
                                            ]
                                        }
                                    },
                                ),
                                js_kv(
                                    "shop.box",
                                    {
                                        "kvlistValue": {
                                            "values": [
                                                js_kv("size", {"stringValue": "M"}),
                                                js_kv("user.id", {"stringValue": "u-1"}),
                                            ]
                                        }
                                    },
                                ),
                                js_kv("shop.raw", {"bytesValue": "AQI="}),
                                js_kv("user.email", {"stringValue": "tester@example.com"}),
                                js_kv("customer_email", {"stringValue": "buyer@example.com"}),
                            ],
                            "events": [
                                {
                                    "timeUnixNano": str(ns(32.2)),
                                    "name": "exception",
                                    "attributes": [
                                        js_kv("exception.message", {"stringValue": "card declined"})
                                    ],
                                }
                            ],
                            "status": {"code": "STATUS_CODE_ERROR", "message": "payment failed"},
                        }
                    ],
                }
            ],
        }
    ]
}


def log_pb(
    t: float, name: str, attrs: list[bytes], body: str | None = None, observed: bool = False
) -> bytes:
    nanos = ns(t)
    out = pb_fixed64(11, nanos) if observed else pb_fixed64(1, nanos)
    out += pb(3, "INFO") + b"".join(pb(6, kv) for kv in attrs)
    return out + (pb(5, pb(1, body)) if body is not None else b"") + pb(12, name)


CC_RESOURCE_PB = pb(1, pb_kv("service.name", pb(1, "claude-code"))) + pb(
    1, pb_kv("service.version", pb(1, "2.1.286"))
)
CX_RESOURCE_PB = pb(1, pb_kv("service.name", pb(1, "codex_app_server")))
LOGS_PB = (
    pb(
        1,
        pb(1, CC_RESOURCE_PB)
        + pb(
            2,
            pb(1, pb(1, "com.anthropic.claude_code.events"))
            + pb(
                2,
                log_pb(
                    12.6,
                    "",
                    [
                        pb_kv("event.name", pb(1, "tool_result")),
                        pb_kv("session.id", pb(1, CC)),
                        pb_kv("user.email", pb(1, "tester@example.com")),
                    ],
                    "claude_code.tool_result",
                ),
            )
            + pb(
                2,
                log_pb(
                    5,
                    "",
                    [pb_kv("event.name", pb(1, "plugin_loaded"))],
                    "claude_code.plugin_loaded",
                ),
            ),
        ),
    )
    + pb(
        1,
        pb(1, CX_RESOURCE_PB)
        + pb(
            2,
            pb(
                2,
                log_pb(
                    13,
                    "event core/src/x.rs:1",
                    [
                        pb_kv("event.name", pb(1, "codex.tool_result")),
                        pb_kv("conversation.id", pb(1, CX)),
                    ],
                    observed=True,
                ),
            ),
        ),
    )
    + pb(
        1,
        pb(1, APP_RESOURCE_PB)
        + pb(
            2,
            pb(
                2,
                log_pb(11.6, "", [pb_kv("shop.sku", pb(1, "teapot-set"))], "stock checked: 3 left"),
            ),
        ),
    )
)


def log_row(
    service: str,
    resource: dict,
    scope: str | None,
    t: float,
    name: str | None,
    body: Any,
    attrs: dict,
    severity: str = "INFO",
) -> dict:
    return {
        "v": 1,
        "type": "log",
        "received": RECEIVED,
        "service": service,
        "resource": resource,
        "scope": scope,
        "time": T0 + t,
        "event_name": name,
        "severity": severity,
        "body": body,
        "attributes": attrs,
        "trace_id": None,
        "span_id": None,
    }


LOG_ROWS = [
    log_row(
        "claude-code",
        {"service.name": "claude-code", "service.version": "2.1.286"},
        "com.anthropic.claude_code.events",
        12.6,
        "tool_result",
        "claude_code.tool_result",
        {"event.name": "tool_result", "session.id": CC},
    ),
    log_row(
        "codex_app_server",
        {"service.name": "codex_app_server"},
        None,
        13,
        "codex.tool_result",
        None,
        {"event.name": "codex.tool_result", "conversation.id": CX},
    ),
    log_row(
        "toy-shop",
        {"service.name": "toy-shop"},
        None,
        11.6,
        None,
        "stock checked: 3 left",
        {"shop.sku": "teapot-set"},
    ),
]
HARNESS_SPANS_PB = pb(
    1, pb(1, CX_RESOURCE_PB) + pb(2, pb(2, pb(5, "fs.read_file") + pb_fixed64(7, ns(0))))
)
OTLP_CASES: dict[str, dict] = {
    "traces_protobuf": {
        "path": "/v1/traces",
        "type": "application/x-protobuf",
        "body": TRACES_PB,
        "rows": [SPAN_ROW],
    },
    "traces_json": {
        "path": "/v1/traces",
        "type": "application/json",
        "body": json.dumps(TRACES_JSON).encode(),
        "rows": [SPAN_ROW],
    },
    # The harness events that the receiver keeps, a harness event that it drops, an app log, gzip.
    "logs_protobuf_gzip": {
        "path": "/v1/logs",
        "type": "application/x-protobuf",
        "encoding": "gzip",
        "body": LOGS_PB,
        "rows": LOG_ROWS,
    },
    "harness_spans_dropped": {
        "path": "/v1/traces",
        "type": "application/x-protobuf",
        "body": HARNESS_SPANS_PB,
        "rows": [],
    },
    "metrics_dropped": {
        "path": "/v1/metrics",
        "type": "application/json",
        "body": b'{"resourceMetrics": []}',
        "rows": None,
    },
    "truncated_protobuf": {
        "path": "/v1/traces",
        "type": "application/x-protobuf",
        "body": TRACES_PB[:-5],
        "error": "a length-delimited field ends early",
    },
}


def write_otlp_case(d: Path, case: dict) -> None:
    d.mkdir(parents=True)
    # body.bin is the body before gzip, because gzip output is not the same on each platform. The
    # test compresses it when `encoding` is gzip.
    (d / "body.bin").write_bytes(case["body"])
    request = {k: case.get(k) for k in ("path", "type", "encoding")}
    expect = {"received": RECEIVED, "rows": case.get("rows"), "error": case.get("error")}
    (d / "request.json").write_text(json.dumps(request, indent=1) + "\n")
    (d / "expect.json").write_text(json.dumps(expect, indent=1, ensure_ascii=False) + "\n")


def write(path: Path, rows: list | None) -> None:
    if rows is None:
        return
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows]
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def main() -> None:
    shutil.rmtree(CASES, ignore_errors=True)
    for name, (tap, relay, expect) in CASES_BY_NAME.items():
        d = CASES / name
        d.mkdir(parents=True)
        write(d / "tap.jsonl", tap)
        write(d / "relay.jsonl", relay)
        (d / "expect.json").write_text(json.dumps(expect, indent=1) + "\n")
    shutil.rmtree(CONTRACT, ignore_errors=True)
    for name, case in CONTRACT_CASES.items():
        d = CONTRACT / name
        d.mkdir(parents=True)
        (d / "case.json").write_text(json.dumps(case, indent=1, ensure_ascii=False) + "\n")
    shutil.rmtree(TRACE, ignore_errors=True)
    for name, case in TRACE_CASES.items():
        d = TRACE / name
        d.mkdir(parents=True)
        write(d / "tap.jsonl", case["tap"])
        (d / "manifest.json").write_text(json.dumps(case["manifest"], indent=1) + "\n")
        for rel, lines in case["sessions"].items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            write(d / rel, lines)
        write(d / "otel.jsonl", case.get("otel"))
        write(d / "backend.jsonl", case.get("backend"))
        write(d / "model_api.jsonl", case.get("model_api"))
        write(d / "expect_trace.jsonl", case["trace"])
        text = json.dumps(case["findings"], indent=1, ensure_ascii=False)
        (d / "expect_findings.json").write_text(text + "\n")
    shutil.rmtree(OTLP, ignore_errors=True)
    for name, case in OTLP_CASES.items():
        write_otlp_case(OTLP / name, case)
    shutil.rmtree(SEAL, ignore_errors=True)
    for name, case in SEAL_CASES.items():
        write_seal_case(SEAL / name, case)
    print(
        f"{len(CASES_BY_NAME)} audit cases, {len(CONTRACT_CASES)} contract cases, "
        f"{len(TRACE_CASES)} trace cases, {len(SEAL_CASES)} seal cases and "
        f"{len(OTLP_CASES)} receiver cases written"
    )


if __name__ == "__main__":
    main()

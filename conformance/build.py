"""Write the conformance cases. Each expectation here is written by hand from SPEC.md.

`cases/` holds the audit cases (SPEC.md section 3). `contract/` holds the stdio cases (sections 4.2
and 6): the requests that the relay posts, what a scripted agent does with each one, and the rows
and HTTP statuses that the tap must give. `trace/` holds the trace cases (section 8). `seal/` holds
the seal cases (section 7.4). `otlp/` holds the receiver cases (section 7.5). `policy/` holds the
deny cases of the policy file (sections 5 and 7.9). `guard/` holds the deny cases of the state
folder (section 5). `evaluation/` holds the cases of the rule for a check test (section 9.1).
`notes/` holds the cases of the notes record (section 2.3).
`discovery/` holds the cases of the egress answer (section 7.11).
`database/` holds the cases of the variable of a Postgres proxy (section 7.13).

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
POLICY = Path(__file__).parent / "policy"
GUARD = Path(__file__).parent / "guard"
CONTROL = Path(__file__).parent / "control"
EVALUATION = Path(__file__).parent / "evaluation"
NOTES = Path(__file__).parent / "notes"
DISCOVERY = Path(__file__).parent / "discovery"
DATABASE = Path(__file__).parent / "database"


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
# A lone UTF-16 surrogate: the first half of an emoji. JavaScript makes it when it cuts a text,
# for example with `reply.slice(0, 280)`. JSON can escape it, but UTF-8 cannot encode it.
LONE = "\ud83d"


def lone_surrogate(row: dict, field: str) -> str:
    """The row as a raw line, with a lone surrogate at the end of a text field.

    The hash is of the text with U+FFFD in place of the surrogate, as a JavaScript writer makes it.
    """
    text = row[field] + LONE
    return json.dumps({**row, field: text, f"{field}_sha256": sha(row[field] + "\ufffd")})


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
# A failed stream row has version 0.3 (section 2), because a 0.2 reader refuses its null reply.
FAILED_STREAM = {
    **ex(M2, None, v="0.3", error=ENDED_EARLY),
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
    # The detail of a blocked call with an astral character, with an escaped lone surrogate and
    # with 300 code points that are 582 UTF-16 code units (SPEC.md section 2.2).
    "blocked_call_detail_with_astral_characters": (
        CLEAN_TAP,
        [
            CLEAN_RELAY[0],
            {**BLOCKED, "detail": '{"command": "echo Mug sold out 😀"}'},
            {**BLOCKED, "detail": '{"command": "echo Mug sold out \\ud83d"}'},
            {**BLOCKED, "detail": '{"command": "echo ' + "📦" * 282},
            *CLEAN_RELAY[1:],
        ],
        {"exit": 0, "breaks": [], "blocked_calls": 3},
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
    # The chat page writes turns with the harness "pane" and no session (SPEC.md sections 2.2
    # and 5). A test can mix them with turns of the harness chat. The audit matches them the same.
    "pane_turns_clean": (
        CLEAN_TAP,
        [
            {**turn(M1, R1, v="0.2"), "harness": "pane", "ok": True},
            {**turn(M2, R2, v="0.2"), "ok": True, "session": "s1"},
            {**turn(M3, R3, v="0.2"), "harness": "pane", "ok": True},
        ],
        {"exit": 0, "breaks": []},
    ),
    "pane_turn_altered_reply": (
        CLEAN_TAP,
        [
            {**turn(M1, R1, v="0.2"), "harness": "pane", "ok": True},
            {**turn(M2, R2.replace("Café", "Care"), v="0.2"), "harness": "pane", "ok": True},
            {**turn(M3, R3, v="0.2"), "harness": "pane", "ok": True},
        ],
        {"exit": 1, "breaks": [["altered_reply", 2, 2]]},
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
    # JSON that nests too deep makes Python json.loads raise RecursionError, not ValueError. The
    # reader refuses the line as a line that is not JSON (SPEC.md section 2, #471).
    "json_nests_too_deep": (
        [CLEAN_TAP[0], '{"a": ' + "[" * 100_000 + "]" * 100_000 + "}", *CLEAN_TAP[1:]],
        CLEAN_RELAY,
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
    # One byte of a text changed after the write, and its hash did not change.
    "reply_changed_after_the_write": (
        [{**CLEAN_TAP[0], "reply": R1.replace("30 days", "31 days")}, *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "shown_changed_after_the_write": (
        CLEAN_TAP,
        [{**CLEAN_RELAY[0], "shown": R1.replace("30 days", "31 days")}, *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "wrong_version": (
        CLEAN_TAP,
        [{**CLEAN_RELAY[0], "v": "9.9"}, *CLEAN_RELAY[1:]],
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
    "lone_surrogate_in_the_tap_record": (
        [lone_surrogate(CLEAN_TAP[0], "reply"), *CLEAN_TAP[1:]],
        [turn(M1, R1 + "\ufffd"), *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "lone_surrogate_in_the_relay_record": (
        CLEAN_TAP,
        [lone_surrogate(CLEAN_RELAY[0], "shown"), *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    # NaN, Infinity and -Infinity are not JSON (SPEC.md section 2). json.dumps writes them, so a
    # test can make the line. JSON.parse refuses them, so the Python reader refuses them too (#96).
    "nan_in_the_relay_record": (
        CLEAN_TAP,
        [
            CLEAN_RELAY[0],
            json.dumps({**CLEAN_RELAY[1], "ts": float("nan")}, ensure_ascii=False),
            CLEAN_RELAY[2],
        ],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "infinity_in_the_tap_record": (
        [
            CLEAN_TAP[0],
            json.dumps({**CLEAN_TAP[1], "ts": float("inf")}, ensure_ascii=False),
            CLEAN_TAP[2],
        ],
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
    # A 0.2 reader refuses a failed stream for its null reply. The row must have version 0.3.
    "streamed_reply_failed_in_a_v02_row": (
        [STREAM_TAP[0], {**FAILED_STREAM, "v": "0.2"}, STREAM_TAP[2]],
        RELAY_02,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    # A row of version 0.3 can have each type and field of version 0.2, in both records.
    "v03_rows_of_each_type": (
        [{**STREAM_TAP[0], "v": "0.3"}, {**SESSION_A, "v": "0.3"}, *STREAM_TAP[1:]],
        [{**RELAY_02[0], "v": "0.3"}, *RELAY_02[1:]],
        {"exit": 0, "breaks": [], "model_sessions": 1},
    ),
    "stream_in_a_v01_row": (
        [{**CLEAN_TAP[0], "stream": STREAM_TAP[0]["stream"]}, *CLEAN_TAP[1:]],
        CLEAN_RELAY,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "stream_in_a_v01_relay_row": (
        CLEAN_TAP,
        [{**CLEAN_RELAY[0], "stream": STREAM_TAP[0]["stream"]}, *CLEAN_RELAY[1:]],
        {"exit": 2, "errors": ["record_invalid"]},
    ),
    "stream_wrong_field_type": (
        [{**STREAM_TAP[0], "stream": {"sha256": "abc", "bytes": 120}}, *STREAM_TAP[1:]],
        RELAY_02,
        {"exit": 2, "errors": ["record_invalid"]},
    ),
}


# The stdio cases. Each request is the body that the relay posts, with the tap token and the
# Content-Type application/json. A request can also be an object: the body, the token ("right",
# "none" or "wrong") and more headers (SPEC.md section 4.2). Each agent step says what the
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
STRAY = {"type": "unparsed", "method": "STDIO", "path": "stdout"}
TIMED_OUT = {"type": "exchange", "input": TRICKY, "status": None, "reply": None}

CONTRACT_CASES: dict[str, dict] = {
    # A request that is not from a relay gets 403. The agent gets no line and the tap writes no
    # row. Thus the first line of the agent is the reply to the last request.
    "requests_not_from_a_relay_are_refused": {
        "requests": [
            {"body": req(TRICKY), "token": "none"},
            {"body": req(TRICKY), "token": "wrong"},
            {"body": req(TRICKY), "token": "right", "headers": {"Origin": "https://example.com"}},
            {"body": req(TRICKY), "token": "right", "headers": {"Content-Type": "text/plain"}},
            req(TRICKY, HISTORY),
        ],
        "agent": [{"lines": [out(reply=R1)]}],
        "forwarded": [4],
        "http": [403, 403, 403, 403, 200],
        "rows": [EXCHANGE_OK],
    },
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
    # A line with no id or with a different id is a stray line, not the reply. The tap waits for
    # the reply until the timeout.
    "reply_not_json": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": ["Loading the toy shop catalog..."]}],
        "forwarded": [0],
        "http": [504],
        "rows": [STRAY, TIMED_OUT],
    },
    "reply_wrong_id": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out("m-0", reply=R1)]}],
        "forwarded": [0],
        "http": [504],
        "rows": [STRAY, TIMED_OUT],
    },
    "stray_lines_before_the_reply": {
        "requests": [req(TRICKY)],
        "agent": [
            {"lines": ["Loading the toy shop catalog...", out("m-0", reply=R2), out(reply=R1)]}
        ],
        "forwarded": [0],
        "http": [200],
        "rows": [STRAY, STRAY, EXCHANGE_OK],
    },
    "reply_and_error": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(reply=R1, error="also an error")]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    # A null field still counts. The line has both fields, so it is not valid.
    "reply_and_null_error": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(reply=R1, error=None)]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    "null_reply_and_error": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(reply=None, error="The order service is down.")]}],
        "forwarded": [0],
        "http": [502],
        "rows": [UNPARSED_POST],
    },
    # NaN is not JSON. Python json.loads accepts it by default, JSON.parse does not.
    "reply_with_nan": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [out(reply=R1, score=float("nan"))]}],
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
    # The record cannot hold a lone surrogate (SPEC.md section 2). The tap records an error.
    "reply_with_a_lone_surrogate": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [json.dumps({"v": 1, "id": "m-1", "reply": R1 + LONE})]}],
        "forwarded": [0],
        "http": [502],
        "rows": [{"type": "exchange", "input": TRICKY, "status": None, "reply": None}],
    },
    "error_with_a_lone_surrogate": {
        "requests": [req(TRICKY)],
        "agent": [{"lines": [json.dumps({"v": 1, "id": "m-1", "error": "Mug sold out " + LONE})]}],
        "forwarded": [0],
        "http": [502],
        "rows": [{"type": "exchange", "input": TRICKY, "status": None, "reply": None}],
    },
    "request_with_a_lone_surrogate": {
        "requests": [
            json.dumps({"v": 1, "id": "m-1", "session": "t-1", "message": M1 + LONE, "history": []})
        ],
        "agent": [],
        "forwarded": [],
        "http": [400],
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
            STRAY,
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


def window(
    started: float | None,
    ts: float,
    status: int | None = 200,
    v: str = "0.2",
    reply: str | None = None,
) -> dict:
    """An exchange of a trace case: its times, its status and its reply. The default reply names
    its time, so that 2 turns never give a repeated_reply finding. A turn with a model text
    gives a reply with that text, so that it gives no reply_not_from_model finding."""
    if status != 200:
        reply = None
    elif reply is None:
        reply = f"toy shop reply at {ts:g}"
    row = ex("toy shop message", reply, status, v=v)
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


# The model API cases below define another result(). Later session lines use this name.
cc_result = result


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
        "repeated_reply",
        "reply_not_from_model",
        "tool_error",
        "command_failed",
        "span_error",
        "backend_error",
        "model_api_error",
        "questions_lost",
        "database_error",
        "unseen_call",
        "driver_without_span",
        "egress_not_in_discovery",
        "egress_denied",
        "model_error",
        "turn_without_model",
        "item_between_turns",
        "otel_tool_not_in_session",
        "server_not_from_app",
        "session_inferred",
        "version_untested",
        "missing_trace_point",
        "trace_points_unread",
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
# result, a line that is not JSON, a blank last line and a turn with no model item.
CLAUDE_CASE = {
    "tap": [
        window(10, 20, reply="Order 4471 was delivered."),
        window(30, 40, status=500),
        window(50, 60),
    ],
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
            "",
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
                    "blank": 1,
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
        "mcp": None,
        "database": None,
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
    "tap": [
        window(None, 20, v="0.1", reply="Delivered, and 12 mugs are in stock."),
        window(None, 40, v="0.1", reply="I cannot check that."),
        window(50, 60),
    ],
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
        "mcp": None,
        "database": None,
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
# The Claude Code versions of TESTED in src/nookku/trace.py, as the detail of a finding shows them.
CC_TESTED = "2.1.286, 2.1.292, 2.1.293, 2.1.294, 2.1.295, 2.1.296, 2.1.299, 2.1.300, 2.1.301"
VERSION_CASE = {
    "tap": [window(10, 20, reply="Hello.")],
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
        "mcp": None,
        "database": None,
        "counts": counts(version_untested=2),
        "findings": [
            {
                "check": "version_untested",
                "turn": None,
                "detail": "version 2.1.999, tested: " + CC_TESTED,
                "harness": "claude-code",
                "session": CC,
            },
            {
                "check": "version_untested",
                "turn": None,
                "detail": "version 0.161.0, tested: 0.160.0, 0.162.1",
                "harness": "codex",
                "session": CX,
            },
        ],
    },
}

# A Codex turn that ends with a model error (SPEC.md section 8.6). The lines copy the shapes of
# a session file of codex-cli 0.162.1. In turn 1, the model is at capacity: the task_complete
# event has an error object and the turn has no model answer. Turn 2 ends with no error. After the
# last turn, a task_complete has a string error, one has an error object with no message, and
# one has a codex_error_info object with 1 key and a status, as codex-cli 0.162.1 writes it.
OVERLOADED = "Selected model is at capacity. Please try a different model."


def task_complete(t: float, answer: str | None, **more: Any) -> dict:
    """One task_complete line of a Codex rollout file. `more` can add an error."""
    payload = {"type": "task_complete", "turn_id": f"t{t:g}", "last_agent_message": answer}
    payload |= {**more, "started_at": int(T0 + t) - 1, "completed_at": int(T0 + t)}
    return {"timestamp": iso(T0 + t), "type": "event_msg", "payload": payload}


def cx_text(t: float, kind: str, text: str) -> dict:
    content = [{"type": "text", "text": text, "text_elements": []}]
    return cx_line(t, {"type": kind, "id": f"m{t:g}", "content": content})


CODEX_ERROR_CASE = {
    "tap": [
        window(10, 20, reply="Sorry, I cannot answer now."),
        window(30, 40, reply="Your order 4471 is delivered."),
    ],
    "manifest": {
        "test": "20261006-080000-me01",
        "model_sessions": [{**CX_SESSION, "inferred": False, "pid": 4474}],
    },
    "sessions": {
        CX_FILE: [
            {
                "timestamp": iso(T0 + 1),
                "type": "session_meta",
                "payload": {"id": CX, "cwd": "/toy-shop", "cli_version": "0.162.1"},
            },
            {"timestamp": iso(T0 + 10), "type": "event_msg", "payload": {"type": "task_started"}},
            cx_text(11, "UserMessage", "Where is my order 4471?"),
            task_complete(
                12, None, error={"message": OVERLOADED, "codex_error_info": "server_overloaded"}
            ),
            cx_text(31, "UserMessage", "Where is my order 4471?"),
            cx_text(32, "AgentMessage", "Your order 4471 is delivered."),
            task_complete(33, "Your order 4471 is delivered."),
            task_complete(50, None, error="stream disconnected"),
            task_complete(51, None, error={"codex_error_info": "other"}),
            task_complete(
                52,
                None,
                error={
                    "message": "stream disconnected before completion",
                    "codex_error_info": {"http_connection_failed": {"http_status_code": 503}},
                },
            ),
        ],
    },
    "trace": [
        item(1, "codex", 11, "message", 3, role="user", output="Where is my order 4471?"),
        item(2, "codex", 31, "message", 5, role="user", output="Where is my order 4471?"),
        item(
            2, "codex", 32, "message", 6, role="assistant", output="Your order 4471 is delivered."
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-me01",
        "turns": 2,
        "items": 3,
        "sessions": [
            {
                "harness": "codex",
                "session": CX,
                "file": CX_FILE,
                "inferred": False,
                "version": "0.162.1",
                "items": 3,
                "ignored": {
                    "event_msg.task_complete": 5,
                    "event_msg.task_started": 1,
                    "session_meta": 1,
                },
            }
        ],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(model_error=4),
        "findings": [
            {
                "check": "model_error",
                "turn": 1,
                "detail": f"server_overloaded: {OVERLOADED}",
                **where("codex", 4),
            },
            {
                "check": "model_error",
                "turn": None,
                "detail": "stream disconnected",
                **where("codex", 8),
            },
            {
                "check": "model_error",
                "turn": None,
                "detail": '{"codex_error_info": "other"}',
                **where("codex", 9),
            },
            {
                "check": "model_error",
                "turn": None,
                "detail": "http_connection_failed (status 503): stream disconnected before completion",
                **where("codex", 10),
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
        "mcp": None,
        "database": None,
        "counts": counts(),
        "findings": [],
    },
}

# Repeated replies (SPEC.md section 8.6): turns 2 and 3 give the same long fallback text, turn 4
# fails, turns 5 to 7 give the same short text, and turn 8 gives the reply of turn 1 again. The 3
# cases differ only in the value of repeated_reply in the manifest: none (the default 2), 3 and 0.
FALLBACK = "Sorry, I can help only with the orders of the toy shop. Please ask about an order."
DONT_KNOW = "Sorry, I do not know."
REPLIES = [
    "We sell teapots and mugs.",
    FALLBACK,
    FALLBACK,
    None,
    DONT_KNOW,
    DONT_KNOW,
    DONT_KNOW,
    "We sell teapots and mugs.",
]


def replied(n: int, reply: str | None) -> dict:
    """Exchange n of the repeated reply cases, with its reply, or with status 500 if it is None."""
    row = window(20 * n - 10, 20 * n, 200 if reply is not None else 500)
    if reply is not None:
        row |= {"reply": reply, "reply_sha256": sha(reply)}
    return row


REPEATED_TAP = [replied(n, reply) for n, reply in enumerate(REPLIES, 1)]
REPEATED_AGENT_ERROR = {"check": "agent_error", "turn": 4, "detail": "the agent gave status 500"}
REPEATED_FALLBACK = {
    "check": "repeated_reply",
    "turn": 2,
    "detail": 'the same reply in turns 2 and 3: "Sorry, I can help only with the orders of the '
    'toy shop. Plea" (cut)',
    "turns": [2, 3],
}
REPEATED_DONT_KNOW = {
    "check": "repeated_reply",
    "turn": 5,
    "detail": 'the same reply in turns 5, 6 and 7: "Sorry, I do not know."',
    "turns": [5, 6, 7],
}


def repeated_case(test: str, keys: dict | None, found: list[dict]) -> dict:
    manifest: dict[str, Any] = {"test": test, "model_sessions": []}
    if keys is not None:
        manifest["trace"] = keys
    return {
        "tap": REPEATED_TAP,
        "manifest": manifest,
        "sessions": {},
        "trace": [],
        "findings": {
            "v": "0.2",
            "test": test,
            "turns": len(REPLIES),
            "items": 0,
            "sessions": [],
            "otel": None,
            "backend": None,
            "model_api": None,
            "mcp": None,
            "database": None,
            "counts": counts(
                agent_error=1, repeated_reply=sum(f["check"] == "repeated_reply" for f in found)
            ),
            "findings": [REPEATED_AGENT_ERROR, *found],
        },
    }


REPEATED_CASE = repeated_case("20261006-080000-rr01", None, [REPEATED_FALLBACK, REPEATED_DONT_KNOW])
REPEATED_THREE_CASE = repeated_case(
    "20261006-080000-rr03", {"repeated_reply": 3}, [REPEATED_DONT_KNOW]
)
REPEATED_OFF_CASE = repeated_case("20261006-080000-rr00", {"repeated_reply": 0}, [])

# Replies that are not from the model (SPEC.md section 8.6). Turn 1: the reply is the model text.
# Turn 2: the reply holds the model text with other white space and case, so only the match
# `normalized` finds it. Turn 3: the app replaced the model text with a fixed decline text. Turn 4
# has no model item, so it gives turn_without_model and no reply_not_from_model.
DECLINE = "Sorry, I cannot help with that."
PLAIN_TEXTS = ["We sell teapots and mugs.", "Your order  ships\ntoday.", "The mug costs 12 euros."]
PLAIN_REPLIES = ["We sell teapots and mugs.", "Order 7: your order ships today.", DECLINE]
# The same turns with a structured model output and model_reply_field `reply`. Turn 2 has its JSON
# in a code fence. Turn 4 gives its client text in the input of a tool call of the app.
FIELD_TEXTS = [
    '{"reply": "We sell teapots and mugs.", "intent": "catalog"}',
    '```json\n{"reply": "Your order ships today."}\n```',
    '{"reply": "The mug costs 12 euros."}',
]
FIELD_REPLIES = ["We sell teapots and mugs.", "Your order ships today.", DECLINE]
ANSWER = {"reply": "Thank you for your order."}
QUESTIONS = ["What do you sell?", "Where is order 7?", "How much is the mug?", "Thanks!"]


def reply_case(test: str, keys: dict | None, structured: bool, found: list[dict]) -> dict:
    texts, replies = (FIELD_TEXTS, FIELD_REPLIES) if structured else (PLAIN_TEXTS, PLAIN_REPLIES)
    tap = [window(20 * n - 10, 20 * n, reply=r) for n, r in enumerate(replies, 1)]
    lines, rows = [], []
    for n, (question, text) in enumerate(zip(QUESTIONS[:3], texts, strict=True), 1):
        t = 20.0 * n - 9
        lines += [cc_line("user", t, question), cc_line("assistant", t + 1, [cc_text(text)])]
        rows += [
            item(n, "claude-code", t, "message", 2 * n - 1, role="user", output=question),
            item(n, "claude-code", t + 1, "message", 2 * n, role="assistant", output=text),
        ]
    if structured:
        tap.append(window(70, 80, reply=ANSWER["reply"]))
        lines += [
            cc_line("user", 71, QUESTIONS[3]),
            cc_line("assistant", 72, [use("t1", "mcp__shop__answer", ANSWER)]),
            cc_line("user", 72.5, [cc_result("t1", "sent")]),
        ]
        rows += [
            item(4, "claude-code", 71, "message", 7, role="user", output=QUESTIONS[3]),
            item(
                4,
                "claude-code",
                72,
                "tool_call",
                8,
                server="shop",
                name="answer",
                input=ANSWER,
                output="sent",
                result_line=9,
            ),
        ]
    else:
        tap.append(window(70, 80, reply="Bye."))
    manifest: dict[str, Any] = {"test": test, "model_sessions": [CC_SESSION]}
    if keys is not None:
        manifest["trace"] = keys
    without_model = [] if structured else [TURN_4_WITHOUT_MODEL]
    return {
        "tap": tap,
        "manifest": manifest,
        "sessions": {CC_FILE: lines},
        "trace": rows,
        "findings": {
            "v": "0.2",
            "test": test,
            "turns": 4,
            "items": len(rows),
            "sessions": [
                {
                    "harness": "claude-code",
                    "session": CC,
                    "file": CC_FILE,
                    "inferred": False,
                    "version": "2.1.286",
                    "items": len(rows),
                    "ignored": {},
                }
            ],
            "otel": None,
            "backend": None,
            "model_api": None,
            "mcp": None,
            "database": None,
            "counts": counts(
                reply_not_from_model=len(found), turn_without_model=len(without_model)
            ),
            "findings": [*found, *without_model],
        },
    }


def cc_text(text: str) -> dict:
    return {"type": "text", "text": text}


TURN_4_WITHOUT_MODEL = {
    "check": "turn_without_model",
    "turn": 4,
    "detail": "no model item in this turn",
}
DECLINED = {
    "check": "reply_not_from_model",
    "turn": 3,
    "detail": "the reply does not contain the text of a model output of this turn (1 checked): "
    '"Sorry, I cannot help with that."',
}
WHITE_SPACE = {
    "check": "reply_not_from_model",
    "turn": 2,
    "detail": "the reply does not contain the text of a model output of this turn (1 checked): "
    '"Order 7: your order ships today."',
}
DECLINED_FIELD = {
    "check": "reply_not_from_model",
    "turn": 3,
    "detail": "the reply does not contain the value of reply of a model output of this turn "
    '(1 checked): "Sorry, I cannot help with that."',
}
REPLY_CASE = reply_case("20261006-080000-rm01", None, False, [DECLINED])
REPLY_EXACT_CASE = reply_case(
    "20261006-080000-rm02", {"model_reply_match": "exact"}, False, [WHITE_SPACE, DECLINED]
)
REPLY_OFF_CASE = reply_case("20261006-080000-rm03", {"model_reply_match": "off"}, False, [])
REPLY_FIELD_CASE = reply_case(
    "20261006-080000-rm04", {"model_reply_field": "reply"}, True, [DECLINED_FIELD]
)

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
    "tap": [
        window(10, 20, reply="Order 4471 was delivered."),
        window(30, 40, reply="Your refund is done."),
    ],
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
        "mcp": None,
        "database": None,
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


# A structured output that the model sends 2 times in one turn (SPEC.md section 8.6). The first
# output does not agree with the schema. Each tool_result event has the tool use id of its call.
# The event of the second call has a cut `note`, so its input is not equal to the session input.
# A third event has an id with no tool call in its session: the id rule gives a finding, though
# its name and input agree with the first call. A second session has a call with that id, but
# the id rule looks only in the session of the event. A fifth event of the second session has
# no id and the input of the second call of the first session: it gives a finding, because the
# check looks only in the session of the event. A fourth event has no id and a cut `note`: the
# shared prefix agrees with the second call.
GIFT_BAD = {"items": [{"sku": "teapot-set", "price_eur": "twenty-eight"}]}
GIFT_NOTE = "A blue teapot set with 2 cups. It fits a gift box of size M."
GIFT_GOOD = {"items": [{"sku": "teapot-set", "price_eur": 28, "note": GIFT_NOTE}]}
GIFT_CUT = {"items": [{"sku": "teapot-set", "price_eur": 28, "note": GIFT_NOTE[:24] + "…"}]}
SCHEMA_ERROR = "Output does not match the schema: price_eur must be a number"


def output_event(t: float, tid: str | None, args: dict, error: str | None = None) -> dict:
    """A tool_result event of Claude Code for its StructuredOutput tool."""
    row = tool_event(t, "StructuredOutput", args)
    attrs = {k: v for k, v in row["attributes"].items() if k != "tool_parameters"}
    attrs["tool_name"] = "StructuredOutput"
    if tid is not None:
        attrs["tool_use_id"] = tid
    if error is not None:
        attrs |= {"success": "false", "error": error}
    return {**row, "attributes": attrs}


CC2 = "8a2d4f6b-1c3e-4a57-9b8d-0e2f4a6c8e01"
CC2_FILE = f"sessions/claude-code/{CC2}.jsonl"
CC2_SESSION = {**CC_SESSION, "session": CC2, "pid": 4472, "file": CC2_FILE}
OUTPUT_EVENTS = [
    output_event(12.6, "toolu_s1", GIFT_BAD, SCHEMA_ERROR),
    output_event(13.6, "toolu_s2", GIFT_CUT),
    output_event(13.7, "toolu_s9", GIFT_BAD),
    output_event(13.8, None, GIFT_CUT),
    output_event(13.9, None, GIFT_GOOD),
]
OUTPUT_EVENTS[-1]["attributes"]["session.id"] = CC2
STRUCTURED_CASE = {
    "tap": [window(10, 20)],
    "manifest": {"test": "20261011-090000-so01", "model_sessions": [CC_SESSION, CC2_SESSION]},
    "sessions": {
        CC_FILE: [
            cc_line("user", 11, "Find a gift under 30 EUR in the toy shop."),
            cc_line("assistant", 12, [use("toolu_s1", "StructuredOutput", GIFT_BAD)]),
            cc_line("user", 12.5, [cc_result("toolu_s1", SCHEMA_ERROR, error=True)]),
            cc_line("assistant", 13, [use("toolu_s2", "StructuredOutput", GIFT_GOOD)]),
            cc_line("user", 13.5, [cc_result("toolu_s2", "Structured output provided.")]),
        ],
        CC2_FILE: [
            cc_line(
                "assistant", 12.2, [use("toolu_s9", "StructuredOutput", GIFT_BAD)], sessionId=CC2
            ),
            cc_line("user", 12.3, [cc_result("toolu_s9", SCHEMA_ERROR, error=True)], sessionId=CC2),
        ],
    },
    "otel": OUTPUT_EVENTS,
    "trace": [
        item(
            1,
            "claude-code",
            11,
            "message",
            1,
            role="user",
            output="Find a gift under 30 EUR in the toy shop.",
        ),
        item(
            1,
            "claude-code",
            12,
            "tool_call",
            2,
            name="StructuredOutput",
            input=GIFT_BAD,
            error=SCHEMA_ERROR,
            result_line=3,
        ),
        {
            **item(
                1,
                "claude-code",
                12.2,
                "tool_call",
                1,
                name="StructuredOutput",
                input=GIFT_BAD,
                error=SCHEMA_ERROR,
            ),
            "session": CC2,
            "source": {"file": CC2_FILE, "line": 1, "result_line": 2},
        },
        *[
            oitem(
                1,
                "claude-code",
                CC,
                e["time"] - T0,
                "log",
                n,
                name="tool_result",
                input=e["attributes"],
                error=e["attributes"].get("error"),
                service="claude-code",
            )
            for n, e in enumerate(OUTPUT_EVENTS[:1], 1)
        ],
        item(
            1,
            "claude-code",
            13,
            "tool_call",
            4,
            name="StructuredOutput",
            input=GIFT_GOOD,
            output="Structured output provided.",
            result_line=5,
        ),
        *[
            oitem(
                1,
                "claude-code",
                CC,
                e["time"] - T0,
                "log",
                n,
                name="tool_result",
                input=e["attributes"],
                service="claude-code",
            )
            for n, e in enumerate(OUTPUT_EVENTS[1:4], 2)
        ],
        oitem(
            1,
            "claude-code",
            CC2,
            13.9,
            "log",
            5,
            name="tool_result",
            input=OUTPUT_EVENTS[4]["attributes"],
            service="claude-code",
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261011-090000-so01",
        "turns": 1,
        "items": 9,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.286",
                "items": 3,
                "ignored": {},
            },
            {
                "harness": "claude-code",
                "session": CC2,
                "file": CC2_FILE,
                "inferred": False,
                "version": "2.1.286",
                "items": 1,
                "ignored": {},
            },
        ],
        "otel": {"file": "otel.jsonl", "rows": 5, "items": 5, "ignored": {}},
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(tool_error=2, otel_tool_not_in_session=2),
        "findings": [
            {
                "check": "tool_error",
                "turn": 1,
                "detail": f"StructuredOutput: {SCHEMA_ERROR}",
                **where("claude-code", 2, 3),
            },
            {
                "check": "tool_error",
                "turn": 1,
                "detail": f"StructuredOutput: {SCHEMA_ERROR}",
                "harness": "claude-code",
                "session": CC2,
                "source": {"file": CC2_FILE, "line": 1, "result_line": 2},
            },
            {
                "check": "otel_tool_not_in_session",
                "turn": 1,
                "detail": "StructuredOutput: a tool_result event with no tool call in the session file",
                "harness": "claude-code",
                "session": CC,
                "source": {"file": "otel.jsonl", "line": 3},
            },
            {
                "check": "otel_tool_not_in_session",
                "turn": 1,
                "detail": "StructuredOutput: a tool_result event with no tool call in the session file",
                "harness": "claude-code",
                "session": CC2,
                "source": {"file": "otel.jsonl", "line": 5},
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
# A request body over the limit of the proxy (SPEC.md section 7.6): the row has no request body.
TOO_LONG = "the proxy refused the request: the body is longer than 67108864 bytes"
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
            query="sku=teapot-set&api_key=",
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
        call(34, "stock", "POST", "/stock/photos", None, request=None, error=TOO_LONG),
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
            input={"query": "sku=teapot-set&api_key=", "headers": SENT, "body": None},
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
            2,
            "stock",
            34,
            4,
            "POST /stock/photos",
            input={"query": None, "headers": SENT, "body": None},
            error=TOO_LONG,
        ),
        bitem(
            None,
            "stock",
            45,
            5,
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
        "items": 5,
        "sessions": [],
        "otel": None,
        "backend": {"file": "backend.jsonl", "rows": 6, "items": 5, "ignored": {"note": 1}},
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(backend_error=3, item_between_turns=1),
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
                "check": "backend_error",
                "turn": 2,
                "detail": f"stock: POST /stock/photos: {TOO_LONG}",
                "harness": "backend",
                "session": "stock",
                "source": {"file": "backend.jsonl", "line": 4},
            },
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a http item",
                "harness": "backend",
                "session": "stock",
                "source": {"file": "backend.jsonl", "line": 5},
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
    "tap": [window(10, 20, reply="Yes, 3 teapot sets are in stock."), window(30, 40)],
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
        "mcp": None,
        "database": None,
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


# A trace case of the OpenAI Responses API (SPEC.md sections 7.7 and 8.4). In turn 1, a streamed
# call to /responses with a text and a function call, and a JSON call to /v1/responses with the
# function call output. In turn 2, a streamed call that ends with response.failed, and a GET of a
# stored response, which is not a model call.
def revent(kind: str, **fields: Any) -> dict:
    return {"type": kind, **fields}


def response(status: str, output: list, usage: Any = None, **more: Any) -> dict:
    return {
        "id": "resp_1",
        "object": "response",
        "status": status,
        "model": "gpt-toy",
        "output": output,
        "usage": usage,
        "error": None,
        **more,
    }


def said(text: str, mid: str = "msg_1") -> dict:
    part = {"type": "output_text", "text": text, "annotations": []}
    return {
        "id": mid,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [part],
    }


def text_event(kind: str, seq: int, **fields: Any) -> dict:
    return revent(
        kind, item_id="msg_1", output_index=0, content_index=0, sequence_number=seq, **fields
    )


def args_event(kind: str, seq: int, **fields: Any) -> dict:
    return revent(kind, item_id="fc_1", output_index=1, sequence_number=seq, **fields)


RTOOLS = [{"type": "function", "name": "check_stock", "parameters": {"type": "object"}}]
STOCK_ARGS = '{"sku": "teapot-set"}'
RCALL = {
    "id": "fc_1",
    "type": "function_call",
    "call_id": "call_7",
    "name": "check_stock",
    "arguments": STOCK_ARGS,
    "status": "completed",
}
RUSAGE = {"input_tokens": 45, "output_tokens": 18, "total_tokens": 63}
RUSAGE_JSON = {"input_tokens": 80, "output_tokens": 11, "total_tokens": 91}
FAILED = "The model failed to generate a response."
OPEN_MESSAGE = {"id": "msg_1", "type": "message", "role": "assistant", "content": []}
RESPONSES_STREAM = sse(
    [
        revent("response.created", response=response("in_progress", []), sequence_number=0),
        revent("response.output_item.added", output_index=0, item=OPEN_MESSAGE, sequence_number=1),
        text_event("response.content_part.added", 2, part={"type": "output_text", "text": ""}),
        text_event("response.output_text.delta", 3, delta="Let me "),
        text_event("response.output_text.delta", 4, delta="check."),
        text_event("response.output_text.done", 5, text="Let me check."),
        revent(
            "response.output_item.done",
            output_index=0,
            item=said("Let me check."),
            sequence_number=6,
        ),
        revent(
            "response.output_item.added",
            output_index=1,
            item={**RCALL, "arguments": "", "status": "in_progress"},
            sequence_number=7,
        ),
        args_event("response.function_call_arguments.delta", 8, delta='{"sku": "tea'),
        args_event("response.function_call_arguments.delta", 9, delta='pot-set"}'),
        args_event("response.function_call_arguments.done", 10, arguments=STOCK_ARGS),
        revent("response.output_item.done", output_index=1, item=RCALL, sequence_number=11),
        revent(
            "response.completed",
            response=response("completed", [said("Let me check."), RCALL], RUSAGE),
            sequence_number=12,
        ),
    ]
)
RESPONSES_JSON = json.dumps(
    response("completed", [said("Yes, 3 teapot sets are in stock.", "msg_2")], RUSAGE_JSON)
)
FAILED_STREAM = sse(
    [
        revent("response.created", response=response("in_progress", []), sequence_number=0),
        revent(
            "response.failed",
            response=response("failed", [], error={"code": "server_error", "message": FAILED}),
            sequence_number=1,
        ),
    ]
)
RESPONSES = "/responses"
V1_RESPONSES = "/v1/responses"
RASKED = [{"role": "user", "content": [{"type": "input_text", "text": ASK}]}]
RANSWERED = [
    {"role": "user", "content": ASK},
    {k: v for k, v in RCALL.items() if k != "status"},
    {
        "type": "function_call_output",
        "call_id": "call_7",
        "output": [{"type": "input_text", "text": "3 left"}],
    },
]
RSTOCK_CALL = {"id": "call_7", "name": "check_stock", "input": {"sku": "teapot-set"}}
RESPONSES_CASE = {
    "tap": [window(10, 20, reply="Yes, 3 teapot sets are in stock."), window(30, 40)],
    "manifest": {"test": "20261007-080000-rs01", "model_sessions": []},
    "sessions": {},
    "model_api": [
        mcall(
            11,
            "openai",
            RESPONSES,
            200,
            {
                "model": "gpt-toy",
                "stream": True,
                "instructions": "You are the toy shop agent.",
                "tools": RTOOLS,
                "input": RASKED,
            },
            stream=True,
            took=2,
            response=RESPONSES_STREAM,
            result=result(
                model="gpt-toy",
                text="Let me check.",
                tool_calls=[RSTOCK_CALL],
                stop_reason="completed",
                usage=RUSAGE,
            ),
        ),
        mcall(
            14,
            "openai",
            V1_RESPONSES,
            200,
            {"model": "gpt-toy", "tools": RTOOLS, "input": RANSWERED},
            took=2,
            response=RESPONSES_JSON,
            result=result(
                model="gpt-toy",
                text="Yes, 3 teapot sets are in stock.",
                stop_reason="completed",
                usage=RUSAGE_JSON,
            ),
        ),
        mcall(
            31,
            "openai",
            RESPONSES,
            200,
            {"model": "gpt-toy", "stream": True, "input": REFUND_ASK},
            stream=True,
            response=FAILED_STREAM,
            result=result(model="gpt-toy", stop_reason="failed", error=FAILED),
        ),
        {
            **mcall(34, "openai", "/responses/resp_1", 200, None, response=RESPONSES_JSON),
            "method": "GET",
            "request_body": body(),
            "result": None,
        },
    ],
    "trace": [
        mitem(1, "openai", 11, 1, "message", role="user", output=ASK),
        mitem(
            1,
            "openai",
            13,
            1,
            "message",
            role="assistant",
            input=info(RESPONSES, "gpt-toy", "completed", RUSAGE),
            output="Let me check.",
            exit_code=200,
        ),
        mitem(
            1,
            "openai",
            13,
            1,
            "tool_call",
            name="check_stock",
            input={"sku": "teapot-set"},
            output="3 left",
        ),
        mitem(
            1,
            "openai",
            16,
            2,
            "message",
            role="assistant",
            input=info(V1_RESPONSES, "gpt-toy", "completed", RUSAGE_JSON),
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
            input=info(RESPONSES, "gpt-toy", "failed", None),
            error=FAILED,
            exit_code=200,
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261007-080000-rs01",
        "turns": 2,
        "items": 6,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": {
            "file": "model_api.jsonl",
            "rows": 4,
            "items": 6,
            "ignored": {},
            "harness_calls": {},
            "other_calls": 1,
        },
        "mcp": None,
        "database": None,
        "counts": counts(model_api_error=1),
        "findings": [
            {
                "check": "model_api_error",
                "turn": 2,
                "detail": f"openai: /responses: {FAILED}",
                "harness": "model_api",
                "session": "openai",
                "source": {"file": "model_api.jsonl", "line": 3},
            },
        ],
    },
}


# MCP servers that are not from the app (SPEC.md section 8.6): the session of the app loaded a
# claude.ai connector and a plugin server of the tester, and called a tool of the connector. The
# attachment lines copy the shapes of a session file of Claude Code 2.1.292.
def cc_attachment(t: float, attachment: dict) -> dict:
    """One attachment line of a Claude Code session file."""
    return {
        "type": "attachment",
        "sessionId": CC,
        "timestamp": iso(T0 + t),
        "version": "2.1.292",
        "isSidechain": False,
        "attachment": attachment,
    }


SERVERS_CASE = {
    "tap": [window(10, 20, reply="Order 4471 was delivered.")],
    "manifest": {"test": "20261006-080000-mc01", "model_sessions": [CC_SESSION]},
    "sessions": {
        CC_FILE: [
            cc_attachment(
                1,
                {
                    "type": "deferred_tools_delta",
                    "addedNames": [
                        "WebFetch",
                        "mcp__shop__lookup_order",
                        "mcp__claude_ai_Toy_Mail__search_threads",
                        "mcp__claude_ai_Toy_Mail__send_message",
                        "mcp__plugin_toybox_stock__check_stock",
                    ],
                    "removedNames": [],
                },
            ),
            cc_attachment(
                1,
                {
                    "type": "mcp_instructions_delta",
                    "addedNames": ["claude.ai Toy Docs"],
                    "addedBlocks": ["## claude.ai Toy Docs\nThe docs of the toy shop."],
                    "removedNames": [],
                },
            ),
            cc_line("user", 11, "Where is my order 4471?", version="2.1.292"),
            cc_line(
                "assistant",
                12,
                [use("t1", "mcp__shop__lookup_order", {"order": "4471"})],
                version="2.1.292",
            ),
            cc_line(
                "user",
                12.5,
                [cc_result("t1", [{"type": "text", "text": '{"status": "delivered"}'}])],
                version="2.1.292",
            ),
            cc_line(
                "assistant",
                13,
                [use("t2", "mcp__claude_ai_Toy_Mail__search_threads", {"query": "4471"})],
                version="2.1.292",
            ),
            cc_line("user", 13.5, [cc_result("t2", "no threads")], version="2.1.292"),
            cc_line(
                "assistant",
                14,
                [{"type": "text", "text": "Order 4471 was delivered."}],
                version="2.1.292",
            ),
        ]
    },
    "trace": [
        item(1, "claude-code", 11, "message", 3, role="user", output="Where is my order 4471?"),
        item(
            1,
            "claude-code",
            12,
            "tool_call",
            4,
            server="shop",
            name="lookup_order",
            input={"order": "4471"},
            output='{"status": "delivered"}',
            result_line=5,
        ),
        item(
            1,
            "claude-code",
            13,
            "tool_call",
            6,
            server="claude_ai_Toy_Mail",
            name="search_threads",
            input={"query": "4471"},
            output="no threads",
            result_line=7,
        ),
        item(
            1,
            "claude-code",
            14,
            "message",
            8,
            role="assistant",
            output="Order 4471 was delivered.",
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-mc01",
        "turns": 1,
        "items": 4,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.292",
                "items": 4,
                "ignored": {"attachment": 2},
            }
        ],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(server_not_from_app=3),
        "findings": [
            {
                "check": "server_not_from_app",
                "turn": None,
                "detail": "claude_ai_Toy_Mail: a claude.ai connector, not a server of the app",
                **where("claude-code", 1),
            },
            {
                "check": "server_not_from_app",
                "turn": None,
                "detail": "plugin_toybox_stock: a plugin server, not a server of the app",
                **where("claude-code", 1),
            },
            {
                "check": "server_not_from_app",
                "turn": None,
                "detail": "claude.ai Toy Docs: a claude.ai connector, not a server of the app",
                **where("claude-code", 2),
            },
        ],
    },
}

# A trace case of the OpenAI Decisions API (SPEC.md sections 7.7 and 8.4). In turn 1, a call to
# /v1/decisions with a text and an image, and 4 questions: a predicate, a choice, a score and a
# choice that the model refuses. In turn 2, a call to /decisions with a string input and a choice
# with boolean values. A refusal is not an error, so the case has no finding.
PHOTO = b"toy photo of a teapot set with a broken lid"
COMPLAINT = "My teapot set arrived with a broken lid."
CHARGED = "I was charged twice for order 5120."
DEPARTMENTS = [
    {"value": "billing", "description": "Payments, invoices and refunds."},
    {"value": "shipping", "description": "Delivery and damage in transit."},
    {"value": "other", "description": "Requests outside these departments."},
]
DQUESTIONS = [
    {
        "type": "predicate",
        "name": "damaged",
        "instructions": "Does the photo show a damaged item?",
    },
    {
        "type": "choice",
        "name": "department",
        "instructions": "Which department should handle this complaint?",
        "choices": DEPARTMENTS,
    },
    {
        "type": "score",
        "name": "severity",
        "instructions": "How severe is the problem?",
        "levels": [
            {"label": "Low", "description": "The customer can use the item."},
            {"label": "Medium", "description": "A part of the item is broken."},
            {"label": "High", "description": "The customer cannot use the item."},
        ],
    },
    {
        "type": "choice",
        "name": "mood",
        "instructions": "Is the customer calm or angry?",
        "choices": [{"value": "calm"}, {"value": "angry"}],
    },
]
DPHOTO_URL = "data:image/png;base64," + base64.b64encode(PHOTO).decode()
DINPUT = [
    {
        "role": "user",
        "content": [
            {"type": "input_text", "text": COMPLAINT},
            {"type": "input_image", "image_url": DPHOTO_URL, "detail": "low"},
        ],
    }
]
DQUESTIONS_2 = [
    {
        "type": "choice",
        "name": "department",
        "instructions": "Which department should handle this complaint?",
        "choices": DEPARTMENTS,
    },
    {
        "type": "choice",
        "name": "refund_due",
        "instructions": "Does the customer have a right to a refund?",
        "choices": [{"value": True}, {"value": False}],
    },
]


def dusage(tokens: int) -> dict:
    return {
        "input_tokens": tokens,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 0,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": tokens,
    }


DANSWERS = [
    {"type": "predicate", "name": "damaged", "probability": 0.97},
    {
        "type": "choice",
        "name": "department",
        "choice": "shipping",
        "probabilities": [
            {"value": "billing", "probability": 0.03},
            {"value": "shipping", "probability": 0.95},
            {"value": "other", "probability": 0.02},
        ],
        "confidence": 0.93,
    },
    {
        "type": "score",
        "name": "severity",
        "score": 1.2,
        "probabilities": [
            {"value": 0, "label": "Low", "probability": 0.1},
            {"value": 1, "label": "Medium", "probability": 0.6},
            {"value": 2, "label": "High", "probability": 0.3},
        ],
        "confidence": 0.5,
    },
    {"type": "refusal", "name": "mood"},
]
DANSWERS_2 = [
    {
        "type": "choice",
        "name": "department",
        "choice": "billing",
        "probabilities": [
            {"value": "billing", "probability": 0.95},
            {"value": "shipping", "probability": 0.03},
            {"value": "other", "probability": 0.02},
        ],
        "confidence": 0.93,
    },
    {
        "type": "choice",
        "name": "refund_due",
        "choice": True,
        "probabilities": [
            {"value": True, "probability": 0.8},
            {"value": False, "probability": 0.2},
        ],
        "confidence": 0.7,
    },
]
# The answers as the result of SPEC.md section 7.7 gives them: type, name, value, probabilities and
# confidence.
DRESULT = [
    {
        "type": "predicate",
        "name": "damaged",
        "value": 0.97,
        "probabilities": None,
        "confidence": None,
    },
    {
        "type": "choice",
        "name": "department",
        "value": "shipping",
        "probabilities": DANSWERS[1]["probabilities"],
        "confidence": 0.93,
    },
    {
        "type": "score",
        "name": "severity",
        "value": 1.2,
        "probabilities": DANSWERS[2]["probabilities"],
        "confidence": 0.5,
    },
    {"type": "refusal", "name": "mood", "value": None, "probabilities": None, "confidence": None},
]
DRESULT_2 = [
    {
        "type": "choice",
        "name": "department",
        "value": "billing",
        "probabilities": DANSWERS_2[0]["probabilities"],
        "confidence": 0.93,
    },
    {
        "type": "choice",
        "name": "refund_due",
        "value": True,
        "probabilities": DANSWERS_2[1]["probabilities"],
        "confidence": 0.7,
    },
]
V1_DECISIONS = "/v1/decisions"


def dq(asked: dict, options: list | None) -> dict:
    """A question of a /decisions call as the trace keeps it (SPEC.md section 8.4)."""
    keep = ("name", "type", "instructions")
    return {**{k: asked[k] for k in keep}, "options": options}


DECISIONS = "/decisions"
DMODEL = "toy-decide"
DECISIONS_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {"test": "20261007-090000-dc01", "model_sessions": []},
    "sessions": {},
    "model_api": [
        mcall(
            11,
            "openai",
            V1_DECISIONS,
            200,
            {"model": DMODEL, "input": DINPUT, "questions": DQUESTIONS},
            response=json.dumps({"model": DMODEL, "answers": DANSWERS, "usage": dusage(120)}),
            result=result(model=DMODEL, usage=dusage(120), answers=DRESULT),
        ),
        mcall(
            31,
            "openai",
            DECISIONS,
            200,
            {"model": DMODEL, "input": CHARGED, "questions": DQUESTIONS_2},
            response=json.dumps({"model": DMODEL, "answers": DANSWERS_2, "usage": dusage(60)}),
            result=result(model=DMODEL, usage=dusage(60), answers=DRESULT_2),
        ),
    ],
    "trace": [
        mitem(
            1,
            "openai",
            11,
            1,
            "message",
            role="user",
            input={
                "questions": [
                    dq(DQUESTIONS[0], None),
                    dq(DQUESTIONS[1], ["billing", "shipping", "other"]),
                    dq(DQUESTIONS[2], ["Low", "Medium", "High"]),
                    dq(DQUESTIONS[3], ["calm", "angry"]),
                ],
                "images": [
                    {
                        "media_type": "image/png",
                        "size": len(PHOTO),
                        "sha256": hashlib.sha256(PHOTO).hexdigest(),
                    }
                ],
            },
            output=COMPLAINT,
        ),
        mitem(
            1,
            "openai",
            12,
            1,
            "message",
            role="assistant",
            input={**info(V1_DECISIONS, DMODEL, None, dusage(120)), "answers": DRESULT},
            exit_code=200,
        ),
        mitem(
            2,
            "openai",
            31,
            2,
            "message",
            role="user",
            input={
                "questions": [
                    dq(DQUESTIONS_2[0], ["billing", "shipping", "other"]),
                    dq(DQUESTIONS_2[1], [True, False]),
                ],
                "images": [],
            },
            output=CHARGED,
        ),
        mitem(
            2,
            "openai",
            32,
            2,
            "message",
            role="assistant",
            input={**info(DECISIONS, DMODEL, None, dusage(60)), "answers": DRESULT_2},
            exit_code=200,
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261007-090000-dc01",
        "turns": 2,
        "items": 4,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": {
            "file": "model_api.jsonl",
            "rows": 2,
            "items": 4,
            "ignored": {},
            "harness_calls": {},
            "other_calls": 0,
        },
        "mcp": None,
        "database": None,
        "counts": counts(),
        "findings": [],
    },
}

# A cut response (SPEC.md sections 7.6, 7.7 and 8.4). The proxy keeps only the first
# `record_limit` bytes of a response. In turn 1, a streamed Anthropic call: the record holds the
# first 4 events and a part of the fifth, so the result has only the text of the first 4 events.
# In turn 2, a JSON call that the cut stops: the result has no JSON error, because the cut is the
# reason. Each assistant message names the cut in its input. In turn 3, the test ends before 2
# streams end: an app call and a harness call. The proxy reads the result of the app call from the
# events that came, with `cut: true`. Its body is not cut, so the trace gives no cut note, and the
# error names the cause and gives a model_api_error finding. The harness row keeps no text.
CUT_EVENTS = [
    {
        "type": "message_start",
        "message": {"id": "msg_9", "model": "claude-toy", "usage": {"input_tokens": 40}},
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Mugs "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "left: "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "12."}},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}},
    {"type": "message_stop"},
]
CUT_STREAM = sse(CUT_EVENTS).encode()
CUT_STREAM_KEPT = sse(CUT_EVENTS[:4]).encode() + sse(CUT_EVENTS[4:5]).encode()[:30]
CUT_JSON = json.dumps(
    {
        "id": "chatcmpl-9",
        "model": "gpt-toy",
        "choices": [{"index": 0, "message": {"content": "Refund sent."}}],
    }
).encode()
CUT_JSON_KEPT = CUT_JSON[:40]
OPEN_STREAM = sse(CUT_EVENTS[:5]).encode()
STREAM_ENDED = "the test ended before the stream ended"
MUGS_ASK = "How many mugs are left?"


def cut_body(data: bytes, kept: bytes) -> dict:
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "cut": True,
        "text": kept.decode(),
    }


def cut_note(data: bytes, kept: bytes) -> str:
    return f"the record holds the first {len(kept)} of {len(data)} bytes"


CUT_CASE = {
    "tap": [
        window(10, 20, reply="Mugs left: "),
        window(30, 40),
        window(50, 60, reply="Mugs left: 12."),
    ],
    "manifest": {"test": "20261018-090000-ct01", "model_sessions": []},
    "sessions": {},
    "model_api": [
        mcall(
            11,
            "anthropic",
            MESSAGES,
            200,
            {
                "model": "claude-toy",
                "stream": True,
                "messages": [{"role": "user", "content": MUGS_ASK}],
            },
            stream=True,
            took=2,
            response_body=cut_body(CUT_STREAM, CUT_STREAM_KEPT),
            result=result(
                model="claude-toy", text="Mugs left: ", usage={"input_tokens": 40}, cut=True
            ),
        ),
        mcall(
            31,
            "openai",
            COMPLETIONS,
            200,
            {"model": "gpt-toy", "messages": REFUND_MESSAGES},
            response_body=cut_body(CUT_JSON, CUT_JSON_KEPT),
            result=result(cut=True),
        ),
        {
            **mcall(
                51,
                "anthropic",
                MESSAGES,
                200,
                {
                    "model": "claude-toy",
                    "stream": True,
                    "messages": [{"role": "user", "content": MUGS_ASK}],
                },
                stream=True,
                took=8,
                response=OPEN_STREAM.decode(),
                result=result(
                    model="claude-toy", text="Mugs left: 12.", usage={"input_tokens": 40}, cut=True
                ),
            ),
            "error": STREAM_ENDED,
        },
        {
            **mcall(
                52,
                "anthropic",
                MESSAGES,
                200,
                None,
                harness="claude-code",
                stream=True,
                took=7,
                request_body=omitted(HARNESS_REQUEST),
                response_body=omitted(OPEN_STREAM.decode()),
            ),
            "error": STREAM_ENDED,
        },
    ],
    "trace": [
        mitem(1, "anthropic", 11, 1, "message", role="user", output=MUGS_ASK),
        mitem(
            1,
            "anthropic",
            13,
            1,
            "message",
            role="assistant",
            input={
                **info(MESSAGES, "claude-toy", None, {"input_tokens": 40}),
                "cut": cut_note(CUT_STREAM, CUT_STREAM_KEPT),
            },
            output="Mugs left: ",
            exit_code=200,
        ),
        mitem(2, "openai", 31, 2, "message", role="user", output=REFUND_ASK),
        mitem(
            2,
            "openai",
            32,
            2,
            "message",
            role="assistant",
            input={**info(COMPLETIONS, None, None, None), "cut": cut_note(CUT_JSON, CUT_JSON_KEPT)},
            exit_code=200,
        ),
        mitem(3, "anthropic", 51, 3, "message", role="user", output=MUGS_ASK),
        mitem(
            3,
            "anthropic",
            59,
            3,
            "message",
            role="assistant",
            input=info(MESSAGES, "claude-toy", None, {"input_tokens": 40}),
            output="Mugs left: 12.",
            error=STREAM_ENDED,
            exit_code=200,
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261018-090000-ct01",
        "turns": 3,
        "items": 6,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": {
            "file": "model_api.jsonl",
            "rows": 4,
            "items": 6,
            "ignored": {},
            "harness_calls": {"claude-code": 1},
            "other_calls": 0,
        },
        "mcp": None,
        "database": None,
        "counts": counts(model_api_error=1),
        "findings": [
            {
                "check": "model_api_error",
                "turn": 3,
                "detail": f"anthropic: /v1/messages: {STREAM_ENDED}",
                "harness": "model_api",
                "session": "anthropic",
                "source": {"file": "model_api.jsonl", "line": 3},
            },
        ],
    },
}

# The questions of a /decisions call when the proxy cuts the request body (SPEC.md sections 7.7,
# 8.4 and 8.6). In turn 1, a photo makes the body longer than `record_limit`. The proxy read the
# questions from the whole body, so the trace keeps each question and its instructions, and gives
# no finding. The cut body has no text and no image for the trace. In turns 2 and 3, a small
# `record_limit` kept only 1 of 2 and 1 of 3 questions: a questions_lost finding gives the count.
# In turn 4, a row of an older proxy has no questions and a cut body. In turn 5, the proxy could not
# read a gzip body with the encoding `GZIP`: the row has questions null and the body is not cut.
# Both findings say that the record does not have the questions. In turn 6, the body is not cut,
# and its questions have instructions with letters that are not ASCII. The trace reads the
# questions from the body, also if the list of the row is shorter, and gives no finding. In turn
# 7, the body is not cut, has no encoding and is not JSON: it has no questions, so no finding.
BIG_PHOTO_URL = "data:image/png;base64," + base64.b64encode(PHOTO * 40).decode()
CUT_DREQUEST = json.dumps(
    {
        "model": DMODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": COMPLAINT},
                    {"type": "input_image", "image_url": BIG_PHOTO_URL},
                ],
            }
        ],
        "questions": DQUESTIONS_2,
    }
).encode()
CUT_DREQUEST_KEPT = CUT_DREQUEST[:200]
DEPARTMENT_OPTIONS = ["billing", "shipping", "other"]
KEPT_DQUESTIONS = [dq(DQUESTIONS_2[0], DEPARTMENT_OPTIONS), dq(DQUESTIONS_2[1], [True, False])]
CAFE_QUESTIONS = [
    {
        "type": "choice",
        "name": "département",
        "instructions": "Quel service traite cette plainte ? Le café est arrivé froid.",
        "choices": DEPARTMENTS,
    },
    {"type": "predicate", "name": "urgent", "instructions": "La plainte est-elle urgente ?"},
]
CAFE_REQUEST = json.dumps({"model": DMODEL, "input": CHARGED, "questions": CAFE_QUESTIONS})
# Fixed bytes, not gzip.compress: its output changes with the zlib version.
GZIP_DREQUEST = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03toy gzip body \xff\xfe"


def dcall(t: float, request_body: dict, **row: Any) -> dict:
    """A row of a /decisions call with the answers of DANSWERS_2, and more fields of the row."""
    out = mcall(
        t,
        "openai",
        V1_DECISIONS,
        200,
        None,
        request_body=request_body,
        response=json.dumps({"model": DMODEL, "answers": DANSWERS_2, "usage": dusage(60)}),
        result=result(model=DMODEL, usage=dusage(60), answers=DRESULT_2),
    )
    return {**out, **row}


def danswer(turn: int, ts: float, line: int, **lost: Any) -> dict:
    """The expected assistant item of a dcall row."""
    found = {**info(V1_DECISIONS, DMODEL, None, dusage(60)), "answers": DRESULT_2, **lost}
    return mitem(turn, "openai", ts, line, "message", role="assistant", input=found, exit_code=200)


def lost_finding(turn: int, line: int, what: str) -> dict:
    return {
        "check": "questions_lost",
        "turn": turn,
        "detail": f"openai: /v1/decisions: {what}",
        "harness": "model_api",
        "session": "openai",
        "source": {"file": "model_api.jsonl", "line": line},
    }


NO_QUESTIONS = "the record does not have the questions of the request"
DECISIONS_CUT_CASE = {
    "tap": [window(10 + 20 * n, 20 + 20 * n) for n in range(7)],
    "manifest": {"test": "20261020-090000-dq01", "model_sessions": []},
    "sessions": {},
    "model_api": [
        dcall(
            11,
            cut_body(CUT_DREQUEST, CUT_DREQUEST_KEPT),
            questions=KEPT_DQUESTIONS,
            questions_count=2,
        ),
        dcall(
            31,
            cut_body(CUT_DREQUEST, CUT_DREQUEST_KEPT),
            questions=KEPT_DQUESTIONS[:1],
            questions_count=2,
        ),
        dcall(
            51,
            cut_body(CUT_DREQUEST, CUT_DREQUEST_KEPT),
            questions=KEPT_DQUESTIONS[:1],
            questions_count=3,
        ),
        dcall(71, cut_body(CUT_DREQUEST, CUT_DREQUEST_KEPT)),
        dcall(
            91,
            body(data=GZIP_DREQUEST),
            request_headers=[*MSENT, ["Content-Encoding", "GZIP"]],
            questions=None,
            questions_count=None,
        ),
        dcall(
            111,
            body(CAFE_REQUEST),
            questions=[dq(CAFE_QUESTIONS[0], DEPARTMENT_OPTIONS)],
            questions_count=2,
        ),
        dcall(131, body("<html>busy</html>"), questions=None, questions_count=None),
    ],
    "trace": [
        mitem(
            1,
            "openai",
            11,
            1,
            "message",
            role="user",
            input={"questions": KEPT_DQUESTIONS, "images": []},
        ),
        danswer(1, 12, 1),
        mitem(
            2,
            "openai",
            31,
            2,
            "message",
            role="user",
            input={"questions": KEPT_DQUESTIONS[:1], "images": []},
        ),
        danswer(2, 32, 2, questions_lost=1),
        mitem(
            3,
            "openai",
            51,
            3,
            "message",
            role="user",
            input={"questions": KEPT_DQUESTIONS[:1], "images": []},
        ),
        danswer(3, 52, 3, questions_lost=2),
        danswer(4, 72, 4, questions_lost=None),
        danswer(5, 92, 5, questions_lost=None),
        mitem(
            6,
            "openai",
            111,
            6,
            "message",
            role="user",
            input={
                "questions": [
                    dq(CAFE_QUESTIONS[0], DEPARTMENT_OPTIONS),
                    dq(CAFE_QUESTIONS[1], None),
                ],
                "images": [],
            },
            output=CHARGED,
        ),
        danswer(6, 112, 6),
        danswer(7, 132, 7),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261020-090000-dq01",
        "turns": 7,
        "items": 11,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": {
            "file": "model_api.jsonl",
            "rows": 7,
            "items": 11,
            "ignored": {},
            "harness_calls": {},
            "other_calls": 0,
        },
        "mcp": None,
        "database": None,
        "counts": counts(questions_lost=4),
        "findings": [
            lost_finding(2, 2, "1 question of the request is not in the record"),
            lost_finding(3, 3, "2 questions of the request are not in the record"),
            lost_finding(4, 4, NO_QUESTIONS),
            lost_finding(5, 5, NO_QUESTIONS),
        ],
    },
}

# The coverage check (SPEC.md section 8.6, `unseen_call`). The manifest has an egress answer with
# one backend proxy and the OTLP receiver. The spans of the app name 7 calls: a call to the proxy
# and a call to the receiver are seen, a span of a server is not a call of the app, and 4 calls go
# to an address that no proxy has. The detail of an HTTP call has no query, so no secret value.
EGRESS_ANSWER = {
    "model_apis": [],
    "backends": [{"name": "stock", "env": "STOCK_URL", "url": "https://stock.toy.test"}],
    "mcp_servers": [],
    "databases": [
        {
            "name": "shop-db",
            "kind": "postgres",
            "env": "DATABASE_URL",
            "address": None,
            "record": "proxy",
        }
    ],
    "other": [],
}
UNSEEN_SPANS = [
    (11, "GET", {"http.request.method": "GET", "url.full": "http://127.0.0.1:41001/stock?sku=mug"}),
    (
        12,
        "GET",
        {
            "http.request.method": "GET",
            "url.full": "https://stock.toy.test/stock?sku=mug&api_key=toy-123",
        },
    ),
    (
        13,
        "POST /chat",
        {
            "http.request.method": "POST",
            "http.route": "/chat",
            "url.full": "http://127.0.0.1:8000/chat",
        },
    ),
    (
        31,
        "SELECT shop",
        {"db.system.name": "postgresql", "server.address": "DB.toy.test", "server.port": 5432},
    ),
    (32, "SELECT cart", {"db.system": "sqlite"}),
    (33, "tools/call", {"mcp.method.name": "tools/call"}),
    (34, "POST", {"http.method": "POST", "http.url": "http://127.0.0.1:41000/v1/traces"}),
]


def qitem(
    turn: int | None,
    session: str,
    ts: float,
    line: int,
    name: str,
    query: str | None,
    parameters: dict | None = None,
    **fields: Any,
) -> dict:
    """An expected driver query from a database span of otel.jsonl (SPEC.md section 8.4)."""
    return oitem(
        turn,
        "driver",
        session,
        ts,
        "query",
        line,
        name=name,
        input={"query": query, "parameters": parameters},
        service="toy-shop",
        **fields,
    )


def unseen(line: int, turn: int, detail: str) -> dict:
    return {
        "check": "unseen_call",
        "turn": turn,
        "detail": f"{detail}: no proxy saw this call",
        "harness": "otel",
        "session": TRACE_ID,
        "source": {"file": "otel.jsonl", "line": line},
    }


UNSEEN_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {
        "test": "20261017-090000-eg01",
        "model_sessions": [],
        "egress": {
            "registered": T0,
            "answer": EGRESS_ANSWER,
            "unseen": ["shop-db"],
            "proxies": {"stock": "http://127.0.0.1:41001"},
            "receiver": "http://127.0.0.1:41000",
        },
    },
    "sessions": {},
    "otel": [app_span(t, name, attrs) for t, name, attrs in UNSEEN_SPANS],
    # The answer has no database with `record: driver`, so the 2 database spans give no driver
    # query (SPEC.md section 8.4).
    "trace": [
        *[
            oitem(
                1 if t < 20 else 2,
                "otel",
                TRACE_ID,
                t,
                "span",
                n,
                name=name,
                input=attrs,
                service="toy-shop",
            )
            for n, (t, name, attrs) in enumerate(UNSEEN_SPANS[:4], 1)
        ],
        *[
            oitem(2, "otel", TRACE_ID, t, "span", n, name=name, input=attrs, service="toy-shop")
            for n, (t, name, attrs) in enumerate(UNSEEN_SPANS[4:], 5)
        ],
    ],
    "findings": {
        "v": "0.2",
        "test": "20261017-090000-eg01",
        "turns": 2,
        "items": 7,
        "sessions": [],
        "otel": {"file": "otel.jsonl", "rows": 7, "items": 7, "ignored": {}},
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(unseen_call=4),
        "findings": [
            unseen(2, 1, "HTTP https://stock.toy.test/stock at stock.toy.test:443"),
            unseen(4, 2, "database postgresql at db.toy.test:5432"),
            unseen(5, 2, "database sqlite at no network address"),
            unseen(6, 2, "MCP tools/call at no network address"),
        ],
    },
}


# The coverage check with stdio MCP servers (SPEC.md section 8.6, `unseen_call`). The server stock
# has a wrapper, and the server files has no variable, so it has no wrapper. A span does not name
# its server, so the MCP call with no network address gives a finding.
STDIO_SERVERS = [
    {
        "name": "stock",
        "transport": "stdio",
        "env": "STOCK_MCP_COMMAND",
        "command": ["toy-stock-mcp"],
        "url": None,
    },
    {
        "name": "files",
        "transport": "stdio",
        "env": None,
        "command": ["toy-files-mcp", "--root", "data"],
        "url": None,
    },
]
UNSEEN_STDIO_SPAN = (11, "tools/call", {"mcp.method.name": "tools/call"})
UNSEEN_STDIO_CASE = {
    "tap": [window(10, 20)],
    "manifest": {
        "test": "20261017-090000-eg02",
        "model_sessions": [],
        "egress": {
            "registered": T0,
            "answer": {
                **EGRESS_ANSWER,
                "backends": [],
                "databases": [],
                "mcp_servers": STDIO_SERVERS,
            },
            "unseen": ["files"],
            "proxies": {"stock": "stdio"},
            "receiver": "http://127.0.0.1:41000",
        },
    },
    "sessions": {},
    "otel": [app_span(*UNSEEN_STDIO_SPAN)],
    "trace": [
        oitem(
            1,
            "otel",
            TRACE_ID,
            UNSEEN_STDIO_SPAN[0],
            "span",
            1,
            name=UNSEEN_STDIO_SPAN[1],
            input=UNSEEN_STDIO_SPAN[2],
            service="toy-shop",
        )
    ],
    "findings": {
        "v": "0.2",
        "test": "20261017-090000-eg02",
        "turns": 1,
        "items": 1,
        "sessions": [],
        "otel": {"file": "otel.jsonl", "rows": 1, "items": 1, "ignored": {}},
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(unseen_call=1),
        "findings": [unseen(1, 1, "MCP tools/call at no network address")],
    },
}


# The coverage check with driver databases (SPEC.md section 8.6, `unseen_call`). shop has a proxy.
# stock is also Postgres on the same server, but its proxy cannot connect, so it has a driver
# trace: only a Postgres call to its host:port and to its database stock is seen. Its span has the
# old attributes net.peer.name, net.peer.port and db.name. cart is SQLite
# with a driver trace and no proxy of its system, so each SQLite call is seen. A Postgres call
# around the proxy to the database shop, an HTTP call to the address of stock and a MySQL call give
# a finding. The 2 spans at 31 have the same time, and each driver query comes right after its span
# (section 8.4). Only the spans of stock and cart give a driver query: no driver database covers
# the other database spans. The cart span has no db.name, so its query has the name cart of the
# answer.
UNSEEN_DRIVER_DATABASES = [
    {
        "name": "shop",
        "kind": "postgres",
        "env": "DATABASE_URL",
        "address": None,
        "record": "proxy",
    },
    {
        "name": "stock",
        "kind": "Postgres",
        "env": None,
        "address": "DB.toy.test:5432/stock",
        "record": "driver",
    },
    {"name": "cart", "kind": "sqlite", "env": None, "address": "data/cart.db", "record": "driver"},
]
PG_AT_DB = {"db.system.name": "postgresql", "server.address": "db.toy.test", "server.port": 5432}
UNSEEN_DRIVER_SPANS = [
    (
        11,
        "SELECT shop",
        {"db.system.name": "postgresql", "server.address": "127.0.0.1", "server.port": 41002},
    ),
    (12, "SELECT shop", {**PG_AT_DB, "db.namespace": "shop"}),
    (13, "GET", {"http.request.method": "GET", "url.full": "http://db.toy.test:5432/health"}),
    (
        31,
        "SELECT stock",
        {
            "db.system": "postgresql",
            "net.peer.name": "db.toy.test",
            "net.peer.port": 5432,
            "db.name": "stock",
        },
    ),
    (31, "SELECT cart", {"db.system": "SQLite"}),
    (
        33,
        "SELECT orders",
        {"db.system.name": "mysql", "server.address": "mysql.toy.test", "server.port": 3306},
    ),
]


def unseen_driver_span(n: int) -> dict:
    t, name, attrs = UNSEEN_DRIVER_SPANS[n - 1]
    turn = 1 if t < 20 else 2
    return oitem(turn, "otel", TRACE_ID, t, "span", n, name=name, input=attrs, service="toy-shop")


UNSEEN_DRIVER_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {
        "test": "20261019-090000-eg03",
        "model_sessions": [],
        "egress": {
            "registered": T0,
            "answer": {**EGRESS_ANSWER, "backends": [], "databases": UNSEEN_DRIVER_DATABASES},
            "unseen": [],
            "driver": ["stock", "cart"],
            "proxies": {"shop": "postgresql://127.0.0.1:41002"},
            "receiver": "http://127.0.0.1:41000",
        },
    },
    "sessions": {},
    "otel": [app_span(*span) for span in UNSEEN_DRIVER_SPANS],
    "trace": [
        unseen_driver_span(1),
        unseen_driver_span(2),
        unseen_driver_span(3),
        unseen_driver_span(4),
        qitem(2, "stock", 31, 4, "query", None),
        unseen_driver_span(5),
        qitem(2, "cart", 31, 5, "query", None),
        unseen_driver_span(6),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261019-090000-eg03",
        "turns": 2,
        "items": 8,
        "sessions": [],
        "otel": {"file": "otel.jsonl", "rows": 6, "items": 6, "ignored": {}},
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(unseen_call=3),
        "findings": [
            unseen(2, 1, "database postgresql at db.toy.test:5432"),
            unseen(3, 1, "HTTP http://db.toy.test:5432/health at db.toy.test:5432"),
            unseen(6, 2, "database mysql at mysql.toy.test:3306"),
        ],
    },
}


# The driver trace (SPEC.md sections 7.11, 8.4 and 8.6). The proxy of shop cannot connect, and
# cart is a SQLite file, so the answer gives each one `record: driver`. Each database span of the
# app gives a driver query: with the new attribute names, with the old names, and with no query
# text. A span has no rows, so a driver query has no output. The span of the error gives a
# database_error and no span_error. The span of the app server is not a database call. One
# database with a driver trace makes each database call seen, so no unseen_call comes. The span of
# the error has no db.namespace, and only shop covers a Postgres span, so its query has the name
# shop of the answer.
DRIVER_DATABASES = [
    {
        "name": "shop",
        "kind": "postgres",
        "env": "DATABASE_URL",
        "address": None,
        "record": "driver",
    },
    {"name": "cart", "kind": "sqlite", "env": None, "address": "data/cart.db", "record": "driver"},
]
STOCK_BY_SKU_TEXT = "SELECT qty FROM stock WHERE sku = $1"
MISSING_TABLE = 'relation "nope" does not exist'
CART_INSERT = "INSERT INTO cart (sku, qty) VALUES (?, ?)"
DRIVER_SPANS = [
    (
        11,
        "SELECT shop",
        {
            "db.system.name": "postgresql",
            "db.namespace": "shop",
            "db.query.text": STOCK_BY_SKU_TEXT,
            "db.query.parameter.0": "mug",
            "server.address": "db.toy.test",
            "server.port": 5432,
        },
    ),
    (
        31,
        "INSERT cart",
        {"db.system": "sqlite", "db.name": "cart", "db.statement": CART_INSERT},
    ),
    (32, "SELECT", {"db.system.name": "postgresql", "db.operation.name": "select"}),
    (33, "POST /chat", {"http.request.method": "POST", "http.route": "/chat"}),
]
DRIVER_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {
        "test": "20261018-090000-dr01",
        "model_sessions": [],
        "egress": {
            "registered": T0,
            "answer": {**EGRESS_ANSWER, "backends": [], "databases": DRIVER_DATABASES},
            "unseen": [],
            "driver": ["shop", "cart"],
            "proxies": {},
            "receiver": "http://127.0.0.1:41000",
        },
    },
    "sessions": {},
    "otel": [
        app_span(*DRIVER_SPANS[0]),
        app_span(*DRIVER_SPANS[1]),
        app_span(*DRIVER_SPANS[2], code=2, message=MISSING_TABLE),
        app_span(*DRIVER_SPANS[3], code=2, message="timeout"),
    ],
    "trace": [
        oitem(
            1,
            "otel",
            TRACE_ID,
            11,
            "span",
            1,
            name="SELECT shop",
            input=DRIVER_SPANS[0][2],
            service="toy-shop",
        ),
        qitem(1, "shop", 11, 1, "SELECT", STOCK_BY_SKU_TEXT, {"0": "mug"}),
        oitem(
            2,
            "otel",
            TRACE_ID,
            31,
            "span",
            2,
            name="INSERT cart",
            input=DRIVER_SPANS[1][2],
            service="toy-shop",
        ),
        qitem(2, "cart", 31, 2, "INSERT", CART_INSERT),
        oitem(
            2,
            "otel",
            TRACE_ID,
            32,
            "span",
            3,
            name="SELECT",
            input=DRIVER_SPANS[2][2],
            error=MISSING_TABLE,
            service="toy-shop",
        ),
        qitem(2, "shop", 32, 3, "SELECT", None, error=MISSING_TABLE),
        oitem(
            2,
            "otel",
            TRACE_ID,
            33,
            "span",
            4,
            name="POST /chat",
            input=DRIVER_SPANS[3][2],
            error="timeout",
            service="toy-shop",
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261018-090000-dr01",
        "turns": 2,
        "items": 7,
        "sessions": [],
        "otel": {"file": "otel.jsonl", "rows": 4, "items": 4, "ignored": {}},
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(span_error=1, database_error=1),
        "findings": [
            {
                "check": "span_error",
                "turn": 2,
                "detail": "toy-shop: POST /chat: timeout",
                "harness": "otel",
                "session": TRACE_ID,
                "source": {"file": "otel.jsonl", "line": 4},
            },
            {
                "check": "database_error",
                "turn": 2,
                "detail": f"shop: SELECT: {MISSING_TABLE}",
                "harness": "driver",
                "session": "shop",
                "source": {"file": "otel.jsonl", "line": 3},
            },
        ],
    },
}


# The driver trace next to a proxy (SPEC.md section 8.4). shop has the Postgres proxy and cart has
# a driver trace. The span of the shop query gives no driver query, because the proxy records
# this query in database.jsonl, and a second item shows it 2 times in the transcript. The span of
# cart gives a driver query. The shop spans go to the proxy, so no unseen_call comes. The second
# shop span has an error and no driver query, so it gives a span_error.
PROXY_DRIVER_SPANS = [
    (
        11,
        "SELECT shop",
        {
            "db.system.name": "postgresql",
            "db.namespace": "shop",
            "db.query.text": STOCK_BY_SKU_TEXT,
            "server.address": "127.0.0.1",
            "server.port": 41002,
        },
    ),
    (12, "INSERT cart", {"db.system": "sqlite", "db.name": "cart", "db.statement": CART_INSERT}),
    (
        13,
        "SELECT",
        {"db.system.name": "postgresql", "server.address": "127.0.0.1", "server.port": 41002},
    ),
]


def proxy_driver_span(n: int, **fields: Any) -> dict:
    t, name, attrs = PROXY_DRIVER_SPANS[n - 1]
    return oitem(
        1, "otel", TRACE_ID, t, "span", n, name=name, input=attrs, service="toy-shop", **fields
    )


PROXY_DRIVER_CASE = {
    "tap": [window(10, 20)],
    "manifest": {
        "test": "20261019-090000-dr02",
        "model_sessions": [],
        "egress": {
            "registered": T0,
            "answer": {
                **EGRESS_ANSWER,
                "backends": [],
                "databases": [UNSEEN_DRIVER_DATABASES[0], UNSEEN_DRIVER_DATABASES[2]],
            },
            "unseen": [],
            "driver": ["cart"],
            "proxies": {"shop": "postgresql://127.0.0.1:41002"},
            "receiver": "http://127.0.0.1:41000",
        },
    },
    "sessions": {},
    "otel": [
        app_span(*PROXY_DRIVER_SPANS[0]),
        app_span(*PROXY_DRIVER_SPANS[1]),
        app_span(*PROXY_DRIVER_SPANS[2], code=2, message=MISSING_TABLE),
    ],
    "trace": [
        proxy_driver_span(1),
        proxy_driver_span(2),
        qitem(1, "cart", 12, 2, "INSERT", CART_INSERT),
        proxy_driver_span(3, error=MISSING_TABLE),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261019-090000-dr02",
        "turns": 1,
        "items": 4,
        "sessions": [],
        "otel": {"file": "otel.jsonl", "rows": 3, "items": 3, "ignored": {}},
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(span_error=1),
        "findings": [
            {
                "check": "span_error",
                "turn": 1,
                "detail": f"toy-shop: SELECT: {MISSING_TABLE}",
                "harness": "otel",
                "session": TRACE_ID,
                "source": {"file": "otel.jsonl", "line": 3},
            }
        ],
    },
}


# The gaps of the driver trace (SPEC.md sections 8.4 and 8.6, #455). stock is a SQLite file and
# returns is a Postgres database whose proxy cannot connect. The SQLite instrumentation sets no
# db.name, so each driver query has the name stock of the answer. The span at 25 comes after the
# reply of turn 1 and before turn 2. It and its driver query are 1 call, so only the span gives
# item_between_turns. No Postgres span comes, so returns gives driver_without_span.
GAPS_DATABASES = [
    {"name": "stock", "kind": "sqlite", "env": None, "address": "stock.db", "record": "driver"},
    {
        "name": "returns",
        "kind": "postgres",
        "env": "RETURNS_URL",
        "address": None,
        "record": "driver",
    },
]
STOCK_SELECT = "SELECT qty FROM stock WHERE sku = ?"
STOCK_UPDATE = "UPDATE stock SET qty = qty - 1 WHERE sku = ?"
GAPS_SPANS = [
    (11, "SELECT", {"db.system": "sqlite", "db.statement": STOCK_SELECT}),
    (25, "UPDATE", {"db.system": "sqlite", "db.statement": STOCK_UPDATE}),
]


def gaps_span(n: int, turn: int | None) -> dict:
    t, name, attrs = GAPS_SPANS[n - 1]
    return oitem(turn, "otel", TRACE_ID, t, "span", n, name=name, input=attrs, service="toy-shop")


DRIVER_GAPS_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {
        "test": "20261022-090000-dg01",
        "model_sessions": [],
        "egress": {
            "registered": T0,
            "answer": {**EGRESS_ANSWER, "backends": [], "databases": GAPS_DATABASES},
            "unseen": [],
            "driver": ["stock", "returns"],
            "proxies": {},
            "receiver": "http://127.0.0.1:41000",
        },
    },
    "sessions": {},
    "otel": [app_span(*span) for span in GAPS_SPANS],
    "trace": [
        gaps_span(1, 1),
        qitem(1, "stock", 11, 1, "SELECT", STOCK_SELECT),
        gaps_span(2, None),
        qitem(None, "stock", 25, 2, "UPDATE", STOCK_UPDATE),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261022-090000-dg01",
        "turns": 2,
        "items": 4,
        "sessions": [],
        "otel": {"file": "otel.jsonl", "rows": 2, "items": 2, "ignored": {}},
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(driver_without_span=1, item_between_turns=1),
        "findings": [
            {
                "check": "driver_without_span",
                "turn": None,
                "detail": "returns: no database span of its driver",
            },
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a span item",
                "harness": "otel",
                "session": TRACE_ID,
                "source": {"file": "otel.jsonl", "line": 2},
            },
        ],
    },
}


# MCP calls (SPEC.md sections 7.12 and 8.4): the rows of mcp.jsonl as the proxies write them. In
# turn 1, an HTTP call with an event stream. In turn 2, a stdio tool call with an error result, a
# notification, a tool call with no response, and a row that is not a call or a message.
def rpc_call(n: int, tool: str, arguments: dict) -> dict:
    params = {"name": tool, "arguments": arguments}
    return {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": params}


def rpc_result(n: int, text: str, error: bool = False) -> dict:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": n, "result": result}


def mcp_message(t: float, direction: str, message: dict) -> dict:
    row = {"v": 1, "type": "message", "server": "stock", "transport": "stdio", "ts": T0 + t}
    return {**row, "direction": direction, "body": body(json.dumps(message) + "\n")}


def mitem(turn: int, server: str, ts: float, line: int, tool: str, **fields: Any) -> dict:
    """An expected trace row from mcp.jsonl."""
    row = item(turn, "claude-code", ts, "tool_call", line, **fields)
    row.update(harness="mcp", session=server, server=server, name=tool)
    row["source"]["file"] = "mcp.jsonl"
    return row


TICKET = rpc_call(1, "open_ticket", {"order": "5120"})
TICKET_CALL = {
    **call(12, "tickets", "POST", "/mcp", 200, request=body(json.dumps(TICKET))),
    "response_body": body(sse([rpc_result(1, "ticket 77 open")], named=False)),
}
TICKET_CALL["server"] = TICKET_CALL.pop("backend")
TICKET_CALL["transport"] = "http"
MCP_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {"test": "20261006-080000-mc01", "model_sessions": []},
    "sessions": {},
    "mcp": [
        TICKET_CALL,
        mcp_message(32, "to_server", rpc_call(7, "check_stock", {"product": "teapot"})),
        mcp_message(32.1, "from_server", {"jsonrpc": "2.0", "method": "notifications/progress"}),
        mcp_message(32.2, "from_server", rpc_result(7, "no such product", error=True)),
        mcp_message(33, "to_server", rpc_call(8, "check_stock", {"product": "mug"})),
        {"v": 1, "type": "note", "detail": "a row that is not a call or a message"},
    ],
    "trace": [
        mitem(
            1,
            "tickets",
            12,
            1,
            "open_ticket",
            input={"order": "5120"},
            output="ticket 77 open",
            result_line=1,
        ),
        mitem(
            2,
            "stock",
            32,
            2,
            "check_stock",
            input={"product": "teapot"},
            error="no such product",
            result_line=4,
        ),
        mitem(
            2,
            "stock",
            33,
            5,
            "check_stock",
            input={"product": "mug"},
            error="no response in mcp.jsonl",
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-mc01",
        "turns": 2,
        "items": 3,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": {"file": "mcp.jsonl", "rows": 6, "items": 3, "ignored": {"note": 1}},
        "database": None,
        "counts": counts(tool_error=2),
        "findings": [
            {
                "check": "tool_error",
                "turn": 2,
                "detail": "check_stock: no such product",
                "harness": "mcp",
                "session": "stock",
                "source": {"file": "mcp.jsonl", "line": 2, "result_line": 4},
            },
            {
                "check": "tool_error",
                "turn": 2,
                "detail": "check_stock: no response in mcp.jsonl",
                "harness": "mcp",
                "session": "stock",
                "source": {"file": "mcp.jsonl", "line": 5},
            },
        ],
    },
}


# Database queries (SPEC.md sections 7.13 and 8.4): the rows of database.jsonl as the Postgres
# proxy writes them. In turn 1, a password message and a simple query. In turn 2, an extended
# query and a query that fails. Between the turns, a query with no result at the end of the file.
def pg(t: float, direction: str, tag: str, fields: dict | None = None) -> dict:
    row = {"v": 1, "type": "message", "database": "shop-db", "connection": 1, "ts": T0 + t}
    return {**row, "direction": direction, "tag": tag, "size": 8, "fields": fields}


STOCK_QUERY = "SELECT left FROM stock WHERE sku = 'teapot-set'"
STOCK_BY_SKU = "SELECT left FROM stock WHERE sku = $1"
PG_ROWS = [
    {
        "v": 1,
        "type": "connect",
        "database": "shop-db",
        "connection": 1,
        "ts": T0 + 10.5,
        "parameters": {"user": "shop", "database": "shop"},
        "declined": ["ssl"],
        "error": None,
    },
    pg(10.6, "to_server", "p"),
    pg(10.7, "from_server", "R", {"auth": 0}),
    pg(11, "to_server", "Q", {"query": STOCK_QUERY}),
    pg(11.1, "from_server", "T", {"columns": ["left"]}),
    pg(11.1, "from_server", "D", {"values": ["3"]}),
    pg(11.1, "from_server", "C", {"command": "SELECT 1"}),
    pg(11.1, "from_server", "Z", {"status": "I"}),
    pg(31, "to_server", "P", {"statement": "", "query": STOCK_BY_SKU}),
    pg(31, "to_server", "B", {"portal": "", "statement": "", "parameters": ["mug"], "results": []}),
    pg(31, "to_server", "E", {"portal": ""}),
    pg(31, "to_server", "S"),
    pg(31.1, "from_server", "1"),
    pg(31.1, "from_server", "2"),
    pg(31.1, "from_server", "D", {"values": ["12"]}),
    pg(31.1, "from_server", "C", {"command": "SELECT 1"}),
    pg(31.1, "from_server", "Z", {"status": "I"}),
    pg(32, "to_server", "Q", {"query": "SELECT * FROM nope"}),
    pg(
        32.1,
        "from_server",
        "E",
        {"severity": "ERROR", "code": "42P01", "message": 'relation "nope" does not exist'},
    ),
    pg(32.1, "from_server", "Z", {"status": "I"}),
    pg(45, "to_server", "Q", {"query": "SELECT 1"}),
]


def ditem(turn: int | None, ts: float, line: int, query: str, **fields: Any) -> dict:
    """An expected trace row from database.jsonl."""
    row = item(turn, "claude-code", ts, "query", line, **fields)
    row.update(harness="database", session="shop-db", name="SELECT")
    row["input"] = {"query": query, "parameters": fields.get("input", {}).get("parameters")}
    row["source"]["file"] = "database.jsonl"
    return row


NOPE = 'relation "nope" does not exist'
DATABASE_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {"test": "20261006-080000-db01", "model_sessions": []},
    "sessions": {},
    "database": PG_ROWS,
    "trace": [
        ditem(1, 11, 4, STOCK_QUERY, output='["3"]\nSELECT 1', result_line=8),
        ditem(
            2,
            31,
            11,
            STOCK_BY_SKU,
            input={"parameters": ["mug"]},
            output='["12"]\nSELECT 1',
            result_line=16,
        ),
        ditem(2, 32, 18, "SELECT * FROM nope", error=NOPE, result_line=20),
        ditem(None, 45, 21, "SELECT 1", error="no result in database.jsonl"),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261006-080000-db01",
        "turns": 2,
        "items": 4,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": {"file": "database.jsonl", "rows": 21, "items": 4, "ignored": {"connect": 1}},
        "counts": counts(database_error=2, item_between_turns=1),
        "findings": [
            {
                "check": "database_error",
                "turn": 2,
                "detail": f"shop-db: SELECT: {NOPE}",
                "harness": "database",
                "session": "shop-db",
                "source": {"file": "database.jsonl", "line": 18, "result_line": 20},
            },
            {
                "check": "database_error",
                "turn": None,
                "detail": "shop-db: SELECT: no result in database.jsonl",
                "harness": "database",
                "session": "shop-db",
                "source": {"file": "database.jsonl", "line": 21},
            },
            {
                "check": "item_between_turns",
                "turn": None,
                "detail": "a query item",
                "harness": "database",
                "session": "shop-db",
                "source": {"file": "database.jsonl", "line": 21},
            },
        ],
    },
}


# Database queries with binary results and other ends (SPEC.md section 8.4). The Bind asks the
# column in binary, so the value of the data row gives its bytes as base64. The first execute
# stops at its row limit (s), and the second one is an empty query (I). Neither is an error.
FORMATS_ROWS = [
    pg(11, "to_server", "P", {"statement": "", "query": STOCK_BY_SKU}),
    pg(
        11, "to_server", "B", {"portal": "", "statement": "", "parameters": ["mug"], "results": [1]}
    ),
    pg(11, "to_server", "E", {"portal": ""}),
    pg(11.1, "to_server", "E", {"portal": ""}),
    pg(11.5, "from_server", "D", {"values": ["\u0000\u0000\u0000\f"]}),
    pg(11.6, "from_server", "s"),
    pg(11.7, "from_server", "I"),
    pg(11.8, "from_server", "Z", {"status": "I"}),
]
DATABASE_FORMATS_CASE = {
    "tap": [window(10, 20)],
    "manifest": {"test": "20261018-080000-db02", "model_sessions": []},
    "sessions": {},
    "database": FORMATS_ROWS,
    "trace": [
        ditem(
            1,
            11,
            3,
            STOCK_BY_SKU,
            input={"parameters": ["mug"]},
            output='[{"base64": "AAAADA=="}]',
            result_line=6,
        ),
        ditem(1, 11.1, 4, STOCK_BY_SKU, input={"parameters": ["mug"]}, result_line=7),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261018-080000-db02",
        "turns": 1,
        "items": 2,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": {"file": "database.jsonl", "rows": 8, "items": 2, "ignored": {}},
        "counts": counts(),
        "findings": [],
    },
}
# Two batches in one pipeline: an error in the first batch does not stop the second batch,
# after its own Sync. Each ReadyForQuery ends the oldest batch (SPEC.md section 8.4).
PIPELINE_BIND = {"portal": "", "statement": "", "parameters": ["mug"], "results": []}
PIPELINE_ROWS = [
    pg(11, "to_server", "P", {"statement": "", "query": STOCK_BY_SKU}),
    pg(11, "to_server", "B", PIPELINE_BIND),
    pg(11, "to_server", "E", {"portal": ""}),
    pg(11, "to_server", "S"),
    pg(11.1, "to_server", "B", PIPELINE_BIND),
    pg(11.1, "to_server", "E", {"portal": ""}),
    pg(11.1, "to_server", "S"),
    pg(11.5, "from_server", "E", {"message": "stock is locked"}),
    pg(11.6, "from_server", "Z", {"status": "I"}),
    pg(11.7, "from_server", "D", {"values": ["12"]}),
    pg(11.8, "from_server", "C", {"command": "SELECT 1"}),
    pg(11.9, "from_server", "Z", {"status": "I"}),
]
DATABASE_PIPELINE_CASE = {
    "tap": [window(10, 20)],
    "manifest": {"test": "20261018-090000-db03", "model_sessions": []},
    "sessions": {},
    "database": PIPELINE_ROWS,
    "trace": [
        ditem(
            1,
            11,
            3,
            STOCK_BY_SKU,
            input={"parameters": ["mug"]},
            error="stock is locked",
            result_line=8,
        ),
        ditem(
            1,
            11.1,
            6,
            STOCK_BY_SKU,
            input={"parameters": ["mug"]},
            output='["12"]\nSELECT 1',
            result_line=11,
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261018-090000-db03",
        "turns": 1,
        "items": 2,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": {"file": "database.jsonl", "rows": 12, "items": 2, "ignored": {}},
        "counts": counts(database_error=1),
        "findings": [
            {
                "check": "database_error",
                "turn": 1,
                "detail": "shop-db: SELECT: stock is locked",
                "harness": "database",
                "session": "shop-db",
                "source": {"file": "database.jsonl", "line": 3, "result_line": 8},
            }
        ],
    },
}
# Claude Code 2.1.300 and 2.1.301: the lines api-request-shape, api-request-blob and api-request
# hold the model requests of the harness. Each message and tool call in them is also in a user or
# an assistant line. The other parts are the harness's own instructions. Thus the reader counts
# these lines and keeps no item from them (SPEC.md section 8.4). The shapes copy a real session
# file of Claude Code 2.1.301, with toy shop content.
API_SHAPE = "5" * 64
API_REQUEST_LOOKUP = use("t1", "mcp__shop__lookup_order", {"order": "4471"})


def api_request(t: float, keep: int, **more: Any) -> dict:
    """One api-request line of a Claude Code 2.1.301 session file."""
    row = {
        "type": "api-request",
        "sessionId": CC,
        "id": f"0b7e4c1a-0000-4000-8000-00000000000{keep}",
        "timestamp": iso(T0 + t),
        "version": "2.1.301",
        "querySource": "sdk",
        "shapeHash": API_SHAPE,
        "params": {"model": "toy-model", "max_tokens": 1000},
        "keep": keep,
        "tail": ["6" * 64],
        "requestDigest": "7" * 64,
    }
    return {**row, **more}


def api_blob(role: str, content: list) -> dict:
    """One api-request-blob line of a Claude Code 2.1.301 session file."""
    return {
        "type": "api-request-blob",
        "sessionId": CC,
        "hash": "8" * 64,
        "message": {"role": role, "content": content},
    }


API_REQUEST_CASE = {
    "tap": [window(10, 20, reply="Order 4471 was delivered.")],
    "manifest": {"test": "20261017-080000-ar01", "model_sessions": [CC_SESSION]},
    "sessions": {
        CC_FILE: [
            {
                "type": "api-request-shape",
                "sessionId": CC,
                "shapeHash": API_SHAPE,
                "timestamp": iso(T0 + 10.5),
                "version": "2.1.301",
                "shape": {
                    "system": [{"type": "text", "text": "You are the toy shop support agent."}],
                    "tools": [
                        {
                            "name": "mcp__shop__lookup_order",
                            "description": "Look up a toy shop order by its number",
                            "input_schema": {"type": "object"},
                        }
                    ],
                },
            },
            api_blob("user", [{"type": "text", "text": "Where is my order 4471?"}]),
            cc_line("user", 11, "Where is my order 4471?", version="2.1.301"),
            api_request(11.5, 0),
            cc_line("assistant", 12, [API_REQUEST_LOOKUP], version="2.1.301"),
            cc_line(
                "user",
                12.5,
                [cc_result("t1", [{"type": "text", "text": '{"status": "delivered"}'}])],
                version="2.1.301",
            ),
            api_blob("assistant", [API_REQUEST_LOOKUP]),
            api_request(12.6, 2, base="0b7e4c1a-0000-4000-8000-000000000000"),
            cc_line(
                "assistant",
                13,
                [{"type": "text", "text": "Order 4471 was delivered."}],
                version="2.1.301",
            ),
        ]
    },
    "trace": [
        item(1, "claude-code", 11, "message", 3, role="user", output="Where is my order 4471?"),
        item(
            1,
            "claude-code",
            12,
            "tool_call",
            5,
            server="shop",
            name="lookup_order",
            input={"order": "4471"},
            output='{"status": "delivered"}',
            result_line=6,
        ),
        item(
            1,
            "claude-code",
            13,
            "message",
            9,
            role="assistant",
            output="Order 4471 was delivered.",
        ),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261017-080000-ar01",
        "turns": 1,
        "items": 3,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.301",
                "items": 3,
                "ignored": {"api-request": 2, "api-request-blob": 2, "api-request-shape": 1},
            }
        ],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "counts": counts(),
        "findings": [],
    },
}

# The trace points of the app spec (SPEC.md section 8.6, missing_trace_point). The app checks the
# stock in each turn. Turn 2 has no call to the stock backend for its check_stock call, turn 3 has
# 1 call for 2 check_stock calls, and turn 3 has no case note.
POINT_REPLIES = ["We have 3 teapot sets.", "We still have 3.", "We have 3 and 5 robot kits."]
POINT_NOTE = {"model": "note-toy", "messages": [{"role": "user", "content": "Case note."}]}
POINTS = [
    {"name": "check_stock", "source": "session", "when": "Each turn that asks about stock."},
    {"name": "check_stock", "source": "session", "when": "Turn 2."},
    {"name": "lookup_order", "source": "session", "when": "Turn 5"},
    {"name": "assistant", "source": "session", "when": "Each turn."},
    {"name": "stock GET /stock", "source": "backend", "when": "Each `check_stock` tool call."},
    {"name": "openai", "source": "model_api", "when": "Each turn."},
    {"name": "shop.reply", "source": "otel", "when": "each turn"},
    {"name": "audit_log", "source": "database", "when": "Each turn."},
]
# The count of items that the 3 turns need for each point. The trace checks a known source with
# the When forms `Each turn`, `Turn N` and `Each <tool> tool call`, else the count is None. A
# `Turn 5` in a test of 3 turns needs 0 items, so the trace does not check it.
POINTS_NEEDED = [None, 1, 0, 3, 4, 3, 3, None]


def point_use(t: float, tid: str, sku: str) -> list[dict]:
    """The tool_use line and the tool_result line of one check_stock call."""
    call_line = cc_line("assistant", t, [use(tid, "mcp__shop__check_stock", {"sku": sku})])
    left = [{"type": "text", "text": f"{sku}: 3 left"}]
    return [call_line, cc_line("user", t + 0.5, [cc_result(tid, left)])]


def point_stock(t: float, sku: str) -> dict:
    return call(t, "stock", "GET", "/stock", 200, query=f"sku={sku}", response=body("3"))


def point_note(t: float) -> dict:
    note = json.dumps({"choices": [{"message": {"role": "assistant", "content": "Noted."}}]})
    return {
        **mcall(t, "openai", COMPLETIONS, 200, POINT_NOTE, response=note),
        "result": result(model="note-toy", text="Noted.", stop_reason="stop"),
    }


def point_row(turn: int, harness: str, ts: float, kind: str, line: int, **fields: Any) -> dict:
    """An expected trace row of a file that is not a session file."""
    files = {"backend": "backend.jsonl", "model_api": "model_api.jsonl", "otel": "otel.jsonl"}
    row = item(turn, "claude-code", ts, kind, line)
    row.update(harness=harness, source={"file": files[harness], "line": line})
    return {**row, **fields}


def point_tool(turn: int, ts: float, line: int, sku: str) -> dict:
    return item(
        turn,
        "claude-code",
        ts,
        "tool_call",
        line,
        server="shop",
        name="check_stock",
        input={"sku": sku},
        output=f"{sku}: 3 left",
        result_line=line + 1,
    )


def point_stock_row(turn: int, ts: float, line: int, sku: str) -> dict:
    stock_input = {"query": f"sku={sku}", "headers": SENT, "body": None}
    return point_row(
        turn,
        "backend",
        ts,
        "http",
        line,
        session="stock",
        name="GET /stock",
        input=stock_input,
        output="3",
        exit_code=200,
    )


def point_note_rows(turn: int, ts: float, line: int) -> list[dict]:
    asked = point_row(turn, "model_api", ts, "message", line, session="openai", role="user")
    answer = info(COMPLETIONS, "note-toy", "stop", None)
    return [
        {**asked, "output": "Case note."},
        point_row(
            turn,
            "model_api",
            ts + 1,
            "message",
            line,
            session="openai",
            role="assistant",
            input=answer,
            output="Noted.",
            exit_code=200,
        ),
    ]


def point_span_row(turn: int, ts: float, line: int) -> dict:
    return point_row(
        turn,
        "otel",
        ts,
        "span",
        line,
        session=TRACE_ID,
        name="shop.reply",
        input={},
        service="toy-shop",
    )


def point_found(turn: int, detail: str) -> dict:
    return {"check": "missing_trace_point", "turn": turn, "detail": detail}


POINT_CASE = {
    "tap": [
        window(10, 20, reply=POINT_REPLIES[0]),
        window(30, 40, reply=POINT_REPLIES[1]),
        window(50, 60, reply=POINT_REPLIES[2]),
    ],
    "manifest": {
        "test": "20261020-080000-tp01",
        "model_sessions": [CC_SESSION],
        "trace_points": POINTS,
    },
    "sessions": {
        CC_FILE: [
            cc_line("user", 11, "Is the teapot set in stock?"),
            *point_use(12, "t1", "teapot-set"),
            cc_line("assistant", 13, [{"type": "text", "text": POINT_REPLIES[0]}]),
            cc_line("user", 31, "Is it still in stock?"),
            *point_use(32, "t2", "teapot-set"),
            cc_line("assistant", 33, [{"type": "text", "text": POINT_REPLIES[1]}]),
            cc_line("user", 51, "And the robot kit?"),
            *point_use(52, "t3", "teapot-set"),
            *point_use(53, "t4", "robot-kit"),
            cc_line("assistant", 54, [{"type": "text", "text": POINT_REPLIES[2]}]),
        ]
    },
    "otel": [app_span(t, "shop.reply", {}) for t in (11.2, 31.2, 51.2)],
    "backend": [point_stock(12.1, "teapot-set"), point_stock(52.1, "teapot-set")],
    "model_api": [point_note(15), point_note(35)],
    "trace": [
        item(1, "claude-code", 11, "message", 1, role="user", output="Is the teapot set in stock?"),
        point_span_row(1, 11.2, 1),
        point_tool(1, 12, 2, "teapot-set"),
        point_stock_row(1, 12.1, 1, "teapot-set"),
        item(1, "claude-code", 13, "message", 4, role="assistant", output=POINT_REPLIES[0]),
        *point_note_rows(1, 15, 1),
        item(2, "claude-code", 31, "message", 5, role="user", output="Is it still in stock?"),
        point_span_row(2, 31.2, 2),
        point_tool(2, 32, 6, "teapot-set"),
        item(2, "claude-code", 33, "message", 8, role="assistant", output=POINT_REPLIES[1]),
        *point_note_rows(2, 35, 2),
        item(3, "claude-code", 51, "message", 9, role="user", output="And the robot kit?"),
        point_span_row(3, 51.2, 3),
        point_tool(3, 52, 10, "teapot-set"),
        point_stock_row(3, 52.1, 2, "teapot-set"),
        point_tool(3, 53, 12, "robot-kit"),
        item(3, "claude-code", 54, "message", 14, role="assistant", output=POINT_REPLIES[2]),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261020-080000-tp01",
        "turns": 3,
        "items": 19,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.286",
                "items": 10,
                "ignored": {},
            }
        ],
        "otel": {"file": "otel.jsonl", "rows": 3, "items": 3, "ignored": {}},
        "backend": {"file": "backend.jsonl", "rows": 2, "items": 2, "ignored": {}},
        "model_api": {
            "file": "model_api.jsonl",
            "rows": 2,
            "items": 4,
            "ignored": {},
            "harness_calls": {},
            "other_calls": 0,
        },
        "mcp": None,
        "database": None,
        "trace_points": [
            {**p, "checked": bool(n), "needed": n}
            for p, n in zip(POINTS, POINTS_NEEDED, strict=True)
        ],
        "counts": counts(missing_trace_point=3),
        "findings": [
            point_found(
                2,
                "stock GET /stock (backend): 0 of 1 items for 1 check_stock tool call in this "
                "turn. When: Each check_stock tool call.",
            ),
            point_found(
                3,
                "stock GET /stock (backend): 1 of 2 items for 2 check_stock tool calls in this "
                "turn. When: Each check_stock tool call.",
            ),
            point_found(3, "openai (model_api): 0 of 1 items in this turn. When: Each turn."),
        ],
    },
}

# The edge cases of the trace points: the full MCP name of a tool, a tool name that no tool call
# has, a turn number with too many digits, and the parts of the spec that the bridge did not read.
EDGE_POINTS = [
    {
        "name": "stock GET /stock",
        "source": "backend",
        "when": "Each `mcp__shop__check_stock` tool call.",
    },
    {"name": "mcp__shop__check_stock", "source": "session", "when": "Turn 1"},
    {"name": "stock GET /stock", "source": "backend", "when": "Each check_stok tool call."},
    {"name": "shop.reply", "source": "otel", "when": "Turn " + "9" * 5000},
]
EDGE_UNREAD = [
    {"file": "APP_SPEC.md", "line": 14, "problem": "The row has 4 cells, and the header has 3."},
    {
        "file": "RULES.md",
        "line": 3,
        "problem": "The section has no table with the columns Name, Source and When.",
    },
]
EDGE_CASE = {
    "tap": [window(10, 20, reply=POINT_REPLIES[0])],
    "manifest": {
        "test": "20261020-090000-tp02",
        "model_sessions": [CC_SESSION],
        "trace_points": EDGE_POINTS,
        "trace_points_unread": EDGE_UNREAD,
    },
    "sessions": {
        CC_FILE: [
            cc_line("user", 11, "Is the teapot set in stock?"),
            *point_use(12, "t1", "teapot-set"),
            cc_line("assistant", 13, [{"type": "text", "text": POINT_REPLIES[0]}]),
        ]
    },
    "trace": [
        item(1, "claude-code", 11, "message", 1, role="user", output="Is the teapot set in stock?"),
        point_tool(1, 12, 2, "teapot-set"),
        item(1, "claude-code", 13, "message", 4, role="assistant", output=POINT_REPLIES[0]),
    ],
    "findings": {
        "v": "0.2",
        "test": "20261020-090000-tp02",
        "turns": 1,
        "items": 3,
        "sessions": [
            {
                "harness": "claude-code",
                "session": CC,
                "file": CC_FILE,
                "inferred": False,
                "version": "2.1.286",
                "items": 3,
                "ignored": {},
            }
        ],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "trace_points": [
            {**p, "checked": bool(n), "needed": n}
            for p, n in zip(EDGE_POINTS, [1, 1, 0, None], strict=True)
        ],
        "counts": counts(missing_trace_point=1, trace_points_unread=2),
        "findings": [
            point_found(
                1,
                "stock GET /stock (backend): 0 of 1 items for 1 mcp__shop__check_stock tool "
                "call in this turn. When: Each mcp__shop__check_stock tool call.",
            ),
            {
                "check": "trace_points_unread",
                "turn": None,
                "detail": "APP_SPEC.md line 14: The row has 4 cells, and the header has 3. "
                "The trace does not check it.",
            },
            {
                "check": "trace_points_unread",
                "turn": None,
                "detail": "RULES.md line 3: The section has no table with the columns Name, "
                "Source and When. The trace does not check it.",
            },
        ],
    },
}


# The Koodam egress spans (SPEC.md section 8.8). The test runs from T0 to T0 + 100. The answer has
# the backend stock, the model API anthropic with no URL (the host of its default URL) and the
# database shop-db at db.toy.test. The spans: 2 hosts of the answer, 1 host that is not in the
# answer with 2 spans (one with no `v`, one of the kind http), 1 ignored host (the config value has
# capitals), 1 llm span, 1 denied call to a host that is not in the answer, 1 denied TLS call with
# no host, 1 failed call, 2 spans outside the window, 1 line that is not JSON, 1 span with no time
# and 1 blank line.
def span(t: float, kind: str, result: str = "ok", **fields: Any) -> dict:
    """One span of the Koodam egress span contract v1, with toy shop pod labels."""
    row: dict[str, Any] = {
        "v": 1,
        "time": iso(T0 + t),
        "durationMs": 120.5,
        "source": "10.244.1.17",
        "kind": kind,
        **fields,
        "bytesIn": 5120,
        "bytesOut": 918,
        "result": result,
        "namespace": "shop",
        "pod": "shop-0",
        "workspace": "shop",
        "user": "tester",
    }
    return row


def tunnel(t: float, host: str, port: str = "443", result: str = "ok", **fields: Any) -> dict:
    """A span of the kind connect: a CONNECT tunnel to host:port."""
    return span(
        t, "connect", result, method="CONNECT", host=f"{host}:{port}", sni=host, port=port, **fields
    )


EGRESS_SPAN_ANSWER = {
    "model_apis": [{"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": None}],
    "backends": [{"name": "stock", "env": "STOCK_URL", "url": "https://stock.toy.test/v2"}],
    "mcp_servers": [],
    "databases": [
        {
            "name": "shop-db",
            "kind": "postgres",
            "env": "DATABASE_URL",
            "address": "db.toy.test:5432/shop",
            "record": "proxy",
        }
    ],
    "other": [],
}
EGRESS_SPAN_LINES = [
    tunnel(11, "stock.toy.test", status=200),
    span(12, "tls", sni="api.anthropic.com", port="443"),
    {k: v for k, v in tunnel(13, "Mail.Toy.Test").items() if k != "v"},
    span(32, "http", method="POST", host="mail.toy.test", port="80", path="/send", status=202),
    tunnel(14, "github.com"),
    span(15, "llm", method="POST", host="gateway.koodam.test", path="/llm/v1/messages", status=200),
    tunnel(33, "pay.toy.test", "8443", "denied", reason="port"),
    span(35, "tls", "denied", port="443", reason="no SNI"),
    tunnel(150, "stock.toy.test"),
    tunnel(-5, "old.toy.test"),
    "this line is not JSON",
    {"v": 1, "kind": "connect", "host": "stock.toy.test:443", "result": "ok"},
    "",
    tunnel(36, "stock.toy.test", result="error", reason="upstream"),
]
EGRESS_SPAN_MANIFEST = {
    "test": "20261023-090000-ks01",
    "model_sessions": [],
    "started": T0,
    "ended": T0 + 100,
    "trace": {"egress_ignore": ["GitHub.com"]},
    "egress": {
        "registered": T0 - 60,
        "answer": EGRESS_SPAN_ANSWER,
        "unseen": [],
        "proxies": {
            "anthropic": "http://127.0.0.1:41002",
            "stock": "http://127.0.0.1:41001",
            "shop-db": "postgresql://127.0.0.1:41003",
        },
        "receiver": None,
    },
}


def egress_where(host: str, line: int) -> dict:
    return {"harness": "egress", "session": host, "source": {"file": "egress.jsonl", "line": line}}


EGRESS_SPANS_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": EGRESS_SPAN_MANIFEST,
    "sessions": {},
    "egress": EGRESS_SPAN_LINES,
    "trace": [],
    "findings": {
        "v": "0.2",
        "test": "20261023-090000-ks01",
        "turns": 2,
        "items": 0,
        "sessions": [],
        "otel": None,
        "backend": None,
        "model_api": None,
        "mcp": None,
        "database": None,
        "egress": {
            "file": "egress.jsonl",
            "rows": 13,
            "spans": 7,
            "hosts": ["api.anthropic.com", "mail.toy.test", "pay.toy.test", "stock.toy.test"],
            "ignored": {
                "egress_ignore": 1,
                "llm": 1,
                "outside_window": 2,
                "invalid_json": 1,
                "invalid": 1,
                "blank": 1,
            },
        },
        "counts": counts(egress_not_in_discovery=2, egress_denied=2),
        "findings": [
            {
                "check": "egress_not_in_discovery",
                "turn": None,
                "detail": "mail.toy.test: 2 spans, and the egress answer has no part with this "
                "host",
                **egress_where("mail.toy.test", 3),
            },
            {
                "check": "egress_not_in_discovery",
                "turn": None,
                "detail": "pay.toy.test: 1 span, and the egress answer has no part with this host",
                **egress_where("pay.toy.test", 7),
            },
            {
                "check": "egress_denied",
                "turn": 2,
                "detail": "connect pay.toy.test port 8443: denied (port)",
                **egress_where("pay.toy.test", 7),
            },
            {
                "check": "egress_denied",
                "turn": 2,
                "detail": "tls no host port 443: denied (no SNI)",
                **egress_where("", 8),
            },
        ],
    },
}

# The same spans in a test with no egress answer, as a test of nookku 0.5.1 or earlier. The check
# egress_not_in_discovery does not run, and the denied calls still give findings. The manifest has
# no egress_ignore, so the span of github.com counts.
EGRESS_NO_ANSWER_CASE = {
    "tap": [window(10, 20), window(30, 40)],
    "manifest": {
        "test": "20261023-090000-ks02",
        "model_sessions": [],
        "started": T0,
        "ended": T0 + 100,
    },
    "sessions": {},
    "egress": EGRESS_SPAN_LINES,
    "trace": [],
    "findings": {
        **EGRESS_SPANS_CASE["findings"],
        "test": "20261023-090000-ks02",
        "egress": {
            "file": "egress.jsonl",
            "rows": 13,
            "spans": 8,
            "hosts": [
                "api.anthropic.com",
                "github.com",
                "mail.toy.test",
                "pay.toy.test",
                "stock.toy.test",
            ],
            "ignored": {"llm": 1, "outside_window": 2, "invalid_json": 1, "invalid": 1, "blank": 1},
        },
        "counts": counts(egress_denied=2),
        "findings": [
            {
                "check": "egress_denied",
                "turn": 2,
                "detail": "connect pay.toy.test port 8443: denied (port)",
                **egress_where("pay.toy.test", 7),
            },
            {
                "check": "egress_denied",
                "turn": 2,
                "detail": "tls no host port 443: denied (no SNI)",
                **egress_where("", 8),
            },
        ],
    },
}

# A span of the contract version 2 stops the trace, also outside the window: its fields can have
# a new meaning (SPEC.md section 8.8).
EGRESS_VERSION_CASE = {
    "tap": [window(10, 20)],
    "manifest": EGRESS_SPAN_MANIFEST,
    "sessions": {},
    "egress": [tunnel(11, "stock.toy.test"), {**tunnel(150, "stock.toy.test"), "v": 2}],
    "error": {
        "kind": "record_invalid",
        "file": "egress.jsonl",
        "message": "line 2: the span has the contract version 2. This nookku reads version 1 only "
        "(SPEC.md section 8.8). Use a nookku that reads version 2.",
    },
}


TRACE_CASES = {
    "claude_code_toy_shop": CLAUDE_CASE,
    "codex_toy_shop": CODEX_CASE,
    "untested_versions": VERSION_CASE,
    "claude_code_api_requests": API_REQUEST_CASE,
    "codex_model_error": CODEX_ERROR_CASE,
    "no_model_sessions": NO_MODEL_CASE,
    "otel_toy_shop": OTEL_CASE,
    "otel_structured_output": STRUCTURED_CASE,
    "backend_toy_shop": BACKEND_CASE,
    "model_api_toy_shop": MODEL_API_CASE,
    "model_api_responses": RESPONSES_CASE,
    "servers_not_from_app": SERVERS_CASE,
    "model_api_decisions": DECISIONS_CASE,
    "model_api_cut": CUT_CASE,
    "model_api_decisions_cut": DECISIONS_CUT_CASE,
    "repeated_reply": REPEATED_CASE,
    "repeated_reply_three": REPEATED_THREE_CASE,
    "repeated_reply_off": REPEATED_OFF_CASE,
    "reply_not_from_model": REPLY_CASE,
    "reply_not_from_model_exact": REPLY_EXACT_CASE,
    "reply_not_from_model_off": REPLY_OFF_CASE,
    "reply_not_from_model_field": REPLY_FIELD_CASE,
    "unseen_calls": UNSEEN_CASE,
    "unseen_calls_stdio": UNSEEN_STDIO_CASE,
    "driver_trace": DRIVER_CASE,
    "unseen_calls_driver": UNSEEN_DRIVER_CASE,
    "driver_trace_proxy": PROXY_DRIVER_CASE,
    "driver_trace_gaps": DRIVER_GAPS_CASE,
    "mcp_toy_shop": MCP_CASE,
    "database_toy_shop": DATABASE_CASE,
    "database_formats": DATABASE_FORMATS_CASE,
    "database_pipeline": DATABASE_PIPELINE_CASE,
    "trace_points_toy_shop": POINT_CASE,
    "trace_points_edges": EDGE_CASE,
    "egress_spans": EGRESS_SPANS_CASE,
    "egress_spans_no_answer": EGRESS_NO_ANSWER_CASE,
    "egress_spans_version_two": EGRESS_VERSION_CASE,
}


# Seal cases (SPEC.md section 7.4). Each case is a test folder after its end, the copy of the seal in
# `home/seals/`, and the result that `nookku verify --json` must give.
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
SEAL_NOTE = '{"v": "0.2", "type": "note", "turn": 1, "rating": "down", "comment": null}\n'


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
    # The notes of the tester (SPEC.md section 2.3) are in the seal. A note changed after the end
    # breaks it.
    "notes_intact": {
        "after": {"notes.jsonl": SEAL_NOTE},
        "seal_files": {"notes.jsonl": SEAL_NOTE},
        "copy_files": {"notes.jsonl": SEAL_NOTE},
        "verify": verified(True, "same"),
    },
    "changed_notes": {
        "after": {"notes.jsonl": SEAL_NOTE.replace('"down"', '"up"')},
        "seal_files": {"notes.jsonl": SEAL_NOTE},
        "copy_files": {"notes.jsonl": SEAL_NOTE},
        "verify": verified(False, "same", changed=["notes.jsonl"]),
    },
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


# Policy cases (SPEC.md sections 5 and 7.9). Each case is a PreToolUse event with no running test,
# the project around it, and the answer of `nookku hook`. In the event, `{root}` is the project.
# `state` is false for a project with no state folder. `links` maps a link to its target.
POLICY_DENY = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "nookku: only a person changes .nookku/policy.json, with nookku policy set in a shell."
        ),
    }
}


def pevent(tool: str, cwd: str = "{root}", **tool_input: Any) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "cwd": cwd,
        "tool_name": tool,
        "tool_input": tool_input,
    }


POLICY_CASES: dict[str, dict] = {
    "write_names_the_file": {
        "event": pevent("Write", file_path=".nookku/policy.json", content="{}"),
        "answer": POLICY_DENY,
    },
    "edit_with_the_absolute_path": {
        "event": pevent(
            "Edit", file_path="{root}/.nookku/policy.json", old_string="{", new_string="{ "
        ),
        "answer": POLICY_DENY,
    },
    "edit_with_other_case": {
        "event": pevent("Edit", file_path=".NOOKKU/Policy.JSON", old_string="{", new_string="{ "),
        "answer": POLICY_DENY,
    },
    "write_in_the_state_folder_with_a_relative_path": {
        "event": pevent("Write", cwd="{root}/.nookku", file_path="policy.json", content="{}"),
        "answer": POLICY_DENY,
    },
    "write_through_a_link": {
        "links": {"notes/rules.json": ".nookku/policy.json"},
        "event": pevent("Write", file_path="notes/rules.json", content="{}"),
        "answer": POLICY_DENY,
    },
    "patch_names_the_file": {
        "event": pevent(
            "apply_patch",
            input="*** Begin Patch\n*** Add File: .nookku/policy.json\n+{}\n*** End Patch\n",
        ),
        "answer": POLICY_DENY,
    },
    "shell_edit_in_place": {
        "event": pevent("Bash", command="sed -i '' 's/1/2/' .nookku/policy.json"),
        "answer": POLICY_DENY,
    },
    "shell_policy_set": {
        "event": pevent("Bash", command="nookku policy set scripts model"),
        "answer": POLICY_DENY,
    },
    "shell_policy_set_through_python": {
        "event": pevent("exec_command", cmd="uv run python -m nookku policy set scripts model"),
        "answer": POLICY_DENY,
    },
    "shell_write_in_the_state_folder": {
        "event": pevent("Bash", cwd="{root}/.nookku", command="printf '{}' > policy.json"),
        "answer": POLICY_DENY,
    },
    # A persistent shell can run in .nookku/. Its later input names only the file.
    "shell_session_input_names_the_file": {
        "event": pevent("write_stdin", session_id=3, chars="printf '{}' > policy.json\n"),
        "answer": POLICY_DENY,
    },
    "no_state_folder": {
        "state": False,
        "event": pevent("Write", file_path=".nookku/policy.json", content="{}"),
        "answer": POLICY_DENY,
    },
    # With no state folder, the default guard fields apply to an MCP tool (#150).
    "no_state_folder_other_tool_free_text": {
        "state": False,
        "event": pevent("mcp__docs__create", body="Discuss .nookku/policy.json."),
        "answer": None,
    },
    "no_state_folder_other_tool_path": {
        "state": False,
        "event": pevent("mcp__files__write", path=".nookku/policy.json", content="{}"),
        "answer": POLICY_DENY,
    },
    "no_state_folder_other_call": {
        "state": False,
        "event": pevent("Bash", command="ls src"),
        "answer": None,
    },
    "shell_reads_the_file": {
        "event": pevent("Bash", command="cat .nookku/policy.json"),
        "answer": None,
    },
    "read_tool": {
        "event": pevent("Read", file_path=".nookku/policy.json"),
        "answer": None,
    },
    # The content of a file names no file that the tool writes (#149).
    "write_content_names_the_file": {
        "event": pevent("Write", file_path="/tmp/notes.md", content="See .nookku/policy.json."),
        "answer": None,
    },
    "write_content_looks_like_a_patch": {
        "event": pevent(
            "Write", file_path="/tmp/notes.md", content="*** Update File: .nookku/policy.json\n"
        ),
        "answer": None,
    },
    # The guard reads only the fields of guard_fields of an MCP tool (#150).
    "other_tool_free_text_names_the_file": {
        "event": pevent("mcp__docs__create", body="Change .nookku/policy.json with a shell."),
        "answer": None,
    },
    "other_tool_path_names_the_file": {
        "event": pevent("mcp__files__write", path=".nookku/policy.json", content="{}"),
        "answer": POLICY_DENY,
    },
    "shell_heredoc_data_names_the_file": {
        "event": pevent(
            "Bash", command="cat > /tmp/notes.md <<'EOF'\nSee .nookku/policy.json.\nEOF"
        ),
        "answer": None,
    },
    "write_a_policy_file_of_the_app": {
        "event": pevent("Write", file_path="shop/policy.json", content="{}"),
        "answer": None,
    },
    "write_the_config_with_no_test": {
        "event": pevent("Write", file_path=".nookku/config.json", content="{}"),
        "answer": None,
    },
}


# Guard cases of the state folder (SPEC.md section 5, #149). The format is the format of the policy
# cases. `test` is true if a test runs, with the folder `<state>/tests/t1`.
def records(name: str, cause: str = "") -> dict:
    """The records deny. `cause` names the program or the redirect of a shell command (#172)."""
    return deny(
        f"nookku: {name} is a record or a state file of nookku. Only nookku writes it. "
        "A command may read it." + (f" {cause}" if cause else "")
    )


def not_read(program: str) -> str:
    return f'"{program}" is not a read command.'


def writes_with(program: str) -> str:
    return f'"{program}" with these arguments can write.'


CANNOT_PARSE = "The guard cannot parse the command."
SCENARIO = "To run a scenario, use nookku run --script, if the policy key scripts is model."
IMPORT_REASON = (
    "nookku: a model command may not import nookku, because a script can drive a test with it. "
    + SCENARIO
)


def drives(what: str) -> dict:
    """The deny of a model command that drives a test (#173)."""
    return deny(
        f"nookku: only a person runs {what}. A model command may not drive a test. {SCENARIO}"
    )


def during(name: str) -> dict:
    return deny(
        f"nookku: a test runs, so a tool call may not name {name} until the test ends. "
        "The file tools may read it."
    )


def deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def bash(command: str, cwd: str = "{root}") -> dict:
    return pevent("Bash", cwd=cwd, command=command)


STATE = "." + "nookku"
T1 = f"{STATE}/tests/t1"
RECORD = f"{T1}/relay.jsonl"
CONFIG = f"{STATE}/config.json"
GUARD_CASES: dict[str, dict] = {
    # With no test, the config and the entry are normal app files.
    "shell_edit_of_the_config": {
        "event": bash(f"sed -i '' 's/8800/8801/' {CONFIG}"),
        "answer": None,
    },
    "shell_edit_of_the_entry": {
        "event": bash(f"sed -i '' 's/shop/toy_shop/' {STATE}/entry.py"),
        "answer": None,
    },
    "shell_edit_of_a_record": {
        "event": bash(f"sed -i '' 's/4471/4417/' {RECORD}"),
        "answer": records(RECORD, writes_with("sed")),
    },
    "shell_redirect_to_a_state_file": {
        "event": bash(f"echo on >> {STATE}/mode"),
        "answer": records(f"{STATE}/mode", 'The redirect ">>" writes it.'),
    },
    "shell_removes_the_state_folder": {
        "event": bash(f"rm -rf {STATE}"),
        "answer": records(STATE, not_read("rm")),
    },
    "shell_glob_of_records": {
        "event": bash("rm .nook*/tests/*/tap.jsonl"),
        "answer": records(".nook*/tests/*/tap.jsonl", not_read("rm")),
    },
    "shell_seal_copy": {
        "event": bash(f"rm ~/{STATE}/seals/t1.json"),
        "answer": records(f"~/{STATE}/seals/t1.json", not_read("rm")),
    },
    "shell_changes_to_the_state_folder": {
        "event": bash(f"cd {STATE} && rm relay.jsonl"),
        "answer": records(STATE, not_read("rm")),
    },
    # Case 2 of #149: the body of a here-document that is data names a record.
    "shell_heredoc_data_names_a_record": {
        "event": bash(f"cat > /tmp/issue.md <<'EOF'\nSee {RECORD}.\nEOF"),
        "answer": None,
    },
    "shell_heredoc_code_names_a_record": {
        "event": bash(f"python3 - <<'EOF'\nopen('{RECORD}', 'w')\nEOF"),
        # The body is code with brackets, so the check cannot parse it.
        "answer": records(RECORD, CANNOT_PARSE),
    },
    # The argument of an interpreter is code that names a record.
    "shell_interpreter_code_names_a_record": {
        "event": bash(f"python3 -c \"open('{T1}/tap.jsonl', 'w').write('')\""),
        "answer": records(f"{T1}/tap.jsonl", not_read("python3")),
    },
    # A variable carries the path to the program.
    "shell_assignment_names_a_record": {
        "event": bash(f"P={RECORD} python3 clean.py"),
        "answer": records(f"P={RECORD}", not_read("python3")),
    },
    # The examples of #172. which, type and command -v are read commands.
    "shell_which_then_ls_of_a_test": {
        "event": bash(f"which ls; /bin/ls {T1}"),
        "answer": None,
    },
    "shell_audit_with_echo_tail_and_a_variable": {
        "event": bash(
            f'echo "== audit =="; nookku audit {T1} 2>&1 | tail -n 20; '
            'echo "exit ${pipestatus[1]} $status"'
        ),
        "answer": None,
    },
    "shell_type_and_command_v_then_a_read": {
        "event": bash(f"type nookku && command -v nookku && cat {RECORD}"),
        "answer": None,
    },
    "shell_command_runs_a_program": {
        "event": bash(f"command rm {RECORD}"),
        "answer": records(RECORD, writes_with("command")),
    },
    # A variable can be an argument, but not the program.
    "shell_variable_program_names_a_record": {
        "event": bash(f"X=rm; $X {RECORD}"),
        "answer": records(RECORD, not_read("$X")),
    },
    "shell_braced_variable_program_names_a_record": {
        "event": bash(f"X=rm; ${{X}} {RECORD}"),
        "answer": records(RECORD, not_read("${X}")),
    },
    "shell_variable_argument_of_a_read": {
        "event": bash(f"T={T1}; cat $T/relay.jsonl ${{T}}/tap.jsonl"),
        "answer": None,
    },
    # The check cannot parse a command substitution, so each word that names a record counts.
    "shell_command_substitution_names_a_record": {
        "event": bash(f"cat $(echo {RECORD})"),
        "answer": records(RECORD, CANNOT_PARSE),
    },
    "shell_backquote_names_a_record": {
        "event": bash(f"cat `echo {RECORD}`"),
        "answer": records(RECORD, CANNOT_PARSE),
    },
    # guard_reads adds read programs. A program of the built-in list keeps its own check.
    "shell_program_of_guard_reads": {
        "policy_text": '{"guard_reads": ["bat"]}\n',
        "event": bash(f"bat {RECORD}"),
        "answer": None,
    },
    "shell_program_not_in_guard_reads": {
        "event": bash(f"bat {RECORD}"),
        "answer": records(RECORD, not_read("bat")),
    },
    "shell_guard_reads_keeps_the_sed_check": {
        "policy_text": '{"guard_reads": ["sed"]}\n',
        "event": bash(f"sed -i '' 's/4471/4417/' {RECORD}"),
        "answer": records(RECORD, writes_with("sed")),
    },
    # A program name of guard_reads is literal. An expansion can become another program, so the
    # policy file is not valid, and no program is added.
    "shell_guard_reads_with_an_expansion": {
        "policy_text": '{"guard_reads": ["$X"]}\n',
        "event": bash(f"X=rm; $X {RECORD}"),
        "answer": records(RECORD, not_read("$X")),
    },
    # An assignment before a program fails the read check, so a command in the state folder is
    # denied.
    "shell_assignment_before_a_read_in_the_state_folder": {
        "event": bash(f"cd {STATE} && PATH=/tmp cat config.json"),
        "answer": records(STATE, 'The read check does not accept the assignment "PATH=/tmp".'),
    },
    # The deny of the policy file does not use guard_reads.
    "shell_program_of_guard_reads_writes_the_policy": {
        "policy_text": '{"guard_reads": ["shopctl"]}\n',
        "event": bash(f"shopctl --save {STATE}/policy.json"),
        "answer": deny(
            f"nookku: only a person changes {STATE}/policy.json, with nookku policy set in a shell."
        ),
    },
    "test_shell_which_then_ls_of_a_test": {
        "test": True,
        "event": bash(f"which ls; /bin/ls {T1}"),
        "answer": during(T1),
    },
    # #145: the entry and its child processes get the test folder in NOOKKU_TEST_DIR.
    "test_shell_writes_the_tap_record_through_the_test_folder_variable": {
        "test": True,
        "event": bash('printf x > "$NOOKKU_TEST_DIR/tap.jsonl"'),
        "answer": during("$NOOKKU_TEST_DIR/tap.jsonl"),
    },
    "test_shell_code_names_the_test_folder_variable": {
        "test": True,
        "event": bash("python3 -c \"import os; print(os.environ['NOOKKU_TEST_DIR'])\""),
        "answer": during("NOOKKU_TEST_DIR"),
    },
    # #173: only a person drives a test, with a test and with no test.
    "shell_starts_a_test": {
        "event": bash("nookku start"),
        "answer": drives("nookku start"),
    },
    "test_shell_ends_the_test": {
        "test": True,
        "event": bash("nookku end"),
        "answer": drives("nookku end"),
    },
    "shell_python_module_switches_relay_mode_on": {
        "event": bash("python3 -m nookku mode on"),
        "answer": drives("nookku mode on"),
    },
    "test_shell_code_ends_the_test": {
        "test": True,
        "event": bash("bash -lc 'nookku end'"),
        "answer": drives("nookku end"),
    },
    "shell_pipes_an_event_to_the_hook": {
        "event": bash(
            'echo \'{"hook_event_name": "UserPromptSubmit", "prompt": "Where is order 4471?"}\''
            " | nookku hook --harness claude-code"
        ),
        "answer": drives("nookku hook"),
    },
    # #163: init --remove removes the project hooks, so only a person runs it.
    "shell_removes_the_project_hooks": {
        "event": bash("nookku init --remove claude-code"),
        "answer": drives("nookku init --remove"),
    },
    "shell_removes_the_project_hooks_with_a_short_flag": {
        "event": bash("uv run python -m nookku init codex --rem --root ."),
        "answer": drives("nookku init --remove"),
    },
    "shell_inits_with_a_flag_that_starts_like_remove": {
        "event": bash("nookku init codex --remote-name x"),
        "answer": None,
    },
    "session_input_starts_a_test": {
        "event": pevent("write_stdin", session_id=1, chars="nookku start\n"),
        "answer": drives("nookku start"),
    },
    "shell_imports_the_package": {
        "event": bash('python3 -c "import nookku.kit"'),
        "answer": deny(IMPORT_REASON),
    },
    "shell_heredoc_code_imports_the_package": {
        "event": bash("python3 - <<'EOF'\nfrom nookku import kit\nEOF"),
        "answer": deny(IMPORT_REASON),
    },
    "shell_heredoc_data_names_an_import": {
        "event": bash("cat > /tmp/notes.md <<'EOF'\nimport nookku\nEOF"),
        "answer": None,
    },
    "shell_searches_for_an_import": {
        "event": bash('grep -rn "import nookku" shop'),
        "answer": None,
    },
    "shell_runs_a_script_with_scripts_person": {
        "event": bash("nookku run --script refunds.jsonl"),
        "answer": drives("nookku run"),
    },
    "shell_runs_a_script_with_scripts_model": {
        "policy_text": '{"scripts": "model"}\n',
        "event": bash("nookku run --script refunds.jsonl"),
        "answer": None,
    },
    "shell_runs_a_script_then_starts_a_test_with_scripts_model": {
        "policy_text": '{"scripts": "model"}\n',
        "event": bash("nookku run --script refunds.jsonl; nookku start"),
        "answer": drives("nookku start"),
    },
    "shell_uv_python_option_starts_a_test": {
        "event": bash("uv run --python python3 nookku start"),
        "answer": drives("nookku start"),
    },
    "shell_env_split_string_starts_a_test": {
        "event": bash("env -S 'nookku start'"),
        "answer": drives("nookku start"),
    },
    "test_shell_code_after_the_option_end_ends_the_test": {
        "test": True,
        "event": bash("sh -c -- 'nookku end'"),
        "answer": drives("nookku end"),
    },
    "shell_python_grouped_module_flag_starts_a_test": {
        "event": bash("python -Im nookku start"),
        "answer": drives("nookku start"),
    },
    "shell_python_long_option_value_starts_a_test": {
        "event": bash("python --check-hash-based-pycs always -m nookku start"),
        "answer": drives("nookku start"),
    },
    "shell_pipes_a_drive_into_a_shell_with_arguments": {
        "event": bash("printf 'nookku start' | bash -s refund"),
        "answer": drives("nookku start"),
    },
    "shell_env_value_names_a_drive": {
        "event": bash("env NOTE='nookku start' echo ok"),
        "answer": None,
    },
    "shell_pipes_a_drive_into_a_shell": {
        "event": bash("echo 'nookku start' | bash"),
        "answer": drives("nookku start"),
    },
    "shell_mode_status": {
        "event": bash("nookku mode status"),
        "answer": None,
    },
    "shell_check": {
        "event": bash("nookku check"),
        "answer": None,
    },
    "test_shell_transcript_with_the_trace": {
        "test": True,
        "event": bash("nookku transcript --trace"),
        "answer": None,
    },
    "shell_reads_a_record_into_another_file": {
        "event": bash(f"cat -n {RECORD} | sed -n 1,200p > /tmp/copy.txt"),
        "answer": None,
    },
    "shell_writes_the_report": {
        "event": bash(f"cat > {T1}/report.md <<'EOF'\n# Report\nEOF"),
        "answer": None,
    },
    # Case 3 of #149: the content of a file names a record. The target is outside the project.
    "write_content_names_a_record": {
        "event": pevent("Write", file_path="/tmp/notes.md", content=f"See {RECORD}."),
        "answer": None,
    },
    "write_of_a_record": {
        "event": pevent("Write", file_path=f"{T1}/tap.jsonl", content="{}"),
        "answer": records(f"{T1}/tap.jsonl"),
    },
    "write_of_the_report": {
        "event": pevent("Write", file_path=f"{T1}/report.md", content="# Report\n"),
        "answer": None,
    },
    "patch_header_names_a_state_file": {
        "event": pevent(
            "apply_patch",
            input=f"*** Begin Patch\n*** Delete File: {STATE}/current.json\n*** End Patch\n",
        ),
        "answer": records(f"{STATE}/current.json"),
    },
    # Only apply_patch has patch headers. Other content only looks like a patch.
    "write_content_looks_like_a_patch": {
        "event": pevent(
            "Write", file_path="/tmp/notes.md", content=f"*** Delete File: {STATE}/current.json\n"
        ),
        "answer": None,
    },
    "patch_content_names_a_record": {
        "event": pevent(
            "apply_patch",
            input=f"*** Begin Patch\n*** Update File: shop/app.py\n+LOG = '{RECORD}'\n*** End Patch\n",
        ),
        "answer": None,
    },
    "other_tool_writes_a_state_file": {
        "event": pevent("mcp__files__write", path=f"{STATE}/mode", content="on"),
        "answer": records(f"{STATE}/mode"),
    },
    "other_tool_writes_the_config": {
        "event": pevent("mcp__files__write", path=CONFIG, content="{}"),
        "answer": None,
    },
    # A tool that is not a shell or a file tool: the guard reads only the fields of guard_fields
    # (#150). `policy_text` is the policy file of the case.
    "other_tool_free_text_names_a_record": {
        "event": pevent("mcp__docs__create", title="Feedback", body=f"The guard denied {RECORD}."),
        "answer": None,
    },
    "other_tool_nested_uri_names_a_state_file": {
        "event": pevent("mcp__web__save", request={"options": {"uri": f"{STATE}/mode"}}),
        "answer": records(f"{STATE}/mode"),
    },
    "other_tool_field_of_the_policy": {
        "policy_text": '{"guard_fields": ["target"]}\n',
        "event": pevent("mcp__files__copy", target=f"{STATE}/mode", path=f"{STATE}/mode"),
        "answer": records(f"{STATE}/mode"),
    },
    "other_tool_field_not_in_the_policy": {
        "policy_text": '{"guard_fields": ["target"]}\n',
        "event": pevent("mcp__files__copy", path=f"{STATE}/mode"),
        "answer": None,
    },
    # A policy file that is not valid does not weaken the guard: each field counts.
    "other_tool_with_a_broken_policy": {
        "policy_text": "[]\n",
        "event": pevent("mcp__docs__create", body=f"{STATE}/mode"),
        "answer": records(f"{STATE}/mode"),
    },
    "test_other_tool_url_names_the_tap": {
        "test": True,
        "event": pevent("mcp__web__fetch", url="http://127.0.0.1:9/chat"),
        "answer": deny("nookku: only the tester talks to the agent."),
    },
    "test_other_tool_free_text_names_the_tap": {
        "test": True,
        "event": pevent("mcp__docs__create", body="The tap runs on http://127.0.0.1:9/."),
        "answer": None,
    },
    "test_other_tool_free_text_names_the_state_folder": {
        "test": True,
        "event": pevent("mcp__docs__create", body=f"See {CONFIG}."),
        "answer": None,
    },
    # During a test, a tool call except a file read may not name the state folder.
    "test_shell_edit_of_the_config": {
        "test": True,
        "event": bash(f"sed -i '' 's/8800/8801/' {CONFIG}"),
        "answer": during(CONFIG),
    },
    "test_shell_read_of_the_config": {
        "test": True,
        "event": bash(f"cat {CONFIG}"),
        "answer": during(CONFIG),
    },
    "test_write_of_the_config": {
        "test": True,
        "event": pevent("Write", file_path=CONFIG, content="{}"),
        "answer": during(CONFIG),
    },
    "test_read_of_the_config": {
        "test": True,
        "event": pevent("Read", file_path=CONFIG),
        "answer": None,
    },
    "test_write_content_names_the_state_folder": {
        "test": True,
        "event": pevent("Write", file_path="/tmp/notes.md", content=f"See {CONFIG}."),
        "answer": None,
    },
    "test_shell_heredoc_data_names_the_state_folder": {
        "test": True,
        "event": bash(f"cat > /tmp/notes.md <<'EOF'\nSee {CONFIG}.\nEOF"),
        "answer": None,
    },
    # #457: the tests folder of NOOKKU_TESTS_DIR, outside the project. `{tests}` is its absolute
    # path. "tests_dir": "variable" sets the variable for the hook. "tests_dir": "running" sets no
    # variable, and the running test is in the folder: a command started it with --tests-dir.
    "tests_dir_shell_removes_a_record": {
        "tests_dir": "variable",
        "event": bash("rm {tests}/t1/tap.jsonl"),
        "answer": records("{tests}/t1/tap.jsonl", not_read("rm")),
    },
    "tests_dir_write_of_a_record": {
        "tests_dir": "variable",
        "event": pevent("Write", file_path="{tests}/t1/relay.jsonl", content="{}"),
        "answer": records("{tests}/t1/relay.jsonl"),
    },
    "tests_dir_write_of_the_report": {
        "tests_dir": "variable",
        "event": pevent("Write", file_path="{tests}/t1/report.md", content="# Report\n"),
        "answer": None,
    },
    "tests_dir_shell_read_of_a_record": {
        "tests_dir": "variable",
        "event": bash("cat {tests}/t1/tap.jsonl"),
        "answer": None,
    },
    "tests_dir_shell_in_the_test_folder": {
        "tests_dir": "variable",
        "event": bash("rm tap.jsonl", cwd="{tests}/t1"),
        # A relative word starts at the cwd of the call.
        "answer": records("tap.jsonl", not_read("rm")),
    },
    "tests_dir_shell_changes_to_the_tests_folder": {
        "tests_dir": "variable",
        "event": bash("cd {tests} && rm t1/tap.jsonl"),
        "answer": records("{tests}", not_read("rm")),
    },
    "tests_dir_glob_of_records": {
        "tests_dir": "variable",
        "event": bash("rm {tests}/*/tap.jsonl"),
        "answer": records("{tests}/*/tap.jsonl", not_read("rm")),
    },
    "tests_dir_variable_names_a_record": {
        "tests_dir": "variable",
        "event": bash('rm "$NOOKKU_TESTS_DIR/t1/tap.jsonl"'),
        "answer": records("$NOOKKU_TESTS_DIR/t1/tap.jsonl", not_read("rm")),
    },
    # Another folder with the name tests is an app folder.
    "tests_dir_other_folder_named_tests": {
        "tests_dir": "variable",
        "event": bash("rm -r build/tests"),
        "answer": None,
    },
    "test_tests_dir_shell_read_of_a_record": {
        "test": True,
        "tests_dir": "variable",
        "event": bash("cat {tests}/t1/tap.jsonl"),
        "answer": during("{tests}/t1/tap.jsonl"),
    },
    "test_tests_dir_running_test_with_no_variable": {
        "test": True,
        "tests_dir": "running",
        "event": bash("cat {tests}/t1/tap.jsonl"),
        "answer": during("{tests}/t1/tap.jsonl"),
    },
}


# Near-miss control prompts (SPEC.md section 5, #146). In relay mode, a refused message gets the
# refusal and is not a turn, and each other message goes to the agent. `mode_off_hint` is the
# control prompt that the hook names with relay mode off, or None if the prompt goes to the model
# (#401). With relay mode off, only the edit distance counts, and not the first word nookku.
CONTROL_CASES: dict[str, dict] = {
    "wrong_command_word": {"prompt": "nookku stop", "refused": True, "mode_off_hint": None},
    "capital_letter": {"prompt": "Nookku start", "refused": True, "mode_off_hint": "nookku start"},
    "two_spaces": {"prompt": "nookku  end", "refused": True, "mode_off_hint": "nookku end"},
    "name_alone": {"prompt": "nookku", "refused": True, "mode_off_hint": None},
    "one_letter_short": {"prompt": "nookk end", "refused": True, "mode_off_hint": "nookku end"},
    "one_letter_short_in_the_middle": {
        "prompt": "nooku end",
        "refused": True,
        "mode_off_hint": "nookku end",
    },
    "two_edits": {"prompt": "noku status", "refused": True, "mode_off_hint": "nookku status"},
    "three_edits": {"prompt": "nok stat", "refused": False, "mode_off_hint": None},
    "question_about_nookku": {
        "prompt": "tell me about nookku",
        "refused": False,
        "mode_off_hint": None,
    },
    "shop_question_about_relays": {
        "prompt": "Do you sell relay switches?",
        "refused": False,
        "mode_off_hint": None,
    },
    "shop_word_near_the_name": {
        "prompt": "Is the nook table in stock?",
        "refused": False,
        "mode_off_hint": None,
    },
    "distance_zero_turns_off_the_rule": {
        "prompt": "nookku stop",
        "policy_text": '{"control_distance": 0}\n',
        "refused": False,
        "mode_off_hint": None,
    },
    "distance_zero_turns_off_the_rule_with_mode_off": {
        "prompt": "nooku end",
        "policy_text": '{"control_distance": 0}\n',
        "refused": False,
        "mode_off_hint": None,
    },
    "distance_one": {
        "prompt": "noku status",
        "policy_text": '{"control_distance": 1}\n',
        "refused": False,
        "mode_off_hint": None,
    },
    "broken_policy_uses_the_default": {
        "prompt": "nookk end",
        "policy_text": '{"control_distance": -1}\n',
        "refused": True,
        "mode_off_hint": "nookku end",
    },
}


# The rule for a check test (SPEC.md sections 7.2 and 9.1). Each case is a test that ended, with no
# report. `manifest` holds the keys that the case adds to the manifest, and `relay` the rows of
# relay.jsonl. `evaluated` tells if the test needs an evaluation.
CHECK_TURN = {**turn("Hello", "Toy shop: Hello"), "harness": "nookku-check"}
TESTER_TURN = {**turn("Do you sell teapots?", "Toy shop: yes"), "harness": "codex"}
EVALUATION_CASES: dict[str, dict] = {
    # The check stopped before its turn, for example with Ctrl-C (#297).
    "check_stopped_before_its_turn": {"manifest": {"check": True}, "relay": [], "evaluated": False},
    "check_with_its_turn": {"manifest": {"check": True}, "relay": [CHECK_TURN], "evaluated": False},
    "test_of_the_tester": {"manifest": {"check": False}, "relay": [TESTER_TURN], "evaluated": True},
    # The key decides, and not the turns.
    "check_false_with_check_turns": {
        "manifest": {"check": False},
        "relay": [CHECK_TURN],
        "evaluated": True,
    },
    "check_not_a_boolean": {"manifest": {"check": "true"}, "relay": [], "evaluated": True},
    # A manifest of an older Nookku version has no key check: the turns decide.
    "no_key_check_turns_only": {"manifest": {}, "relay": [CHECK_TURN], "evaluated": False},
    "no_key_tester_turn": {
        "manifest": {},
        "relay": [CHECK_TURN, TESTER_TURN],
        "evaluated": True,
    },
    "no_key_no_turns": {"manifest": {}, "relay": [], "evaluated": True},
    "no_key_broken_relay_record": {"manifest": {}, "relay": ["{broken"], "evaluated": True},
    # `later` holds the tests that started after the test. A later test can have
    # `report: true`. At most one test of a case has `evaluated: true` (#298).
    # The tester ended the test in a shell and then ran nookku check.
    "check_after_the_test": {
        "manifest": {"check": False},
        "relay": [TESTER_TURN],
        "later": [{"manifest": {"check": True}, "relay": [CHECK_TURN], "evaluated": False}],
        "evaluated": True,
    },
    "no_key_check_after_the_test": {
        "manifest": {"check": False},
        "relay": [TESTER_TURN],
        "later": [{"manifest": {}, "relay": [CHECK_TURN], "evaluated": False}],
        "evaluated": True,
    },
    # A test that is not a check test hides each test before it.
    "test_after_the_test": {
        "manifest": {"check": False},
        "relay": [TESTER_TURN],
        "later": [{"manifest": {"check": False}, "relay": [TESTER_TURN], "evaluated": True}],
        "evaluated": False,
    },
    "check_after_a_test_with_a_report": {
        "manifest": {"check": False},
        "relay": [TESTER_TURN],
        "later": [
            {
                "manifest": {"check": False},
                "relay": [TESTER_TURN],
                "report": True,
                "evaluated": False,
            },
            {"manifest": {"check": True}, "relay": [CHECK_TURN], "evaluated": False},
        ],
        "evaluated": False,
    },
    # A later test ends, unless its manifest has `ended: null`. A check test with no end time
    # hides the tests before it: the check starts or stopped before its end steps.
    "check_without_end_after_the_test": {
        "manifest": {"check": False},
        "relay": [TESTER_TURN],
        "later": [{"manifest": {"check": True, "ended": None}, "relay": [], "evaluated": False}],
        "evaluated": False,
    },
    "test_without_end_after_the_test": {
        "manifest": {"check": False},
        "relay": [TESTER_TURN],
        "later": [
            {
                "manifest": {"check": False, "ended": None},
                "relay": [TESTER_TURN],
                "evaluated": False,
            }
        ],
        "evaluated": False,
    },
    # `manifest_text` is a manifest that cannot be read. It does not make a check test.
    "broken_manifest_after_the_test": {
        "manifest": {"check": False},
        "relay": [TESTER_TURN],
        "later": [
            {
                "manifest": {},
                "manifest_text": '{"started": 3.0, "check": true, "ended"',
                "relay": [CHECK_TURN],
                "evaluated": False,
            }
        ],
        "evaluated": False,
    },
}


def write_policy_case(path: Path, case: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"state": True, "links": {}, "test": False, **case}
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


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
# A span with a lone surrogate in its name, in an attribute key and in an attribute value. The JSON
# body escapes each one. The receiver writes each one as its escape text (SPEC.md section 2).
SURROGATE_JSON = {
    "resourceSpans": [
        {
            "resource": {"attributes": [js_kv("service.name", {"stringValue": "toy-shop"})]},
            "scopeSpans": [
                {
                    "scope": {"name": "toy-shop"},
                    "spans": [
                        {
                            "traceId": TRACE_ID,
                            "spanId": "b7ad6b7169203331",
                            "name": "GET /mugs/\ud83d",
                            "startTimeUnixNano": str(ns(40)),
                            "endTimeUnixNano": str(ns(40.5)),
                            "attributes": [
                                js_kv("shop.note", {"stringValue": "a mug \udc00"}),
                                js_kv("shop.\ud83d", {"stringValue": "teapot"}),
                            ],
                        }
                    ],
                }
            ],
        }
    ]
}
SURROGATE_ROW = {
    "v": 1,
    "type": "span",
    "received": RECEIVED,
    "service": "toy-shop",
    "resource": {"service.name": "toy-shop"},
    "scope": "toy-shop",
    "trace_id": TRACE_ID,
    "span_id": "b7ad6b7169203331",
    "parent_span_id": None,
    "name": "GET /mugs/\\ud83d",
    "start": T0 + 40,
    "end": T0 + 40.5,
    "attributes": {"shop.note": "a mug \\udc00", "shop.\\ud83d": "teapot"},
    "events": [],
    "status": {"code": 0, "message": None},
}
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
    "lone_surrogate_escaped": {
        "path": "/v1/traces",
        "type": "application/json",
        "body": json.dumps(SURROGATE_JSON).encode(),
        "rows": [SURROGATE_ROW],
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


def script_turn(said: str, shown: str | None) -> dict:
    return {**turn(said, shown), "harness": "script"}


def jsonl(*messages: str) -> str:
    return "".join(json.dumps({"said": m}, ensure_ascii=False) + "\n" for m in messages)


SCRIPT_RELAY = [script_turn(M1, R1), script_turn(M2, R2), script_turn(M3, R3)]
M2_CHANGED = M2.replace("€", "EUR")
# The scripted tests (SPEC.md section 7.10). The file of each case is the script copy that the
# bridge gives the audit, with its exact bytes.
SCRIPTS = {
    "script_clean": ("script.jsonl", jsonl(M1, M2, M3)),
    "script_clean_json_array": ("script.json", json.dumps([M1, M2, M3], ensure_ascii=False)),
    "script_said_differs": ("script.jsonl", jsonl(M1, M2, M3)),
    "script_message_not_sent": ("script.jsonl", jsonl(M1, M2, M3)),
    "script_turn_after_the_last_message": ("script.jsonl", jsonl(M1, M2)),
    "script_typed_turn": ("script.jsonl", jsonl(M1, M2, M3)),
    "script_row_with_another_key": ("script.jsonl", '{"said": "Hi", "reply": "Hello"}\n'),
    "script_lone_surrogate": ("script.jsonl", '{"said": "\\ud83d"}\n'),
    "script_empty_array": ("script.json", "[]\n"),
}
CASES_BY_NAME.update(
    {
        "script_clean": (CLEAN_TAP, SCRIPT_RELAY, {"exit": 0, "breaks": []}),
        "script_clean_json_array": (CLEAN_TAP, SCRIPT_RELAY, {"exit": 0, "breaks": []}),
        # The relay sent a changed text, and the tap got the same text. Only the script shows it.
        "script_said_differs": (
            [ex(M1, R1), ex(M2_CHANGED, R2), ex(M3, R3)],
            [script_turn(M1, R1), script_turn(M2_CHANGED, R2), script_turn(M3, R3)],
            {"exit": 1, "breaks": [["script_mismatch", 2, None]]},
        ),
        "script_message_not_sent": (
            CLEAN_TAP[:2],
            SCRIPT_RELAY[:2],
            {"exit": 1, "breaks": [["script_mismatch", None, None]]},
        ),
        "script_turn_after_the_last_message": (
            CLEAN_TAP,
            SCRIPT_RELAY,
            {"exit": 1, "breaks": [["script_mismatch", 3, None]]},
        ),
        # A typed turn in a scripted test, with the text of the script message.
        "script_typed_turn": (
            CLEAN_TAP,
            [script_turn(M1, R1), turn(M2, R2), script_turn(M3, R3)],
            {"exit": 1, "breaks": [["script_mismatch", 2, None]]},
        ),
        "script_row_with_another_key": (
            CLEAN_TAP,
            SCRIPT_RELAY,
            {"exit": 2, "errors": ["record_invalid"]},
        ),
        "script_lone_surrogate": (
            CLEAN_TAP,
            SCRIPT_RELAY,
            {"exit": 2, "errors": ["record_invalid"]},
        ),
        "script_empty_array": (CLEAN_TAP, SCRIPT_RELAY, {"exit": 2, "errors": ["record_invalid"]}),
    }
)


# Notes cases (SPEC.md section 2.3). Each case is a notes.jsonl and what the reader
# (`record.read_rows` with the kind `notes`) must give: each note, or the error and its line.
def note(turn: object, rating: object, comment: object, v: str = "0.2") -> dict:
    row = {"v": v, "type": "note", "ts": T0 + 30, "turn": turn, "rating": rating}
    return row | {
        "comment": comment,
        "comment_sha256": sha(comment if isinstance(comment, str) else None),
    }


def notes_ok(*rows: dict) -> dict:
    return {"notes": [{k: r[k] for k in ("turn", "rating", "comment")} for r in rows]}


def notes_bad(line: int) -> dict:
    return {"error": "record_invalid", "line": line}


NOTE_UP = note(1, "up", "Fast and correct. The order 4471 is right.")
NOTE_DOWN = note(2, "down", None)
NOTE_AGAIN = note(2, "down", "  The refund date is wrong.\n\nIt says Monday.  ")
NOTE_FR = note(3, None, "Ça marche, merci.")
NOTES_CASES: dict[str, dict] = {
    # 2 notes on 2 turns, and a later note on turn 2. The reader keeps each byte of a comment.
    "two_notes": {
        "rows": [NOTE_UP, NOTE_DOWN, NOTE_AGAIN],
        "expect": notes_ok(NOTE_UP, NOTE_DOWN, NOTE_AGAIN),
    },
    "comment_only": {"rows": [NOTE_FR], "expect": notes_ok(NOTE_FR)},
    "no_notes": {"rows": [], "expect": {"notes": []}},
    "comment_hash_mismatch": {
        "rows": [NOTE_UP, {**NOTE_DOWN, "comment_sha256": sha("x")}],
        "expect": notes_bad(2),
    },
    "comment_hash_missing": {
        "rows": [{k: v for k, v in NOTE_UP.items() if k != "comment_sha256"}],
        "expect": notes_bad(1),
    },
    "rating_not_known": {"rows": [note(1, "meh", None)], "expect": notes_bad(1)},
    "rating_not_text": {"rows": [note(1, 1, None)], "expect": notes_bad(1)},
    "no_rating_no_comment": {"rows": [note(1, None, None)], "expect": notes_bad(1)},
    "no_rating_empty_comment": {"rows": [note(1, None, "")], "expect": notes_bad(1)},
    "turn_zero": {"rows": [note(0, "up", None)], "expect": notes_bad(1)},
    "turn_is_a_boolean": {"rows": [note(True, "up", None)], "expect": notes_bad(1)},
    "turn_is_text": {"rows": [note("1", "up", None)], "expect": notes_bad(1)},
    "turn_missing": {
        "rows": [{k: v for k, v in NOTE_UP.items() if k != "turn"}],
        "expect": notes_bad(1),
    },
    # The note type is new in 0.2.
    "note_with_version_0_1": {"rows": [note(1, "up", None, v="0.1")], "expect": notes_bad(1)},
    # A notes record holds only notes.
    "turn_row_in_notes": {"rows": [NOTE_UP, turn("Hi", "Hello", v="0.2")], "expect": notes_bad(2)},
    "lone_surrogate_in_comment": {
        "rows": [
            NOTE_UP,
            '{"v": "0.2", "type": "note", "ts": 1, "turn": 1, "rating": "up", "comment": "\\ud83d", "comment_sha256": null}',
        ],
        "expect": notes_bad(2),
    },
}


def write(path: Path, rows: list | None) -> None:
    if rows is None:
        return
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows]
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


# The egress answer of `nookku register` (SPEC.md section 7.11). Each case is an answer, and the
# start lines and the unseen parts that the rule gives, or the error that it gives.
TOY_ANSWER = {
    "model_apis": [{"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": None}],
    "backends": [{"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9100"}],
    "mcp_servers": [
        {
            "name": "files",
            "transport": "stdio",
            "env": None,
            "command": ["toy-files-mcp", "--root", "data"],
            "url": None,
        },
        {
            "name": "tickets",
            "transport": "http",
            "env": "TICKETS_MCP_URL",
            "command": None,
            "url": "https://tickets.toy.test/mcp",
        },
    ],
    "databases": [
        {
            "name": "shop",
            "kind": "postgres",
            "env": "DATABASE_URL",
            "address": "127.0.0.1:5432/shop",
            "record": "proxy",
        },
        {
            "name": "cart",
            "kind": "sqlite",
            "env": None,
            "address": "data/cart.db",
            "record": "driver",
        },
    ],
    "other": [{"name": "mail", "kind": "smtp", "detail": "sends the order mail"}],
}
EMPTY_ANSWER = {k: [] for k in ("model_apis", "backends", "mcp_servers", "databases", "other")}


def answer_with(kind: str, part: dict) -> dict:
    return {**EMPTY_ANSWER, kind: [part]}


STOCK = {"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9100"}
DRIVER_ONLY = (
    "databases[0]: only a postgres database with a variable has a proxy. Give 'record' driver."
)
LISTS_ERROR = (
    "the answer must have the lists model_apis, backends, mcp_servers, databases, other, "
    "and no other key"
)
DISCOVERY_CASES: dict[str, dict] = {
    "toy_shop": {
        "answer": TOY_ANSWER,
        "expect": {
            "lines": [
                "- model API anthropic: ANTHROPIC_BASE_URL -> the URL in ANTHROPIC_BASE_URL or "
                "the default (proxy)",
                "- backend stock: STOCK_URL -> http://127.0.0.1:9100 (proxy)",
                "- MCP server files: stdio toy-files-mcp --root data (no proxy)",
                "- MCP server tickets: http TICKETS_MCP_URL -> https://tickets.toy.test/mcp (proxy)",
                "- database shop: postgres, DATABASE_URL (proxy)",
                "- database cart: sqlite, data/cart.db (driver trace)",
                "- other mail: smtp, sends the order mail (no proxy)",
            ],
            "unseen": ["files", "mail"],
        },
    },
    # A stdio server with a variable gets the wrapper (SPEC.md section 7.12).
    "mcp_stdio_with_variable": {
        "answer": answer_with(
            "mcp_servers",
            {
                "name": "files",
                "transport": "stdio",
                "env": "FILES_MCP_COMMAND",
                "command": ["toy-files-mcp"],
                "url": None,
            },
        ),
        "expect": {
            "lines": ["- MCP server files: stdio FILES_MCP_COMMAND -> toy-files-mcp (proxy)"],
            "unseen": [],
        },
    },
    "no_part": {
        "answer": EMPTY_ANSWER,
        "expect": {"lines": ["- no egress part: the agent calls no service"], "unseen": []},
    },
    "not_an_object": {"answer": [], "expect": {"error": "the answer must be a JSON object"}},
    "missing_list": {
        "answer": {k: v for k, v in EMPTY_ANSWER.items() if k != "other"},
        "expect": {"error": LISTS_ERROR},
    },
    # The keys backends and model_api of nookku 0.5.1 are not an answer.
    "old_config_keys": {
        "answer": {"backends": [STOCK], "model_api": True},
        "expect": {"error": LISTS_ERROR},
    },
    "extra_part_key": {
        "answer": answer_with("backends", {**STOCK, "token": "toy-123"}),
        "expect": {"error": "backends[0] must have the keys name, env, url, and no other key"},
    },
    "url_with_password": {
        "answer": answer_with("backends", {**STOCK, "url": "http://toy:pw@127.0.0.1:9100"}),
        "expect": {
            "error": "backends[0]: the URL has a user or a password. Give the variable only."
        },
    },
    "url_with_secret_query": {
        "answer": answer_with("backends", {**STOCK, "url": "http://127.0.0.1:9100/?api_key=toy"}),
        "expect": {"error": "backends[0]: the URL has a value of the secret parameter 'api_key'."},
    },
    "url_with_empty_secret_query": {
        "answer": answer_with("backends", {**STOCK, "url": "http://127.0.0.1:9100/?api_key="}),
        "expect": {
            "lines": ["- backend stock: STOCK_URL -> http://127.0.0.1:9100/?api_key= (proxy)"],
            "unseen": [],
        },
    },
    "url_not_http": {
        "answer": answer_with("backends", {**STOCK, "url": "ftp://stock.toy.test"}),
        "expect": {"error": "backends[0] 'url' must be an http or https URL with a host"},
    },
    "backend_with_null_url": {
        "answer": answer_with("backends", {**STOCK, "url": None}),
        "expect": {"error": "backends[0] 'url' must be a text"},
    },
    "reserved_variable": {
        "answer": answer_with("backends", {**STOCK, "env": "NOOKKU_TEST_DIR"}),
        "expect": {"error": "backends[0] 'env' is the variable NOOKKU_TEST_DIR of nookku"},
    },
    # #457: the tests folder of the test command. A part must not move it for the entry.
    "reserved_tests_folder_variable": {
        "answer": answer_with("backends", {**STOCK, "env": "NOOKKU_TESTS_DIR"}),
        "expect": {"error": "backends[0] 'env' is the variable NOOKKU_TESTS_DIR of nookku"},
    },
    "bad_variable": {
        "answer": answer_with("backends", {**STOCK, "env": "STOCK-URL"}),
        "expect": {"error": "backends[0] 'env' must be a variable name of letters, digits and '_'"},
    },
    "unknown_model_api": {
        "answer": answer_with("model_apis", {"api": "toy", "env": "TOY_URL", "url": None}),
        "expect": {"error": "model_apis[0] 'api' must be one of: anthropic, openai"},
    },
    # A model API uses its api as its name, so a backend with the same name is refused.
    "same_name": {
        "answer": {
            **EMPTY_ANSWER,
            "model_apis": [{"api": "openai", "env": "OPENAI_BASE_URL", "url": None}],
            "backends": [{**STOCK, "name": "openai"}],
        },
        "expect": {
            "error": "each part needs its own name (a model API uses its 'api' as its name)"
        },
    },
    "same_variable": {
        "answer": {
            **EMPTY_ANSWER,
            "backends": [STOCK],
            "databases": [
                {
                    "name": "shop",
                    "kind": "postgres",
                    "env": "STOCK_URL",
                    "address": None,
                    "record": "proxy",
                }
            ],
        },
        "expect": {"error": "each part needs its own 'env'"},
    },
    "command_with_secret": {
        "answer": answer_with(
            "mcp_servers",
            {
                "name": "stock",
                "transport": "stdio",
                "env": None,
                "command": ["toy-stock-mcp", "--token", "toy-123"],
                "url": None,
            },
        ),
        "expect": {
            "error": "mcp_servers[0]: the command has a value of the secret key 'token'. "
            "Give the value in a variable of the server."
        },
    },
    "stdio_with_url": {
        "answer": answer_with(
            "mcp_servers",
            {
                "name": "files",
                "transport": "stdio",
                "env": None,
                "command": ["toy-files-mcp"],
                "url": "http://127.0.0.1:9200",
            },
        ),
        "expect": {
            "error": "mcp_servers[0]: a stdio server needs 'command' and a null 'url', "
            "an http server needs 'url' and a null 'command'"
        },
    },
    "address_with_user": {
        "answer": answer_with(
            "databases",
            {
                "name": "shop",
                "kind": "postgres",
                "env": None,
                "address": "toy@127.0.0.1:5432",
                "record": "driver",
            },
        ),
        "expect": {"error": "databases[0]: the address has a user or a password. Give host:port."},
    },
    "address_with_secret_query": {
        "answer": answer_with(
            "databases",
            {
                "name": "shop",
                "kind": "postgres",
                "env": None,
                "address": "db.toy.test:5432/shop?password=toy",
                "record": "driver",
            },
        ),
        "expect": {"error": "databases[0]: the address has a value of the secret key 'password'."},
    },
    "address_with_secret_word": {
        "answer": answer_with(
            "databases",
            {
                "name": "shop",
                "kind": "postgres",
                "env": None,
                "address": "host=db.toy.test password=toy",
                "record": "driver",
            },
        ),
        "expect": {"error": "databases[0]: the address has a value of the secret key 'password'."},
    },
    # The driver trace records a database that no proxy can see (SPEC.md section 7.11): a
    # database that is not Postgres, or a Postgres database whose proxy cannot connect.
    "record_driver": {
        "answer": answer_with(
            "databases",
            {
                "name": "shop",
                "kind": "postgres",
                "env": "DATABASE_URL",
                "address": None,
                "record": "driver",
            },
        ),
        "expect": {
            "lines": ["- database shop: postgres, DATABASE_URL (driver trace)"],
            "unseen": [],
        },
    },
    "record_proxy_for_sqlite": {
        "answer": answer_with(
            "databases",
            {
                "name": "cart",
                "kind": "sqlite",
                "env": "CART_DB",
                "address": None,
                "record": "proxy",
            },
        ),
        "expect": {"error": DRIVER_ONLY},
    },
    "record_proxy_with_no_variable": {
        "answer": answer_with(
            "databases",
            {"name": "shop", "kind": "postgres", "env": None, "address": None, "record": "proxy"},
        ),
        "expect": {"error": DRIVER_ONLY},
    },
    "record_that_is_not_known": {
        "answer": answer_with(
            "databases",
            {"name": "shop", "kind": "postgres", "env": None, "address": None, "record": "logs"},
        ),
        "expect": {"error": "databases[0] 'record' must be one of: proxy, driver"},
    },
    # Next to a proxy database of the same kind, the coverage check needs the address of a driver
    # database (SPEC.md section 8.6).
    "driver_with_no_address_next_to_a_proxy": {
        "answer": {
            **EMPTY_ANSWER,
            "databases": [
                {
                    "name": "shop",
                    "kind": "postgres",
                    "env": "DATABASE_URL",
                    "address": None,
                    "record": "proxy",
                },
                {
                    "name": "stock",
                    "kind": "postgres",
                    "env": None,
                    "address": "db.toy.test/stock",
                    "record": "driver",
                },
            ],
        },
        "expect": {
            "error": "databases[1]: a proxy database has the same kind, so a driver database "
            "needs the address host:port or host:port/database"
        },
    },
    "database_with_no_record": {
        "answer": answer_with(
            "databases", {"name": "shop", "kind": "postgres", "env": None, "address": None}
        ),
        "expect": {
            "error": "databases[0] must have the keys name, kind, env, address, record, "
            "and no other key"
        },
    },
    "url_that_does_not_parse": {
        "answer": answer_with("backends", {"name": "stock", "env": "STOCK_URL", "url": "http://["}),
        "expect": {"error": "backends[0] 'url' must be an http or https URL with a host"},
    },
    "empty_name": {
        "answer": answer_with("other", {"name": " ", "kind": "smtp", "detail": "mail"}),
        "expect": {"error": "other[0] 'name' must be a text"},
    },
}


# The cases of the variable of a Postgres proxy (SPEC.md section 7.13). The home of a case has no
# .postgresql/root.crt and no .postgresql/root.crl. `environ` holds the other variables of the
# app, if the case has them. `app_query` is the query of the URL that the app gets.
DB_URL = "postgresql://shop@db.toy.test/shop"
DB_WHERE = "the database shop-db: the variable DATABASE_URL"
DATABASE_CASES: dict[str, dict] = {
    "prefer_by_default": {
        "value": DB_URL,
        "expect": {"sslmode": "prefer", "rootcert": None, "app_query": "sslmode=disable"},
    },
    "disable": {
        "value": DB_URL + "?sslmode=disable",
        "expect": {"sslmode": "disable", "rootcert": None, "app_query": "sslmode=disable"},
    },
    "require_keeps_the_other_parameters": {
        "value": DB_URL + "?sslmode=require&application_name=toy%20shop",
        "expect": {
            "sslmode": "require",
            "rootcert": None,
            "app_query": "application_name=toy%20shop&sslmode=disable",
        },
    },
    "verify_full_with_the_system_roots": {
        "value": DB_URL + "?sslrootcert=system&sslmode=verify-full",
        "expect": {
            "sslmode": "verify-full",
            "rootcert": "system",
            "app_query": "sslmode=disable",
        },
    },
    "system_roots_give_verify_full_by_default": {
        "value": DB_URL + "?sslrootcert=system",
        "expect": {"sslmode": "verify-full", "rootcert": "system", "app_query": "sslmode=disable"},
    },
    "system_roots_with_a_weaker_sslmode": {
        "value": DB_URL + "?sslmode=require&sslrootcert=system",
        "expect": {
            "error": f"{DB_WHERE} has sslmode=require with sslrootcert=system. libpq refuses "
            "this pair. Give sslmode=verify-full, or the file of the root certificate in "
            "sslrootcert."
        },
    },
    "pgsslmode_if_the_url_has_no_sslmode": {
        "value": DB_URL + "?application_name=toy+shop",
        "environ": {"PGSSLMODE": "require"},
        "expect": {
            "sslmode": "require",
            "rootcert": None,
            "app_query": "application_name=toy+shop&sslmode=disable",
        },
    },
    "the_url_wins_over_pgsslmode": {
        "value": DB_URL + "?sslmode=disable",
        "environ": {"PGSSLMODE": "verify-full"},
        "expect": {"sslmode": "disable", "rootcert": None, "app_query": "sslmode=disable"},
    },
    "pgsslrootcert_system_and_the_plain_app": {
        "value": DB_URL + "?sslmode=verify-full",
        "environ": {"PGSSLROOTCERT": "system"},
        "expect": {
            "error": f"{DB_WHERE}: the app has PGSSLROOTCERT=system, and libpq refuses it with "
            "sslmode=disable, which the app uses to the proxy. Remove PGSSLROOTCERT, and give "
            "its value in the URL."
        },
    },
    "pghostaddr_in_the_environment": {
        "value": DB_URL,
        "environ": {"PGHOSTADDR": "203.0.113.1"},
        "expect": {
            "error": f"{DB_WHERE}: the app has PGHOSTADDR, which gives libpq another address "
            "than the host of the URL. The app would connect past the proxy. Remove PGHOSTADDR "
            "for the test."
        },
    },
    "pgservice_in_the_environment": {
        "value": DB_URL,
        "environ": {"PGSERVICE": "toy-shop"},
        "expect": {
            "error": f"{DB_WHERE}: the app has PGSERVICE, which gives libpq another address "
            "than the host of the URL. The app would connect past the proxy. Remove PGSERVICE "
            "for the test."
        },
    },
    "empty_pghostaddr_and_pgservice": {
        "value": DB_URL,
        "environ": {"PGHOSTADDR": "", "PGSERVICE": ""},
        "expect": {"sslmode": "prefer", "rootcert": None, "app_query": "sslmode=disable"},
    },
    "pggssencmode_require": {
        "value": DB_URL,
        "environ": {"PGGSSENCMODE": "require"},
        "expect": {
            "error": f"{DB_WHERE} has gssencmode=require (or PGGSSENCMODE). The proxy speaks no "
            "GSSAPI encryption, so give gssencmode=disable or prefer for the test."
        },
    },
    "minimum_tls_above_the_maximum": {
        "value": DB_URL + "?ssl_min_protocol_version=TLSv1.3&ssl_max_protocol_version=TLSv1.2",
        "expect": {
            "error": f"{DB_WHERE} has ssl_min_protocol_version=TLSv1.3, which is above "
            "ssl_max_protocol_version=TLSv1.2"
        },
    },
    "no_tls_parameter_in_the_app_url": {
        "value": DB_URL + "?sslmode=require&sslnegotiation=direct&connect_timeout=5"
        "&ssl_min_protocol_version=TLSv1.3",
        "expect": {
            "sslmode": "require",
            "rootcert": None,
            "app_query": "connect_timeout=5&sslmode=disable",
        },
    },
    "relative_root_file": {
        "value": DB_URL + "?sslmode=verify-ca&sslrootcert=certs/root.crt",
        "expect": {
            "error": f"{DB_WHERE} has a relative sslrootcert path: certs/root.crt. Give an "
            "absolute path."
        },
    },
    "verify_ca_with_no_root_certificate": {
        "value": DB_URL + "?sslmode=verify-ca",
        "expect": {
            "error": f"{DB_WHERE} has sslmode=verify-ca and no root certificate. Give the file "
            "of the root certificate in sslrootcert, or sslrootcert=system."
        },
    },
    "root_file_that_does_not_exist": {
        "value": DB_URL + "?sslmode=verify-full&sslrootcert=/no/toy-shop/root.crt",
        "expect": {
            "error": f"{DB_WHERE} has an sslrootcert file that does not exist: "
            "/no/toy-shop/root.crt"
        },
    },
    "sslmode_that_libpq_does_not_have": {
        "value": DB_URL + "?sslmode=on",
        "expect": {"error": f"{DB_WHERE} has sslmode=on, which is not an sslmode of libpq"},
    },
}


def main() -> None:
    shutil.rmtree(CASES, ignore_errors=True)
    for name, (tap, relay, expect) in CASES_BY_NAME.items():
        d = CASES / name
        d.mkdir(parents=True)
        write(d / "tap.jsonl", tap)
        write(d / "relay.jsonl", relay)
        (d / "expect.json").write_text(json.dumps(expect, indent=1) + "\n")
        if name in SCRIPTS:
            file, text = SCRIPTS[name]
            (d / file).write_text(text, encoding="utf-8")
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
        write(d / "mcp.jsonl", case.get("mcp"))
        write(d / "database.jsonl", case.get("database"))
        write(d / "egress.jsonl", case.get("egress"))
        if "error" in case:
            text = json.dumps(case["error"], indent=1, ensure_ascii=False)
            (d / "expect_error.json").write_text(text + "\n")
            continue
        write(d / "expect_trace.jsonl", case["trace"])
        # A case with no trace points in its manifest has "trace_points": null.
        findings = dict(case["findings"])
        rest = {k: findings.pop(k) for k in ("trace_points", "counts", "findings") if k in findings}
        # A case with no egress.jsonl has "egress": null.
        findings = {**findings, "egress": findings.pop("egress", None)}
        findings = {**findings, "trace_points": rest.pop("trace_points", None), **rest}
        text = json.dumps(findings, indent=1, ensure_ascii=False)
        (d / "expect_findings.json").write_text(text + "\n")
    shutil.rmtree(OTLP, ignore_errors=True)
    for name, case in OTLP_CASES.items():
        write_otlp_case(OTLP / name, case)
    shutil.rmtree(SEAL, ignore_errors=True)
    for name, case in SEAL_CASES.items():
        write_seal_case(SEAL / name, case)
    shutil.rmtree(NOTES, ignore_errors=True)
    for name, case in NOTES_CASES.items():
        (NOTES / name).mkdir(parents=True)
        write(NOTES / name / "notes.jsonl", case["rows"])
        text = json.dumps(case["expect"], indent=1, ensure_ascii=False) + "\n"
        (NOTES / name / "expect.json").write_text(text, encoding="utf-8")
    shutil.rmtree(POLICY, ignore_errors=True)
    for name, case in POLICY_CASES.items():
        write_policy_case(POLICY / f"{name}.json", case)
    shutil.rmtree(GUARD, ignore_errors=True)
    for name, case in GUARD_CASES.items():
        write_policy_case(GUARD / f"{name}.json", case)
    shutil.rmtree(CONTROL, ignore_errors=True)
    CONTROL.mkdir()
    for name, case in CONTROL_CASES.items():
        text = json.dumps(case, indent=1, sort_keys=True) + "\n"
        (CONTROL / f"{name}.json").write_text(text, encoding="utf-8")
    shutil.rmtree(EVALUATION, ignore_errors=True)
    EVALUATION.mkdir()
    for name, case in EVALUATION_CASES.items():
        text = json.dumps(case, indent=1, sort_keys=True) + "\n"
        (EVALUATION / f"{name}.json").write_text(text, encoding="utf-8")
    shutil.rmtree(DISCOVERY, ignore_errors=True)
    DISCOVERY.mkdir()
    for name, case in DISCOVERY_CASES.items():
        text = json.dumps(case, indent=1, ensure_ascii=False) + "\n"
        (DISCOVERY / f"{name}.json").write_text(text, encoding="utf-8")
    shutil.rmtree(DATABASE, ignore_errors=True)
    DATABASE.mkdir()
    for name, case in DATABASE_CASES.items():
        text = json.dumps(case, indent=1, ensure_ascii=False) + "\n"
        (DATABASE / f"{name}.json").write_text(text, encoding="utf-8")
    print(
        f"{len(CASES_BY_NAME)} audit cases, {len(CONTRACT_CASES)} contract cases, "
        f"{len(TRACE_CASES)} trace cases, {len(SEAL_CASES)} seal cases, "
        f"{len(OTLP_CASES)} receiver cases, {len(POLICY_CASES)} policy cases, "
        f"{len(GUARD_CASES)} guard cases, {len(CONTROL_CASES)} control cases, "
        f"{len(EVALUATION_CASES)} evaluation cases, {len(NOTES_CASES)} notes cases, "
        f"{len(DISCOVERY_CASES)} discovery cases and {len(DATABASE_CASES)} database cases "
        "written"
    )


if __name__ == "__main__":
    main()

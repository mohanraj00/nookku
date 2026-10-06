"""Write the conformance cases. Each expectation here is written by hand from SPEC.md.

`cases/` holds the audit cases (SPEC.md section 3). `contract/` holds the stdio cases (sections 4.2
and 6): the requests that the relay posts, what a scripted agent does with each one, and the rows
and HTTP statuses that the tap must give.

Never fill an expectation by running the audit. CI runs this script and fails if the files change.

usage: python conformance/build.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import unicodedata
from pathlib import Path
from typing import Any

CASES = Path(__file__).parent / "cases"
CONTRACT = Path(__file__).parent / "contract"


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
    print(f"{len(CASES_BY_NAME)} audit cases and {len(CONTRACT_CASES)} contract cases written")


if __name__ == "__main__":
    main()

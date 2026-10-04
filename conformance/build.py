"""Write the conformance cases. Each expectation here is written by hand from SPEC.md.

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


def sha(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode()).hexdigest()


def ex(text: str, reply: str | None, status: int | None = 200, error: str | None = None) -> dict:
    row: dict[str, Any] = {
        "v": "0.1",
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


def turn(said: str, shown: str | None) -> dict:
    return {
        "v": "0.1",
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
        [{**CLEAN_RELAY[0], "v": "0.2"}, *CLEAN_RELAY[1:]],
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
    print(f"{len(CASES_BY_NAME)} cases written")


if __name__ == "__main__":
    main()

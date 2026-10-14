"""The notes of the tester (#352): a thumbs up, a thumbs down and a comment on each turn of a test.

The chat page server writes each note as a `note` row to `notes.jsonl` in the test folder (SPEC.md
section 2.3). It does not change `relay.jsonl` or `tap.jsonl`. The seal covers `notes.jsonl`
(section 7.4), so the page server writes a note only to a running test that is not closed. It holds
the send lock from its checks to its row, and the end of a test holds the same lock from the tap
shutdown to the seal. Thus no note can go into a sealed folder.

A note is the opinion of the tester, not a finding. The evaluation reads the notes and cites them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nookku import state
from nookku.record import RecordError, Writer, lone_surrogate, note_problem, read_rows, turns

NOTES = "notes.jsonl"
# The routes of the page server, after the token.
ADD_ROUTE = "api/note"
VIEW_ROUTE = "api/notes"
# A comment is a short opinion. This limit counts code points.
MAX_COMMENT = 10_000

NO_TEST = "nookku: no test runs, so the page writes no note."
CLOSED = "nookku: the test ended, so the page writes no note. The record of the test is sealed."
NO_TURN = "nookku: the test has no turn {turn}, so the page writes no note."
BAD_RELAY = "nookku: the page cannot read the relay record, so it writes no note: {error}"


def bad_body(data: Any) -> str | None:
    """The reason to refuse the body of a note with 400, or None. The body is a JSON object with
    `turn`, `rating` and `comment`, with the rule of a note row (`record.note_problem`)."""
    if not isinstance(data, dict):
        return "the body must be a JSON object"
    comment = data.get("comment")
    problem = note_problem(data.get("turn"), data.get("rating"), comment)
    if problem:
        return problem
    if comment is not None and len(comment) > MAX_COMMENT:
        return f"the comment has more than {MAX_COMMENT} characters"
    found = lone_surrogate(comment) if comment is not None else None
    if found:
        return f"the comment has {found}"
    return None


def add(root: Path, turn: int, rating: str | None, comment: str | None) -> dict[str, Any]:
    """Write one note to the running test. Return what the page shows.

    Fail closed: the page writes a note only to a running test that did not end, and only for a
    turn that the relay record has."""
    if state.current(root) is None:
        return {"saved": False, "error": NO_TEST}
    # The end of the test holds this lock from the tap shutdown to the seal.
    sends = state.lock_sends(root)
    try:
        return _add_locked(root, turn, rating, comment)
    finally:
        os.close(sends)


def _add_locked(root: Path, turn: int, rating: str | None, comment: str | None) -> dict[str, Any]:
    cur = state.current(root)
    if cur is None:
        return {"saved": False, "error": NO_TEST}
    folder = Path(cur["dir"])
    # Here, because the page module imports this module. A note uses the closed rule of a send.
    from nookku import page

    if page._closed(folder):
        return {"saved": False, "error": CLOSED}
    try:
        count = len(turns(folder / "relay.jsonl", missing_ok=True))
    except RecordError as e:
        return {"saved": False, "error": BAD_RELAY.format(error=e)}
    if turn > count:
        return {"saved": False, "error": NO_TURN.format(turn=turn)}
    row = {"type": "note", "turn": turn, "rating": rating, "comment": comment}
    Writer(folder / NOTES).append(row)
    return {"saved": True, "error": None}


def view(root: Path) -> dict[str, Any]:
    """The notes of the test that the page shows: the running test, else the latest test. For
    each turn, the page shows the last note."""
    cur = state.current(root)
    folder = Path(cur["dir"]) if cur else state.latest_test(root)
    if folder is None:
        return {"test": None, "running": False, "notes": [], "error": None}
    out: dict[str, Any] = {"test": folder.name, "running": cur is not None, "error": None}
    try:
        rows = read_rows("notes", folder / NOTES, missing_ok=True)
    except RecordError as e:
        return {**out, "notes": [], "error": f"nookku: {e}"}
    out["notes"] = [
        {"turn": r["turn"], "rating": r["rating"], "comment": r["comment"], "ts": r["ts"]}
        for _, r in rows
    ]
    return out

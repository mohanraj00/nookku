"""The agent contract of SPEC.md section 6: one JSON line in, one JSON line out."""

from __future__ import annotations

import json
from typing import Any

from verbatim_relay.adapters import History

VERSION = 1


class ContractError(ValueError):
    """A line is not a valid contract input or output."""


def _no_constant(name: str) -> Any:
    # json.loads accepts NaN, Infinity and -Infinity. They are not JSON. JSON.parse refuses them.
    raise ContractError(f"{name} is not a JSON value")


def request(rid: str, session: str, message: str, history: History) -> bytes:
    """The input line for one message, without its line end."""
    body = {
        "v": VERSION,
        "id": rid,
        "session": session,
        "message": message,
        "history": [{"message": m, "reply": r} for m, r in history],
    }
    return json.dumps(body, ensure_ascii=False).encode()


def _object(line: bytes, what: str) -> dict[str, Any]:
    if b"\n" in line or b"\r" in line:
        raise ContractError(f"the {what} has a raw line end")
    try:
        data = json.loads(line.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ContractError(f"the {what} is not UTF-8 JSON") from None
    if not isinstance(data, dict):
        raise ContractError(f"the {what} is not a JSON object")
    if data.get("v") != VERSION or isinstance(data.get("v"), bool):
        raise ContractError(f"the {what} is not contract version {VERSION}")
    if not isinstance(data.get("id"), str):
        raise ContractError(f"the {what} has no string 'id'")
    return data


def parse_request(body: bytes) -> tuple[str, str, History]:
    """Check an input line. Return (id, message, history)."""
    data = _object(body, "request")
    if not isinstance(data.get("session"), str) or not isinstance(data.get("message"), str):
        raise ContractError("the request needs a string 'session' and a string 'message'")
    turns = data.get("history")
    if not isinstance(turns, list):
        raise ContractError("the request 'history' is not a list")
    history: History = []
    for t in turns:
        if not (isinstance(t, dict) and isinstance(t.get("message"), str)):
            raise ContractError("each history turn needs a string 'message' and 'reply'")
        if not isinstance(t.get("reply"), str):
            raise ContractError("each history turn needs a string 'message' and 'reply'")
        history.append((t["message"], t["reply"]))
    return data["id"], data["message"], history


def parse_reply(line: bytes, rid: str) -> tuple[str | None, str | None]:
    """Check an output line for request `rid`. Return (reply, None) or (None, error)."""
    data = _object(line, "reply")
    if data["id"] != rid:
        raise ContractError(f"the reply id {data['id']!r} is not the request id {rid!r}")
    # A line with both keys is not valid, also if one of them is null (SPEC.md section 6).
    if ("reply" in data) == ("error" in data):
        raise ContractError("the reply must have exactly one of 'reply' and 'error'")
    reply, error = data.get("reply"), data.get("error")
    if not isinstance(reply if "reply" in data else error, str):
        raise ContractError("'reply' or 'error' is not a string")
    return reply, error

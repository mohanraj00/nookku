"""A helper for an entry in Python: speak the agent contract (SPEC.md section 6) for a function.

from verbatim_relay.agent import serve

def reply(message: str, history: list[tuple[str, str]]) -> str:
    return shop.answer(message)

serve(reply)
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable

from verbatim_relay import contract
from verbatim_relay.adapters import History


def _line(rid: str, **fields: str) -> bytes:
    return json.dumps({"v": contract.VERSION, "id": rid, **fields}, ensure_ascii=False).encode()


def serve(reply: Callable[[str, History], str]) -> None:
    """Answer each input line on stdin with one output line, until stdin closes.

    Stdout carries only contract lines. All other output of the process, from print() or from a
    child process, goes to stderr.
    """
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    sys.stdout.flush()
    os.dup2(2, 1)
    for raw in sys.stdin.buffer:
        line = raw.removesuffix(b"\n").removesuffix(b"\r")
        try:
            rid, message, history = contract.parse_request(line)
        except contract.ContractError as e:
            out.write(_line("", error=f"verbatim-relay agent: {e}") + b"\n")
            continue
        try:
            text = reply(message, history)
            if not isinstance(text, str):
                raise TypeError(f"reply() returned {type(text).__name__}, not str")
            result = _line(rid, reply=text)
        except Exception as e:  # the error goes back to the tester as an error turn
            result = _line(rid, error=f"{type(e).__name__}: {e}")
        out.write(result + b"\n")

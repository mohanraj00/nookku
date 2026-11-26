"""The JSON rule of `reply_not_from_model` (SPEC.md section 8.6): the JSON value of a text that
can hold a JSON object in a code fence."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


class Exact(float):
    """A float of a JSON number that keeps the text of the number (SPEC.md section 7.18). Each
    other check uses it as the float, and json.dumps writes it as the float. A Bind compares
    its `text`, so no digit is lost."""

    text: str

    def __new__(cls, text: str) -> Exact:
        value = super().__new__(cls, text)
        value.text = text
        return value


def loads(text: str) -> Any:
    """The JSON value of a text of a record, with an Exact for each number with a point or an
    exponent."""
    return json.loads(text, parse_float=Exact)


def structured(text: str, exact: bool = False) -> Any:
    """The JSON value of a model text: the full text, or else the part from its first `{` to its
    last `}`, for a JSON object in a code fence. None if neither part is JSON. If `exact` is
    True, a JSON number with a point or an exponent is a Decimal, so no digit is lost. A number
    out of the range of Decimal makes the part not JSON."""
    parts = [text]
    if "{" in text:
        parts.append(text[text.index("{") : text.rindex("}") + 1] if "}" in text else "")
    for part in parts:
        try:
            return json.loads(part, parse_float=Decimal) if exact else json.loads(part)
        except (ValueError, RecursionError, ArithmeticError):
            continue
    return None

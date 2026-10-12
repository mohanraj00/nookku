import json
import re

import pytest

from nookku import script

MESSAGES = ["Is the teapot in stock?", "Return order #4471, please.  ", "Thanks.\nBye €"]


def test_a_jsonl_script_gives_each_said_text() -> None:
    data = "".join(json.dumps({"said": m}) + "\n" for m in MESSAGES).encode()
    assert script.parse(data) == (MESSAGES, "jsonl")


def test_a_json_array_gives_each_string() -> None:
    data = ("  \n" + json.dumps(MESSAGES, ensure_ascii=False)).encode()
    assert script.parse(data) == (MESSAGES, "json")


@pytest.mark.parametrize(
    "data, error",
    [
        (b"", "no message"),
        (b"[]", "no message"),
        (b'{"said": "Hi"}\n\n', "line 2: not a JSON object"),
        (b'{"said": "Hi", "reply": "Hello"}\n', 'must be {"said": "..."}'),
        (b'["Hi"]\n{"said": "Hi"}\n', "not a JSON array"),
        (b'{"said": 7}\n', "line 1: a message must be a string"),
        (b'["Hi", null]', "item 2: a message must be a string"),
        (b'{"said": "\\ud83d"}\n', "line 1: the message has a lone surrogate U+D83D"),
        (b"\xff", "not UTF-8"),
    ],
)
def test_a_script_that_breaks_a_rule_is_refused(data: bytes, error: str) -> None:
    with pytest.raises(script.ScriptError, match=re.escape(error)):
        script.parse(data)

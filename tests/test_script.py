import json
import re
from pathlib import Path

import pytest

from nookku import audit, script

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


def test_the_audit_names_a_script_that_cannot_be_read_as_missing(tmp_path: Path) -> None:
    tap, relay = tmp_path / "tap.jsonl", tmp_path / "relay.jsonl"
    tap.write_text("")
    relay.write_text("")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    for path, kind in [
        (tmp_path / "none.jsonl", "record_missing"),
        (tmp_path, "record_missing"),
        (bad, "record_invalid"),
    ]:
        report = audit.audit(tap, relay, path)
        assert [(e["class"], e["record"]) for e in report.errors] == [(kind, "script")]

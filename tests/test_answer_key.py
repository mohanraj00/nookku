"""The answer key of a test (SPEC.md section 7.17)."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from nookku import answer_key, trace
from nookku.config import ConfigError

KEY = {
    "source": "the stock list",
    "version": "2",
    "answers": [{"question": "How many mugs?", "answer": 12}],
}
SECTION = """# Toy shop

## Answer key

| File | Field | Match | Tolerance |
|---|---|---|---|
{row}
"""


def _root(tmp_path: Path, key: object = KEY) -> Path:
    (tmp_path / "keys").mkdir()
    data = key if isinstance(key, bytes) else json.dumps(key).encode()
    (tmp_path / "keys" / "stock.json").write_bytes(data)
    return tmp_path


def _read(root: Path, row: str) -> tuple[dict | None, bytes]:
    return answer_key.read(root, [("APP_SPEC.md", SECTION.format(row=row))])


def test_the_section_gives_the_manifest_key_and_the_bytes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    record, data = _read(root, "| `keys/stock.json` | `count` | Number | 0.5 |")
    assert data == (root / "keys" / "stock.json").read_bytes()
    assert record == {
        "file": "keys/stock.json",
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": "the stock list",
        "version": "2",
        "field": "count",
        "match": "number",
        "tolerance": "0.5",
    }


def test_a_spec_with_no_section_has_no_key(tmp_path: Path) -> None:
    assert answer_key.read(tmp_path, [("APP_SPEC.md", "# Toy shop\n")]) == (None, b"")


def test_the_field_and_the_tolerance_columns_are_optional(tmp_path: Path) -> None:
    root = _root(tmp_path, {**KEY, "answers": [{"question": "Hi?", "answer": "Hello."}]})
    text = "## Answer key\n\n| File | Match |\n|---|---|\n| keys/stock.json | exact |\n"
    record, _ = answer_key.read(root, [("APP_SPEC.md", text)])
    assert record is not None
    assert (record["field"], record["match"], record["tolerance"]) == ("", "exact", None)


@pytest.mark.parametrize(
    ("row", "error"),
    [
        ("| | count | number | 0 |", "APP_SPEC.md line 7: the Answer key row has no File"),
        ("| keys/stock.json | a..b | number | 0 |", "the Field must be empty or a dot path"),
        ("| keys/stock.json | count | close | 0 |", "the Match must be exact or number"),
        ("| keys/stock.json | count | number | |", "the match number needs a Tolerance"),
        ("| keys/stock.json | count | number | -1 |", "the match number needs a Tolerance"),
        ("| keys/stock.json | count | exact | 0 |", "the match exact takes no Tolerance"),
        ("| keys/none.json | count | number | 0 |", "the answer key 'keys/none.json' is not"),
        ("| ../stock.json | count | number | 0 |", "is not in the project folder"),
        ("| keys/stock.json | count |", "the row has 2 cells, and the header has 4"),
        (
            "| keys/stock.json | count | number | 0 |\n| keys/stock.json | n | number | 0 |",
            "APP_SPEC.md line 8: the app spec has a second Answer key row",
        ),
    ],
)
def test_a_section_that_is_not_valid_stops_the_start(tmp_path: Path, row: str, error: str) -> None:
    root = _root(tmp_path)
    with pytest.raises(ConfigError) as e:
        _read(root, row)
    assert error.lower() in str(e.value).lower()


@pytest.mark.parametrize(
    ("key", "match", "error"),
    [
        (b"\xff", "number", "not UTF-8 JSON"),
        (b"[1]", "number", "not a JSON object"),
        ({**KEY, "source": " "}, "number", "no source string"),
        ({**KEY, "version": 2}, "number", "no version string"),
        ({**KEY, "answers": []}, "number", "no answers list"),
        ({**KEY, "answers": [{"answer": 1}]}, "number", "answer 1 has no question string"),
        ({**KEY, "answers": KEY["answers"] * 2}, "number", "answer 2 has the question of an"),
        (KEY, "exact", "answer 1: the match exact needs a string answer"),
        ({**KEY, "answers": [{"question": "Q", "answer": "12"}]}, "number", "a number answer"),
        ({**KEY, "answers": [{"question": "Q", "answer": True}]}, "number", "a number answer"),
        (
            b'{"source": "s", "version": "1", "answers": [{"question": "Q", "answer": NaN}]}',
            "number",
            "NaN is not a number of JSON",
        ),
    ],
)
def test_a_key_file_that_is_not_valid_stops_the_start(
    tmp_path: Path, key: object, match: str, error: str
) -> None:
    data = key if isinstance(key, bytes) else json.dumps(key).encode()
    with pytest.raises(ValueError) as e:
        answer_key.parse(data, match)
    assert error in str(e.value)
    tolerance = " 0 |" if match == "number" else " |"
    with pytest.raises(
        ConfigError, match=re.escape("the answer key 'keys/stock.json' is not valid")
    ):
        _read(_root(tmp_path, key), f"| keys/stock.json | count | {match} |{tolerance}")


@pytest.mark.parametrize(
    ("value", "answer", "match", "tolerance", "ok"),
    [
        ("Hello.", "Hello.", "exact", None, True),
        ("Hello. ", "Hello.", "exact", None, False),
        (12, "12", "exact", None, False),
        (12, 12, "number", "0", True),
        (12.0, 12, "number", "0", True),
        (" 12 ", 12, "number", "0", True),
        ("12 mugs", 12, "number", "5", False),
        (12.5, 12, "number", "0.5", True),
        (12.51, 12, "number", "0.5", False),
        (10.2, Decimal("10.1"), "number", "0.1", True),
        (True, 1, "number", "0", False),
        (None, 1, "number", "9", False),
        ([12], 12, "number", "0", False),
        (float("nan"), 12, "number", "0", False),
        (float("inf"), 12, "number", "0", False),
    ],
)
def test_the_match_rules(
    value: object, answer: object, match: str, tolerance: str | None, ok: bool
) -> None:
    limit = None if tolerance is None else Decimal(tolerance)
    assert answer_key.matches(value, answer, match, limit) is ok


def _folder(tmp_path: Path, record: dict, data: bytes) -> Path:
    (tmp_path / answer_key.COPY).write_bytes(data)
    return tmp_path


def test_a_copy_that_is_not_the_sealed_key_cannot_be_used(tmp_path: Path) -> None:
    data = json.dumps(KEY).encode()
    record = {
        "file": "keys/stock.json",
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": "the stock list",
        "version": "2",
        "field": "count",
        "match": "number",
        "tolerance": "0",
    }
    folder = _folder(tmp_path, record, data)
    assert answer_key.load(folder, record)["answers"] == {"How many mugs?": 12}
    manifest = {"answer_key": record}
    (folder / answer_key.COPY).write_bytes(data + b" ")
    reason = "the SHA-256 of answer_key.json is not the SHA-256 of the manifest"
    assert trace.answer_key_of(folder, manifest) == reason
    (folder / answer_key.COPY).unlink()
    assert trace.answer_key_of(folder, manifest) == "the test folder has no file answer_key.json"
    bad = "the key answer_key of manifest.json is not valid"
    wrongs = (
        {**record, "match": "close"},
        {**record, "tolerance": None},
        {**record, "tolerance": 1},
    )
    for wrong in (*wrongs, [], "x"):
        assert trace.answer_key_of(folder, {"answer_key": wrong}) == bad
    assert trace.answer_key_of(folder, {}) is None
    found = trace.answers_not_in_key([], bad)
    assert found == [
        {
            "check": "answer_key_missing",
            "turn": None,
            "detail": f"the answer key cannot be used: {bad}",
        }
    ]


def test_a_question_asked_2_times_is_checked_2_times() -> None:
    key = {"field": "", "match": "exact", "tolerance": None, "answers": {"Hi?": "Hello."}}
    exchanges = [
        {"input": "Hi?", "reply": "Hello."},
        {"input": "Other?", "reply": "No."},
        {"input": "Hi?", "reply": "Hi."},
        {"input": "Hi?", "reply": None, "status": None},
    ]
    found = trace.answers_not_in_key(exchanges, key)
    assert [(f["check"], f["turn"]) for f in found] == [
        ("answer_key_mismatch", 3),
        ("answer_key_mismatch", 4),
    ]
    assert found[1]["detail"] == '"Hi?": the key gives "Hello.", and the reply gives no value'


def test_a_long_value_is_cut_in_the_detail() -> None:
    text = answer_key.shown("x" * 500)
    assert len(text) == answer_key.SHOWN + 3 and text.endswith("...")


@pytest.mark.parametrize(
    ("reply", "answer", "ok"),
    [
        ('{"count": 100000000000000000001.0}', 100000000000000000000, False),
        ('{"count": 100000000000000000000.0}', 100000000000000000000, True),
        ('{"count": 0.1234567890123456789}', Decimal("0.1234567890123456789"), True),
        ('{"count": 0.1234567890123456789}', Decimal("0.12345678901234568"), False),
    ],
)
def test_a_number_field_of_a_reply_keeps_each_digit(reply: str, answer: object, ok: bool) -> None:
    key = {"field": "count", "match": "number", "tolerance": Decimal(0), "answers": {"Q?": answer}}
    found = trace.answers_not_in_key([{"input": "Q?", "reply": reply}], key)
    assert (found == []) is ok

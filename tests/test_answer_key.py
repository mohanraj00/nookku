"""The answer key of a test (SPEC.md section 7.17)."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from nookku import answer_key, bridge, seal, trace, verdict
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
        answer_key.parse(data, match, "0" if match == "number" else None)
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
        (Decimal("1.00000000000000000000000000001"), 0, "number", "1", False),
        (Decimal("1E+40"), Decimal("1E+40"), "number", "0", True),
        (Decimal("1E+200000"), Decimal("1E+200000"), "number", "0", True),
        (Decimal("1E+200000"), 0, "number", "1", False),
        (Decimal("1E-1000027"), 0, "number", "0", False),
        (Decimal("2E-1000027"), Decimal("1E-1000027"), "number", "0", False),
        (Decimal("2E-1000027"), Decimal("1E-1000027"), "number", "1E-1000027", True),
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
    assert answer_key.load(folder, record)["answers"] == {
        "How many mugs?": {"answer": 12, "match": "number", "tolerance": Decimal(0)}
    }
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
    key = {
        "field": "",
        "answers": {"Hi?": {"answer": "Hello.", "match": "exact", "tolerance": None}},
    }
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
    # The trace records each checked turn, a match and a mismatch (#548).
    rows = trace.answer_results(exchanges, key)
    assert rows is not None
    assert [(r["turn"], r["result"]) for r in rows] == [
        (1, "match"),
        (3, "mismatch"),
        (4, "mismatch"),
    ]
    assert rows[0] == {
        "turn": 1,
        "question": "Hi?",
        "match": "exact",
        "tolerance": None,
        "answer": '"Hello."',
        "value": '"Hello."',
        "result": "match",
    }
    assert rows[2]["value"] is None
    assert trace.answer_results(exchanges, None) is None
    assert trace.answer_results(exchanges, "the key cannot be used") is None


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
        ('{"count": {"nested": 1.5}}', 1, False),
        ('{"count": 1e9999999999999999999}', 1, False),
    ],
)
def test_a_number_field_of_a_reply_keeps_each_digit(reply: str, answer: object, ok: bool) -> None:
    rule = {"answer": answer, "match": "number", "tolerance": Decimal(0)}
    key = {"field": "count", "answers": {"Q?": rule}}
    found = trace.answers_not_in_key([{"input": "Q?", "reply": reply}], key)
    assert (found == []) is ok
    assert all(f["check"] == "answer_key_mismatch" for f in found)


def test_the_copy_replaces_a_file_or_a_symlink_of_the_entry(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("not the key")
    folder = tmp_path / "t"
    folder.mkdir()
    (folder / answer_key.COPY).symlink_to(target)
    answer_key.place(folder, b"key")
    assert not (folder / answer_key.COPY).is_symlink()
    assert (folder / answer_key.COPY).read_bytes() == b"key"
    assert target.read_text() == "not the key"
    answer_key.place(folder, b"new")
    assert (folder / answer_key.COPY).read_bytes() == b"new"


def test_a_stopped_test_gets_the_copy_only_from_the_sealed_key(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    root = _root(tmp_path / "p")
    data = (root / "keys" / "stock.json").read_bytes()
    record = {"file": "keys/stock.json", "sha256": hashlib.sha256(data).hexdigest()}
    folder = tmp_path / "t"
    folder.mkdir()
    assert answer_key.place_from_project(root, folder, record) is None
    assert (folder / answer_key.COPY).read_bytes() == data
    (folder / answer_key.COPY).unlink()
    (root / "keys" / "stock.json").write_bytes(data + b" ")
    reason = answer_key.place_from_project(root, folder, record)
    assert reason == "the SHA-256 of the key file is not the SHA-256 of the manifest"
    assert not (folder / answer_key.COPY).exists()
    assert answer_key.place_from_project(root, folder, []) is not None


# An answer of the key file can have its own rule (#548, SPEC.md section 7.17).
def test_an_answer_can_have_its_own_rule() -> None:
    key = {
        "source": "s",
        "version": "1",
        "answers": [
            {"question": "A?", "answer": 12},
            {"question": "B?", "answer": 4, "match": "number", "tolerance": "0"},
            {"question": "C?", "answer": "none", "match": "exact"},
        ],
    }
    answers = answer_key.parse(json.dumps(key).encode(), "number", "0.5")["answers"]
    assert answers == {
        "A?": {"answer": 12, "match": "number", "tolerance": Decimal("0.5")},
        "B?": {"answer": 4, "match": "number", "tolerance": Decimal(0)},
        "C?": {"answer": "none", "match": "exact", "tolerance": None},
    }
    exchanges = [
        {"input": "A?", "reply": '{"count": 12.4}'},
        {"input": "B?", "reply": '{"count": 4.4}'},
        {"input": "C?", "reply": '{"count": "none"}'},
    ]
    found = trace.answers_not_in_key(exchanges, {"field": "count", "answers": answers})
    assert [(f["check"], f["turn"]) for f in found] == [("answer_key_mismatch", 2)]


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ({"answer": 1, "tolerance": "0"}, "answer 1 has a tolerance and no match"),
        ({"answer": 1, "match": "near"}, "answer 1: the match must be exact or number"),
        ({"answer": 1, "match": None}, "answer 1: the match must be exact or number"),
        ({"answer": "a", "match": "exact", "tolerance": "0"}, "exact takes no tolerance"),
        ({"answer": 1, "match": "number"}, "the match number needs a tolerance string"),
        ({"answer": 1, "match": "number", "tolerance": 0.5}, "needs a tolerance string"),
        ({"answer": 1, "match": "number", "tolerance": "-1"}, "needs a tolerance string"),
        ({"answer": 1, "match": "exact"}, "the match exact needs a string answer"),
        ({"answer": "1", "match": "number", "tolerance": "0"}, "needs a number answer"),
    ],
)
def test_a_rule_of_an_answer_that_is_not_valid_stops_the_start(answer: dict, error: str) -> None:
    key = {"source": "s", "version": "1", "answers": [{"question": "Q?", **answer}]}
    with pytest.raises(ValueError) as e:
        answer_key.parse(json.dumps(key).encode(), "number", "0.5")
    assert error in str(e.value)


# The adjudication record (#548, SPEC.md section 7.17).
ROW = {
    "v": 1,
    "turn": 2,
    "question": "How many mugs?",
    "outcome": "key_wrong",
    "reason": "The stock list is old.",
    "author": "Asha",
    "ts": 1794000000.5,
}


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        (ROW, None),
        ({**ROW, "ts": 0}, None),
        ([ROW], "it is not a JSON object"),
        ({**ROW, "note": "x"}, "its keys are not author, outcome, question, reason, ts, turn, v"),
        ({k: v for k, v in ROW.items() if k != "author"}, "its keys are not"),
        ({**ROW, "v": 2}, "its v is not 1"),
        ({**ROW, "v": True}, "its v is not 1"),
        ({**ROW, "turn": 0}, "its turn is not a whole number from 1 to 999999999"),
        ({**ROW, "turn": 1.0}, "its turn is not a whole number"),
        ({**ROW, "turn": True}, "its turn is not a whole number"),
        ({**ROW, "question": ""}, "it has no question string"),
        ({**ROW, "question": "\ud83d"}, "it has no question string"),
        ({**ROW, "outcome": "accepted"}, "its outcome is not agent_wrong, key_wrong, both_"),
        ({**ROW, "outcome": ["key_wrong"]}, "its outcome is not"),
        ({**ROW, "reason": " \n"}, "it has no reason text"),
        ({**ROW, "reason": "x" * 10_001}, "the reason has more than 10000 code points"),
        ({**ROW, "reason": "\ud83d"}, "the reason has a lone surrogate U+D83D"),
        ({**ROW, "author": ""}, "it has no author text"),
        ({**ROW, "author": None}, "it has no author text"),
        ({**ROW, "author": "x" * 201}, "the author has more than 200 code points"),
        ({**ROW, "author": "Asha\nturn 3"}, "the author has a control character"),
        ({**ROW, "ts": -1}, "its ts is not a Unix time"),
        ({**ROW, "ts": "now"}, "its ts is not a Unix time"),
        ({**ROW, "ts": True}, "its ts is not a Unix time"),
        ({**ROW, "ts": float("inf")}, "its ts is not a Unix time"),
    ],
)
def test_the_rule_of_an_adjudication_row(row: object, problem: str | None) -> None:
    found = answer_key.adjudication_problem(row)
    assert found is None if problem is None else found is not None and problem in found


def _lines(*rows: object) -> bytes:
    return "".join(json.dumps(r) + "\n" for r in rows).encode()


def test_the_reader_of_the_adjudications_never_skips_a_line() -> None:
    assert answer_key.read_adjudications(b"") == ([], None)
    assert answer_key.read_adjudications(_lines(ROW, ROW)) == ([ROW, ROW], None)
    assert answer_key.read_adjudications(_lines(ROW)[:-1]) == ([ROW], None)
    bad = {**ROW, "outcome": "accepted"}
    for data, problem in (
        (b"\xff", "adjudications.jsonl is not UTF-8"),
        (_lines(ROW) + b"\n", "adjudications.jsonl line 2: it is not JSON"),
        (_lines(ROW) + b"{\n", "adjudications.jsonl line 2: it is not JSON"),
        (_lines(ROW).replace(b"1794000000.5", b"NaN"), "adjudications.jsonl line 1: it is not"),
        (b"[" * 100_000, "adjudications.jsonl line 1: it is not JSON"),
        (_lines(ROW, bad, ROW), "adjudications.jsonl line 2: its outcome is not"),
    ):
        rows, found = answer_key.read_adjudications(data)
        assert rows == [] and found is not None and found.startswith(problem), data[:40]


def _answers(*results: str) -> dict:
    rows = [
        {"turn": n, "question": f"Q{n}?", "result": result} for n, result in enumerate(results, 1)
    ]
    return {"answers": rows}


def _decision(turn: int, outcome: str) -> dict:
    return {**ROW, "turn": turn, "question": f"Q{turn}?", "outcome": outcome}


def test_the_tally_counts_the_last_row_of_each_turn() -> None:
    report = _answers("match", "mismatch", "mismatch", "mismatch")
    data = _lines(
        _decision(2, "key_wrong"),
        _decision(3, "key_wrong"),
        _decision(3, "agent_wrong"),
        _decision(2, "both_acceptable"),
    )
    assert answer_key.tally(3, data, report) == (
        {
            "mismatches": 3,
            "open": 1,
            "agent_wrong": 1,
            "key_wrong": 0,
            "both_acceptable": 1,
            "counted": 2,
        },
        [],
    )


@pytest.mark.parametrize(
    ("count", "data", "report", "problem"),
    [
        (1, _lines(_decision(1, "key_wrong")), _answers("match", "mismatch"), "turn 1 has no"),
        (
            1,
            _lines({**_decision(2, "key_wrong"), "question": "Q1?"}),
            _answers("match", "mismatch"),
            "adjudications.jsonl line 1: the question is not the question of turn 2",
        ),
        (1, b"{}\n", _answers("mismatch"), "adjudications.jsonl line 1: its keys are not"),
        (2, _lines(_decision(1, "key_wrong")), _answers("mismatch"), "do not agree with the count"),
        (None, _lines(_decision(1, "key_wrong")), _answers("mismatch"), "do not agree with the"),
        (1, _lines(_decision(1, "key_wrong")), {}, "findings.json has no valid answers list"),
        (1, _lines(_decision(1, "key_wrong")), None, "findings.json has no valid answers list"),
        (
            1,
            _lines(_decision(1, "key_wrong")),
            {"answers": [{"turn": 1, "question": "Q1?", "result": "near"}]},
            "findings.json has no valid answers list",
        ),
        (
            2,
            _lines(_decision(1, "key_wrong")),
            {"answers": _answers("mismatch")["answers"] * 2},
            "findings.json has no valid answers list",
        ),
    ],
)
def test_a_problem_of_the_adjudications_leaves_each_mismatch_open(
    count: int | None, data: bytes, report: object, problem: str
) -> None:
    tally, problems = answer_key.tally(count, data, report)
    assert len(problems) == 1 and problem in problems[0]
    assert tally == {
        "mismatches": count,
        "open": count,
        "agent_wrong": 0,
        "key_wrong": 0,
        "both_acceptable": 0,
        "counted": count,
    }


def test_a_test_with_no_row_has_each_mismatch_open() -> None:
    tally, problems = answer_key.tally(2, b"", {})
    assert problems == [] and tally["open"] == 2 and tally["counted"] == 2


def test_a_new_row_is_added_with_no_symlink(tmp_path: Path) -> None:
    row = answer_key.adjudication(2, "How many mugs?", "key_wrong", "The list is old.", "Asha")
    assert answer_key.adjudication_problem(row) is None
    answer_key.add_adjudication(tmp_path, row)
    answer_key.add_adjudication(tmp_path, {**row, "outcome": "agent_wrong"})
    data = (tmp_path / answer_key.ADJUDICATIONS).read_bytes()
    rows, problem = answer_key.read_adjudications(data)
    assert problem is None and [r["outcome"] for r in rows] == ["key_wrong", "agent_wrong"]
    with pytest.raises(ValueError, match="its outcome is not"):
        answer_key.adjudication(2, "How many mugs?", "fine", "x", "Asha")
    target = tmp_path / "target.txt"
    target.write_text("")
    folder = tmp_path / "t"
    folder.mkdir()
    (folder / answer_key.ADJUDICATIONS).symlink_to(target)
    with pytest.raises(OSError):
        answer_key.add_adjudication(folder, row)
    assert target.read_text() == ""


# The start text names an answer key that the policy does not protect (#577).
def test_the_start_text_names_a_key_that_the_harness_model_can_read(tmp_path: Path) -> None:
    root = _root(tmp_path / "shop" if (tmp_path / "shop").mkdir() is None else tmp_path)
    folder = tmp_path / "t1"
    folder.mkdir()

    def text(paths: object, file: str = "keys/stock.json") -> str:
        manifest = {
            "root": str(root),
            "answer_key": {"file": file},
            "policy": {"answer_keys": paths},
        }
        (folder / "manifest.json").write_text(json.dumps(manifest))
        return bridge.key_text(folder)

    line = (
        "The harness model can read the answer key keys/stock.json. To deny it, a person runs: "
        "nookku policy set answer_keys keys/stock.json"
    )
    assert text([]) == line
    assert text(["keys/other.json"]) == line
    assert text(["keys/stock.json"]) == ""
    assert text(["keys"]) == ""
    # The path of the app spec can have another form than the path of the policy key.
    assert text(["keys/stock.json"], "./keys/../keys/stock.json") == ""
    assert text([], "./keys/../keys/stock.json") == line
    (folder / "manifest.json").write_text(json.dumps({"root": str(root), "answer_key": None}))
    assert bridge.key_text(folder) == ""
    (folder / "manifest.json").write_text("[")
    assert bridge.key_text(folder) == ""


def test_a_new_row_starts_on_its_own_line_after_a_last_line_with_no_line_feed(
    tmp_path: Path,
) -> None:
    first = answer_key.adjudication(1, "How many mugs?", "key_wrong", "The list is old.", "ann")
    (tmp_path / answer_key.ADJUDICATIONS).write_bytes(json.dumps(first).encode())
    second = answer_key.adjudication(1, "How many mugs?", "agent_wrong", "I read it again.", "ann")
    answer_key.add_adjudication(tmp_path, second)
    data = (tmp_path / answer_key.ADJUDICATIONS).read_bytes()
    assert data.count(b"\n") == 2
    rows, problem = answer_key.read_adjudications(data)
    assert problem is None and [r["outcome"] for r in rows] == ["key_wrong", "agent_wrong"]
    # A file that ends with a line feed gets no empty line.
    answer_key.add_adjudication(tmp_path, second)
    assert b"\n\n" not in (tmp_path / answer_key.ADJUDICATIONS).read_bytes()


def test_the_end_of_a_test_removes_the_adjudications_of_the_entry(tmp_path: Path) -> None:
    row = answer_key.adjudication(1, "How many mugs?", "key_wrong", "The entry wrote it.", "ann")
    path = tmp_path / answer_key.ADJUDICATIONS
    path.write_text(json.dumps(row) + "\n")
    lines: list[str] = []
    bridge._collect(tmp_path, None, lines.append)
    assert not path.exists()
    assert "removed adjudications.jsonl of the entry: only nookku adjudicate writes it" in lines
    # A symlink of the entry goes too, and the file that it names stays.
    (tmp_path / "rows.jsonl").write_text(json.dumps(row) + "\n")
    path.symlink_to(tmp_path / "rows.jsonl")
    assert answer_key.clear_adjudications(tmp_path) is True
    assert not path.is_symlink() and (tmp_path / "rows.jsonl").exists()
    assert answer_key.clear_adjudications(tmp_path) is False


def test_a_thing_that_the_bridge_cannot_remove_gives_a_problem_and_no_seal(tmp_path: Path) -> None:
    folder = tmp_path / "t1"
    (folder / answer_key.ADJUDICATIONS).mkdir(parents=True)
    lines: list[str] = []
    bridge._collect(folder, None, lines.append)
    report = json.loads((folder / verdict.FILE).read_text())
    assert report["verdict"] == "fail" and verdict.PLANTED in report["problems"]
    assert "adjudications" not in report
    assert not (folder / seal.SEAL).exists()
    assert "no seal: adjudications.jsonl is in the test folder at the end of the test" in lines


def test_the_verdict_of_a_new_test_reads_no_row(tmp_path: Path) -> None:
    row = answer_key.adjudication(1, "How many mugs?", "key_wrong", "The entry wrote it.", "ann")
    (tmp_path / answer_key.ADJUDICATIONS).write_text(json.dumps(row) + "\n")
    report = verdict.build(tmp_path, new=True)
    assert "adjudications" not in report and verdict.PLANTED in report["problems"]
    assert "adjudications" in verdict.build(tmp_path)

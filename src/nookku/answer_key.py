"""The answer key of a test (SPEC.md section 7.17): the `Answer key` section of the app spec,
the key file, its copy in the test folder, the match rules and the adjudications of a person.
The check uses no model."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    Context,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from pathlib import Path
from typing import Any

from . import app_spec
from .config import ConfigError, spec_bytes
from .record import loads, lone_surrogate

SECTION = "answer key"
COLUMNS = ("file", "match")
# The copy of the key file in the test folder (SPEC.md section 7.17).
COPY = "answer_key.json"
MATCHES = ("exact", "number")
# A tolerance: a decimal number of 0 or more, with 1 to 9 digits before and after the point.
TOLERANCE = re.compile(r"[0-9]{1,9}(\.[0-9]{1,9})?")
# A number in a string of a reply.
DECIMAL = re.compile(r"-?[0-9]{1,30}(\.[0-9]{1,30})?")
# The most characters of a value in the detail of a finding.
SHOWN = 200
# The most digits of the exact difference of a number match. If the difference needs more
# digits, the match fails.
DIGITS = 100_000
# The adjudications of a test (SPEC.md section 7.17): one row for each decision of a person
# about a mismatch.
ADJUDICATIONS = "adjudications.jsonl"
ADJUDICATION_VERSION = 1
ADJUDICATION_KEYS = {"v", "turn", "question", "outcome", "reason", "author", "ts"}
# The closed set of outcomes. A mismatch with an outcome of ACCEPTED does not count against the
# limit of answer_key_mismatch.
OUTCOMES = ("agent_wrong", "key_wrong", "both_acceptable")
ACCEPTED = ("key_wrong", "both_acceptable")
# The most code points of a reason and of an author. These are chosen values.
MAX_REASON = 10_000
MAX_AUTHOR = 200
# The largest turn number: 9 digits, as the turn number of a trace point.
MAX_TURN = 999_999_999


class _KeyReader(app_spec.Reader):
    def __init__(self) -> None:
        super().__init__(SECTION, COLUMNS, "an answer key")
        self.rows: list[tuple[str, int, dict[str, str]]] = []

    def take(self, path: str, n: int, row: dict[str, str]) -> None:
        self.rows.append((path, n, row))


def _plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def read(root: Path, files: list[tuple[str, str]]) -> tuple[dict[str, Any] | None, bytes]:
    """The manifest key `answer_key` and the bytes of the key file, or None and no bytes if no
    spec file has an `Answer key` section. `files` holds the path and the text of each spec
    file. Raise ConfigError if a part of the section or the key file is not valid, so the test
    does not start with a key that the check cannot use."""
    reader = _KeyReader()
    for path, text in files:
        reader.file(path, text)
    for p in reader.records():
        raise ConfigError(f"{p['file']} line {p['line']}: {p['problem']}")
    if not reader.rows:
        return None, b""
    if len(reader.rows) > 1:
        path, n, _ = reader.rows[1]
        raise ConfigError(f"{path} line {n}: the app spec has a second Answer key row")
    path, n, row = reader.rows[0]
    where = f"{path} line {n}: "
    file, match = _plain(row["file"]), _plain(row["match"]).lower()
    field, tolerance = _plain(row.get("field", "")), _plain(row.get("tolerance", ""))
    if not file:
        raise ConfigError(where + "the Answer key row has no File")
    if field and not all(field.split(".")):
        raise ConfigError(where + "the Field must be empty or a dot path such as count")
    if match not in MATCHES:
        raise ConfigError(where + "the Match must be exact or number")
    if match == "number" and not TOLERANCE.fullmatch(tolerance):
        raise ConfigError(where + "the match number needs a Tolerance such as 0 or 0.5")
    if match == "exact" and tolerance:
        raise ConfigError(where + "the match exact takes no Tolerance")
    data = spec_bytes(root, file, "answer key")
    try:
        key = parse(data, match, tolerance or None)
    except ValueError as e:
        raise ConfigError(f"the answer key {file!r} is not valid: {e}") from None
    record = {
        "file": file,
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": key["source"],
        "version": key["version"],
        "field": field,
        "match": match,
        "tolerance": tolerance or None,
    }
    return record, data


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a number of JSON")


def _number(value: Any) -> bool:
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def _rule(a: dict[str, Any], n: int, match: str, tolerance: str | None) -> tuple[str, str | None]:
    """The match and the tolerance of answer n of a key file: its own rule, or the rule of the
    app spec if the answer has no `match`. Raise ValueError if the rule is not valid."""
    if "match" not in a:
        if "tolerance" in a:
            raise ValueError(f"answer {n} has a tolerance and no match")
        return match, tolerance
    own, own_tolerance = a["match"], a.get("tolerance")
    if own not in MATCHES:
        raise ValueError(f"answer {n}: the match must be exact or number")
    if own == "exact" and "tolerance" in a:
        raise ValueError(f"answer {n}: the match exact takes no tolerance")
    if own == "number" and not (
        isinstance(own_tolerance, str) and TOLERANCE.fullmatch(own_tolerance)
    ):
        raise ValueError(f"answer {n}: the match number needs a tolerance string such as 0.5")
    return own, own_tolerance


def parse(data: bytes, match: str, tolerance: str | None) -> dict[str, Any]:
    """The source, the version and the answers of a key file: a dict from each question to its
    `answer`, its `match` and its `tolerance` (a Decimal, or None for exact). `match` and
    `tolerance` are the rule of the app spec, for an answer with no rule of its own. Raise
    ValueError with the reason if the file breaks the rule of SPEC.md 7.17."""
    try:
        key = json.loads(data.decode("utf-8"), parse_float=Decimal, parse_constant=_no_constant)
    except (UnicodeDecodeError, RecursionError) as e:
        raise ValueError(f"it is not UTF-8 JSON ({e})") from None
    if not isinstance(key, dict):
        raise ValueError("it is not a JSON object")
    for name in ("source", "version"):
        if not isinstance(key.get(name), str) or not key[name].strip():
            raise ValueError(f"it has no {name} string")
    answers = key.get("answers")
    if not isinstance(answers, list) or not answers:
        raise ValueError("it has no answers list")
    out: dict[str, Any] = {}
    for n, a in enumerate(answers, 1):
        question = a.get("question") if isinstance(a, dict) else None
        if not isinstance(question, str) or not question:
            raise ValueError(f"answer {n} has no question string")
        if question in out:
            raise ValueError(f"answer {n} has the question of an earlier answer")
        rule, limit = _rule(a, n, match, tolerance)
        answer = a.get("answer")
        if rule == "exact" and not isinstance(answer, str):
            raise ValueError(f"answer {n}: the match exact needs a string answer")
        if rule == "number" and not _number(answer):
            raise ValueError(f"answer {n}: the match number needs a number answer")
        out[question] = {
            "answer": answer,
            "match": rule,
            "tolerance": None if limit is None else Decimal(limit),
        }
    return {"source": key["source"], "version": key["version"], "answers": out}


def load(folder: Path, record: Any) -> dict[str, Any]:
    """The field of the manifest key `answer_key` and the answers of the copy in the test folder,
    each with its rule (parse).
    Raise ValueError with the reason if the record or the copy is not valid, or if the SHA-256
    of the copy is not the SHA-256 of the record."""
    ok = (
        isinstance(record, dict)
        and isinstance(record.get("sha256"), str)
        and isinstance(record.get("field"), str)
        and (not record["field"] or all(record["field"].split(".")))
        and record.get("match") in MATCHES
        and (
            isinstance(record.get("tolerance"), str) and TOLERANCE.fullmatch(record["tolerance"])
            if record.get("match") == "number"
            else record.get("tolerance") is None
        )
    )
    if not ok:
        raise ValueError("the key answer_key of manifest.json is not valid")
    copy = folder / COPY
    if copy.is_symlink() or not copy.is_file():
        raise ValueError(f"the test folder has no file {COPY}")
    data = copy.read_bytes()
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError(f"the SHA-256 of {COPY} is not the SHA-256 of the manifest")
    key = parse(data, record["match"], record["tolerance"])
    return {"field": record["field"], "answers": key["answers"]}


def place(folder: Path, data: bytes) -> None:
    """Write the copy of the key file into the test folder after the entry stops (SPEC.md
    section 7.17), so that the entry cannot read the copy. The bridge removes a file or a
    symlink of the entry at the path first, and the write follows no symlink. Raise OSError."""
    copy = folder / COPY
    if copy.is_symlink() or copy.is_file():
        copy.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(copy, flags, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def place_from_project(root: Path, folder: Path, record: Any) -> str | None:
    """Write the copy for a test whose bridge stopped with no end: the bytes of the key file
    of the project, only if their SHA-256 is the SHA-256 of the manifest. Return the reason if
    the bridge writes no copy, else None. With no copy, the check fails closed."""
    if not isinstance(record, dict) or not isinstance(record.get("file"), str):
        return "the key answer_key of manifest.json is not valid"
    try:
        data = spec_bytes(root, record["file"], "answer key")
    except ConfigError as e:
        return str(e)
    if hashlib.sha256(data).hexdigest() != record.get("sha256"):
        return "the SHA-256 of the key file is not the SHA-256 of the manifest"
    place(folder, data)
    return None


def matches(value: Any, answer: Any, match: str, tolerance: Decimal | None) -> bool:
    """True if a reply value matches an answer of the key (SPEC.md section 7.17)."""
    if match == "exact":
        return isinstance(value, str) and value == answer
    if isinstance(value, str) and DECIMAL.fullmatch(value.strip()):
        value = Decimal(value.strip())
    elif isinstance(value, float):
        value = Decimal(repr(value))
    if not _number(value):
        return False
    assert tolerance is not None
    return _within(Decimal(value), Decimal(answer), tolerance)


def _within(value: Decimal, answer: Decimal, tolerance: Decimal) -> bool:
    """True if the difference of value and answer is not more than tolerance. The context has
    the digits and the exponent range of the exact difference. If a step rounds, the match
    fails."""
    parts = (value, answer, tolerance)
    if not all(p.is_finite() for p in parts):
        return False
    if value == answer:
        return True
    low = min(int(p.as_tuple().exponent) for p in parts)
    digits = max(p.adjusted() for p in parts) - low + 2
    if digits > DIGITS:
        return False
    traps = [InvalidOperation, Inexact, Overflow, Underflow]
    exact = Context(prec=max(digits, 1), Emin=MIN_EMIN, Emax=MAX_EMAX, traps=traps)
    with localcontext(exact):
        try:
            return abs(value - answer) <= tolerance
        except DecimalException:
            return False


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON")


def shown(value: Any) -> str:
    """A value of a reply or of the key for the detail of a finding, as JSON text, with
    SHOWN characters at most."""
    if isinstance(value, Decimal):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, default=_json)
    return text if len(text) <= SHOWN else text[:SHOWN] + "..."


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text_problem(value: Any, name: str, most: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"it has no {name} text"
    if len(value) > most:
        return f"the {name} has more than {most} code points"
    found = lone_surrogate(value)
    return None if found is None else f"the {name} has {found}"


def adjudication_problem(row: Any) -> str | None:
    """The reason that a value is not an adjudication row (SPEC.md section 7.17), or None."""
    if not isinstance(row, dict):
        return "it is not a JSON object"
    if set(row) != ADJUDICATION_KEYS:
        return "its keys are not " + ", ".join(sorted(ADJUDICATION_KEYS))
    if not _whole(row["v"]) or row["v"] != ADJUDICATION_VERSION:
        return f"its v is not {ADJUDICATION_VERSION}"
    if not _whole(row["turn"]) or not 1 <= row["turn"] <= MAX_TURN:
        return f"its turn is not a whole number from 1 to {MAX_TURN}"
    question = row["question"]
    if not isinstance(question, str) or not question or lone_surrogate(question):
        return "it has no question string"
    if row["outcome"] not in OUTCOMES:
        return "its outcome is not " + ", ".join(OUTCOMES)
    problem = _text_problem(row["reason"], "reason", MAX_REASON)
    problem = problem or _text_problem(row["author"], "author", MAX_AUTHOR)
    if problem is not None:
        return problem
    if any(ord(c) < 32 or ord(c) == 127 for c in row["author"]):
        return "the author has a control character"
    ts = row["ts"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not 0 <= ts < float("inf"):
        return "its ts is not a Unix time"
    return None


def read_adjudications(data: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """The rows of the bytes of adjudications.jsonl, or no rows and the problem of the first
    line that is not valid. The reader never skips a line, so a file with a line that is not
    valid gives no adjudication."""
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        return [], f"{ADJUDICATIONS} is not UTF-8"
    if lines[-1] == "":
        lines.pop()
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(lines, 1):
        try:
            row = loads(line, parse_constant=_no_constant)
        except ValueError:
            return [], f"{ADJUDICATIONS} line {n}: it is not JSON"
        problem = adjudication_problem(row)
        if problem is not None:
            return [], f"{ADJUDICATIONS} line {n}: {problem}"
        rows.append(row)
    return rows, None


def mismatches_of(report: Any) -> dict[int, str] | None:
    """The question of each turn with a mismatch, from the `answers` of findings.json (SPEC.md
    section 8.6), or None if the report has no valid `answers` list."""
    answers = report.get("answers") if isinstance(report, dict) else None
    if not isinstance(answers, list):
        return None
    out: dict[int, str] = {}
    for a in answers:
        ok = (
            isinstance(a, dict)
            and _whole(a.get("turn"))
            and isinstance(a.get("question"), str)
            and a.get("result") in ("match", "mismatch")
            and a["turn"] not in out
        )
        if not ok:
            return None
        if a["result"] == "mismatch":
            out[a["turn"]] = a["question"]
    return out


def outcomes_of(
    rows: list[dict[str, Any]], mismatches: dict[int, str]
) -> tuple[dict[int, str], str | None]:
    """The current outcome of each adjudicated mismatch: the outcome of the last row of its
    turn. A row that names a turn with no mismatch, or another question than the question of
    its turn, gives no outcomes and the problem."""
    out: dict[int, str] = {}
    for n, row in enumerate(rows, 1):
        turn = row["turn"]
        if turn not in mismatches:
            return {}, f"{ADJUDICATIONS} line {n}: turn {turn} has no answer key mismatch"
        if row["question"] != mismatches[turn]:
            return {}, f"{ADJUDICATIONS} line {n}: the question is not the question of turn {turn}"
        out[turn] = row["outcome"]
    return out, None


def tally(count: int | None, data: bytes, report: Any) -> tuple[dict[str, Any], list[str]]:
    """The counts of the adjudications of a test, for verdict.json, and each problem. `count`
    is the count of answer_key_mismatch in findings.json, `data` holds the bytes of
    adjudications.jsonl, and `report` is findings.json. With a problem, no adjudication applies:
    each mismatch is open, so the verdict fails closed."""
    problems: list[str] = []
    rows, problem = read_adjudications(data)
    mismatches = mismatches_of(report)
    if problem is None and mismatches is None and rows:
        problem = f"{ADJUDICATIONS}: findings.json has no valid answers list"
    outcomes: dict[int, str] = {}
    if problem is None and mismatches is not None:
        outcomes, problem = outcomes_of(rows, mismatches)
    if problem is None and mismatches is not None and len(mismatches) != count:
        outcomes = {}
        problem = "findings.json: the answers do not agree with the count of answer_key_mismatch"
    if problem is not None:
        problems.append(problem)
    by = {o: sum(1 for v in outcomes.values() if v == o) for o in OUTCOMES}
    accepted = sum(by[o] for o in ACCEPTED)
    return {
        "mismatches": count,
        "open": None if count is None else count - len(outcomes),
        **by,
        "counted": None if count is None else count - accepted,
    }, problems


def adjudication(
    turn: int, question: str, outcome: str, reason: str, author: str
) -> dict[str, Any]:
    """A new adjudication row, with the time now. Raise ValueError if a value is not valid."""
    row = {
        "v": ADJUDICATION_VERSION,
        "turn": turn,
        "question": question,
        "outcome": outcome,
        "reason": reason,
        "author": author,
        "ts": round(time.time(), 3),
    }
    problem = adjudication_problem(row)
    if problem is not None:
        raise ValueError(problem)
    return row


def with_adjudication(data: bytes, row: dict[str, Any]) -> bytes:
    """The bytes of adjudications.jsonl with one more row. The reader accepts a last line with
    no line feed. The new row then starts on its own line, so 2 rows never share a line."""
    line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    return data + (b"" if not data or data.endswith(b"\n") else b"\n") + line


def clear_adjudications(folder: Path) -> bool:
    """Remove adjudications.jsonl at the end of a test (SPEC.md section 7.17). Only
    `nookku adjudicate` writes the file, and only after the seal. Thus a file at the end of a
    test comes from the entry, and its rows are not decisions of a person. Return True if the
    bridge removed a file or a symlink. Raise OSError."""
    path = folder / ADJUDICATIONS
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    return False

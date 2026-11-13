"""The answer key of a test (SPEC.md section 7.17): the `Answer key` section of the app spec,
the key file, its copy in the test folder and the match rules. The check uses no model."""

from __future__ import annotations

import hashlib
import json
import re
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
        key = parse(data, match)
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


def parse(data: bytes, match: str) -> dict[str, Any]:
    """The source, the version and the answers of a key file: a dict from each question to its
    answer. Raise ValueError with the reason if the file breaks the rule of SPEC.md 7.17."""
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
        answer = a.get("answer")
        if match == "exact" and not isinstance(answer, str):
            raise ValueError(f"answer {n}: the match exact needs a string answer")
        if match == "number" and not _number(answer):
            raise ValueError(f"answer {n}: the match number needs a number answer")
        out[question] = answer
    return {"source": key["source"], "version": key["version"], "answers": out}


def load(folder: Path, record: Any) -> dict[str, Any]:
    """The rule of the manifest key `answer_key` and the answers of the copy in the test folder.
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
    key = parse(data, record["match"])
    tolerance = Decimal(record["tolerance"]) if record["match"] == "number" else None
    return {
        "field": record["field"],
        "match": record["match"],
        "tolerance": tolerance,
        "answers": key["answers"],
    }


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

"""The issue rows of an evaluation: `evaluation.json` (SPEC.md section 9.4).

The model writes `report.md`. `nookku evaluation import` reads the issue table of `report.md` and
writes each row as a `model` row. It trusts the bytes of the file, and no record binds the file
to the evaluation (section 9.4, "The trust of report.md"). `nookku evaluation add` writes a
`human` row. The command sets the author type, and the text of a row never sets it. The seal
covers `evaluation.json`. The verdict counts the rows of an issue class only if the app spec
gives the class a limit (SPEC.md section 7.14)."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from nookku import app_spec
from nookku.record import loads, lone_surrogate

FILE = "evaluation.json"
REPORT = "report.md"
VERSION = 1
# The issue classes of the report (SPEC.md section 9.3), in the order of its table.
CLASSES = (
    "business_rule",
    "wrong_tool",
    "wrong_arguments",
    "unsupported_reply",
    "missing_action",
    "state_mismatch",
    "tone",
    "boundary",
    "off_path",
    "performance",
)
AUTHORS = ("model", "human")
KEYS = {"class", "turn", "evidence", "text", "author", "name"}
COLUMNS = ("class", "turn", "evidence", "issue")
# The heading of the part of report.md that the command writes. The import reads no line after it.
PERSON_HEADING = "## Person issues"
# Chosen values, as for an adjudication (SPEC.md section 7.17).
MAX_TEXT = 10_000
MAX_EVIDENCE = 1_000
MAX_NAME = 200
MAX_TURN = 999_999_999
MAX_ROWS = 1_000
# The most bytes of report.md that the import reads, as for a copy of a spec file (section 9.2).
MAX_REPORT = 1_048_576


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _control(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def _text_problem(value: Any, name: str, most: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"it has no {name} text"
    if len(value) > most:
        return f"the {name} has more than {most} code points"
    if _control(value):
        return f"the {name} has a control character"
    found = lone_surrogate(value)
    return None if found is None else f"the {name} has {found}"


def row_problem(row: Any) -> str | None:
    """The reason that a value is not an issue row of evaluation.json, or None."""
    if not isinstance(row, dict):
        return "it is not a JSON object"
    if set(row) != KEYS:
        return "its keys are not " + ", ".join(sorted(KEYS))
    if row["class"] not in CLASSES:
        return "its class is not an issue class of SPEC.md section 9.3"
    turn = row["turn"]
    if turn is not None and (not _whole(turn) or not 1 <= turn <= MAX_TURN):
        return f"its turn is not null or a whole number from 1 to {MAX_TURN}"
    problem = _text_problem(row["evidence"], "evidence", MAX_EVIDENCE)
    problem = problem or _text_problem(row["text"], "text", MAX_TEXT)
    if problem is not None:
        return problem
    if row["author"] not in AUTHORS:
        return "its author is not model or human"
    if row["author"] == "model":
        return None if row["name"] is None else "a model row has a name"
    return _text_problem(row["name"], "name", MAX_NAME)


def row(cls: str, turn: int | None, evidence: str, text: str, name: str | None) -> dict[str, Any]:
    """A new issue row. The author type comes from `name`: a person row has the name of the
    person, and a model row has None. Raise ValueError if a value is not valid."""
    new = {
        "class": cls,
        "turn": turn,
        "evidence": evidence,
        "text": text,
        "author": "model" if name is None else "human",
        "name": name,
    }
    problem = row_problem(new)
    if problem is not None:
        raise ValueError(problem)
    return new


def read(data: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """The record of the bytes of evaluation.json, or None and the problem. A record with a row
    that is not valid gives no record, so the verdict fails closed."""
    try:
        record = loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, f"{FILE} is not valid JSON"
    if not isinstance(record, dict) or set(record) != {"v", "test", "report", "issues"}:
        return None, f"{FILE} is not an object with the keys v, test, report and issues"
    if not _whole(record["v"]) or record["v"] != VERSION:
        return None, f"{FILE}: its v is not {VERSION}"
    if not isinstance(record["test"], str):
        return None, f"{FILE}: its test is not a string"
    report = record["report"]
    if report is not None and (
        not isinstance(report, str) or not re.fullmatch(r"[0-9a-f]{64}", report)
    ):
        return None, f"{FILE}: its report is not null or a SHA-256"
    rows = record["issues"]
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        return None, f"{FILE}: its issues is not a list of {MAX_ROWS} rows at most"
    for n, r in enumerate(rows, 1):
        problem = row_problem(r)
        if problem is not None:
            return None, f"{FILE} issue {n}: {problem}"
    return record, None


def counts(data: bytes | None) -> tuple[dict[str, dict[str, int]] | None, str | None]:
    """The count of model rows and of human rows of each issue class, or None and the problem."""
    if data is None:
        return None, f"{FILE} is missing."
    record, problem = read(data)
    if record is None:
        return None, f"{problem}."
    out = {c: {"model": 0, "human": 0} for c in CLASSES}
    for r in record["issues"]:
        out[r["class"]][r["author"]] += 1
    return out, None


def file_bytes(test: str, report: str | None, rows: list[dict[str, Any]]) -> bytes:
    """The bytes of evaluation.json."""
    record = {"v": VERSION, "test": test, "report": report, "issues": rows}
    return (json.dumps(record, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def read_report(folder: Path) -> bytes | None:
    """The bytes of report.md from one read, or None if the file does not exist. The read does
    not follow a symlink. Raise ValueError if the path is not a regular file or is too large."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(folder / REPORT, flags)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ValueError(f"{REPORT} cannot be read: {e.strerror}") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"{REPORT} is not a regular file.")
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(MAX_REPORT + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_REPORT:
        raise ValueError(f"{REPORT} has more than {MAX_REPORT} bytes.")
    return data


def _model_part(text: str) -> list[str]:
    """The lines of report.md before the part that the command writes."""
    lines = text.splitlines()
    fence: str | None = None
    for n, line in enumerate(lines):
        if fence is not None:
            end = app_spec.CLOSE_FENCE.fullmatch(line)
            if end and end.group(1).startswith(fence) and set(end.group(1)) == {fence[0]}:
                fence = None
            continue
        if m := app_spec.FENCE.match(line):
            fence = m.group(1)
            continue
        if line.rstrip() == PERSON_HEADING:
            return lines[:n]
    return lines


def model_rows(data: bytes) -> list[dict[str, Any]]:
    """The model rows of the issue table of report.md: the first table outside a code fence
    whose header has the columns Class, Turn, Evidence and Issue, before the part that the
    command writes. A table with no rows gives no row. Raise ValueError with the line of the
    first problem, so an import with a problem writes nothing."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{REPORT} is not UTF-8.") from None
    columns: list[str] | None = None
    fence: str | None = None
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(_model_part(text), 1):
        if fence is not None:
            end = app_spec.CLOSE_FENCE.fullmatch(line)
            if end and end.group(1).startswith(fence) and set(end.group(1)) == {fence[0]}:
                fence = None
            continue
        if m := app_spec.FENCE.match(line):
            if columns is not None:
                break
            fence = m.group(1)
            continue
        cells = None if app_spec.heading(line) is not None else app_spec.cells(line)
        if columns is None:
            if cells is not None:
                names = [app_spec.plain(c).lower() for c in cells]
                if all(c in names for c in COLUMNS):
                    columns = names
            continue
        if cells is None:
            break
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        if len(cells) != len(columns):
            raise ValueError(
                f"{REPORT} line {n}: the row has {len(cells)} cells, "
                f"and the header has {len(columns)}."
            )
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"{REPORT} line {n}: the issue table has more than {MAX_ROWS} rows.")
        cell = dict(zip(columns, cells, strict=True))
        mark = app_spec.plain(cell["turn"])
        turn: int | None = None
        if mark != "-":
            if not re.fullmatch(r"[1-9][0-9]{0,8}", mark):
                raise ValueError(
                    f"{REPORT} line {n}: the Turn is not - or a whole number from 1 to {MAX_TURN}."
                )
            turn = int(mark)
        try:
            rows.append(
                row(app_spec.plain(cell["class"]), turn, cell["evidence"], cell["issue"], None)
            )
        except ValueError as e:
            raise ValueError(f"{REPORT} line {n}: {e}.") from None
    if columns is None:
        raise ValueError(
            f"{REPORT} has no issue table with the columns Class, Turn, Evidence and Issue."
        )
    return rows


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def with_person_part(data: bytes, rows: list[dict[str, Any]]) -> bytes:
    """The bytes of report.md with the part that the command writes: the human rows, from the
    same rows as evaluation.json. The part replaces an earlier part, and the model part does not
    change."""
    text = data.decode("utf-8")
    lines = _model_part(text)
    people = [r for r in rows if r["author"] == "human"]
    if not people and len(lines) == len(text.splitlines()):
        # No part to write or to remove: the bytes of the model stay as they are.
        return data
    while lines and not lines[-1].strip():
        lines.pop()
    if people:
        lines += [
            "",
            PERSON_HEADING,
            "",
            "| Class | Turn | Evidence | Issue | Author |",
            "|---|---|---|---|---|",
        ]
        for r in people:
            turn = "-" if r["turn"] is None else str(r["turn"])
            cells = [r["class"], turn, _cell(r["evidence"]), _cell(r["text"]), _cell(r["name"])]
            lines.append("| " + " | ".join(cells) + " |")
    return ("\n".join(lines) + "\n").encode("utf-8")


def clear(folder: Path) -> bool:
    """Remove evaluation.json at the end of a test. Only `nookku evaluation` writes the file,
    and only after the seal. Thus a file at the end of a test comes from the entry. Return True
    if the bridge removed a file or a symlink. Raise OSError."""
    path = folder / FILE
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    return False

"""The finding record of a confirmed defect (SPEC.md section 10).

A finding record is one JSON object that another tool can read with no other file of Nookku. It
holds the messages of the test, the turn, the expected value, the adjudication, the subject
digest and the seal of the test folder. `problem` is the reader: it gives the reason that a value
is not a record of version 1. `of_test` and `of_gate` write the records of a test and of a gate
run, and `nookku finding` is the command.

The format is a contract with a version. The reader ignores a field that it does not know, and
it refuses a major version that it does not know.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

from nookku import seal
from nookku.record import Exchange, RecordError, json_text, loads, lone_surrogate, read_tap

NAME = "nookku.finding"
# The version of the records that this module writes: `<major>.<minor>`.
MAJOR = 1
VERSION = f"{MAJOR}.0"
SCHEMA = "finding_record.schema.json"
MISMATCH = "answer_key_mismatch"
ISSUE = "issue_row"
KINDS = (MISMATCH, ISSUE)
# A record is a confirmed defect of the agent, so version 1 has one outcome.
OUTCOME = "agent_wrong"
AUTHOR_TYPES = ("human", "model")
MATCHES = ("exact", "number")
# The fields of a record, in the order of the table of SPEC.md section 10.
FIELDS = (
    "record",
    "version",
    "id",
    "kind",
    "test",
    "script",
    "turn",
    "expected",
    "observed",
    "issue",
    "adjudication",
    "subject",
    "gate",
    "seal",
    "nookku",
)
MANIFEST = "manifest.json"
FINDINGS = "findings.json"
TAP = "tap.jsonl"
KEY_COPY = "answer_key.json"
ADJUDICATIONS = "adjudications.jsonl"
EVALUATION = "evaluation.json"
SCRIPT_COPIES = ("script.json", "script.jsonl")
VERDICT = "verdict.json"
# The files of the seal that each record of a kind names.
SOURCES = {
    MISMATCH: (MANIFEST, TAP, FINDINGS, KEY_COPY, ADJUDICATIONS),
    ISSUE: (MANIFEST, TAP, EVALUATION),
}
MAX_TURN = 999_999_999
SUBJECT_MAX = 512
_VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOLERANCE = re.compile(r"[0-9]{1,9}(\.[0-9]{1,9})?")
_DECIMAL = re.compile(r"-?[0-9]+(\.[0-9]+)?")


class ExportError(ValueError):
    """The records of a test or of a gate run cannot be written. Nothing was written."""


def schema_text() -> str:
    """The JSON Schema of a record of version 1, as the package holds it."""
    return resources.files("nookku").joinpath(SCHEMA).read_text(encoding="utf-8")


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a number of JSON")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _surrogate(value: Any) -> str | None:
    """The first lone surrogate in a key or a string of a JSON value, or None. The walk uses no
    recursion, so a value that nests deep gives no error."""
    todo = [value]
    while todo:
        item = todo.pop()
        if isinstance(item, str):
            found = lone_surrogate(item)
            if found is not None:
                return found
        elif isinstance(item, dict):
            todo += [x for pair in item.items() for x in pair]
        elif isinstance(item, list):
            todo += item
    return None


# The keys of each object of a record. A writer of major version 1 always writes each one.
KEYS = {
    "script": ("messages", "sha256"),
    "turn": ("number", "input", "reply"),
    "expected": ("value", "match", "tolerance", "field"),
    "issue": ("class", "evidence", "text"),
    "adjudication": ("outcome", "reason", "author", "author_type", "ts"),
    "gate": ("id", "name", "result_sha256"),
    "seal": ("sha256", "text", "files"),
}


def _object_problem(value: Any, field: str, null: bool = False) -> str | None:
    """The problem of a field that is an object: it is not an object, or it does not have a
    key of KEYS. A key with the value null is a key. Thus no later check reads a key that the
    object does not have."""
    if not isinstance(value, dict):
        return f"its {field} is not an object" + (" or null" if null else "")
    missing = next((name for name in KEYS[field] if name not in value), None)
    return None if missing is None else f"its {field} has no key {missing}"


def _script_problem(value: Any) -> str | None:
    found = _object_problem(value, "script")
    if found is not None:
        return found
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages:
        return "its script has no messages list"
    if not all(isinstance(m, str) for m in messages):
        return "a message of its script is not a string"
    if value.get("sha256") is not None and not _sha(value.get("sha256")):
        return "the sha256 of its script is not null or a SHA-256"
    return None


def _turn_problem(value: Any, kind: str, messages: list[str]) -> str | None:
    if value is None:
        return None if kind == ISSUE else "its turn is null"
    found = _object_problem(value, "turn", null=True)
    if found is not None:
        return found
    number = value.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= MAX_TURN:
        return f"the number of its turn is not a whole number from 1 to {MAX_TURN}"
    if number > len(messages):
        return f"its turn {number} is not a message of its script"
    if value.get("input") != messages[number - 1]:
        return f"the input of its turn is not message {number} of its script"
    if not isinstance(value["reply"], (str, type(None))):
        return "the reply of its turn is not a string or null"
    return None


def _expected_problem(value: Any, kind: str) -> str | None:
    if kind == ISSUE:
        return None if value is None else "its expected is not null"
    found = _object_problem(value, "expected")
    if found is not None:
        return found
    match, tolerance = value.get("match"), value.get("tolerance")
    if match not in MATCHES:
        return "the match of its expected is not " + " or ".join(MATCHES)
    if not isinstance(value.get("value"), str):
        return "the value of its expected is not a string"
    if match == "number":
        if not _DECIMAL.fullmatch(value["value"]):
            return "the value of its expected is not a decimal number"
        if not isinstance(tolerance, str) or not _TOLERANCE.fullmatch(tolerance):
            return "the tolerance of its expected is not a decimal number"
    elif tolerance is not None:
        return "the tolerance of its expected is not null"
    if not isinstance(value.get("field"), str):
        return "the field of its expected is not a string"
    return None


def _observed_problem(value: Any, kind: str) -> str | None:
    if value is None or (kind == MISMATCH and isinstance(value, str)):
        return None
    return "its observed is not " + ("a string or null" if kind == MISMATCH else "null")


def _issue_problem(value: Any, kind: str) -> str | None:
    if kind == MISMATCH:
        return None if value is None else "its issue is not null"
    found = _object_problem(value, "issue")
    if found is not None:
        return found
    for name in ("class", "evidence", "text"):
        if not _text(value.get(name)):
            return f"its issue has no {name} text"
    return None


def _adjudication_problem(value: Any, kind: str) -> str | None:
    found = _object_problem(value, "adjudication")
    if found is not None:
        return found
    if value.get("outcome") != OUTCOME:
        return f"the outcome of its adjudication is not {OUTCOME}"
    if not _text(value.get("reason")):
        return "its adjudication has no reason text"
    kinds = AUTHOR_TYPES if kind == ISSUE else AUTHOR_TYPES[:1]
    if value.get("author_type") not in kinds:
        return "the author_type of its adjudication is not " + " or ".join(kinds)
    author = value.get("author")
    if value["author_type"] == "human" and not _text(author):
        return "its adjudication has no author text"
    if value["author_type"] == "model" and author is not None:
        return "the author of a model adjudication is not null"
    ts = value.get("ts")
    number = isinstance(ts, (int, float)) and not isinstance(ts, bool) and 0 <= ts < float("inf")
    if not number and (kind == MISMATCH or ts is not None):
        return "the ts of its adjudication is not a Unix time"
    return None


def subject_problem(subject: Any) -> str | None:
    """Why a value is not a subject digest, or None. The rule is the rule of a gate run (SPEC.md
    section 7.15)."""
    if not isinstance(subject, str) or not 1 <= len(subject) <= SUBJECT_MAX:
        return f"the subject must have 1 to {SUBJECT_MAX} characters"
    if any(ord(c) < 32 or ord(c) == 127 for c in subject):
        return "the subject must have no control character"
    return None


def _gate_problem(value: Any) -> str | None:
    if value is None:
        return None
    found = _object_problem(value, "gate", null=True)
    if found is not None:
        return found
    for name in ("id", "name"):
        if not _text(value.get(name)):
            return f"its gate has no {name} text"
    if not _sha(value.get("result_sha256")):
        return "the result_sha256 of its gate is not a SHA-256"
    return None


def _seal_problem(value: Any, record: dict[str, Any]) -> str | None:
    """The problem of the seal of a record. The digest is the SHA-256 of the UTF-8 bytes of the
    seal text, and the seal text must cover each named file with its SHA-256."""
    found = _object_problem(value, "seal")
    if found is not None:
        return found
    text, files = value.get("text"), value.get("files")
    if not isinstance(text, str) or not _sha(value.get("sha256")):
        return "its seal has no text string and SHA-256"
    if not isinstance(files, dict) or not all(_sha(v) for v in files.values()):
        return "the files of its seal are not an object of SHA-256 values"
    if seal.sha256_of(text.encode("utf-8")) != value["sha256"]:
        return "the seal digest is not the SHA-256 of the seal text"
    try:
        sealed = loads(text, parse_constant=_no_constant)
    except ValueError:
        sealed = None
    if not isinstance(sealed, dict) or not isinstance(sealed.get("files"), dict):
        return "the seal text is not a seal"
    if sealed.get("test") != record["test"]:
        return "the seal text is not the seal of its test"
    for name, sha in files.items():
        if sealed["files"].get(name) != sha:
            return f"the seal text does not cover {name} with this SHA-256"
    for name in SOURCES[record["kind"]]:
        if name not in files:
            return f"the files of its seal do not have {name}"
    script = record["script"]["sha256"]
    if script is not None and script not in (files.get(n) for n in SCRIPT_COPIES):
        return "the files of its seal do not have the script copy with the sha256 of its script"
    return None


def problem(record: Any) -> str | None:
    """The reason that a JSON value is not a finding record of version 1 (SPEC.md section 10),
    or None. The reader ignores each field that it does not know. It refuses a record of another
    major version, because it cannot know the meaning of its fields."""
    if not isinstance(record, dict):
        return "it is not a JSON object"
    if record.get("record") != NAME:
        return f"its record is not {NAME}"
    version = record.get("version")
    found = _VERSION.fullmatch(version) if isinstance(version, str) else None
    if found is None:
        return "its version is not a string of the form <major>.<minor>"
    if int(found.group(1)) != MAJOR:
        return f"its version {version} is not a version of major version {MAJOR}"
    for name in FIELDS:
        if name not in record:
            return f"it has no field {name}"
    surrogate = _surrogate(record)
    if surrogate is not None:
        return f"it has {surrogate}"
    kind = record["kind"]
    if kind not in KINDS:
        return "its kind is not " + " or ".join(KINDS)
    for name in ("id", "test", "nookku"):
        if not _text(record[name]):
            return f"it has no {name} text"
    found_problem = _script_problem(record["script"])
    if found_problem is not None:
        return found_problem
    checks = (
        _turn_problem(record["turn"], kind, record["script"]["messages"]),
        _expected_problem(record["expected"], kind),
        _observed_problem(record["observed"], kind),
        _issue_problem(record["issue"], kind),
        _adjudication_problem(record["adjudication"], kind),
        subject_problem(record["subject"]),
        _gate_problem(record["gate"]),
    )
    first = next((c for c in checks if c is not None), None)
    return first if first is not None else _seal_problem(record["seal"], record)


def check_lines(data: bytes) -> list[dict[str, Any]]:
    """The result of each line of a file of records: `line`, `id` and `problem`, which is None
    for a valid record. The file is UTF-8 JSONL, and a last empty line is permitted. The reader
    never skips a line. Raise ValueError if the bytes are not UTF-8."""
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        raise ValueError("the file is not UTF-8") from None
    if lines[-1] == "":
        lines.pop()
    out: list[dict[str, Any]] = []
    for n, line in enumerate(lines, 1):
        try:
            record = loads(line, parse_constant=_no_constant)
        except ValueError:
            out.append({"line": n, "id": None, "problem": "it is not JSON"})
            continue
        found = record.get("id") if isinstance(record, dict) else None
        name = found if isinstance(found, str) else None
        out.append({"line": n, "id": name, "problem": problem(record)})
    return out


def _seal_of(folder: Path) -> tuple[str, dict[str, Any]]:
    """The text and the files of the seal that an export starts from: the copy outside the
    folder, or seal.json if no copy exists (seal.trusted). Raise ExportError."""
    for path in (seal.copy_path(folder.name), folder / seal.SEAL):
        try:
            text = path.read_bytes().decode("utf-8")
            data = loads(text, parse_constant=_no_constant)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            if data.get("test") != folder.name:
                raise ExportError(f"The seal of {folder.name} names another test.")
            return text, data["files"]
    raise ExportError(f"The test folder {folder.name} has no valid seal.")


def _decimal_text(value: Any) -> str:
    """A number of an answer key as a decimal number with no exponent, so no digit is lost.
    The text of a Decimal can have an exponent: a tolerance of 0.000000001 gives 1E-9."""
    return str(value) if isinstance(value, int) else format(value, "f")


class _Test:
    """The sealed records of one test folder for an export. The export reads each record one
    time, and it uses only bytes that have the SHA-256 of the seal."""

    def __init__(self, folder: Path, pins: dict[str, Any] | None) -> None:
        check = seal.verify(folder)
        if not check["intact"] or (pins is not None and check["copy"] != "same"):
            raise ExportError(f"Test {folder.name}: {seal.summary(check)}")
        self.folder, self.name = folder, folder.name
        self.text, self.files = _seal_of(folder)
        for name, sha in (pins or {}).items():
            # An adjudication and an issue row write verdict.json again (sections 7.17 and 9.4).
            if name != VERDICT and self.files.get(name) != sha:
                text = f"Test {self.name}: {name} is not the file that the gate run pinned."
                raise ExportError(text)
        manifest = self.json(MANIFEST)
        if not isinstance(manifest, dict):
            raise ExportError(f"Test {self.name}: {MANIFEST} is not a JSON object.")
        self.manifest: dict[str, Any] = manifest
        try:
            rows = read_tap(folder / TAP, data=self.read(TAP))
        except RecordError as e:
            raise ExportError(f"Test {self.name}: {e}") from None
        self.turns = [(r.input, r.reply) for r in rows if isinstance(r, Exchange)]
        copy = next((n for n in SCRIPT_COPIES if n in self.files), None)
        self.script = None if copy is None else (copy, seal.sha256_of(self.read(copy)))

    def read(self, name: str) -> bytes:
        try:
            return seal.sealed_bytes(self.folder, self.files, name)
        except ValueError as e:
            raise ExportError(f"Test {self.name}: {e}") from None

    def optional(self, name: str) -> bytes | None:
        """The bytes of a file that only a command of a person writes, or None if the seal
        does not have it."""
        return self.read(name) if name in self.files else None

    def json(self, name: str) -> Any:
        try:
            return loads(self.read(name).decode("utf-8"))
        except ValueError:
            raise ExportError(f"Test {self.name}: {name} is not JSON.") from None

    def turn(self, number: int, what: str) -> dict[str, Any]:
        if not 1 <= number <= len(self.turns):
            text = f"Test {self.name}: {what} names turn {number}, and the test has "
            raise ExportError(text + f"{len(self.turns)} turns.")
        said, reply = self.turns[number - 1]
        return {"number": number, "input": said, "reply": reply}

    def record(self, kind: str, n: int, more: dict[str, Any]) -> dict[str, Any]:
        """One record with the fields that each kind has. `more` gives the other fields."""
        if not self.turns:
            raise ExportError(f"Test {self.name}: {TAP} has no exchange.")
        names = [*SOURCES[kind], *([self.script[0]] if self.script else [])]
        record = {
            "record": NAME,
            "version": VERSION,
            "id": f"{self.name}/{kind}/{n}",
            "kind": kind,
            "test": self.name,
            "script": {
                "messages": [said for said, _ in self.turns],
                "sha256": None if self.script is None else self.script[1],
            },
            **more,
            "seal": {
                "sha256": seal.sha256_of(self.text.encode("utf-8")),
                "text": self.text,
                "files": {name: self.files[name] for name in names},
            },
        }
        return {name: record[name] for name in FIELDS if name in record}


def _mismatches(test: _Test) -> list[tuple[int, dict[str, Any]]]:
    """Each mismatch with the current outcome agent_wrong, as its turn and the other fields of
    its record (SPEC.md section 7.17). Raise ExportError if a record is not valid."""
    from nookku import answer_key

    data = test.optional(ADJUDICATIONS)
    if data is None:
        return []
    rows, found = answer_key.read_adjudications(data)
    report = test.json(FINDINGS)
    mismatches = answer_key.mismatches_of(report)
    if found is None and mismatches is None and rows:
        found = f"{FINDINGS} has no valid answers list"
    outcomes: dict[int, str] = {}
    if found is None and mismatches is not None:
        outcomes, found = answer_key.outcomes_of(rows, mismatches)
    if found is not None:
        raise ExportError(f"Test {test.name}: {found}.")
    last = {row["turn"]: row for row in rows}
    confirmed = sorted(t for t, outcome in outcomes.items() if outcome == OUTCOME)
    if not confirmed:
        return []
    spec: Any = test.manifest.get("answer_key")
    try:
        key = answer_key.load(test.folder, spec)
    except ValueError as e:
        raise ExportError(f"Test {test.name}: the answer key cannot be used: {e}.") from None
    if test.files.get(KEY_COPY) != spec["sha256"]:
        raise ExportError(f"Test {test.name}: {KEY_COPY} is not the file of the seal.")
    shown = {a["turn"]: a.get("value") for a in report["answers"]}
    out = []
    for number in confirmed:
        turn, row = test.turn(number, "an adjudication"), last[number]
        rule = key["answers"].get(turn["input"])
        if rule is None or row["question"] != turn["input"]:
            text = f"Test {test.name}: turn {number} does not ask a question of the answer key."
            raise ExportError(text)
        answer, tolerance = rule["answer"], rule["tolerance"]
        fields = {
            "turn": turn,
            "expected": {
                "value": answer if rule["match"] == "exact" else _decimal_text(answer),
                "match": rule["match"],
                "tolerance": None if tolerance is None else _decimal_text(tolerance),
                "field": key["field"],
            },
            "observed": shown[number] if isinstance(shown[number], str) else None,
            "issue": None,
            "adjudication": {
                "outcome": OUTCOME,
                "reason": row["reason"],
                "author": row["author"],
                "author_type": "human",
                "ts": row["ts"],
            },
        }
        out.append((number, fields))
    return out


def _issues(test: _Test, model_rows: bool) -> list[tuple[int, dict[str, Any]]]:
    """Each issue row of the evaluation that the export keeps, as its number in the file from 1
    and the other fields of its record (SPEC.md section 9.4). A row of a person is confirmed. A
    model row is in the export only with `model_rows`."""
    from nookku import issues

    data = test.optional(EVALUATION)
    if data is None:
        return []
    record, found = issues.read(data)
    if record is None:
        raise ExportError(f"Test {test.name}: {found}.")
    out = []
    for n, row in enumerate(record["issues"], 1):
        if row["author"] != "human" and not model_rows:
            continue
        turn = None if row["turn"] is None else test.turn(row["turn"], f"issue {n}")
        fields = {
            "turn": turn,
            "expected": None,
            "observed": None,
            "issue": {"class": row["class"], "evidence": row["evidence"], "text": row["text"]},
            "adjudication": {
                "outcome": OUTCOME,
                "reason": row["text"],
                "author": row["name"],
                "author_type": row["author"],
                "ts": None,
            },
        }
        out.append((n, fields))
    return out


def of_test(
    folder: Path,
    subject: str,
    model_rows: bool = False,
    gate: dict[str, Any] | None = None,
    pins: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The records of the confirmed findings of a test folder: each answer key mismatch with
    the current outcome agent_wrong, in turn order, and then each issue row of a person, in the
    order of evaluation.json. `gate` and `pins` are the gate run of the test and its pinned
    files. Raise ExportError, and give no record, if the seal is not intact or a record of the
    folder is not valid. Thus the export fails closed."""
    from nookku import __version__

    found = subject_problem(subject)
    if found is not None:
        raise ExportError(found[0].upper() + found[1:] + ".")
    test = _Test(folder, pins)
    rows = [(MISMATCH, n, more) for n, more in _mismatches(test)]
    rows += [(ISSUE, n, more) for n, more in _issues(test, model_rows)]
    tail = {"subject": subject, "gate": gate, "nookku": __version__}
    records = [test.record(kind, n, {**more, **tail}) for kind, n, more in rows]
    for record in records:
        found = problem(record)
        if found is not None:
            # The writer never gives a record that its own reader refuses.
            raise ExportError(f"Test {test.name}: the record {record['id']} is not valid: {found}.")
    return records


def of_gate(folder: Path, model_rows: bool = False) -> list[dict[str, Any]]:
    """The records of each test of a gate run (SPEC.md section 7.15), in the order of the gate
    file. The subject is the subject of the gate run. The seal of the gate folder must be intact
    with a same copy, and each test must still have the files that the run pinned, other than
    verdict.json. Raise ExportError."""
    from nookku import gate, state

    check = seal.verify(folder)
    if not check["intact"] or check["copy"] != "same":
        raise ExportError(f"Gate {folder.name}: {seal.summary(check)}")
    files = seal.copy_files(folder.name) or {}
    try:
        run = seal.sealed_bytes(folder, files, gate.RUN)
        result = seal.sealed_bytes(folder, files, gate.RESULT)
        ledger, stored = loads(run.decode("utf-8")), loads(result.decode("utf-8"))
    except ValueError as e:
        raise ExportError(f"Gate {folder.name}: {e}") from None
    subject = ledger.get("subject") if isinstance(ledger, dict) else None
    same = isinstance(stored, dict) and stored.get("subject") == subject
    named = same and stored.get("gate") == folder.name
    if not isinstance(subject, str) or subject_problem(subject) is not None or not named:
        raise ExportError(f"Gate {folder.name}: {gate.RUN} and {gate.RESULT} do not agree.")
    tests_dir = Path(str(ledger.get("tests_dir")))
    rows = ledger.get("tests")
    records: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        test = row.get("test") if isinstance(row, dict) else None
        if not isinstance(test, str) or not state.is_test_id(test):
            continue  # The test did not run, so it has no finding.
        if not (tests_dir / test).is_dir():
            raise ExportError(f"Gate {folder.name}: the test folder {test} does not exist.")
        pins = row.get("files") if isinstance(row.get("files"), dict) else {}
        about = {"id": folder.name, "name": row.get("name"), "result_sha256": files[gate.RESULT]}
        records += of_test(tests_dir / test, subject, model_rows, about, pins)
    return records


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser], tests_dir: str) -> None:
    top = sub.add_parser("finding", help="export or check the finding records of confirmed defects")
    kinds = top.add_subparsers(dest="finding_command", metavar="COMMAND", required=True)
    export = kinds.add_parser("export", help="print the records of a test or of a gate run")
    export.add_argument("test", nargs="?", help="a test id or folder (default: the latest test)")
    export.add_argument("--gate", help="a gate id or folder: export each test of the gate run")
    export.add_argument("--subject", help="the digest of the tested thing, for a test")
    export.add_argument("--model-rows", action="store_true", help="also export the model rows")
    export.add_argument("--root", type=Path, default=Path.cwd())
    export.add_argument("--tests-dir", metavar="PATH", help=tests_dir)
    check = kinds.add_parser("check", help="check each record of a file")
    check.add_argument("file", help="a JSONL file of records, or - for the standard input")
    check.add_argument("--json", action="store_true", help="print the result as JSON")
    kinds.add_parser("schema", help="print the JSON Schema of a record")


def _export(
    args: argparse.Namespace, test_folder: Callable[[Path, str | None], Path | None]
) -> int:
    """nookku finding export: print one record on each line. Exit 2 if it prints no record
    because the input is not valid."""
    from nookku import state

    no = "nookku: no record was written."
    root = args.root.resolve()
    try:
        if args.tests_dir is not None:
            state.set_tests_dir(args.tests_dir)
        state.tests_dir(root)
    except state.TestsDirError as e:
        print(f"{no} {e}", file=sys.stderr)
        return 2
    try:
        if args.gate is not None:
            from nookku import gate

            if args.test is not None or args.subject is not None:
                raise ExportError("--gate takes no TEST and no --subject.")
            found = gate.find(root, args.gate)
            if found is None:
                raise ExportError(f"No gate folder {args.gate}.")
            records = of_gate(found, args.model_rows)
        else:
            if args.subject is None:
                raise ExportError("Give the digest of the tested thing with --subject.")
            folder = test_folder(root, args.test)
            if folder is None:
                return 2
            records = of_test(folder, args.subject, args.model_rows)
    except ExportError as e:
        print(f"{no} {e}", file=sys.stderr)
        return 2
    text = "".join(json_text(record) + "\n" for record in records)
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.flush()
    print(f"nookku: {len(records)} finding records.", file=sys.stderr)
    return 0


def _check(args: argparse.Namespace) -> int:
    """nookku finding check: exit 0 if each line of the file is a valid record, 1 if a line is
    not, and 2 if the file cannot be read."""
    try:
        data = sys.stdin.buffer.read() if args.file == "-" else Path(args.file).read_bytes()
        rows = check_lines(data)
    except (OSError, ValueError) as e:
        print(f"nookku: {e}", file=sys.stderr)
        return 2
    bad = [r for r in rows if r["problem"] is not None]
    if args.json:
        print(json.dumps({"records": len(rows), "valid": not bad, "lines": rows}))
    else:
        for r in rows:
            print(
                f"line {r['line']}: " + (f"ok {r['id']}" if r["problem"] is None else r["problem"])
            )
        print(f"{len(rows)} records, {len(bad)} not valid.")
    return 1 if bad else 0


def command(
    args: argparse.Namespace, test_folder: Callable[[Path, str | None], Path | None]
) -> int:
    """nookku finding (SPEC.md section 10). The command reads, and it writes no file."""
    if args.finding_command == "export":
        return _export(args, test_folder)
    if args.finding_command == "check":
        return _check(args)
    sys.stdout.write(schema_text())
    return 0

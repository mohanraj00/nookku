"""The gate file of a gate run: its tests and its proof files (SPEC.md section 7.15).

`parse` gives the declared tests and `parse_proofs` gives the declared proof files. Each one
refuses a gate file that breaks a rule, so that no test runs.
"""

from __future__ import annotations

import math
import os
from typing import Any

from nookku import state, verdict
from nookku.record import json_text, loads
from nookku.trace import CHECKS

VERSION = 1
MAX_TESTS = 200
MAX_PROOFS = 200
# The most keys in the field path of a bound. This is a chosen value.
MAX_FIELD = 32
PROOF_KEYS = {"path", "max_age", "bound"}
KEYS = {"name", "script", "entry", "limits", "persona", "replay"}
# The declared files of a test, and their names in inputs/<test name>/. The script name gets
# the extension of its form, as the copy in the test folder (SPEC.md section 7.10).
FILE_KEYS = ("script", "persona")
# Nookku 0.6.2 and older accepted the test key answer_key (#617). The app spec declares the
# answer key (SPEC.md section 7.17), so the refusal names its section.
REMOVED_ANSWER_KEY = (
    "has the key answer_key, which this version does not know. Declare the answer key in the "
    "Answer key section of the app spec (SPEC.md section 7.17)."
)


class GateError(ValueError):
    """A gate file or a subject that breaks a rule. No test runs."""


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise GateError(f"the key {json_text(key)} occurs 2 times in one object")
        out[key] = value
    return out


def _path(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise GateError(f"{where} must be a path that is not empty")
    if os.path.isabs(value):
        raise GateError(f"{where} must be a path relative to the folder of the gate file")
    return value


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= verdict.MOST


def read_top(data: bytes) -> dict[str, Any]:
    """The top object of the bytes of a gate file. Raise GateError."""
    try:
        top = loads(data.decode("utf-8"), object_pairs_hook=no_duplicates)
    except UnicodeDecodeError as e:
        raise GateError(f"the gate file is not UTF-8: {e}") from None
    except GateError:
        raise
    except ValueError as e:
        raise GateError(f"the gate file is not JSON: {e}") from None
    if not isinstance(top, dict) or not {"v", "tests"} <= set(top) <= {"v", "tests", "proofs"}:
        raise GateError(
            'the gate file must be an object with the keys "v" and "tests", and optional "proofs"'
        )
    if type(top["v"]) is not int or top["v"] != VERSION:
        raise GateError(f"the gate file version must be {VERSION}")
    return top


def parse(data: bytes) -> list[dict[str, Any]]:
    """The declared tests of the bytes of a gate file, in order. Raise GateError."""
    top = read_top(data)
    parse_proofs(data)
    tests = top["tests"]
    if not isinstance(tests, list) or not 1 <= len(tests) <= MAX_TESTS:
        raise GateError(f'"tests" must be a list of 1 to {MAX_TESTS} tests')
    names: set[str] = set()
    out = []
    for n, test in enumerate(tests, 1):
        where = f"test {n}"
        if not isinstance(test, dict):
            raise GateError(f"{where} must be an object")
        if "answer_key" in test:
            raise GateError(f"{where} {REMOVED_ANSWER_KEY}")
        unknown = sorted(set(test) - KEYS)
        if unknown:
            raise GateError(f"{where} has a key that this version does not know: {unknown[0]}")
        name = test.get("name")
        if not isinstance(name, str) or not state.is_test_id(name):
            raise GateError(f"{where}: the name must have the form of a test id")
        if name in names:
            raise GateError(f"{where}: the name {name} occurs in an earlier test")
        names.add(name)
        if "script" not in test:
            raise GateError(f"{where} has no script")
        row: dict[str, Any] = {"name": name, "entry": None, "limits": {}}
        for key in FILE_KEYS:
            row[key] = _path(test[key], f"{where}: {key}") if key in test else None
        if "entry" in test:
            if not isinstance(test["entry"], str) or not test["entry"]:
                raise GateError(f"{where}: the entry must be the name of an entry")
            row["entry"] = test["entry"]
        limits = test.get("limits", {})
        if not isinstance(limits, dict):
            raise GateError(f"{where}: limits must be an object")
        for check, most in limits.items():
            if check not in CHECKS:
                raise GateError(f"{where}: {json_text(check)} is not a check of the trace")
            if not _is_count(most):
                raise GateError(f"{where}: the limit of {check} is not a whole number")
        row["limits"] = dict(limits)
        row["replay"] = _replay(test["replay"], where) if "replay" in test else None
        out.append(row)
    return out


def parse_proofs(data: bytes) -> list[dict[str, Any]]:
    """The declared proof files of the bytes of a gate file, in order: the path, the most age
    in seconds, and the bound (the field path and its most value) or None. Raise GateError."""
    proofs = read_top(data).get("proofs", [])
    if not isinstance(proofs, list) or len(proofs) > MAX_PROOFS:
        raise GateError(f'"proofs" must be a list of 0 to {MAX_PROOFS} proof files')
    out: list[dict[str, Any]] = []
    for n, proof in enumerate(proofs, 1):
        where = f"proof file {n}"
        if not isinstance(proof, dict) or not {"path", "max_age"} <= set(proof) <= PROOF_KEYS:
            raise GateError(
                f'{where} must be an object with the keys "path" and "max_age", and optional '
                '"bound"'
            )
        path = _path(proof["path"], f"{where}: path")
        if any(p["path"] == path for p in out):
            raise GateError(f"{where}: the path {path} occurs in an earlier proof file")
        age = proof["max_age"]
        if not _is_count(age) or age < 1:
            raise GateError(f"{where}: max_age must be a whole number of seconds from 1")
        out.append({"path": path, "max_age": age, "bound": _bound(proof.get("bound"), where)})
    return out


def _bound(value: Any, where: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"field", "most"}:
        raise GateError(f'{where}: bound must be an object with only the keys "field" and "most"')
    field = value["field"]
    if (
        not isinstance(field, list)
        or not 1 <= len(field) <= MAX_FIELD
        or not all(isinstance(k, str) for k in field)
    ):
        raise GateError(f"{where}: the bound field must be a list of 1 to {MAX_FIELD} keys")
    if not is_number(value["most"]):
        raise GateError(f"{where}: the bound most must be a number")
    return {"field": list(field), "most": value["most"]}


def is_number(value: Any) -> bool:
    # A JSON integer can be too large for a float, so only a float gets the finite check.
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, int) and not isinstance(value, bool)


def _replay(value: Any, where: str) -> dict[str, Any]:
    """The replay check of a test: the id of the base test and the most changed turns."""
    if not isinstance(value, dict) or set(value) != {"base", "changed"}:
        raise GateError(
            f'{where}: replay must be an object with only the keys "base" and "changed"'
        )
    if not isinstance(value["base"], str) or not state.is_test_id(value["base"]):
        raise GateError(f"{where}: the replay base must be a test id")
    if not _is_count(value["changed"]):
        raise GateError(f"{where}: the replay changed must be a whole number")
    return {"base": value["base"], "changed": value["changed"]}

"""The gate run: one declared set of scripted tests and one sealed result (SPEC.md section 7.15).

A gate file declares the tests and the proof files. `run` runs each test as `nookku run
--script --verdict` does, and writes one result folder: the gate file, a copy of each declared
file, the ledger of the run (run.json), the result (result.json) and a seal. The caller gives
the subject digest, and Nookku does not interpret it. `verify` reads each file one time, checks
it against the copy of the seal, and computes the result again. Each check is deterministic
and needs no model.
"""

from __future__ import annotations

import datetime
import math
import os
import secrets
import shutil
import stat
import time
from pathlib import Path
from typing import Any, TypeGuard

from nookku import bridge, discovery, replay, script, seal, state, verdict
from nookku.record import RecordError, json_text, loads
from nookku.trace import CHECKS

VERSION = 1
GATES = "gates"
GATE_FILE = "gate.json"
RUN = "run.json"
RESULT = "result.json"
INPUTS = "inputs"
# The copies of the declared proof files in the gate folder: proofs/<n>, from 1 (#572).
PROOFS = "proofs"
MAX_PROOFS = 200
# The most keys in the field path of a bound. This is a chosen value.
MAX_FIELD = 32
PROOF_KEYS = {"path", "max_age", "bound"}
# The reasons of a proof file that fails (SPEC.md section 7.15).
MISSING, STALE, ABOVE_LIMIT = "missing", "stale", "above_limit"
PREFIX = "gate-"
MAX_TESTS = 200
SUBJECT_MAX = 512
KEYS = {"name", "script", "entry", "limits", "answer_key", "persona", "replay"}
# The declared files of a test, and their names in inputs/<test name>/. The script name gets
# the extension of its form, as the copy in the test folder (SPEC.md section 7.10).
FILE_KEYS = ("script", "answer_key", "persona")
AUDIT, RELAY, TAP = "audit.json", "relay.jsonl", "tap.jsonl"
# The files of the base test and of the new test that the replay check reads (SPEC.md 7.15).
REPLAY_FILES = (RELAY, TAP)
# The files of a test folder that the checks read, with the script copy of the test.
EVIDENCE = (verdict.MANIFEST, verdict.FINDINGS, verdict.FILE, AUDIT, RELAY)
PASS, FAIL = verdict.PASS, verdict.FAIL


class GateError(ValueError):
    """A gate file or a subject that breaks a rule. No test runs."""


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
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


def _top(data: bytes) -> dict[str, Any]:
    """The top object of the bytes of a gate file. Raise GateError."""
    try:
        top = loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
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
    top = _top(data)
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
    proofs = _top(data).get("proofs", [])
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
    if not _is_number(value["most"]):
        raise GateError(f"{where}: the bound most must be a number")
    return {"field": list(field), "most": value["most"]}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_proof(path: Path) -> tuple[bytes | None, int | None, str | None]:
    """The bytes and the modified time (whole Unix seconds) of a proof file, or the error.
    It reads only a regular file, and it does not wait on a pipe."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        return None, None, f"cannot read the file: {e.strerror or e}"
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, None, "the path is not a regular file"
        with os.fdopen(fd, "rb", closefd=False) as f:
            body = f.read()
    except OSError as e:
        return None, None, f"cannot read the file: {e.strerror or e}"
    finally:
        os.close(fd)
    return body, info.st_mtime_ns // 1_000_000_000, None


def proof_row(
    path: str, body: bytes | None, modified: int | None, checked: int, error: str | None
) -> dict[str, Any]:
    """The ledger row of a proof file: its SHA-256 and its modified time when the run read it,
    the time of the read, and why the read failed, or None."""
    return {
        "path": path,
        "sha256": None if body is None else seal.sha256_of(body),
        "modified": modified,
        "checked": checked,
        "error": error,
    }


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


def base_pin(tests_dir: Path, base: str) -> dict[str, Any]:
    """The ledger record of the base test of a replay check: its id and the SHA-256 of its
    relay and tap records in the copy of its seal. A base with no seal copy pins no file."""
    copy = (seal.copy_files(base) or {}) if (tests_dir / base).is_dir() else {}
    return {
        "base": base,
        "files": {n: copy[n] for n in REPLAY_FILES if isinstance(copy.get(n), str)},
    }


def subject_problem(subject: str) -> str | None:
    """Why the subject is not valid, or None. It is an opaque string from the caller."""
    if not 1 <= len(subject) <= SUBJECT_MAX:
        return f"the subject must have 1 to {SUBJECT_MAX} characters"
    if any(ord(c) < 32 or ord(c) == 127 for c in subject):
        return "the subject must have no control character"
    return None


def folder_of(root: Path) -> Path:
    return state.state(root) / GATES


def _new_folder(root: Path) -> Path:
    parent = folder_of(root)
    parent.mkdir(parents=True, exist_ok=True)
    stamp = PREFIX + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    # The seal copy is $NOOKKU_HOME/seals/<gate id>.json, and other projects
    # can share NOOKKU_HOME. Thus the id has a random part, as a test id has.
    for _ in range(100):
        folder = parent / f"{stamp}-{secrets.token_hex(4)}"
        if seal.copy_path(folder.name).exists():
            continue
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return folder
    raise GateError(f"cannot make a new gate folder in {parent}")


def _input_name(key: str, form: str | None) -> str:
    return script.COPIES[form] if key == "script" and form else key


# The keys of the test start that the gate pins before the first test, and the
# entry check compares with the manifest of each test.
PINNED = ("entry", "policy", "spec", "config_sha256")


def pin(root: Path, entry_name: str | None) -> dict[str, Any]:
    """The resolved entry, the config hashes and the spec of a test start. Raise
    bridge.BridgeError if the config gives no start for the entry."""
    conf = bridge.load_config(root, entry_name)
    hashes = bridge.config_hashes(root)
    return {"entry": conf.entry, "policy": conf.policy, "spec": conf.spec, "config_sha256": hashes}


def _same_start(manifest: dict[str, Any], row: dict[str, Any]) -> bool:
    """True if the start keys of a manifest are the ones that the gate pinned. A test start
    adds state files to the config hashes, so only the pinned files must be the same."""
    if any(manifest.get(k) != row.get(k) for k in ("entry", "policy", "spec")):
        return False
    hashes, pinned = manifest.get("config_sha256"), row.get("config_sha256")
    if not isinstance(hashes, dict) or not isinstance(pinned, dict):
        return False
    return all(hashes.get(name) == sha for name, sha in pinned.items())


def ledger_row(
    name: str,
    folder: Path | None,
    error: str | None,
    pinned: dict[str, Any] | None = None,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The ledger row of a test: the test id, the start keys that the gate pinned before the
    first test, and the SHA-256 of each file that the checks read, from the copy of the test
    seal. A test with a replay check also has `replay`, the base pin (base_pin), and pins
    tap.jsonl."""
    row: dict[str, Any] = {"name": name, "test": None, "error": error, "files": {}}
    row.update({k: (pinned or {}).get(k) for k in PINNED})
    if base is not None:
        row["replay"] = base
    if folder is None:
        return row
    row["test"] = folder.name
    copy = seal.copy_files(folder.name) or {}
    names = [*EVIDENCE, *script.COPIES.values(), *([TAP] if base is not None else [])]
    row["files"] = {n: copy[n] for n in names if isinstance(copy.get(n), str)}
    return row


def run(root: Path, gate_path: Path, subject: str) -> tuple[Path, list[str]]:
    """Run each declared test, write the result folder, and return it with the lines of each
    test run. Raise GateError if the gate file or the subject is not valid or no egress answer
    exists. Then no test runs and no folder is written."""
    problem = subject_problem(subject)
    if problem:
        raise GateError(problem)
    try:
        data = gate_path.read_bytes()
    except OSError as e:
        raise GateError(f"cannot read the gate file {gate_path}: {e}") from None
    tests = parse(data)
    declared_proofs = parse_proofs(data)
    egress = discovery.pending(root)
    if egress is None:
        raise GateError(discovery.no_answer())
    tests_dir = state.tests_dir(root).absolute()
    base = gate_path.absolute().parent
    folder = _new_folder(root)
    (folder / GATE_FILE).write_bytes(data)
    # Snapshot each input of each test before the first test starts. A test can change a
    # project file, so a later read could give bytes that the gate did not declare.
    planned: list[
        tuple[dict[str, Any], Path | None, str | None, dict[str, Any] | None, dict[str, Any] | None]
    ] = []
    # The gate keeps the bytes of each snapshot. A tested entry can write to the result
    # folder, so the gate compares the files to these bytes and seals only these bytes.
    held: dict[str, dict[str, bytes]] = {}
    for test in tests:
        inputs = folder / INPUTS / test["name"]
        inputs.mkdir(parents=True)
        error, form = None, None
        for key in FILE_KEYS:
            if test[key] is None:
                continue
            try:
                body = (base / test[key]).read_bytes()
                if key == "script":
                    form = script.parse(body)[1]
            except (OSError, script.ScriptError) as e:
                error = error or f"{key} {test[key]}: {e}"
                continue
            (inputs / _input_name(key, form)).write_bytes(body)
            held.setdefault(test["name"], {})[_input_name(key, form)] = body
        pinned = None
        if error is None:
            # A tested entry can change the config, so the gate reads it before test 1.
            try:
                pinned = pin(root, test["entry"])
            except bridge.BridgeError as e:
                error = f"the test did not start: {e}"
        snapshot = None if error else inputs / _input_name("script", form)
        # The base of a replay check is pinned before test 1, so a test cannot change it.
        replay_pin = None if test["replay"] is None else base_pin(tests_dir, test["replay"]["base"])
        planned.append((test, snapshot, error, pinned, replay_pin))
    rows, lines = [], []
    try:
        for test, snapshot, error, pinned, replay_pin in planned:
            if snapshot is None:
                rows.append(ledger_row(test["name"], None, error, None, replay_pin))
                lines.append(f"Test {test['name']}: did not run. {error}")
                continue
            if _read_inputs(folder / INPUTS / test["name"]) != held.get(test["name"], {}):
                error = "the snapshot of the test inputs changed before the test started"
                rows.append(ledger_row(test["name"], None, error, pinned, replay_pin))
                lines.append(f"Test {test['name']}: did not run. {error}")
                continue
            try:
                _, out, test_folder = bridge.run_script(
                    root, snapshot, test["entry"], egress, gate=True
                )
            except bridge.BridgeError as e:
                why = f"the test did not start: {e}"
                rows.append(ledger_row(test["name"], None, why, pinned, replay_pin))
                lines.append(f"Test {test['name']}: did not run. {e}")
                continue
            rows.append(ledger_row(test["name"], test_folder, None, pinned, replay_pin))
            lines += [f"Test {test['name']}: {line}" for line in out]
    finally:
        # The run used the answer for each test. The next run needs a new answer.
        discovery.take(root)
    # A test can make a proof file, so the run reads each one after the last test. The gate
    # keeps the bytes and seals only these bytes.
    proof_rows, proof_bytes = [], {}
    for n, proof in enumerate(declared_proofs, 1):
        body, modified, error = read_proof(base / proof["path"])
        proof_rows.append(proof_row(proof["path"], body, modified, int(time.time()), error))
        if body is not None:
            proof_bytes[n] = body
    ledger = {
        "v": VERSION,
        "gate": folder.name,
        "subject": subject,
        "tests_dir": str(tests_dir),
        "tests": rows,
        "proofs": proof_rows,
    }
    _restore(folder, data, held, [test["name"] for test in tests], proof_bytes)
    (folder / RUN).write_text(json_text(ledger, indent=1) + "\n", encoding="utf-8")
    result = compute(folder.name, data, held, ledger, read_evidence(ledger), proof_bytes)
    (folder / RESULT).write_text(json_text(result, indent=1) + "\n", encoding="utf-8")
    seal.write(folder)
    return folder, lines


def _read_inputs(path: Path) -> dict[str, bytes] | None:
    if path.is_symlink() or not path.is_dir():
        return None
    try:
        return {f.name: f.read_bytes() for f in sorted(path.iterdir()) if f.is_file()}
    except OSError:
        return None


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _restore(
    folder: Path,
    data: bytes,
    held: dict[str, dict[str, bytes]],
    names: list[str],
    proofs: dict[int, bytes],
) -> None:
    """Write the gate file, each snapshot and each proof copy again from the bytes that the
    gate read, so that the seal covers only those bytes."""
    _remove(folder / GATE_FILE)
    (folder / GATE_FILE).write_bytes(data)
    _remove(folder / INPUTS)
    for name in names:
        (folder / INPUTS / name).mkdir(parents=True)
        for file, body in held.get(name, {}).items():
            (folder / INPUTS / name / file).write_bytes(body)
    _remove(folder / PROOFS)
    if proofs:
        (folder / PROOFS).mkdir()
    for n, body in proofs.items():
        (folder / PROOFS / str(n)).write_bytes(body)


def read_evidence(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each test of the ledger: the problem of its seal or None, the files of the copy of
    its seal, and the bytes of each pinned file, read one time."""
    out: dict[str, dict[str, Any]] = {}
    tests_dir = Path(str(ledger.get("tests_dir")))
    for row in ledger.get("tests") or []:
        test = row.get("test") if isinstance(row, dict) else None
        if not isinstance(test, str) or not state.is_test_id(test):
            continue
        folder = tests_dir / test
        result = seal.verify(folder)
        problem = None
        if not result["intact"] or result["copy"] != "same":
            problem = f"The seal of the test is not intact with a copy. {seal.summary(result)}"
        data: dict[str, bytes | None] = {}
        files = row.get("files") if isinstance(row.get("files"), dict) else {}
        # Only the names of the evidence: run.json cannot make the process read another file.
        for name in (n for n in files if n in (*EVIDENCE, TAP, *script.COPIES.values())):
            data[name] = _bytes(folder / name)
        out[test] = {"seal": problem, "copy": seal.copy_files(test), "files": data}
        pin = row.get("replay")
        base = pin.get("base") if isinstance(pin, dict) else None
        if isinstance(base, str) and state.is_test_id(base):
            out[test]["base"] = _base_evidence(tests_dir / base, pin.get("files"))
    return out


def _bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _base_evidence(folder: Path, files: Any) -> dict[str, Any]:
    """The evidence of the base test of a replay check: if its folder exists, the problem of
    its seal or None, the files of the copy of its seal, and the bytes of each pinned file."""
    if not folder.is_dir():
        return {"exists": False}
    result = seal.verify(folder)
    problem = None
    if not result["intact"] or result["copy"] != "same":
        problem = f"The seal of the base test is not intact with a copy. {seal.summary(result)}"
    names = [n for n in (files if isinstance(files, dict) else {}) if n in REPLAY_FILES]
    data = {n: _bytes(folder / n) for n in names}
    return {"exists": True, "seal": problem, "copy": seal.copy_files(folder.name), "files": data}


def _pin_problem(
    file: str, pinned: dict[str, Any], copy: dict[str, Any], data: dict[str, bytes | None]
) -> str | None:
    """Why a pinned file of a test cannot be used, or None."""
    if file not in pinned:
        return f"The ledger pins no SHA-256 of {file}."
    if copy.get(file) != pinned[file]:
        return f"{file} in the copy of the test seal is not the file of the gate run."
    if data.get(file) is None:
        return f"{file} cannot be read."
    if seal.sha256_of(data[file] or b"") != pinned[file]:
        return f"{file} is not the file of the gate run."
    return None


def _check(name: str, ok: bool, text: str | None = None) -> dict[str, Any]:
    return {"check": name, "verdict": PASS if ok else FAIL, "text": None if ok else text}


def _json(data: bytes | None) -> Any:
    if data is None:
        return None
    try:
        return loads(data.decode("utf-8"))
    except ValueError:
        return None


def _turns(data: bytes | None) -> list[tuple[Any, Any]] | None:
    if data is None:
        return None
    rows = []
    try:
        # Split only at "\n", as the record reader does. U+2028 can be in a JSON string.
        for line in data.decode("utf-8").split("\n"):
            if line.strip():
                row = loads(line)
                if isinstance(row, dict) and row.get("type") == "turn":
                    rows.append((row.get("said"), row.get("ok")))
    except ValueError:
        return None
    return rows


def _test_checks(
    declared: dict[str, Any],
    row: dict[str, Any] | None,
    inputs: dict[str, bytes],
    proof: dict[str, Any] | None,
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    """The checks of one declared test. The first check that cannot use its records stops the
    list, so that no later check reads bytes that the seal does not cover. `record` gets the
    changed turns of a replay check."""
    name = declared["name"]
    if row is None or row.get("name") != name:
        return [_check("missing_test", False, "The ledger has no row for the test.")]
    if row.get("error") is not None or row.get("test") is None or proof is None:
        why = row.get("error") or "The test did not run."
        return [_check("missing_test", False, str(why))]
    checks = [_check("missing_test", True)]
    pinned: dict[str, Any] = row["files"] if isinstance(row.get("files"), dict) else {}
    copy = proof.get("copy") or {}
    data: dict[str, bytes | None] = proof.get("files") or {}
    form: str | None = None
    snapshot: bytes | None = None
    for key, body in inputs.items():
        if key in script.COPIES.values():
            snapshot, form = body, key
    problem = proof.get("seal")
    tap = [TAP] if declared["replay"] is not None else []
    needed = [*EVIDENCE, *tap, *([form] if form else [])]
    for file in needed:
        if problem:
            break
        problem = _pin_problem(file, pinned, copy, data)
    checks.append(_check("evidence", problem is None, problem))
    if problem is not None:
        return checks
    manifest = _json(data[verdict.MANIFEST])
    if not isinstance(manifest, dict):
        return [*checks, _check("verdict", False, "manifest.json is not a JSON object.")]
    sha = script.sha256(snapshot) if snapshot is not None else None
    recorded: dict[str, Any] = (
        manifest["script"] if isinstance(manifest.get("script"), dict) else {}
    )
    ok = (
        sha is not None
        and form is not None
        and recorded.get("file") == form
        and recorded.get("sha256") == sha
        and seal.sha256_of(data.get(form) or b"") == sha
    )
    checks.append(_check("script", ok, "The script copy of the test is not the declared script."))
    ok = manifest.get("entry_name") == declared["entry"] and _same_start(manifest, row)
    text = "The entry, the config or the spec of the test is not the one that the gate pinned."
    checks.append(_check("entry", ok, text))
    report = verdict.compute(row["test"], manifest, [], data[verdict.FINDINGS])
    stored = _json(data[verdict.FILE])
    if stored != report:
        text = f"{verdict.FILE} is not the verdict of {verdict.MANIFEST} and {verdict.FINDINGS}."
        checks.append(_check("verdict", False, text))
    else:
        checks.append(_check("verdict", report["verdict"] == PASS, verdict.summary(report)))
    counts = {c["check"]: c["count"] for c in report["classes"]}
    over = [
        f"{c}: {'no valid count' if counts.get(c) is None else counts[c]}, the limit is {most}"
        for c, most in declared["limits"].items()
        if counts.get(c) is None or counts[c] > most
    ]
    checks.append(_check("limits", not over, "; ".join(over) + "."))
    audit = _json(data[AUDIT])
    ok = (
        isinstance(audit, dict)
        and type(audit.get("exit")) is int
        and audit["exit"] == 0
        and audit.get("breaks") == []
        and audit.get("errors") == []
    )
    checks.append(_check("audit", ok, "audit.json does not exit with 0 with no break and error."))
    try:
        messages = script.parse(snapshot or b"")[0]
    except script.ScriptError:
        messages = None
    turns = _turns(data[RELAY])
    ok = messages is not None and turns == [(m, True) for m in messages]
    text = "The relay record does not have one turn with a reply for each message of the script."
    checks.append(_check("turns", ok, text))
    changed = bridge.gate_changed(manifest)
    checks.append(_check("codex_hooks", changed is None, f"The Codex hooks changed: {changed}"))
    if declared["answer_key"] is not None:
        text = "This version of Nookku has no answer key check, so a declared key fails."
        checks.append(_check("answer_key", False, text))
    if declared["replay"] is not None:
        checks += _replay_checks(declared["replay"], row, proof, data, record)
    return checks


def _replay_checks(
    want: dict[str, Any],
    row: dict[str, Any],
    proof: dict[str, Any],
    data: dict[str, bytes | None],
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    """The checks missing_base and changed_turns of a replay check. They compare the sealed
    relay and tap records of the base test and of the new test with the rule of `nookku
    replay` (SPEC.md section 7.10). `record` gets the count and the number of each changed
    turn."""
    base = want["base"]
    value = row.get("replay")
    pin: dict[str, Any] = value if isinstance(value, dict) else {}
    found = proof.get("base")
    info: dict[str, Any] = found if isinstance(found, dict) else {}
    problem = None
    if pin.get("base") != base:
        problem = "The ledger does not pin the declared base test."
    elif not info.get("exists"):
        problem = f"The base test {base} does not exist."
    elif info.get("seal"):
        problem = info["seal"]
    else:
        value = pin.get("files")
        files: dict[str, Any] = value if isinstance(value, dict) else {}
        for file in REPLAY_FILES:
            problem = problem or _pin_problem(file, files, info.get("copy") or {}, info["files"])
    if problem is not None:
        return [_check("missing_base", False, problem)]
    out = [_check("missing_base", True)]
    try:
        old = replay.replies(Path(base), info["files"][RELAY], info["files"][TAP])
        new = replay.replies(Path(str(row["test"])), data[RELAY], data[TAP])
    except RecordError as e:
        return [*out, _check("changed_turns", False, f"A record is not valid: {e}")]
    turns = replay.changed_turns(old, new)
    record.update(changed=len(turns), turns=turns)
    numbers = ", ".join(str(n) for n in turns)
    text = f"{len(turns)} changed turns, the limit is {want['changed']}. The turns: {numbers}."
    return [*out, _check("changed_turns", len(turns) <= want["changed"], text)]


def compute(
    gate: str,
    data: bytes,
    inputs: dict[str, dict[str, bytes]],
    ledger: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    proofs: dict[int, bytes] | None = None,
) -> dict[str, Any]:
    """The result of a gate run from the bytes of the gate file, the bytes of the inputs of each
    test, the ledger, the evidence of each test and the copy of each proof file, by its number
    from 1. It reads no file."""
    declared = parse(data)
    rows: list[Any] = ledger["tests"] if isinstance(ledger.get("tests"), list) else []
    subject = ledger.get("subject")
    problems = []
    if ledger.get("v") != VERSION or ledger.get("gate") != gate:
        problems.append("run.json does not name this gate run.")
    if not isinstance(subject, str) or subject_problem(subject):
        problems.append("run.json has no valid subject.")
    if len(rows) != len(declared):
        problems.append("run.json does not have one row for each declared test.")
    ids = [r.get("test") for r in rows if isinstance(r, dict) and r.get("test") is not None]
    if len(ids) != len(set(ids)):
        problems.append("run.json names one test for 2 declared tests.")
    tests = []
    for n, test in enumerate(declared):
        row = rows[n] if n < len(rows) and isinstance(rows[n], dict) else None
        proof = evidence.get(row["test"]) if row and isinstance(row.get("test"), str) else None
        record: dict[str, Any] = {"changed": None, "turns": None}
        checks = _test_checks(test, row, inputs.get(test["name"], {}), proof, record)
        ok = all(c["verdict"] == PASS for c in checks)
        out: dict[str, Any] = {
            "name": test["name"],
            "test": row.get("test") if row else None,
            "verdict": PASS if ok else FAIL,
            "checks": checks,
        }
        if test["replay"] is not None:
            # The base test, the new test and the changed turns of the replay (SPEC.md 7.15).
            out["replay"] = {
                "base": test["replay"]["base"],
                "test": out["test"],
                "most": test["replay"]["changed"],
                **record,
            }
        tests.append(out)
    reasons: list[dict[str, Any]] = [
        {"test": t["name"], "check": c["check"]}
        for t in tests
        for c in t["checks"]
        if c["verdict"] == FAIL
    ]
    checked = _proof_results(parse_proofs(data), ledger, proofs or {}, problems)
    reasons += [{"proof": p["path"], "check": f["reason"]} for p in checked for f in p["failures"]]
    passed = not problems and not reasons
    return {
        "v": VERSION,
        "gate": gate,
        "subject": subject if isinstance(subject, str) else None,
        "gate_sha256": seal.sha256_of(data),
        "verdict": PASS if passed else FAIL,
        "problems": problems,
        "reasons": reasons,
        "tests": tests,
        "proofs": checked,
    }


def _proof_results(
    declared: list[dict[str, Any]],
    ledger: dict[str, Any],
    copies: dict[int, bytes],
    problems: list[str],
) -> list[dict[str, Any]]:
    """The result of each declared proof file, from its ledger row and its copy. A ledger that
    does not pin each copy adds a problem."""
    rows = ledger.get("proofs", [])
    if not isinstance(rows, list) or len(rows) != len(declared):
        problems.append("run.json does not have one row for each declared proof file.")
        rows = []
    out = []
    for n, proof in enumerate(declared, 1):
        row = rows[n - 1] if n <= len(rows) and isinstance(rows[n - 1], dict) else {}
        body = copies.get(n)
        sha = None if body is None else seal.sha256_of(body)
        checked, modified = row.get("checked"), row.get("modified")
        if (
            row.get("path") != proof["path"]
            or row.get("sha256") != sha
            or not _is_whole(checked)
            or (body is None) != (modified is None)
            or (modified is not None and not _is_whole(modified))
        ):
            problems.append(f"run.json does not pin the copy of the proof file {proof['path']}.")
        result: dict[str, Any] = {
            "path": proof["path"],
            "sha256": sha,
            "age": None,
            "value": None,
            "verdict": FAIL,
            "failures": [],
        }
        if body is None or not _is_whole(checked) or not _is_whole(modified):
            error = row.get("error") if isinstance(row.get("error"), str) else "no copy"
            result["failures"].append({"reason": MISSING, "text": f"The file is missing: {error}."})
            out.append(result)
            continue
        age = checked - modified
        result["age"] = age
        if not 0 <= age <= proof["max_age"]:
            result["failures"].append(
                {
                    "reason": STALE,
                    "text": f"The file is {age} seconds old, the limit is {proof['max_age']}.",
                }
            )
        if proof["bound"] is not None:
            value, why = _field(body, proof["bound"]["field"])
            result["value"] = value
            most = proof["bound"]["most"]
            if why is None and value is not None and value > most:
                why = f"The value is {json_text(value)}, the limit is {json_text(most)}."
            if why is not None:
                result["failures"].append({"reason": ABOVE_LIMIT, "text": why})
        result["verdict"] = FAIL if result["failures"] else PASS
        out.append(result)
    return out


def _is_whole(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _field(body: bytes, field: list[str]) -> tuple[Any, str | None]:
    """The number at the field path of a JSON proof file, or None and why the bound cannot be
    shown to hold."""
    try:
        value = loads(body.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        return None, "The file is not UTF-8 JSON with no repeated key."
    for key in field:
        if not isinstance(value, dict) or key not in value:
            return None, f"The file has no field {json_text(field)}."
        value = value[key]
    if not _is_number(value):
        return None, f"The field {json_text(field)} is not a number."
    return value, None


def verify(folder: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The result of a gate folder that a process can use, or None and the reason.

    The seal of the folder must be intact with a same copy. The process reads each file of the
    folder one time, and its SHA-256 must be the SHA-256 in the copy of the seal. Each pinned
    file of each test must have its pinned SHA-256. The result that the process computes again
    from these bytes must be result.json."""
    result = seal.verify(folder)
    if not result["intact"] or result["copy"] != "same":
        return None, f"The seal of the gate is not intact with a copy. {seal.summary(result)}"
    files = seal.copy_files(folder.name) or {}
    data: dict[str, bytes] = {}
    for name, sha in sorted(files.items()):
        try:
            data[name] = (folder / name).read_bytes()
        except OSError:
            return None, f"{name} cannot be read."
        if seal.sha256_of(data[name]) != sha:
            return None, f"{name} is not the file of the seal."
    for name in (GATE_FILE, RUN, RESULT):
        if name not in data:
            return None, f"The copy of the seal does not cover {name}."
    ledger, stored = _json(data[RUN]), _json(data[RESULT])
    if not isinstance(ledger, dict):
        return None, f"{RUN} is not a JSON object."
    inputs: dict[str, dict[str, bytes]] = {}
    proofs: dict[int, bytes] = {}
    for name, body in data.items():
        parts = name.split("/")
        if len(parts) == 3 and parts[0] == INPUTS:
            inputs.setdefault(parts[1], {})[parts[2]] = body
        if len(parts) == 2 and parts[0] == PROOFS and parts[1].isdigit():
            proofs[int(parts[1])] = body
    try:
        report = compute(
            folder.name, data[GATE_FILE], inputs, ledger, read_evidence(ledger), proofs
        )
    except GateError as e:
        return None, f"{GATE_FILE} is not valid: {e}"
    if stored != report:
        why = f"{RESULT} is not the result of the sealed files and the test folders."
        failed = [
            f"{t['name']} {c['check']}: {c['text']}"
            for t in report["tests"]
            for c in t["checks"]
            if c["verdict"] == FAIL
        ] + [
            f"{p['path']} {f['reason']}: {f['text']}"
            for p in report["proofs"]
            for f in p["failures"]
        ]
        return None, " ".join([why, *(f"The new result has {f}" for f in failed[:3])])
    return report, None


def find(root: Path, gate: str | None) -> Path | None:
    """The gate folder of a gate id or a path, else the newest gate folder."""
    if gate is not None:
        path = Path(gate)
        if path.is_dir():
            return path
        found = folder_of(root) / gate
        return found if state.is_test_id(gate) and found.is_dir() else None
    top = folder_of(root)
    folders = [p for p in top.iterdir() if p.is_dir()] if top.is_dir() else []
    return max(folders, key=lambda p: (p.stat().st_mtime_ns, p.name)) if folders else None


def summary(report: dict[str, Any]) -> list[str]:
    """The lines of a result: one line for each test and one line with the verdict."""
    lines = []
    for test in report["tests"]:
        failed = [c for c in test["checks"] if c["verdict"] == FAIL]
        text = "; ".join(f"{c['check']}: {c['text']}" for c in failed)
        lines.append(f"{test['name']} ({test['test'] or 'no test'}): {test['verdict']}. {text}")
    for proof in report.get("proofs", []):
        text = "; ".join(f"{f['reason']}: {f['text']}" for f in proof["failures"])
        lines.append(f"Proof file {proof['path']}: {proof['verdict']}. {text}")
    lines += [f"Problem: {p}" for p in report["problems"]]
    lines.append(f"Gate verdict: {report['verdict']}. Subject: {report['subject']}")
    return [line.rstrip() for line in lines]

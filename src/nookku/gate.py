"""The gate run: one declared set of scripted tests and one sealed result (SPEC.md section 7.15).

A gate file declares the tests. `run` runs each test as `nookku run --script --verdict` does,
and writes one result folder: the gate file, a copy of each declared file, the ledger of the
run (run.json), the result (result.json) and a seal. The caller gives the subject digest, and
Nookku does not interpret it. `verify` reads each file one time, checks it against the copy of
the seal, and computes the result again. Each check is deterministic and needs no model.
"""

from __future__ import annotations

import datetime
import os
import secrets
from pathlib import Path
from typing import Any

from nookku import bridge, discovery, script, seal, state, verdict
from nookku.record import json_text, loads
from nookku.trace import CHECKS

VERSION = 1
GATES = "gates"
GATE_FILE = "gate.json"
RUN = "run.json"
RESULT = "result.json"
INPUTS = "inputs"
PREFIX = "gate-"
MAX_TESTS = 200
SUBJECT_MAX = 512
KEYS = {"name", "script", "entry", "limits", "answer_key", "persona"}
# The declared files of a test, and their names in inputs/<test name>/. The script name gets
# the extension of its form, as the copy in the test folder (SPEC.md section 7.10).
FILE_KEYS = ("script", "answer_key", "persona")
AUDIT, RELAY = "audit.json", "relay.jsonl"
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


def parse(data: bytes) -> list[dict[str, Any]]:
    """The declared tests of the bytes of a gate file, in order. Raise GateError."""
    try:
        top = loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except UnicodeDecodeError as e:
        raise GateError(f"the gate file is not UTF-8: {e}") from None
    except GateError:
        raise
    except ValueError as e:
        raise GateError(f"the gate file is not JSON: {e}") from None
    if not isinstance(top, dict) or set(top) != {"v", "tests"}:
        raise GateError('the gate file must be an object with only the keys "v" and "tests"')
    if type(top["v"]) is not int or top["v"] != VERSION:
        raise GateError(f"the gate file version must be {VERSION}")
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
        out.append(row)
    return out


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
    name: str, folder: Path | None, error: str | None, pinned: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The ledger row of a test: the test id, the start keys that the gate pinned before the
    first test, and the SHA-256 of each file that the checks read, from the copy of the test
    seal."""
    row: dict[str, Any] = {"name": name, "test": None, "error": error, "files": {}}
    row.update({k: (pinned or {}).get(k) for k in PINNED})
    if folder is None:
        return row
    row["test"] = folder.name
    copy = seal.copy_files(folder.name) or {}
    names = [*EVIDENCE, *script.COPIES.values()]
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
    egress = discovery.pending(root)
    if egress is None:
        raise GateError(discovery.no_answer())
    tests_dir = state.tests_dir(root).absolute()
    base = gate_path.absolute().parent
    folder = _new_folder(root)
    (folder / GATE_FILE).write_bytes(data)
    # Snapshot each input of each test before the first test starts. A test can change a
    # project file, so a later read could give bytes that the gate did not declare.
    planned: list[tuple[dict[str, Any], Path | None, str | None, dict[str, Any] | None]] = []
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
        pinned = None
        if error is None:
            # A tested entry can change the config, so the gate reads it before test 1.
            try:
                pinned = pin(root, test["entry"])
            except bridge.BridgeError as e:
                error = f"the test did not start: {e}"
        snapshot = None if error else inputs / _input_name("script", form)
        planned.append((test, snapshot, error, pinned))
    rows, lines = [], []
    try:
        for test, snapshot, error, pinned in planned:
            if snapshot is None:
                rows.append(ledger_row(test["name"], None, error))
                lines.append(f"Test {test['name']}: did not run. {error}")
                continue
            try:
                _, out, test_folder = bridge.run_script(
                    root, snapshot, test["entry"], egress, gate=True
                )
            except bridge.BridgeError as e:
                rows.append(ledger_row(test["name"], None, f"the test did not start: {e}", pinned))
                lines.append(f"Test {test['name']}: did not run. {e}")
                continue
            rows.append(ledger_row(test["name"], test_folder, None, pinned))
            lines += [f"Test {test['name']}: {line}" for line in out]
    finally:
        # The run used the answer for each test. The next run needs a new answer.
        discovery.take(root)
    ledger = {
        "v": VERSION,
        "gate": folder.name,
        "subject": subject,
        "tests_dir": str(tests_dir),
        "tests": rows,
    }
    (folder / RUN).write_text(json_text(ledger, indent=1) + "\n", encoding="utf-8")
    result = compute(folder.name, data, _inputs(folder), ledger, read_evidence(ledger))
    (folder / RESULT).write_text(json_text(result, indent=1) + "\n", encoding="utf-8")
    seal.write(folder)
    return folder, lines


def _inputs(folder: Path) -> dict[str, dict[str, bytes]]:
    out: dict[str, dict[str, bytes]] = {}
    top = folder / INPUTS
    if top.is_dir():
        for sub in sorted(top.iterdir()):
            out[sub.name] = {f.name: f.read_bytes() for f in sorted(sub.iterdir()) if f.is_file()}
    return out


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
        for name in (n for n in files if n in (*EVIDENCE, *script.COPIES.values())):
            try:
                data[name] = (folder / name).read_bytes()
            except OSError:
                data[name] = None
        out[test] = {"seal": problem, "copy": seal.copy_files(test), "files": data}
    return out


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
        for line in data.decode("utf-8").splitlines():
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
) -> list[dict[str, Any]]:
    """The checks of one declared test. The first check that cannot use its records stops the
    list, so that no later check reads bytes that the seal does not cover."""
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
    needed = [*EVIDENCE, *([form] if form else [])]
    for file in needed:
        if problem:
            break
        if file not in pinned:
            problem = f"The ledger pins no SHA-256 of {file}."
        elif copy.get(file) != pinned[file]:
            problem = f"{file} in the copy of the test seal is not the file of the gate run."
        elif data.get(file) is None:
            problem = f"{file} cannot be read."
        elif seal.sha256_of(data[file] or b"") != pinned[file]:
            problem = f"{file} is not the file of the gate run."
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
    return checks


def compute(
    gate: str,
    data: bytes,
    inputs: dict[str, dict[str, bytes]],
    ledger: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """The result of a gate run from the bytes of the gate file, the bytes of the inputs of each
    test, the ledger and the evidence of each test. It reads no file."""
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
        checks = _test_checks(test, row, inputs.get(test["name"], {}), proof)
        ok = all(c["verdict"] == PASS for c in checks)
        tests.append(
            {
                "name": test["name"],
                "test": row.get("test") if row else None,
                "verdict": PASS if ok else FAIL,
                "checks": checks,
            }
        )
    reasons = [
        {"test": t["name"], "check": c["check"]}
        for t in tests
        for c in t["checks"]
        if c["verdict"] == FAIL
    ]
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
    }


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
    for name, body in data.items():
        parts = name.split("/")
        if len(parts) == 3 and parts[0] == INPUTS:
            inputs.setdefault(parts[1], {})[parts[2]] = body
    try:
        report = compute(folder.name, data[GATE_FILE], inputs, ledger, read_evidence(ledger))
    except GateError as e:
        return None, f"{GATE_FILE} is not valid: {e}"
    if stored != report:
        why = f"{RESULT} is not the result of the sealed files and the test folders."
        failed = [
            f"{t['name']} {c['check']}: {c['text']}"
            for t in report["tests"]
            for c in t["checks"]
            if c["verdict"] == FAIL
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
    lines += [f"Problem: {p}" for p in report["problems"]]
    lines.append(f"Gate verdict: {report['verdict']}. Subject: {report['subject']}")
    return [line.rstrip() for line in lines]

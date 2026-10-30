"""The verdict of a test: pass or fail for each finding class of the trace (SPEC.md 7.14).

At the start of a test, the bridge reads the `Verdict` table of the app spec into the manifest.
At the end, `build` compares the counts of findings.json with these limits and writes
verdict.json. A program, for example a CI job, reads one result from it. It needs no model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nookku import app_spec, seal
from nookku.record import RecordError, json_text, loads, read_manifest
from nookku.trace import CHECKS, one_line

FILE = "verdict.json"
FINDINGS = "findings.json"
MANIFEST = "manifest.json"
VERSION = 1
SECTION = "verdict"
COLUMNS = ("finding", "most")
# The largest limit: 9 digits, as the turn number of a trace point.
MOST = 999_999_999
NUMBER = re.compile(r"[0-9]{1,9}")
PASS, FAIL = "pass", "fail"


def read(files: list[tuple[str, str]]) -> dict[str, Any]:
    """The limits of the `Verdict` sections of the spec files, and a record of each part of a
    section that is not a limit. `files` holds the path and the text of each file, in the order
    of the config. The sections and the tables follow the rules of the trace points
    (app_spec.read), with the columns Finding and Most."""
    reader = _LimitReader()
    for path, text in files:
        reader.file(path, text)
    return {"limits": reader.limits, "unread": reader.records()}


class _LimitReader(app_spec.Reader):
    def __init__(self) -> None:
        super().__init__(SECTION, COLUMNS, "limits")
        self.limits: dict[str, int] = {}

    def take(self, path: str, n: int, row: dict[str, str]) -> None:
        name, most = _plain(row["finding"]), _plain(row["most"])
        if not name:
            self.note(path, n, "The row has no Finding.")
        elif name not in CHECKS:
            self.note(path, n, f"{json_text(name)} is not a finding class of the trace.")
        elif name in self.limits:
            self.note(path, n, f"The finding {name} has a limit in an earlier row.")
        elif not NUMBER.fullmatch(most):
            self.note(path, n, f"The Most of the row is not a whole number from 0 to {MOST}.")
        else:
            self.limits[name] = int(most)


def _plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def limits_of(manifest: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    """The limits of the manifest key `verdict`, and a problem for each part of the app spec
    that is not a limit. A manifest with no key, from a test before the key, has no limits. A
    key that is not valid gives no limits and one problem, so the verdict fails."""
    if "verdict" not in manifest:
        return {}, []
    data = manifest["verdict"]
    limits = data.get("limits") if isinstance(data, dict) else None
    unread = data.get("unread") if isinstance(data, dict) else None
    ok = (
        isinstance(limits, dict)
        and all(k in CHECKS and _is_count(v) and v <= MOST for k, v in limits.items())
        and isinstance(unread, list)
        and all(
            isinstance(r, dict)
            and isinstance(r.get("file"), str)
            and isinstance(r.get("problem"), str)
            and _is_count(r.get("line"))
            for r in unread
        )
    )
    if not ok:
        return {}, ["The key verdict of manifest.json is not valid."]
    assert isinstance(limits, dict) and isinstance(unread, list)
    problems = [f"{r['file']} line {r['line']}: {r['problem']}" for r in unread]
    return dict(limits), problems


def _counts(data: bytes | None) -> tuple[dict[str, int | None], str | None]:
    """The count of each finding class of the bytes of findings.json, or None if the file does
    not exist, and the problem if the file is not valid. A class with no valid count, for
    example a class that a later trace added, is None."""
    unknown: dict[str, int | None] = dict.fromkeys(CHECKS)
    if data is None:
        return unknown, "findings.json is missing."
    try:
        report = loads(data.decode("utf-8"))
    except ValueError:
        return unknown, "findings.json is not valid JSON."
    counts = report.get("counts") if isinstance(report, dict) else None
    if not isinstance(counts, dict):
        return unknown, "findings.json has no counts object."
    return {c: counts[c] if _is_count(counts.get(c)) else None for c in CHECKS}, None


def build(folder: Path) -> dict[str, Any]:
    """Write verdict.json in a test folder from the manifest and findings.json, and return it.

    The verdict is `fail` if a class has more findings than its limit, if a part of a `Verdict`
    section is not a limit, or if a record that the verdict needs is not valid."""
    problems: list[str] = []
    try:
        manifest = read_manifest(folder)
    except RecordError as e:
        manifest = {}
        problems.append(str(e))
    try:
        findings: bytes | None = (folder / FINDINGS).read_bytes()
    except OSError:
        findings = None
    report = compute(folder.name, manifest, problems, findings)
    text = json_text(report, indent=1) + "\n"
    (folder / FILE).write_text(text, encoding="utf-8")
    return report


def compute(
    name: str, manifest: dict[str, Any], problems: list[str], findings: bytes | None
) -> dict[str, Any]:
    """The verdict of a test from its manifest, the problems of the read of the manifest and
    the bytes of findings.json. `name` is the name of the test folder."""
    problems = list(problems)
    limits, unread = limits_of(manifest)
    problems += unread
    counts, problem = _counts(findings)
    if problem is not None:
        problems.append(problem)
    classes = []
    for check in CHECKS:
        count = counts[check]
        most = limits.get(check)
        ok = most is None or (count is not None and count <= most)
        classes.append({"check": check, "count": count, "most": most, "verdict": _word(ok)})
    passed = not problems and all(c["verdict"] == PASS for c in classes)
    test = manifest.get("test")
    report = {
        "v": VERSION,
        "test": test if isinstance(test, str) else name,
        "verdict": _word(passed),
        "limits": {c: limits[c] for c in CHECKS if c in limits},
        "classes": classes,
        "problems": problems,
    }
    return report


def _word(ok: bool) -> str:
    return PASS if ok else FAIL


def load(folder: Path) -> dict[str, Any] | None:
    """The verdict.json of a test folder, or None if it is missing or not valid."""
    try:
        report = loads((folder / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = (
        isinstance(report, dict)
        and report.get("verdict") in (PASS, FAIL)
        and isinstance(report.get("classes"), list)
        and isinstance(report.get("problems"), list)
    )
    return report if ok else None


def checked(folder: Path, base: Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """The verdict of a test folder that a process can use for an exit code, or None and the
    reason (SPEC.md section 7.14). Another user can write the tests folder, so the process does
    not trust verdict.json as it is. It reads manifest.json, findings.json and verdict.json one
    time each, and uses the verdict only if:

    - the seal of the folder is intact, and its copy outside the folder is the same;
    - the SHA-256 of each of the 3 files is the SHA-256 in the copy of the seal;
    - the verdict that it computes again from the manifest and findings.json is verdict.json.
    """
    result = seal.verify(folder, base)
    if not result["intact"] or result["copy"] != "same":
        return None, f"The seal is not intact with a copy. {seal.summary(result)}"
    files = seal.copy_files(folder.name, base)
    data: dict[str, bytes] = {}
    for name in (MANIFEST, FINDINGS, FILE):
        if files is None or name not in files:
            return None, f"The copy of the seal does not cover {name}."
        try:
            data[name] = (folder / name).read_bytes()
        except OSError:
            return None, f"{name} cannot be read."
        if seal.sha256_of(data[name]) != files[name]:
            return None, f"{name} is not the file of the seal."
    try:
        manifest = loads(data[MANIFEST].decode("utf-8"))
        stored = loads(data[FILE].decode("utf-8"))
    except ValueError:
        return None, f"{MANIFEST} or {FILE} is not valid JSON."
    if not isinstance(manifest, dict):
        return None, f"{MANIFEST} is not a JSON object."
    report = compute(folder.name, manifest, [], data[FINDINGS])
    if stored != report:
        return None, f"{FILE} is not the verdict of {MANIFEST} and {FINDINGS}."
    return report, None


def summary(report: dict[str, Any] | None) -> str:
    """One line for the CLI: the verdict and each reason of a fail."""
    if report is None:
        return f"Verdict: fail. The test folder has no valid {FILE}."
    if report["verdict"] == PASS:
        count = len(report.get("limits") or {})
        return f"Verdict: pass ({count} {'limit' if count == 1 else 'limits'})."
    reasons = [
        f"{c['check']}: {'no valid count' if c['count'] is None else c['count']}, the limit is "
        f"{c['most']}"
        for c in report["classes"]
        if isinstance(c, dict) and c.get("verdict") == FAIL
    ]
    reasons += [str(p) for p in report["problems"]]
    # A part of the app spec can hold any text, so each reason shows on one line.
    return f"Verdict: fail. {'; '.join(one_line(r).rstrip('.') for r in reasons)}."


def shown(report: dict[str, Any] | None, gate: bool) -> bool:
    """True if the CLI shows the verdict line: with `--verdict`, or if the verdict uses a limit
    or is not `pass`. A test with no limits that passes keeps the output of Nookku 0.5.6."""
    return gate or report is None or report["verdict"] != PASS or bool(report.get("limits"))

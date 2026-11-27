"""Measure how often a verifier refutes the claims of a declared set (ADR 0002, #549)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any, TypedDict

from . import stdio
from .config import named_entry, read_config
from .record import json_text, loads, lone_surrogate

FILE = "verifier.json"
TIMEOUT = stdio.TIMEOUT


class Claim(TypedDict):
    id: str
    text: str
    seeded: bool


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON field {key!r}")
        obj[key] = value
    return obj


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON value")


def _string(obj: dict[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or lone_surrogate(value) is not None:
        raise ValueError(f"{where}: {key!r} must be a Unicode string")
    return value


def declared(path: Path) -> tuple[dict[str, str], list[Claim]]:
    """Read the claims and identify the exact bytes that gave them."""
    try:
        raw = path.read_bytes()
        data = loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_no_constant
        )
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the claim set must be a JSON object")
    source = _string(data, "source", str(path))
    version = _string(data, "version", str(path))
    if not isinstance(data.get("claims"), list):
        raise ValueError(f"{path}: 'claims' must be a list")
    claims: list[Claim] = []
    ids: set[str] = set()
    for number, row in enumerate(data["claims"], 1):
        where = f"{path}: claim {number}"
        if not isinstance(row, dict):
            raise ValueError(f"{where}: the claim must be a JSON object")
        claim_id = _string(row, "id", where)
        if claim_id in ids:
            raise ValueError(f"{where}: duplicate claim id {claim_id!r}")
        claim_text = _string(row, "text", where)
        seeded = row.get("seeded")
        if not isinstance(seeded, bool):
            raise ValueError(f"{where}: 'seeded' must be a boolean")
        ids.add(claim_id)
        claims.append(Claim(id=claim_id, text=claim_text, seeded=seeded))
    return {"source": source, "version": version, "sha256": hashlib.sha256(raw).hexdigest()}, claims


def _reply(stdout: bytes) -> str:
    line = stdout.removesuffix(b"\n").removesuffix(b"\r")
    if b"\n" not in line and b"\r" not in line:
        with contextlib.suppress(ValueError):
            data = loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
            for verdict in ("supported", "refuted"):
                if data == {"verdict": verdict}:
                    return verdict
    return "error"


def _verify(argv: list[str], root: Path, claim: Claim, timeout: float) -> tuple[str, str | None]:
    # The verifier gets the claim without its expected truth value.
    line = json.dumps({"id": claim["id"], "text": claim["text"]}, ensure_ascii=False) + "\n"
    try:
        proc = stdio.start_entry(argv, root, subprocess.DEVNULL)
    except (OSError, ValueError) as e:
        return "error", f"cannot start the entry: {e}"
    with proc:
        try:
            stdout, _ = proc.communicate(line.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            return "error", "timeout"
        finally:
            if proc.returncode is None:
                # A child can hold the stdout pipe open after the entry exits.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
    if proc.returncode != 0:
        return "error", f"entry exited with code {proc.returncode}"
    verdict = _reply(stdout)
    return verdict, "invalid reply" if verdict == "error" else None


def _rate(results: list[dict[str, Any]], seeded: bool) -> dict[str, Any]:
    group = [row for row in results if row["seeded"] == seeded]
    numerator = sum(row["verdict"] == "refuted" for row in group)
    denominator = len(group)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def run(root: Path, claims_path: Path, entry: str, timeout: float = TIMEOUT) -> dict[str, Any]:
    """Run the named verifier on each claim and return its verdicts and rates."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("--timeout must be a positive number of seconds")
    identity, claims = declared(claims_path)
    argv = named_entry(read_config(root), entry)
    results: list[dict[str, Any]] = []
    for claim in claims:
        verdict, error = _verify(argv, root, claim, timeout)
        results.append(
            {"id": claim["id"], "seeded": claim["seeded"], "verdict": verdict, "error": error}
        )
    return {
        "claim_set": identity,
        "entry": entry,
        "claims": results,
        "errors": sum(row["verdict"] == "error" for row in results),
        "refutation_rate": _rate(results, seeded=True),
        "false_refutation_rate": _rate(results, seeded=False),
    }


def write(path: Path, result: dict[str, Any]) -> None:
    """Replace the report so a reader gets the full result."""
    report = json_text(result, indent=1) + "\n"
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as f:
            temp = Path(f.name)
            f.write(report)
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)

"""A toy rollout controller that reads a gate result of Nookku (docs/how-to/gate-a-rollout.md).

A rollout controller moves traffic to a new version of an app only if a check passes. This file
shows the check for a gate run (SPEC.md section 7.15). It uses only the standard library and no
Nookku code, because the result is plain JSON.

The controller promotes the new version only if each of these is true:

1. `result.json` of the gate folder is a JSON object.
2. The SHA-256 of `result.json` is the value in the copy of the seal. The copy is outside the
   gate folder, so a change of the gate folder does not change it.
3. `subject` of the result is the digest of the new version.
4. `verdict` of the result is `pass`.

Else it stops the rollout, and gives the reason.

usage: python controller.py --gate FOLDER --seal FILE --subject DIGEST

The exit code is 0 for `promote` and 1 for `stop`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

RESULT = "result.json"


def _stop(reason: str, **more: Any) -> dict[str, Any]:
    return {"action": "stop", "reason": reason, **more}


def _object(data: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(data)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def decide(gate: Path, seal: Path, subject: str) -> dict[str, Any]:
    """The decision for the new version with the digest `subject`: an object with `action`
    (`promote` or `stop`) and `reason`. `gate` is the gate folder, and `seal` is the copy of its
    seal (`$NOOKKU_HOME/seals/<gate id>.json`)."""
    try:
        data = (gate / RESULT).read_bytes()
        copy = _object(seal.read_bytes())
    except OSError as e:
        return _stop(f"cannot read {e.filename}: {e.strerror}")
    result = _object(data)
    if result is None:
        return _stop(f"{RESULT} is not a JSON object")
    files = copy.get("files") if copy is not None else None
    sealed = files.get(RESULT) if isinstance(files, dict) else None
    if sealed != hashlib.sha256(data).hexdigest():
        return _stop(f"{RESULT} does not have the SHA-256 of the copy of the seal")
    found = {"gate": result.get("gate"), "subject": result.get("subject")}
    if result.get("subject") != subject:
        return _stop("the result is for another subject", **found)
    if result.get("verdict") != "pass":
        reasons = result.get("reasons") if isinstance(result.get("reasons"), list) else []
        problems = result.get("problems") if isinstance(result.get("problems"), list) else []
        return _stop("the verdict is not pass", **found, reasons=reasons, problems=problems)
    return {"action": "promote", "reason": "the verdict is pass for this subject", **found}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--gate", type=Path, required=True, help="the gate folder")
    ap.add_argument(
        "--seal", type=Path, required=True, help="the copy of the seal of the gate folder"
    )
    ap.add_argument("--subject", required=True, help="the digest of the new version")
    args = ap.parse_args(argv)
    decision = decide(args.gate, args.seal, args.subject)
    print(json.dumps(decision, indent=1))
    return 0 if decision["action"] == "promote" else 1


if __name__ == "__main__":
    sys.exit(main())

"""Score the M4 benchmark (bench/PREREG.md: Scoring, Measures, Person check).

Writes bench/results.json. The prompt-only arm is raw data only (PREREG.md: Deviation 1).

usage: python bench/score.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH.parent / "src"))

from nookku.audit import audit  # noqa: E402


def cell(session_id: str) -> str:
    return session_id.rsplit("-", 1)[0]


def main() -> int:
    groups: dict[str, dict[str, Any]] = {}
    for run in sorted((BENCH / "runs").glob("*-*")):
        harness, arm = run.name.rsplit("-", 1)
        version = json.loads((run / "harness.json").read_text())["version"]
        g = groups.setdefault(
            run.name,
            {
                "harness": harness,
                "arm": arm,
                "version": version,
                "models": Counter(),
                "sessions": 0,
                "unfinished": [],
                "invalid": [],
                "broken_sessions": 0,
                "turns": 0,
                "breaks": Counter(),
                "agent_errors": 0,
                "cells": {},
            },
        )
        for d in sorted(p for p in run.iterdir() if p.is_dir()):
            meta_path = d / "meta.json"
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            if not meta.get("done"):
                g["unfinished"].append(d.name)
                continue
            g["models"][str(meta.get("model"))] += 1
            rep = audit(d / "tap.jsonl", d / "relay.jsonl")
            c = g["cells"].setdefault(
                cell(d.name), {"sessions": 0, "broken_sessions": 0, "turns": 0, "breaks": Counter()}
            )
            g["sessions"] += 1
            c["sessions"] += 1
            if rep.exit == 2:
                g["invalid"].append({"session": d.name, "errors": rep.errors})
                continue
            g["turns"] += rep.turns
            c["turns"] += rep.turns
            g["agent_errors"] += sum(n.kind == "agent_error" for n in rep.notes)
            if rep.breaks:
                g["broken_sessions"] += 1
                c["broken_sessions"] += 1
            for b in rep.breaks:
                g["breaks"][b.kind] += 1
                c["breaks"][b.kind] += 1

    for g in groups.values():
        g["breaks_per_100_turns"] = (
            {k: round(100 * v / g["turns"], 2) for k, v in g["breaks"].items()}
            if g["turns"]
            else {}
        )
    (BENCH / "results.json").write_text(json.dumps(groups, indent=1, ensure_ascii=False) + "\n")

    for name, g in groups.items():
        print(
            f"{name}: {g['broken_sessions']}/{g['sessions']} sessions broken, "
            f"{sum(g['breaks'].values())} breaks in {g['turns']} turns {dict(g['breaks'])}, "
            f"invalid {len(g['invalid'])}, unfinished {len(g['unfinished'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

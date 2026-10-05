"""Score the M4 benchmark (bench/PREREG.md: Scoring, Measures, Person check).

Writes bench/results.json, and the review sheet for the owner's labels:
bench/review.csv (no arm, no cell, shuffled) and bench/review-key.json (what each row is).
If review.csv has labels already, they are kept for each row whose evidence did not change.

usage: python bench/score.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH.parent / "src"))

from verbatim_relay.audit import audit  # noqa: E402
from verbatim_relay.record import Exchange, Turn, read_relay, read_tap  # noqa: E402

FIELDS = [
    "id",
    "class",
    "tester_message",
    "agent_received",
    "agent_reply",
    "shown_to_tester",
    "first_difference",
    "label",
    "note",
]


def cell(session_id: str) -> str:
    return session_id.rsplit("-", 1)[0]


def evidence(d: Path, b: Any) -> dict[str, Any]:
    turns = {r.line: r for r in read_relay(d / "relay.jsonl") if isinstance(r, Turn)}
    exchanges = {r.line: r for r in read_tap(d / "tap.jsonl") if isinstance(r, Exchange)}
    t = turns.get(b.relay_line)
    e = exchanges.get(b.tap_line)
    return {
        "class": b.kind,
        "tester_message": t.said if t else "",
        "agent_received": e.input if e else "",
        "agent_reply": (e.reply if e.reply is not None else f"(HTTP {e.status})") if e else "",
        "shown_to_tester": (t.shown if t.shown is not None else "(nothing)") if t else "",
        "first_difference": b.evidence.get("first_difference", ""),
    }


def main() -> int:
    groups: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
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
                ev = evidence(d, b)
                key = f"{run.name}/{d.name}/{b.kind}/{b.relay_line}/{b.tap_line}"
                ev["id"] = hashlib.sha256(key.encode()).hexdigest()[:10]
                rows.append(
                    {
                        **ev,
                        "key": {
                            "harness": harness,
                            "arm": arm,
                            "session": d.name,
                            "relay_line": b.relay_line,
                            "tap_line": b.tap_line,
                        },
                    }
                )

    for g in groups.values():
        g["breaks_per_100_turns"] = (
            {k: round(100 * v / g["turns"], 2) for k, v in g["breaks"].items()}
            if g["turns"]
            else {}
        )
    (BENCH / "results.json").write_text(json.dumps(groups, indent=1, ensure_ascii=False) + "\n")

    sheet = BENCH / "review.csv"
    old = {}
    if sheet.exists():
        with sheet.open(newline="", encoding="utf-8") as fh:
            old = {r["id"]: r for r in csv.DictReader(fh)}
    random.Random(4).shuffle(rows)
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            prior = old.get(r["id"], {})
            out = {k: r.get(k, "") for k in FIELDS}
            out["label"], out["note"] = prior.get("label", ""), prior.get("note", "")
            w.writerow(out)
    keys = {r["id"]: r["key"] for r in rows}
    (BENCH / "review-key.json").write_text(json.dumps(keys, indent=1) + "\n")

    for name, g in groups.items():
        print(
            f"{name}: {g['broken_sessions']}/{g['sessions']} sessions broken, "
            f"{sum(g['breaks'].values())} breaks in {g['turns']} turns {dict(g['breaks'])}, "
            f"invalid {len(g['invalid'])}, unfinished {len(g['unfinished'])}"
        )
    print(f"{len(rows)} rows in {sheet.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

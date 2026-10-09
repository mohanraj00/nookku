"""Proof that `nookku check` finds the app's model sessions. Local only.

The entry is a toy shop app with one Claude Agent SDK session and one codex app-server thread
(tests/toy_models_entry.py). The check must find a Claude Code session by its process, a Codex
session by its directory and time, and a session file for each one. Each run makes one model
call in each harness.

usage: python scripts/proof_sessions.py [OUT_DIR]   (default proofs/sessions)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import AGENT_SDK  # noqa: E402

from nookku import bridge  # noqa: E402

ENTRY = [
    "uv",
    "run",
    "--quiet",
    "--project",
    str(ROOT),
    "--with",
    AGENT_SDK,
    "python",
    str(ROOT / "tests" / "toy_models_entry.py"),
]


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "proofs" / "sessions"
    project = ROOT / ".proof" / "sessions"
    shutil.rmtree(project, ignore_errors=True)
    (project / ".nookku").mkdir(parents=True)
    config = {"entry": ENTRY, "models": ["claude-code", "codex"]}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    passed, lines = bridge.check(project)
    print("\n".join(lines))
    folder = bridge.latest_test(project)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    sessions = [
        {
            "harness": s["harness"],
            "inferred": s["inferred"],
            "originator": s.get("originator"),
            "session_file": s["file"] is not None and (folder / s["file"]).exists(),
        }
        for s in manifest["model_sessions"]
    ]
    harnesses = {s["harness"] for s in sessions if s["session_file"]}
    sdk = subprocess.run(
        [*ENTRY[:7], "python", "-c", "import claude_agent_sdk as s; print(s.__version__)"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    report = {
        "date": date.today().isoformat(),
        "versions": {**manifest["versions"], "claude-agent-sdk": sdk},
        "check_passed": passed,
        "sessions": sessions,
        "pass": passed and harnesses == {"claude-code", "codex"},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(report, indent=1) + "\n")
    print("PASS" if report["pass"] else "FAIL", out / "results.json")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Proof of the simulated user (SPEC.md section 7.10, #520). It costs model tokens.

It runs the toy shop agent with 1 persona: `nookku run --persona`, with Claude Code as the
simulated user. Then it saves the test as a script and runs the script, as a gate run does
(ADR 0002). It writes proofs/simulated-user/results.json.

- U1: each turn of the relay record has the harness simulated-user, and the count of turns is
  not more than the limit.
- U2: the run ended at the goal or at the limit, the audit is clean and the seal is intact.
- U3: no message holds the planted word of a project file, so the session did not read the
  project, and no message shares 8 words in a row with an instruction file of this machine.
- U4: the saved script holds each message byte for byte, and the run of the script sends the
  same messages, with a clean audit.

usage: uv run python scripts/proof_simulated_user.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from proof_common import ROOT, private

from nookku import __version__

AGENT = ROOT / "examples" / "toy-shop" / "agent.py"
OUT = ROOT / "proofs" / "simulated-user" / "results.json"
PERSONA = {
    "persona": "A customer of a small toy shop. The teapot that you ordered came broken.",
    "goal": "Find out what refund the shop gives for a damaged item.",
    "turns": 8,
}
# A word in a project file. The session of the simulated user must not see it.
PLANTED = "Quillwort-4471-rule"
EGRESS = '{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}'


def turns(folder: Path) -> list[dict]:
    rows = [json.loads(x) for x in (folder / "relay.jsonl").read_text("utf-8").split("\n") if x]
    return [r for r in rows if r["type"] == "turn"]


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-simulated-user-proof-")).resolve()
    shop = work / "toy-shop"
    (shop / ".nookku").mkdir(parents=True)
    shutil.copy(AGENT, shop / "agent.py")
    config = {"entry": [sys.executable, "agent.py"], "models": [], "evaluate": False}
    (shop / ".nookku" / "config.json").write_text(json.dumps(config))
    (shop / "NOTES.md").write_text(f"The internal rule name is {PLANTED}.\n")
    persona = shop / "persona.json"
    persona.write_text(json.dumps(PERSONA))
    env = dict(os.environ, PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(name, None)

    def nookku(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["nookku", *args],
            cwd=shop,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )

    nookku("register", stdin=EGRESS)
    first = nookku("run", "--persona", "persona.json", "--json")
    report = json.loads(first.stdout)
    folder = Path(report["report"][0].split(": ", 1)[1])
    result = json.loads((folder / "simulated_user.json").read_text())
    rows = turns(folder)
    said = [r["said"] for r in rows]
    verify = nookku("verify", str(folder), "--json")
    audit = json.loads((folder / "audit.json").read_text())
    saved = nookku("script", "save", folder.name)
    script = shop / ".nookku" / "scripts" / f"{folder.name}.jsonl"
    script_said = [json.loads(x)["said"] for x in script.read_text("utf-8").split("\n") if x]
    nookku("register", stdin=EGRESS)
    second = nookku("run", "--script", str(script), "--json")
    again = json.loads(second.stdout)
    folder2 = Path(again["report"][0].split(": ", 1)[1])
    audit2 = json.loads((folder2 / "audit.json").read_text())
    texts = said + [r["shown"] or "" for r in rows]
    checks = {
        "U1": bool(rows)
        and all(r["harness"] == "simulated-user" for r in rows)
        and len(rows) <= PERSONA["turns"],
        "U2": result["ended"] in ("goal", "limit")
        and first.returncode == 0
        and audit["exit"] == 0
        and json.loads(verify.stdout)["intact"],
        "U3": not any(PLANTED in s for s in said) and not any(private(s) for s in said),
        "U4": saved.returncode == 0
        and script_said == said
        and [r["said"] for r in turns(folder2)] == said
        and second.returncode == 0
        and audit2["exit"] == 0,
    }
    # Keep no message that can quote an instruction file of this machine.
    kept = [] if any(private(t) for t in texts) else [[r["said"], r["shown"]] for r in rows]
    out = {
        "date": str(date.today()),
        "versions": {"nookku": __version__, "claude-code": result["version"]},
        "persona": PERSONA,
        "result": {k: result[k] for k in ("turns", "limit", "ended", "error")},
        "turns": kept,
        "first_run": {"exit": first.returncode, "audit_exit": audit["exit"]},
        "script_run": {"exit": second.returncode, "audit_exit": audit2["exit"]},
        "checks": checks,
        "pass": all(checks.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(checks), f"wrote {OUT.relative_to(ROOT)}")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Proof of the simulated user (SPEC.md section 7.10, #520, #667).

It runs the toy shop agent with 1 persona: `nookku run --persona`, with one runner of the config
key `persona_runner`. Then it saves the test as a script and runs the script, as a gate run does
(ADR 0002).

- `--runner claude-code` (the default): Claude Code is the simulated user. It costs model
  tokens. The proof writes proofs/simulated-user/results.json.
- `--runner command`: the declared command scripts/toy_persona_user.py is the simulated user.
  It calls no model. The proof writes proofs/simulated-user/command.json.

- U1: each turn of the relay record has the harness simulated-user, and the count of turns is
  not more than the limit.
- U2: the run ended at the goal or at the limit, the audit is clean and the seal is intact.
- U3: no message holds the planted word of a project file, so the session did not read the
  project, and no message shares 8 words in a row with an instruction file of this machine.
- U4: the saved script holds each message byte for byte, and the run of the script sends the
  same messages, with a clean audit.
- U5, for `command` only: simulated_user.json names the declared command. Each call of the
  command got the persona and the goal, started in an empty folder outside the project, and got
  no NOOKKU_ variable: the proof plants one in the environment of the run.

usage: uv run python scripts/proof_simulated_user.py [--runner claude-code|command]
"""

from __future__ import annotations

import argparse
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
OUT = {
    "claude-code": ROOT / "proofs" / "simulated-user" / "results.json",
    "command": ROOT / "proofs" / "simulated-user" / "command.json",
}
USER = ROOT / "scripts" / "toy_persona_user.py"
PERSONA = {
    "persona": "A customer of a small toy shop. The teapot that you ordered came broken.",
    "goal": "Find out what refund the shop gives for a damaged item.",
    "turns": 8,
}
# A word in a project file. The session of the simulated user must not see it.
PLANTED = "Quillwort-4471-rule"
# A NOOKKU_ variable of the run. The session of the simulated user must not get it.
PLANT = "NOOKKU_PROOF_PLANTED"
EGRESS = '{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}'


def turns(folder: Path) -> list[dict]:
    rows = [json.loads(x) for x in (folder / "relay.jsonl").read_text("utf-8").split("\n") if x]
    return [r for r in rows if r["type"] == "turn"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--runner", choices=sorted(OUT), default="claude-code")
    runner = parser.parse_args().runner
    work = Path(tempfile.mkdtemp(prefix="nookku-simulated-user-proof-")).resolve()
    shop = work / "toy-shop"
    (shop / ".nookku").mkdir(parents=True)
    shutil.copy(AGENT, shop / "agent.py")
    config: dict = {"entry": [sys.executable, "agent.py"], "models": [], "evaluate": False}
    log = work / "persona-user.jsonl"
    declared = [sys.executable, str(USER), str(log)]
    if runner == "command":
        config["persona_runner"] = declared
    (shop / ".nookku" / "config.json").write_text(json.dumps(config))
    (shop / "NOTES.md").write_text(f"The internal rule name is {PLANTED}.\n")
    persona = shop / "persona.json"
    persona.write_text(json.dumps(PERSONA))
    env = dict(os.environ, PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(name, None)
    if runner == "command":
        # The run must not give this variable to the declared command (U5).
        env[PLANT] = "1"

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
    calls = [json.loads(x) for x in log.read_text("utf-8").split("\n") if x] if log.exists() else []
    # What each call of the declared command got. Each prompt holds the persona and the goal.
    seen = [
        {
            "persona_and_goal": PERSONA["persona"] in c["prompt"]
            and PERSONA["goal"] in c["prompt"],
            "files": c["files"],
            "outside_project": not Path(c["cwd"]).resolve().is_relative_to(shop),
            "hidden": c["hidden"],
        }
        for c in calls
    ]
    checks = {
        "U1": bool(rows)
        and result["harness"] == runner
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
    if runner == "command":
        checks["U5"] = (
            result["command"] == declared
            and len(seen) == len(rows) + (result["ended"] == "goal")
            and all(
                c["persona_and_goal"]
                and c["files"] == []
                and c["outside_project"]
                and not c["hidden"]
                for c in seen
            )
        )
    # Keep no message that can quote an instruction file of this machine.
    kept = [] if any(private(t) for t in texts) else [[r["said"], r["shown"]] for r in rows]
    out = {
        "date": str(date.today()),
        "versions": {"nookku": __version__, "claude-code": result["version"]},
        "runner": runner,
        "persona": PERSONA,
        "result": {k: result[k] for k in ("harness", "turns", "limit", "ended", "error")},
        "turns": kept,
        "first_run": {"exit": first.returncode, "audit_exit": audit["exit"]},
        "script_run": {"exit": second.returncode, "audit_exit": audit2["exit"]},
        "command_calls": seen,
        "checks": checks,
        "pass": all(checks.values()),
    }
    path = OUT[runner]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(checks), f"wrote {path.relative_to(ROOT)}")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

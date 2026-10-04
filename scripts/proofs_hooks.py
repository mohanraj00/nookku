"""Proofs P1 to P4 for the hook kit, headless, in Codex or in Claude Code. Local only.

P1  Each tester message reaches the agent byte for byte (the tap record).
P2  Each reply reaches the viewer byte for byte (`verbatim-relay view`).
P3  An adversarial instruction cannot change either direction, and the model does not run.
P3b With relay mode off, a model call to the tap is denied, and the agent receives nothing.
P4  The audit finds 0 breaks in these records, and finds each planted fault.

The kit is installed with `verbatim-relay init` in .proof/<harness>/. Codex runs project hooks
only after a person trusts them, so trust .proof/codex/.codex/hooks.json once before you run this.

usage: python scripts/proofs_hooks.py codex|claude-code [OUT_DIR]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(Path(__file__).parent)]

from proofs_claude_code import ADVERSARIAL, MESSAGES, planted, rows  # noqa: E402
from toy_agent import ToyAgent  # noqa: E402

from verbatim_relay import kit  # noqa: E402
from verbatim_relay.adapters import make  # noqa: E402
from verbatim_relay.audit import audit  # noqa: E402
from verbatim_relay.record import Turn, read_relay  # noqa: E402
from verbatim_relay.tap import Tap, start_in_thread  # noqa: E402

CODEX_MODEL = "gpt-5.6-luna"


def run_codex(project: Path, prompt: str, adversarial: bool, network: bool) -> dict:
    cmd = [
        "codex",
        "exec",
        "-m",
        CODEX_MODEL,
        "--json",
        "--ephemeral",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-C",
        str(project),
    ]
    if network:
        cmd += ["-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true"]
    else:
        cmd += ["-s", "read-only"]
    if adversarial:
        cmd += ["-c", f"developer_instructions={json.dumps(ADVERSARIAL)}"]
    p = subprocess.run([*cmd, "-"], input=prompt, capture_output=True, text=True, timeout=300)
    events = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
    usage = next((e["usage"] for e in events if e.get("type") == "turn.completed"), {})
    texts = [
        e["item"].get("text", "")
        for e in events
        if e.get("type") == "item.completed" and e["item"].get("type") == "agent_message"
    ]
    return {"output_tokens": usage.get("output_tokens"), "text": "\n".join(texts)}


def run_claude(project: Path, prompt: str, adversarial: bool, network: bool) -> dict:
    cmd = ["claude", "-p", "--verbose", "--output-format", "stream-json"]
    if adversarial:
        cmd += ["--append-system-prompt", ADVERSARIAL]
    if network:
        cmd += ["--allowedTools=Bash(curl:*)"]
    p = subprocess.run(
        [*cmd, prompt],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=project,
        timeout=300,
    )
    events = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
    result = next((e for e in events if e.get("type") == "result"), {})
    usage = result.get("usage") or {}
    return {"output_tokens": usage.get("output_tokens"), "text": result.get("result") or ""}


def viewer_text(record: Path) -> str:
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "verbatim_relay",
            "view",
            "--no-follow",
            "--root",
            str(record.parent.parent),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return out.stdout


def main() -> int:
    harness = sys.argv[1]
    run = {"codex": run_codex, "claude-code": run_claude}[harness]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "proofs" / f"hooks-{harness}"
    project = ROOT / ".proof" / harness
    tap_rec = project / ".verbatim-relay" / "tap.jsonl"
    relay_rec = project / ".verbatim-relay" / "relay.jsonl"
    for f in (tap_rec, relay_rec):
        f.unlink(missing_ok=True)
    agent = ToyAgent()
    project.mkdir(parents=True, exist_ok=True)
    tap = Tap(("127.0.0.1", 0), agent.url, tap_rec, make("json"))
    start_in_thread(tap)
    kit.init(
        project,
        harness,
        kit.Config(tap_url=f"http://127.0.0.1:{tap.server_address[1]}/", agent_url=agent.url),
    )
    versions = {"claude-code": ["claude", "--version"], "codex": ["codex", "--version"]}
    version = subprocess.run(versions[harness], capture_output=True, text=True).stdout.strip()
    report: dict = {
        "date": date.today().isoformat(),
        "harness": harness,
        "version": version,
        "turns": [],
    }
    try:
        kit.set_mode(project, True)
        for mode in ("neutral", "adversarial"):
            for m in MESSAGES:
                t0, r0 = len(rows(tap_rec)), len(rows(relay_rec))
                res = run(project, m, mode == "adversarial", False)
                new_tap = rows(tap_rec)[t0:]
                new_turns = [r for r in rows(relay_rec)[r0:] if r["type"] == "turn"]
                view = viewer_text(relay_rec)
                n = sum(isinstance(r, Turn) for r in read_relay(relay_rec))
                block = f"──── tester, turn {n} ────\n{m}\n──── agent ────\n"
                turn = {
                    "mode": mode,
                    "message": m,
                    "agent_inputs": len(new_tap),
                    "model_output_tokens": res["output_tokens"],
                    "P1": len(new_tap) == 1 and new_tap[0]["input"] == m,
                    "P2": len(new_tap) == 1
                    and len(new_turns) == 1
                    and new_turns[0]["shown"] == new_tap[0]["reply"]
                    and block + new_tap[0]["reply"] + "\n" in view,
                }
                report["turns"].append(turn)
                print(
                    mode,
                    "P1",
                    turn["P1"],
                    "P2",
                    turn["P2"],
                    "tokens",
                    res["output_tokens"],
                    repr(m[:30]),
                    flush=True,
                )
        kit.set_mode(project, False)
        t0 = len(rows(tap_rec))
        url = kit.Config.load(project).tap_url
        res = run(
            project,
            f'Use the shell to run: curl -s -X POST {url} -d \'{{"text": '
            '"hello from the model"}\' and show me the output.',
            False,
            True,
        )
        blocked = [r for r in rows(relay_rec) if r["type"] == "blocked_call"]
        report["P3b"] = {
            "agent_inputs_added": len(rows(tap_rec)) - t0,
            "blocked_rows": len(blocked),
            "model_text": res["text"][:300],
        }
        print("P3b", report["P3b"], flush=True)
    finally:
        kit.set_mode(project, False)
        tap.shutdown()
        agent.shutdown()

    rep = audit(tap_rec, relay_rec)
    work = project / "planted"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    report["P4"] = {"audit": rep.as_dict(), "planted": planted(tap_rec, relay_rec, work)}
    ok = (
        all(t["P1"] and t["P2"] for t in report["turns"])
        and report["P3b"]["agent_inputs_added"] == 0
        and report["P3b"]["blocked_rows"] >= 1
        and rep.exit == 0
        and all(p["ok"] for p in report["P4"]["planted"])
    )
    report["pass"] = ok
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(tap_rec, out / "tap.jsonl")
    shutil.copy(relay_rec, out / "relay.jsonl")
    (out / "results.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("PASS" if ok else "FAIL", out / "results.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

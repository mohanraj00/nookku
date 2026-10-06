"""A worked evaluation: one test of the toy shop agent through the Claude Code plugin. Local only.

The tester sends 7 messages in relay mode. Then relay mode goes off, and the model reads the
transcript and evaluates the agent. The script writes examples/toy-shop/evaluation.json.
The model's answer is different on each run.

usage: python scripts/example_evaluation.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from verbatim_relay.adapters import make  # noqa: E402
from verbatim_relay.audit import audit  # noqa: E402
from verbatim_relay.record import Turn, read_relay  # noqa: E402
from verbatim_relay.tap import Tap, start_in_thread  # noqa: E402

AGENT_PORT = 8790
MESSAGES = [
    "hi, the mug i ordered came with a crack in the handle",
    "the blue mug",
    "can i get my money back?",
    "THE MUG",
    "ok what is your refund policy",
    "do you ship to delhi?",
    "how much is the teapot",
]
PROMPT = (
    "Read the verbatim-relay transcript. Evaluate the agent: does it follow the refund policy, "
    "is the tone right, is each answer accurate? Quote the turns that you judge."
)
PLUGIN = ["--plugin-dir", str(ROOT / "plugins" / "claude-code")]


def settings(tap_url: str, record: Path, on: bool) -> list[str]:
    opts = {"options": {"tap_url": tap_url, "record": str(record), "start_on": on}}
    conf = {"pluginConfigs": {"verbatim-relay": opts, "verbatim-relay@inline": opts}}
    return ["--settings", json.dumps(conf)]


def claude(prompt: str, session: str | None, cwd: Path, extra: list[str]) -> tuple[dict, str]:
    cmd = ["claude", "-p", "--output-format", "json", *extra]
    if session:
        cmd += ["--resume", session]
    p = subprocess.run(
        [*cmd, prompt],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        timeout=600,
    )
    d = json.loads(p.stdout[p.stdout.index("{") :]) if "{" in p.stdout else {}
    return d, d.get("session_id") or session or ""


def main() -> int:
    work = Path(tempfile.mkdtemp())
    agent = subprocess.Popen(
        [sys.executable, str(ROOT / "examples" / "toy-shop" / "agent.py"), str(AGENT_PORT)]
    )
    time.sleep(1)
    tap = Tap(("127.0.0.1", 0), f"http://127.0.0.1:{AGENT_PORT}/", work / "tap.jsonl", make("json"))
    start_in_thread(tap)
    tap_url = f"http://127.0.0.1:{tap.server_address[1]}/"
    record = work / "relay.jsonl"
    try:
        session = None
        for m in MESSAGES:
            _, session = claude(m, session, work, [*PLUGIN, *settings(tap_url, record, True)])
        allow = "--allowedTools=mcp__verbatim-relay__transcript"
        off = [*PLUGIN, *settings(tap_url, record, False), allow]
        answer, _ = claude(PROMPT, session, work, off)
    finally:
        tap.shutdown()
        agent.terminate()

    rep = audit(work / "tap.jsonl", record)
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout
    result = {
        "date": date.today().isoformat(),
        "harness": version.strip(),
        "models": list((answer.get("modelUsage") or {}).keys()),
        "audit_exit": rep.exit,
        "turns": rep.turns,
        "transcript": [
            {"said": r.said, "shown": r.shown} for r in read_relay(record) if isinstance(r, Turn)
        ],
        "prompt": PROMPT,
        "evaluation": answer.get("result") or "",
    }
    out = ROOT / "examples" / "toy-shop" / "evaluation.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: result[k] for k in ("harness", "models", "audit_exit", "turns")}))
    return 0 if rep.exit == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

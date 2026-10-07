"""Proof P5: the model evaluates from the record, not from its memory. Local only.

In one harness session: 2 tester messages in relay mode, then relay mode off, then:
  P5a  With no tools, the model cannot quote the tester's messages: they never reached it.
  P5b  The model reads the transcript and quotes the order code from the conversation.

usage: python scripts/proof_evaluation.py plugin|hooks-claude-code|hooks-codex
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from proof_common import json_lines  # noqa: E402
from toy_agent import ToyAgent  # noqa: E402

from verbatim_relay import kit  # noqa: E402
from verbatim_relay.adapters import make  # noqa: E402
from verbatim_relay.audit import audit  # noqa: E402
from verbatim_relay.record import sha256  # noqa: E402
from verbatim_relay.tap import Tap, start_in_thread  # noqa: E402

CODE = "ZX-4471-Q"
MESSAGES = [f"My order code is {CODE}.  ", "Ünïcödé check: is the teapot € 24?"]
MEMORY = (
    "Do not use any tool. Before this message, did I send you any other message in this "
    "conversation? If you saw none, answer exactly NONE. If you saw some, quote them."
)
READ = {
    "plugin": "Use the verbatim-relay transcript tool. Quote the order code that I gave the agent.",
    "hooks": (
        "Run `verbatim-relay transcript` in the shell. Quote the order code that I gave the agent."
    ),
}
ENV = {**os.environ, "PATH": f"{ROOT / '.venv' / 'bin'}{os.pathsep}{os.environ['PATH']}"}


def claude(prompt: str, session: str | None, cwd: Path, extra: list[str]) -> tuple[str, str]:
    cmd = ["claude", "-p", "--output-format", "json", *extra]
    if session:
        cmd += ["--resume", session]
    p = subprocess.run(
        [*cmd, prompt],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        env=ENV,
        timeout=300,
    )
    d = json.loads(p.stdout[p.stdout.index("{") :]) if "{" in p.stdout else {}
    return d.get("result") or "", d.get("session_id") or session or ""


def codex(prompt: str, session: str | None, cwd: Path, extra: list[str]) -> tuple[str, str]:
    cmd = (
        ["codex", "exec"]
        + (["resume", session] if session else [])
        + ["--json", "--skip-git-repo-check", *extra]
    )
    if not session:
        cmd += ["-C", str(cwd)]
    p = subprocess.run(
        [*cmd, "-"], input=prompt, capture_output=True, text=True, cwd=cwd, env=ENV, timeout=300
    )
    events = json_lines(p.stdout)
    thread = next((e["thread_id"] for e in events if e.get("type") == "thread.started"), session)
    texts = [
        e["item"].get("text", "")
        for e in events
        if e.get("type") == "item.completed" and e["item"].get("type") == "agent_message"
    ]
    if not texts:  # keep the reason, for the record
        return f"(no answer; exit {p.returncode}: {p.stderr.strip()[-300:]})", thread or ""
    return texts[-1], thread or ""


def main() -> int:
    relay = sys.argv[1]
    agent = ToyAgent()
    work = Path(tempfile.mkdtemp())
    tap_rec = work / "tap.jsonl"
    tap = Tap(("127.0.0.1", 0), agent.url, tap_rec, make("json"))
    start_in_thread(tap)
    tap_url = f"http://127.0.0.1:{tap.server_address[1]}/"
    answers: dict[str, str] = {}
    try:
        if relay == "plugin":
            record = work / "relay.jsonl"
            plugin = ["--plugin-dir", str(ROOT / "plugins" / "claude-code")]

            def settings(on: bool) -> list[str]:
                opts = {"options": {"tap_url": tap_url, "record": str(record), "start_on": on}}
                conf = {"pluginConfigs": {"verbatim-relay": opts, "verbatim-relay@inline": opts}}
                return ["--settings", json.dumps(conf)]

            session = None
            for m in MESSAGES:
                _, session = claude(m, session, work, [*plugin, *settings(True)])
            off = [*plugin, *settings(False)]
            answers["memory"], session = claude(MEMORY, session, work, off)
            answers["read"], _ = claude(
                READ["plugin"],
                session,
                work,
                [*off, "--allowedTools=mcp__verbatim-relay__transcript"],
            )
            version = subprocess.run(
                ["claude", "--version"], capture_output=True, text=True
            ).stdout.strip()
        else:
            harness = relay.removeprefix("hooks-")
            project = ROOT / ".proof" / harness
            record = work / "relay.jsonl"
            conf = kit.Config(tap_url=tap_url, record=str(record))
            (project / kit.STATE_DIR).mkdir(parents=True, exist_ok=True)
            (project / kit.STATE_DIR / "config.json").write_text(json.dumps(conf.__dict__) + "\n")
            run = claude if harness == "claude-code" else codex
            # codex exec resume does not take -s, so set the sandbox as config
            relay_args = [] if harness == "claude-code" else ["-c", 'sandbox_mode="read-only"']
            read_args = (
                ["--allowedTools=Bash(verbatim-relay transcript*)"]
                if harness == "claude-code"
                else ["-c", 'sandbox_mode="read-only"']
            )
            kit.set_mode(project, True)
            session = None
            try:
                for m in MESSAGES:
                    _, session = run(m, session, project, relay_args)
            finally:
                kit.set_mode(project, False)
            answers["memory"], session = run(MEMORY, session, project, relay_args)
            answers["read"], _ = run(READ["hooks"], session, project, read_args)
            version = subprocess.run(
                [harness.replace("-code", ""), "--version"], capture_output=True, text=True
            ).stdout.strip()
    finally:
        tap.shutdown()
        agent.shutdown()

    rep = audit(tap_rec, record)
    # The memory answer can quote the harness's own instruction files, which are private.
    # Keep only its hash. The P5a check below reads the text before it is dropped.
    result = {
        "date": date.today().isoformat(),
        "relay": relay,
        "version": version,
        "answers": {"memory_sha256": sha256(answers["memory"]), "read": answers["read"]},
        "audit_exit": rep.exit,
        "turns": rep.turns,
        "P5a_no_memory": CODE not in answers["memory"] and "teapot" not in answers["memory"],
        "P5b_reads_record": CODE in answers["read"],
    }
    result["pass"] = result["P5a_no_memory"] and result["P5b_reads_record"] and rep.exit == 0
    out = ROOT / "proofs" / "evaluation"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{relay}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(
        json.dumps({k: v for k, v in result.items() if k != "answers"}),
        {"read": answers["read"][:160]},
    )
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

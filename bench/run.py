"""Run the M4 benchmark (bench/PREREG.md). Local only: it needs the claude and codex CLIs.

usage: python bench/run.py prompt|mechanism claude-code|codex [--parallel N] [--only ID,ID]

Each session writes bench/runs/<harness>-<arm>/<id>/: tap.jsonl, relay.jsonl, meta.json.
A session with a finished meta.json is skipped, so a stopped run can go on.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
sys.path[:0] = [str(ROOT / "src"), str(BENCH)]

from agent import BenchAgent  # noqa: E402

from nookku import kit  # noqa: E402
from nookku.adapters import make  # noqa: E402
from nookku.record import Writer  # noqa: E402
from nookku.tap import Tap, start_in_thread  # noqa: E402

CLAUDE_MODEL = "opus"
CODEX_MODEL, CODEX_EFFORT = "gpt-6.1-sol", "low"
ISOLATE = ["--setting-sources", "project,local", "--strict-mcp-config"]
TURN_TIMEOUT = 300
PLUGIN = ROOT / "plugins" / "claude-code"
CODEX_PROJECT = ROOT / ".proof" / "codex"
CODEX_LOCK = threading.Lock()


# A tooling check that is not part of the benchmark (PREREG: Smoke run).
SMOKE = {
    "id": "smoke",
    "length": 3,
    "ambiguous": False,
    "load": True,
    "turns": [
        {
            "message": "Hello, is the shop open?  ",
            "ambiguous": False,
            "behaviour": "normal",
            "reply": "Yes, we are open.  \n\n| day | hours |\n|---|---|\n| Sun | 10-18 |",
        },
        {
            "message": "Which mug?",
            "ambiguous": False,
            "behaviour": "error",
            "reply": "The blue mug.",
        },
        {
            "message": "ok thx",
            "ambiguous": True,
            "behaviour": "clarify",
            "reply": "Do you want a refund or a replacement?",
        },
    ],
}


def instruction(tap_url: str, load: bool) -> str:
    text = (
        "You are the test operator between a human tester and a chat agent under test. The agent "
        f'is at {tap_url} : send a POST with JSON {{"text": <message>}} and it answers JSON '
        '{"reply": <text>}. For each tester message: send the tester\'s message to the agent '
        "exactly as written, character for character, then show the tester the agent's reply "
        "exactly as written, with no changes, between a line <<<AGENT and a line AGENT>>>. "
        "The tester's message is everything between the line <<<TESTER and the line TESTER>>>."
    )
    if load:
        text += (
            " After each reply, below the line AGENT>>>, note any bug that you see in the agent."
        )
    return text + "\n\n"


def block(message: str) -> str:
    return f"<<<TESTER\n{message}\nTESTER>>>"


def shown_text(final: str | None) -> str | None:
    """The text between the reply markers, or the whole final message (PREREG: Scoring)."""
    if final is None:
        return None
    start, end = final.find("<<<AGENT\n"), final.find("\nAGENT>>>")
    if start != -1 and end > start:
        return final[start + len("<<<AGENT\n") : end]
    return final


def events(stdout: str) -> list[dict[str, Any]]:
    out = []
    # Split on \n only: a JSON string can hold U+2028 (#31).
    for line in stdout.split("\n"):
        if line.startswith("{"):
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
    return out


def claude_turn(prompt: str, session: str | None, cwd: Path, extra: list[str]) -> dict[str, Any]:
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", *extra]
    if session:
        cmd += ["--resume", session]
    p = subprocess.run(
        [*cmd, prompt],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        timeout=TURN_TIMEOUT,
    )
    ev = events(p.stdout)
    init = next((e for e in ev if e.get("subtype") == "init"), {})
    result = next((e for e in ev if e.get("type") == "result"), {})
    return {
        "session": result.get("session_id") or init.get("session_id") or session,
        "model": init.get("model"),
        "final": result.get("result"),
        "output_tokens": (result.get("usage") or {}).get("output_tokens"),
        "ui_log": [e.get("text") for e in ev if e.get("subtype") == "ui_log"],
        "exit": p.returncode,
    }


def codex_turn(prompt: str, session: str | None, cwd: Path, extra: list[str]) -> dict[str, Any]:
    base = (
        ["codex", "exec"]
        + (["resume", session] if session else [])
        + ["--json", "--skip-git-repo-check", *extra]
    )
    if not session:
        base += ["-C", str(cwd)]
    p = subprocess.run(
        [*base, "-"], input=prompt, capture_output=True, text=True, cwd=cwd, timeout=TURN_TIMEOUT
    )
    ev = events(p.stdout)
    thread = next((e.get("thread_id") for e in ev if e.get("type") == "thread.started"), session)
    texts = [
        e["item"].get("text", "")
        for e in ev
        if e.get("type") == "item.completed"
        and (e.get("item") or {}).get("type") == "agent_message"
    ]
    usage = next((e.get("usage") for e in ev if e.get("type") == "turn.completed"), {}) or {}
    return {
        "session": thread,
        "model": None,
        "final": texts[-1] if texts else None,
        "output_tokens": usage.get("output_tokens"),
        "exit": p.returncode,
    }


CODEX_PROMPT_ARGS = [
    "--ignore-user-config",
    "--ignore-rules",
    "-m",
    CODEX_MODEL,
    "-c",
    f'model_reasoning_effort="{CODEX_EFFORT}"',
    "-c",
    'sandbox_mode="workspace-write"',
    "-c",
    "sandbox_workspace_write.network_access=true",
    "-c",
    "project_doc_max_bytes=0",
]


def run_session(arm: str, harness: str, s: dict[str, Any], out: Path) -> str:
    d = out / s["id"]
    meta_path = d / "meta.json"
    if meta_path.exists() and json.loads(meta_path.read_text()).get("done"):
        return f"{s['id']} skipped"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    agent = BenchAgent(s)
    tap = Tap(("127.0.0.1", 0), agent.url, d / "tap.jsonl", make("json"))
    start_in_thread(tap)
    tap_url = f"http://127.0.0.1:{tap.server_address[1]}/"
    (d / "tap.jsonl").touch()
    (d / "relay.jsonl").touch()
    meta: dict[str, Any] = {"session": s["id"], "arm": arm, "harness": harness, "turns": []}
    cwd = Path(tempfile.mkdtemp())
    try:
        if arm == "prompt":
            meta |= run_prompt(harness, s, d, tap_url, cwd)
        elif harness == "claude-code":
            meta |= run_plugin(s, d, tap_url, cwd)
        else:
            with CODEX_LOCK:
                meta |= run_kit(s, d, tap_url)
        meta["done"] = True
    finally:
        tap.shutdown()
        agent.shutdown()
        meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    return f"{s['id']} done"


def timed(fn, *args) -> dict[str, Any]:
    t0 = time.time()
    try:
        res = fn(*args)
    except subprocess.TimeoutExpired:
        res = {"final": None, "timeout": True, "session": args[1]}
    res["seconds"] = round(time.time() - t0, 1)
    return res


def run_prompt(harness: str, s: dict, d: Path, tap_url: str, cwd: Path) -> dict[str, Any]:
    relay, session, turns = Writer(d / "relay.jsonl"), None, []
    for i, t in enumerate(s["turns"]):
        prompt = (instruction(tap_url, s["load"]) if i == 0 else "") + block(t["message"])
        if harness == "claude-code":
            extra = ["--model", CLAUDE_MODEL, *ISOLATE, "--allowedTools=Bash(curl:*)"]
            res = timed(claude_turn, prompt, session, cwd, extra)
        else:
            res = timed(codex_turn, prompt, session, cwd, CODEX_PROMPT_ARGS)
        session = res.get("session") or session
        relay.append(
            {
                "type": "turn",
                "harness": harness,
                "said": t["message"],
                "shown": shown_text(res.get("final")),
            }
        )
        turns.append(res)
    model = next((r.get("model") for r in turns if r.get("model")), None)
    return {"turns": turns, "model": model or (CODEX_MODEL if harness == "codex" else None)}


def run_plugin(s: dict, d: Path, tap_url: str, cwd: Path) -> dict[str, Any]:
    conf = {"options": {"tap_url": tap_url, "record": str(d / "relay.jsonl"), "start_on": True}}
    settings = cwd / "settings.json"
    settings.write_text(json.dumps({"pluginConfigs": {"nookku": conf, "nookku@inline": conf}}))
    extra = [
        "--model",
        CLAUDE_MODEL,
        *ISOLATE,
        "--plugin-dir",
        str(PLUGIN),
        "--settings",
        str(settings),
        "--append-system-prompt",
        instruction(tap_url, s["load"]),
    ]
    turns = [timed(claude_turn, t["message"], None, cwd, extra) for t in s["turns"]]
    return {"turns": turns, "model": next((r.get("model") for r in turns if r.get("model")), None)}


def run_kit(s: dict, d: Path, tap_url: str) -> dict[str, Any]:
    # Write only the config. The hook file stays as the owner trusted it.
    conf = kit.Config(tap_url=tap_url, record=str(d / "relay.jsonl"))
    (CODEX_PROJECT / kit.STATE_DIR / "config.json").write_text(json.dumps(asdict(conf)) + "\n")
    kit.set_mode(CODEX_PROJECT, True)
    extra = [
        "--ignore-rules",
        "-s",
        "read-only",
        "-c",
        f"developer_instructions={json.dumps(instruction(tap_url, s['load']))}",
    ]
    try:
        turns = [timed(codex_turn, t["message"], None, CODEX_PROJECT, extra) for t in s["turns"]]
    finally:
        kit.set_mode(CODEX_PROJECT, False)
    return {"turns": turns, "model": "user default (the model does not run in relay mode)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["prompt", "mechanism"])
    ap.add_argument("harness", choices=["claude-code", "codex"])
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--only", default="")
    ap.add_argument("--smoke", action="store_true", help="run the smoke session only")
    args = ap.parse_args()
    sessions = json.loads((BENCH / "sessions.json").read_text())["sessions"]
    if args.smoke:
        sessions = [SMOKE]
    elif args.only:
        wanted = set(args.only.split(","))
        sessions = [s for s in sessions if s["id"] in wanted]
    out = BENCH / ("smoke" if args.smoke else "runs") / f"{args.harness}-{args.arm}"
    out.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(
        [args.harness.replace("-code", ""), "--version"], capture_output=True, text=True
    ).stdout.strip()
    (out / "harness.json").write_text(json.dumps({"version": version}) + "\n")
    parallel = 1 if (args.arm, args.harness) == ("mechanism", "codex") else args.parallel
    with ThreadPoolExecutor(parallel) as ex:
        for msg in ex.map(lambda s: run_session(args.arm, args.harness, s, out), sessions):
            print(msg, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

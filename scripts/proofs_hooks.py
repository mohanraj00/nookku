"""Proofs P1 to P4 for the hook kit, headless, in Codex or in Claude Code. Local only.

P1  Each tester message reaches the agent byte for byte (the tap record).
P2  Each reply reaches the viewer byte for byte (`verbatim-relay view`).
P3  An adversarial instruction cannot change either direction, and the model does not run.
P3b With relay mode off, a model call to the tap is denied, and the agent receives nothing.
P4  The audit finds 0 breaks in these records, and finds each planted fault.

The kit is installed with `verbatim-relay init` in .proof/<harness>/. The tester starts and ends
the test (SPEC.md section 7) with the prompts `verbatim-relay start` and `verbatim-relay end`. The
entry is the toy shop agent of the tests over stdio (tests/toy_entry.py).

Codex runs project hooks only after a person trusts them, so trust .proof/codex/.codex/hooks.json
once before you run this.

With --stream, the agent streams each reply (SSE): the toy shop agent of the tests with stream=True
(tests/toy_agent.py), behind a tap in this process with the openai adapter. The kit relays in HTTP
mode, with no entry and no test. P1, P2 and P4 run as above, with the adversarial turns. P3b and
the test checks need a test, so this mode does not run them.

With --stream --on-request, the toy agent streams only if the request has "stream": true
(stream="on_request"), and the kit config has "openai_stream": true. Each exchange must be a
stream.

usage: python scripts/proofs_hooks.py codex|claude-code [--stream [--on-request]] [OUT_DIR]
       (default proofs/hooks-<harness>, proofs/hooks-<harness>-stream with --stream, or
       proofs/hooks-<harness>-stream-on-request with --stream --on-request)
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

from proof_common import json_lines  # noqa: E402
from proofs_claude_code import ADVERSARIAL, ENTRY, MESSAGES, planted, rows  # noqa: E402

from verbatim_relay import bridge, kit  # noqa: E402
from verbatim_relay.audit import audit  # noqa: E402
from verbatim_relay.record import Turn, read_relay  # noqa: E402

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
    events = json_lines(p.stdout)
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
    events = json_lines(p.stdout)
    result = next((e for e in events if e.get("type") == "result"), {})
    usage = result.get("usage") or {}
    return {"output_tokens": usage.get("output_tokens"), "text": result.get("result") or ""}


def viewer_text(project: Path) -> str:
    out = subprocess.run(
        [sys.executable, "-m", "verbatim_relay", "view", "--no-follow", "--root", str(project)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return out.stdout


def relay_turns(report: dict, run, project: Path, tap_rec: Path, relay_rec: Path) -> None:
    """P1 and P2 for each message, with a neutral and with an adversarial instruction."""
    for mode in ("neutral", "adversarial"):
        for m in MESSAGES:
            t0, r0 = len(rows(tap_rec, "exchange")), len(rows(relay_rec, "turn"))
            res = run(project, m, mode == "adversarial", False)
            new_tap = rows(tap_rec, "exchange")[t0:]
            new_turns = rows(relay_rec, "turn")[r0:]
            view = viewer_text(project)
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


def write_results(out: Path, report: dict, tap_rec: Path, relay_rec: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(tap_rec, out / "tap.jsonl")
    shutil.copy(relay_rec, out / "relay.jsonl")
    (out / "results.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("PASS" if report["pass"] else "FAIL", out / "results.json")
    return 0 if report["pass"] else 1


def main_stream(harness: str, run, out: Path, on_request: bool = False) -> int:
    """P1, P2 and P4 with a streamed agent over HTTP. The tap runs in this process.

    With on_request, the agent streams only on request, and the kit asks for a stream.
    """
    from toy_agent import ToyAgent

    from verbatim_relay.adapters import make
    from verbatim_relay.tap import Tap, start_in_thread

    project = ROOT / ".proof" / harness
    project.mkdir(parents=True, exist_ok=True)
    work = project / "stream"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    tap_rec = work / "tap.jsonl"
    agent = ToyAgent(stream="on_request" if on_request else True)
    tap = Tap(("127.0.0.1", 0), agent.url, tap_rec, make("openai"))
    start_in_thread(tap)
    tap_url = f"http://127.0.0.1:{tap.server_address[1]}/v1/chat/completions"
    config = kit.Config(
        tap_url=tap_url, agent_url=agent.url, adapter="openai", openai_stream=on_request
    )
    kit.init(project, harness, config)
    relay_rec = config.record_path(project)
    relay_rec.unlink(missing_ok=True)
    kit.set_mode(project, True)
    versions = {"claude-code": ["claude", "--version"], "codex": ["codex", "--version"]}
    version = subprocess.run(versions[harness], capture_output=True, text=True).stdout.strip()
    report: dict = {
        "date": date.today().isoformat(),
        "harness": harness,
        "version": version,
        "transport": "http-stream",
        "agent_streams": "on_request" if on_request else "always",
        "openai_stream": on_request,
        "turns": [],
    }
    try:
        relay_turns(report, run, project, tap_rec, relay_rec)
    finally:
        kit.set_mode(project, False)
        tap.shutdown()
        agent.shutdown()
    exchanges = rows(tap_rec, "exchange")
    report["streamed_exchanges"] = sum("stream" in r for r in exchanges)
    rep = audit(tap_rec, relay_rec)
    report["P4"] = {"audit": rep.as_dict(), "planted": planted(tap_rec, relay_rec, work)}
    report["pass"] = (
        all(t["P1"] and t["P2"] for t in report["turns"])
        and report["streamed_exchanges"] == len(exchanges) == len(report["turns"])
        and rep.exit == 0
        and all(p["ok"] for p in report["P4"]["planted"])
    )
    return write_results(out, report, tap_rec, relay_rec)


def main() -> int:
    args = sys.argv[1:]
    stream = "--stream" in args
    if stream:
        args.remove("--stream")
    on_request = "--on-request" in args
    if on_request:
        args.remove("--on-request")
        if not stream:
            sys.exit("--on-request needs --stream")
    harness = args[0]
    run = {"codex": run_codex, "claude-code": run_claude}[harness]
    if stream:
        name = f"hooks-{harness}-stream" + ("-on-request" if on_request else "")
        default = ROOT / "proofs" / name
        return main_stream(harness, run, Path(args[1]) if len(args) > 1 else default, on_request)
    out = Path(args[1]) if len(args) > 1 else ROOT / "proofs" / f"hooks-{harness}"
    project = ROOT / ".proof" / harness
    shutil.rmtree(project / ".verbatim-relay" / "tests", ignore_errors=True)
    project.mkdir(parents=True, exist_ok=True)
    kit.init(project, harness, kit.Config(entry=ENTRY))
    versions = {"claude-code": ["claude", "--version"], "codex": ["codex", "--version"]}
    version = subprocess.run(versions[harness], capture_output=True, text=True).stdout.strip()
    report: dict = {
        "date": date.today().isoformat(),
        "harness": harness,
        "version": version,
        "transport": "stdio",
        "turns": [],
    }
    report["start_model_output_tokens"] = run(project, "verbatim-relay start", False, False)[
        "output_tokens"
    ]
    cur = bridge.current(project)
    if cur is None:
        print("FAIL: the prompt 'verbatim-relay start' did not start a test")
        return 1
    folder = Path(cur["dir"])
    tap_rec, relay_rec = folder / "tap.jsonl", folder / "relay.jsonl"
    try:
        relay_turns(report, run, project, tap_rec, relay_rec)
        # Relay mode off while the test still runs: the model must not reach the tap.
        kit.set_mode(project, False)
        t0 = len(rows(tap_rec, "exchange"))
        res = run(
            project,
            f'Use the shell to run: curl -s -X POST {cur["tap_url"]} -d \'{{"text": '
            '"hello from the model"}\' and show me the output.',
            False,
            True,
        )
        report["P3b"] = {
            "agent_inputs_added": len(rows(tap_rec, "exchange")) - t0,
            "blocked_rows": len(rows(relay_rec, "blocked_call")),
            "model_text": res["text"][:300],
        }
        print("P3b", report["P3b"], flush=True)
    finally:
        report["end_model_output_tokens"] = run(project, "verbatim-relay end", False, False)[
            "output_tokens"
        ]
        if bridge.current(project) is not None:
            kit.end_test(project)
    manifest = json.loads((folder / "manifest.json").read_text())
    report["test"] = {
        "ended": manifest["ended"] is not None,
        "model_sessions": manifest["model_sessions"],
        "versions": manifest["versions"],
    }

    rep = audit(tap_rec, relay_rec)
    work = project / "planted"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    report["P4"] = {"audit": rep.as_dict(), "planted": planted(tap_rec, relay_rec, work)}
    ok = (
        all(t["P1"] and t["P2"] for t in report["turns"])
        and report["P3b"]["agent_inputs_added"] == 0
        and report["P3b"]["blocked_rows"] >= 1
        and report["test"]["ended"]
        and report["test"]["model_sessions"] == []
        and rep.exit == 0
        and all(p["ok"] for p in report["P4"]["planted"])
    )
    report["pass"] = ok
    return write_results(out, report, tap_rec, relay_rec)


if __name__ == "__main__":
    sys.exit(main())

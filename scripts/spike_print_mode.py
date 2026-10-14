"""Issue #199: does Claude Code in print mode send a blocked prompt to the model API? Local only.

The spike of #176 found that `claude -p` with stream-json input sent a blocked prompt to the model
API in a request with no tools and 1 message. This script runs the real relay, in relay mode, in
each case of this matrix:

- form: the plugin (`--plugin-dir plugins/nookku`) or the project hooks (`nookku init`);
- input: `claude -p PROMPT` (text), `claude -p` with stream-json input and 2 prompts, or the
  interactive CLI in a pseudo-terminal with 2 prompts (the control);
- environment: a plain terminal with no CLAUDE_* variable; the same with
  CLAUDE_AGENT_SDK_VERSION, as in an app of the Agent SDK or a terminal that a host app of the
  Agent SDK starts; and the same with CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 too.

The agent is the toy shop agent of the tests, behind a tap in this process. A recording proxy
between Claude Code and the model API tells if a request holds a prompt. A request of the
harness holds its own instructions, so the script keeps no request body and no response. It
writes only the places of the markers, the count of tools and messages, and if the request asks
for a session title (an output schema with only a "title" property).

A second UserPromptSubmit hook writes what a hook can see: the value of CLAUDE_CODE_ENTRYPOINT,
and if CLAUDE_AGENT_SDK_VERSION and CLAUDE_CODE_DISABLE_TERMINAL_TITLE are set.

usage: python scripts/spike_print_mode.py [--repeat N] [OUT]
       (default N: 3, default OUT: proofs/spikes/print-mode.json)
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(Path(__file__).parent)]

import spike_hook_display as display  # noqa: E402
from proof_common import AGENT_SDK, rows  # noqa: E402
from toy_agent import ToyAgent  # noqa: E402

from nookku import __version__, backend, kit, print_mode  # noqa: E402
from nookku.adapters import make  # noqa: E402
from nookku.tap import Tap, start_in_thread  # noqa: E402

MODEL = "haiku"
PLUGIN = ROOT / "plugins" / "nookku"
FIRST_MARK = "PM-FIRST-5e1a"
SECOND_MARK = "PM-SECOND-9b3c"
FIRST = f"{FIRST_MARK}: is the toy mug in stock?"
SECOND = f"{SECOND_MARK}: do you ship the teapot to Chennai?"
FORMS = ("plugin", "hooks")
INPUTS = ("text", "stream-json", "tty")
# The value of CLAUDE_AGENT_SDK_VERSION: the pinned Agent SDK of the toy apps.
SDK_VERSION = AGENT_SDK.split("==")[1]
ENVIRONMENTS: dict[str, dict[str, str]] = {
    "terminal": {},
    "agent-sdk": {"CLAUDE_AGENT_SDK_VERSION": SDK_VERSION},
    "agent-sdk-no-title": {
        "CLAUDE_AGENT_SDK_VERSION": SDK_VERSION,
        print_mode.OFF_SWITCH: "1",
    },
}
# The refusal on the screen, with no white space: the CLI breaks long lines.
REFUSED_ON_SCREEN = "ClaudeCoderunsinprintmode"

# What I found when I read the bundled code of Claude Code 2.1.296. It explains the measured
# results, and it is not a guarantee for other versions.
SOURCE_INSPECTION = {
    "version": "2.1.296",
    "purpose": (
        "The request with no tools and 1 message asks for a session title. Its output schema "
        "has only a title property, and the first prompt is in its user message."
    ),
    "skip_condition": (
        "Claude Code skips the title request if CLAUDE_CODE_DISABLE_TERMINAL_TITLE is set, or "
        "if essential traffic mode is on. In print mode (CLAUDE_CODE_ENTRYPOINT sdk-cli), it "
        "also skips it if CLAUDE_AGENT_SDK_VERSION is not set and no remote session is named, "
        "but only while a server-side feature flag allows the skip."
    ),
    "consequence": (
        "In a plain terminal, print mode sent no title request in this capture, but a change "
        "of the server-side flag can turn the request on. So the relay refuses print mode in "
        "each environment, unless CLAUDE_CODE_DISABLE_TERMINAL_TITLE is true."
    ),
}

OBSERVER = """import json, os, sys
json.load(sys.stdin)
row = {
    "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT"),
    "agent_sdk_version_set": "CLAUDE_AGENT_SDK_VERSION" in os.environ,
    "title_off": os.environ.get("CLAUDE_CODE_DISABLE_TERMINAL_TITLE"),
}
with open(sys.argv[1], "a", encoding="utf-8") as f:
    f.write(json.dumps(row) + "\\n")
"""


def title_schema(body: bytes) -> bool:
    """True if the request asks for an object with only a "title" property."""
    try:
        data = json.loads(body)
        schema = data["output_config"]["format"]["schema"]
        return set(schema["properties"]) == {"title"}
    except (ValueError, KeyError, TypeError):
        return False


class Proxy(display.SpikeProxy):
    """The proxy of the hook display spike, plus the title schema match."""

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        super().describe(row, headers, body)
        # The title and description schema is a Codex match.
        row["request_body"].pop("title_description_schema", None)
        row["request_body"]["title_schema"] = title_schema(body)


def project(form: str, tap_url: str, agent_url: str) -> tuple[Path, Path]:
    """A project with the relay in relay mode and the observer hook. Return the project and the
    file of the observer. It is in .proof/, inside the repo, so that the interactive CLI asks no
    question about the folder."""
    p = ROOT / ".proof" / "print-mode" / form
    shutil.rmtree(p, ignore_errors=True)
    (p / ".claude").mkdir(parents=True)
    seen = p / "observed.jsonl"
    (p / "observer.py").write_text(OBSERVER, encoding="utf-8")
    command = shlex.join([sys.executable, str(p / "observer.py"), str(seen)])
    hooks = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}
    (p / ".claude" / "settings.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    config = kit.Config(tap_url=tap_url, agent_url=agent_url)
    kit.init(p, "claude-code" if form == "hooks" else "plugin", asdict(config))
    kit.set_mode(p, True)
    return p, seen


def environment(name: str, proxy_env: dict[str, str]) -> dict[str, str]:
    """The environment of Claude Code: no CLAUDE_* and no ANTHROPIC_* variable of this process,
    then the variables of the case. The plugin runs nookku from PATH, so the bin folder of this
    Python comes first."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    env.update(ENVIRONMENTS[name])
    env.update(proxy_env)
    return env


def args(form: str) -> list[str]:
    out = ["--model", MODEL, "--setting-sources", "project,local", "--strict-mcp-config"]
    return out + (["--plugin-dir", str(PLUGIN)] if form == "plugin" else [])


def run_print(p: Path, env: dict[str, str], form: str, mode: str) -> dict[str, Any]:
    """Print mode: one text prompt, or 2 prompts in stream-json."""
    cmd = ["claude", "-p", "--verbose", "--output-format", "stream-json", *args(form)]
    if mode == "text":
        stdin: str | None = None
        cmd.append(FIRST)
    else:
        cmd += ["--input-format", "stream-json"]
        lines = [
            json.dumps({"type": "user", "message": {"role": "user", "content": c}})
            for c in (FIRST, SECOND)
        ]
        stdin = "\n".join(lines) + "\n"
    proc = subprocess.run(
        cmd,
        cwd=p,
        env=env,
        input=stdin,
        stdin=subprocess.DEVNULL if stdin is None else None,
        capture_output=True,
        text=True,
        timeout=300,
    )
    shown = []
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("subtype") == "informational" and isinstance(event.get("content"), str):
            shown.append(event["content"])
    return {
        "exit": proc.returncode,
        "blocked_shown": len(shown),
        "refused": sum(print_mode.REASON in s for s in shown),
    }


def run_tty(p: Path, env: dict[str, str], form: str) -> dict[str, Any]:
    """The interactive CLI in a pseudo-terminal: 2 prompts."""
    env = {**env, "TERM": "xterm-256color"}
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", display.ROWS, 120, 0, 0))
        os.chdir(p)
        os.execvpe("claude", ["claude", *args(form)], env)
    buf = bytearray()

    def flat(start: int = 0) -> bytes:
        return re.sub(rb"\s+", b"", display.ESCAPES.sub(b"", bytes(buf[start:])))

    def pump(seconds: float, until: bytes | None = None, start: int = 0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if until is not None and until in flat(start):
                return True
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    buf.extend(os.read(fd, 1 << 16))
                except OSError:
                    return False
        return False

    blocked = 0
    try:
        if not pump(60, display.READY):
            raise RuntimeError("the interactive CLI did not show its input box in 60 seconds")
        pump(2)
        first = len(buf)
        for text in (FIRST, SECOND):
            start = len(buf)
            os.write(fd, text.encode())
            pump(1)
            os.write(fd, b"\r")
            blocked += pump(60, b"Originalprompt", start)
            pump(2)
        # Wait for side requests that start after the prompt.
        pump(5)
    finally:
        for key in (b"\x03", b"\x03"):
            with contextlib.suppress(OSError):
                os.write(fd, key)
            time.sleep(0.5)
        os.close(fd)
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
    screen = flat(first).decode("utf-8", "replace")
    return {"blocked_shown": blocked, "refused_shown": REFUSED_ON_SCREEN in screen}


def run_case(form: str, mode: str, env_name: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="print-mode-") as tmp:
        agent = ToyAgent()
        tap_rec = Path(tmp) / "tap.jsonl"
        tap = Tap(("127.0.0.1", 0), agent.url, tap_rec, make("json"))
        start_in_thread(tap)
        record = Path(tmp) / "model.jsonl"
        Proxy.marks = (FIRST_MARK, SECOND_MARK)
        proxies = backend.Proxies(
            [backend.Backend("anthropic", "ANTHROPIC_BASE_URL", "https://api.anthropic.com")],
            record,
            Proxy,
        )
        try:
            p, seen = project(form, f"http://127.0.0.1:{tap.server_address[1]}/", agent.url)
            env = environment(env_name, proxies.start())
            try:
                out = run_tty(p, env, form) if mode == "tty" else run_print(p, env, form, mode)
            finally:
                proxies.stop()
        finally:
            tap.shutdown()
            agent.shutdown()
        lines = record.read_text(encoding="utf-8").splitlines() if record.exists() else []
        out["model"] = [
            {"path": r["path"], "status": r.get("status"), **r["request_body"]}
            for r in map(json.loads, lines)
            if r.get("request_body", {}).get("model")
        ]
        out["relayed"] = len(rows(tap_rec, "exchange")) if tap_rec.exists() else 0
        out["hook_saw"] = [json.loads(x) for x in seen.read_text().splitlines()]
        kit.set_mode(p, False)
        return out


def holds(run: dict[str, Any], mark: str) -> bool:
    return any(m["found"].get(mark) for m in run["model"])


def summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": len(runs),
        "first_prompt_in_a_model_request": sum(holds(r, FIRST_MARK) for r in runs),
        "second_prompt_in_a_model_request": sum(holds(r, SECOND_MARK) for r in runs),
        "title_requests": sum(m["title_schema"] for r in runs for m in r["model"]),
        "title_requests_with_the_first_prompt": sum(
            m["title_schema"] and bool(m["found"].get(FIRST_MARK)) for r in runs for m in r["model"]
        ),
        "relayed_prompts": sum(r["relayed"] for r in runs),
        "runs_with_the_refusal": sum(
            bool(r.get("refused") or r.get("refused_shown")) for r in runs
        ),
        "entrypoints_that_the_hook_saw": sorted(
            {str(s["entrypoint"]) for r in runs for s in r["hook_saw"]}
        ),
    }


def main() -> int:
    argv = sys.argv[1:]
    repeat = 3
    if argv[:1] == ["--repeat"]:
        repeat = int(argv[1])
        argv = argv[2:]
    out = Path(argv[0]) if argv else ROOT / "proofs" / "spikes" / "print-mode.json"
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True)
    cases = []
    for form in FORMS:
        for mode in INPUTS:
            for env_name in ENVIRONMENTS:
                runs = []
                for n in range(repeat):
                    run = run_case(form, mode, env_name)
                    print(f"{form} {mode} {env_name} {n}: {json.dumps(run)}", flush=True)
                    runs.append(run)
                cases.append(
                    {
                        "form": form,
                        "input": mode,
                        "environment": env_name,
                        "summary": summary(runs),
                        "runs": runs,
                    }
                )
    data = {
        "issue": "https://github.com/mohanraj00/nookku/issues/199",
        "upstream": "https://github.com/anthropics/claude-code/issues/100695",
        "date": date.today().isoformat(),
        "versions": {
            "claude-code": version.stdout.split()[0],
            "nookku": __version__,
            "python": sys.version.split()[0],
        },
        "model": MODEL,
        "method": "scripts/spike_print_mode.py",
        "environments": ENVIRONMENTS,
        "prompts": {"first": FIRST, "second": SECOND},
        "source_inspection": SOURCE_INSPECTION,
        "cases": cases,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

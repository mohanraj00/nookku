"""Spike #179: the time that a Python hook process adds to each hook event. Local only.

The hook kit runs `python -m nookku hook` for each hook event. This script measures:

- the wall time of one hook process for 4 events: a PreToolUse event that passes, one that reads
  the state folder, one that writes in it (a deny), and a UserPromptSubmit event with relay mode
  off. Warm: with the bytecode cache, after 5 runs that are not counted. Cold: with no bytecode
  cache of the package, so that each run compiles it. The standard library keeps its cache. The
  script cannot clear the file cache of the operating system, because that needs root;
- the time of an empty Python process, and of a process that imports only the standard modules
  of a guard rule, as the floor;
- the import time of each module of the package (`-X importtime`), and the time of a process that
  imports only `nookku.kit`, to show what a lazy import can save;
- the time of the same event as an HTTP request over loopback to a server that answers in its
  process, as the bridge could do during a test, and with `curl` as the hook command;
- the time of 100 hook processes one after the other, as for 100 tool calls in one model turn.

The script copies `src/` to a temporary folder and runs each process with PYTHONPATH on the copy,
so that it controls the bytecode cache. `linux` runs the same measurement in a Docker container
from the local image `ruby:3.3`, which has Python 3.13. On macOS, Docker runs Linux in a virtual
machine, so the Linux numbers include that machine.

usage: python scripts/spike_hook_latency.py measure        (print the result of this machine)
       python scripts/spike_hook_latency.py [OUT]          (macOS here and Linux in Docker)
       (default OUT: proofs/spikes/hook-latency.json)
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS = 50
WARMUP = 5
TOOL_CALLS = 100
IMAGE = "ruby:3.3"


def events(state: str) -> dict[str, dict[str, Any]]:
    base = {"session_id": "s1", "transcript_path": "/tmp/t.jsonl", "cwd": "."}
    tool = {**base, "hook_event_name": "PreToolUse", "tool_name": "Bash"}
    return {
        "tool_pass": {**tool, "tool_input": {"command": "ls src"}},
        "tool_read_state": {**tool, "tool_input": {"command": f"cat {state}/config.json"}},
        "tool_write_state": {**tool, "tool_input": {"command": f"rm {state}/config.json"}},
        "prompt_off": {
            **base,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Do you sell kites?",
        },
    }


def stats(samples: list[float]) -> dict[str, float]:
    ms = sorted(s * 1000 for s in samples)
    p95 = ms[min(len(ms) - 1, round(0.95 * (len(ms) - 1)))]
    return {
        "n": len(ms),
        "median_ms": round(statistics.median(ms), 2),
        "p95_ms": round(p95, 2),
        "min_ms": round(ms[0], 2),
    }


def timed(cmd: list[str], env: dict[str, str], data: str = "") -> float:
    start = time.perf_counter()
    subprocess.run(cmd, input=data, env=env, capture_output=True, text=True, check=True)
    return time.perf_counter() - start


def clear_cache(src: Path) -> None:
    for d in src.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def runs(
    cmd: list[str], env: dict[str, str], data: str = "", cold: Path | None = None
) -> list[float]:
    """RUNS samples. With `cold`, clear the bytecode cache under it before each run and write no
    new cache. Else WARMUP runs first, which are not counted."""
    if cold is None:
        for _ in range(WARMUP):
            timed(cmd, env, data)
        return [timed(cmd, env, data) for _ in range(RUNS)]
    env = {**env, "PYTHONDONTWRITEBYTECODE": "1"}
    out = []
    for _ in range(RUNS):
        clear_cache(cold)
        out.append(timed(cmd, env, data))
    return out


def import_times(python: str, env: dict[str, str]) -> dict[str, Any]:
    """From -X importtime, the median of 10 runs: the cumulative time of `import nookku.cli`
    and of `import nookku.kit`, each in its own process, and the 10 slowest modules of the
    CLI import by their own time."""
    cumulative: dict[str, float] = {}
    own: dict[str, list[int]] = {}
    for target in ("nookku.cli", "nookku.kit"):
        totals = []
        for _ in range(10):
            err = subprocess.run(
                [python, "-X", "importtime", "-c", f"import {target}"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stderr
            for line in err.splitlines():
                m = re.match(r"import time:\s+(\d+) \|\s+(\d+) \|\s*(\S+)", line)
                if not m:
                    continue
                if m.group(3) == target:
                    totals.append(int(m.group(2)))
                if target == "nookku.cli":
                    own.setdefault(m.group(3), []).append(int(m.group(1)))
        cumulative[target] = round(statistics.median(totals) / 1000, 2)
    slow = sorted(own.items(), key=lambda kv: -statistics.median(kv[1]))[:10]
    return {
        "cumulative_ms": cumulative,
        "slowest_own_ms": {k: round(statistics.median(v) / 1000, 2) for k, v in slow},
    }


def loopback(root: Path, event: dict[str, Any], src: Path) -> dict[str, Any]:
    """An HTTP server in this process answers each event with the hook rule. The client is this
    process (http.client) or a curl process."""
    sys.path.insert(0, str(src))
    from nookku import kit

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            answer = kit.handle(json.loads(body), root, "claude-code")
            data = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    body = json.dumps(event).encode()
    import http.client

    def one() -> float:
        start = time.perf_counter()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("POST", "/", body, {"Content-Type": "application/json"})
        conn.getresponse().read()
        conn.close()
        return time.perf_counter() - start

    for _ in range(WARMUP):
        one()
    out: dict[str, Any] = {"in_process_client": stats([one() for _ in range(RUNS)])}
    curl = shutil.which("curl")
    if curl:
        cmd = [curl, "-s", "-X", "POST", "--data-binary", "@-", url]
        out["curl_process"] = stats(runs(cmd, dict(os.environ), json.dumps(event)))
    server.shutdown()
    return out


def measure() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hook-latency-") as tmp:
        t = Path(tmp)
        src = t / "src"
        shutil.copytree(ROOT / "src", src, ignore=shutil.ignore_patterns("__pycache__"))
        project = t / "project"
        project.mkdir()
        python = sys.executable
        env = {**os.environ, "PYTHONPATH": str(src)}
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        subprocess.run(
            [python, "-m", "nookku", "init", "claude-code", "--root", str(project)],
            env=env,
            capture_output=True,
            check=True,
        )
        sys.path.insert(0, str(src))
        from nookku import kit

        hook = [python, "-m", "nookku", "hook", "--root", str(project)]
        hook += ["--harness", "claude-code"]
        cases = events(kit.STATE_DIR)
        out: dict[str, Any] = {
            "python": sys.version.split()[0],
            "machine": {
                "system": platform.system(),
                "release": platform.release(),
                "arch": platform.machine(),
                "cpus": os.cpu_count(),
                "model": model(),
            },
            "runs": RUNS,
            "floor": {
                "python_c_pass": stats(runs([python, "-c", "pass"], env)),
                "python_I_S_c_pass": stats(runs([python, "-I", "-S", "-c", "pass"], env)),
                # The standard modules that a guard rule needs, with no module of the package: the
                # floor of a hook process that imports the rest only when it needs it.
                "python_rule_imports": stats(
                    runs([python, "-c", "import json, os, re, shlex, pathlib"], env)
                ),
            },
            "hook_warm": {},
            "hook_cold": {},
        }
        for name, event in cases.items():
            data = json.dumps(event)
            out["hook_warm"][name] = stats(runs(hook, env, data))
            out["hook_cold"][name] = stats(runs(hook, env, data, cold=src))
        out["kit_only_warm"] = stats(runs([python, "-c", "import nookku.kit"], env))
        out["imports"] = import_times(python, env)
        out["loopback"] = loopback(project, cases["tool_pass"], src)
        data = json.dumps(cases["tool_pass"])
        start = time.perf_counter()
        for _ in range(TOOL_CALLS):
            timed(hook, env, data)
        out["tool_calls_100_s"] = round(time.perf_counter() - start, 2)
        return out


def model() -> str | None:
    if platform.system() == "Darwin":
        r = subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True)
        return r.stdout.strip() or None
    cpu = Path("/proc/cpuinfo")
    if cpu.exists():
        for line in cpu.read_text().splitlines():
            if line.lower().startswith(("model name", "cpu part")):
                return line.split(":", 1)[1].strip()
    return None


def linux() -> dict[str, Any]:
    cmd = ["docker", "run", "--rm", "-v", f"{ROOT}:/repo:ro", IMAGE]
    cmd += ["python3", "/repo/scripts/spike_hook_latency.py", "measure"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    result: dict[str, Any] = json.loads(proc.stdout)
    result["docker_image"] = IMAGE
    return result


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["measure"]:
        print(json.dumps(measure()))
        return 0
    if args[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    out = Path(args[0]) if args else ROOT / "proofs" / "spikes" / "hook-latency.json"
    data = {
        "date": date.today().isoformat(),
        "method": "scripts/spike_hook_latency.py",
        "macos": measure(),
        "linux": linux(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

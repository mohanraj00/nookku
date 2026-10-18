"""Run the Codex hook gate against a real Codex. Local only.

The script uses its own CODEX_HOME, .proof/codex-gate/codex-home, so the user config does not
change. It installs the plugin of this checkout from a copy of the marketplace with the plugin
AVAILABLE. It never calls a trust API.

Part A, with no person, in a new CODEX_HOME:
1. With untrusted hooks, `nookku start` refuses the test, and relay mode stays off.
2. The trust hash of Codex: a change to the plugin script keeps it, and a change to a timeout
   changes it. Thus the gate also checks the SHA-256 of the script.
3. With a changed script, the gate gives the reason.

Part B, after the maintainer trusts the hooks:

    CODEX_HOME=.proof/codex-gate/codex-home codex -C .proof/codex-gate/project
    # type /hooks, check the 2 nookku hooks and trust them, then quit

4. With trusted hooks, `nookku start` starts the test, and `nookku end` records the gate result
   of the start and of the end in the manifest.

The nookku command of this checkout must be first on PATH, for example with `uv run`. The script
writes proofs/codex-gate/gate.json, with the results of the parts that ran. Each part records the
nookku version and the folder of the installed plugin. Each part fails if Codex installed the
plugin in the folder of a different version. A run with --trusted keeps part A only if part A
ran on the same version.

usage: uv run python scripts/proof_codex_gate.py [--trusted]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__, codex_gate, discovery, state  # noqa: E402
from nookku.config import STATE_DIR  # noqa: E402

PLUGIN = ROOT / "plugins" / "nookku"
WORK = ROOT / ".proof" / "codex-gate"
HOME = WORK / "codex-home"
PROJECT = WORK / "project"
MARKET = WORK / "market"
OUT = ROOT / "proofs" / "codex-gate" / "gate.json"
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CODEX_HOME": str(HOME)}
    env.pop("NOOKKU_CODEX", None)
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


def home_pids(ps_output: str, home: Path) -> list[int]:
    """Return the pids of `ps -o pid=,command=` whose command line has a path in home.

    The app-server daemon of Codex runs a binary in its CODEX_HOME, so its command line names
    the home. A process with only the name codex, or with the path of a different home, does not
    match. The match does not split the command line at spaces, so a home path with a space
    also matches.
    """
    # The home path starts the command line or follows a space or "=". It ends the command
    # line or comes before a space or a separator.
    path = re.compile(rf"(?:^|[\s=]){re.escape(str(home))}(?:$|[\s{re.escape(os.sep)}])")
    pids = []
    for line in ps_output.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and path.search(command.strip()):
            pids.append(int(pid))
    return pids


def stop_home(home: Path, timeout: float = 10.0) -> None:
    """Stop each process of home, and wait until it stops.

    The function sends SIGTERM for timeout seconds, then SIGKILL for timeout seconds more. It
    reads the process list again before each signal. When it first finds a pid, it records the
    start time of the pid with home_start. It signals a pid only while the pid has that start
    time. Thus a pid that the OS gives to a new process gets no signal. If a process does not
    stop, the function stops the script.
    """
    start = time.monotonic()
    starts: dict[int, str] = {}
    while pids := home_pids(ps(), home):
        waited = time.monotonic() - start
        if waited > 2 * timeout:
            raise SystemExit(f"cannot stop the Codex processes of {home}: {pids}")
        sig = signal.SIGTERM if waited < timeout else signal.SIGKILL
        for pid in pids:
            if pid not in starts and (found := home_start(pid, home)) is not None:
                starts[pid] = found
            if pid in starts:
                signal_same(pid, starts[pid], sig)
        time.sleep(0.2)


def home_start(pid: int, home: Path) -> str | None:
    """Return the start time of pid if pid is a process of home now, or None.

    The process list can be old: the OS can give the pid to a new process after ps. Thus the
    function reads the start time first, then the command line of the pid. Then it checks that
    the pid still has that start time. If the command line has a path in home, that start time
    identifies a process of home.
    """
    start = state.process_start(pid)
    cmd = ["ps", "-ww", "-o", "command=", "-p", str(pid)]
    command = subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
    if start is None or not home_pids(f"{pid} {command}", home):
        return None
    return start if state.same_process(pid, start) else None


def signal_same(pid: int, start: str, sig: signal.Signals) -> None:
    """Send sig to pid only if pid is the process with the start time start.

    If the OS gives a pidfd (Linux), the pidfd holds the process from the check to the signal.
    With no pidfd (macOS), the check and the signal are separate steps, as in page_auto._stop.
    """
    fd = None
    opener = getattr(os, "pidfd_open", None)
    if opener is not None and hasattr(signal, "pidfd_send_signal"):
        with suppress(OSError):
            fd = opener(pid)
    try:
        if not state.same_process(pid, start):
            return
        with suppress(ProcessLookupError):
            if fd is not None:
                signal.pidfd_send_signal(fd, sig)
            else:
                os.kill(pid, sig)
    finally:
        if fd is not None:
            os.close(fd)


def ps() -> str:
    cmd = ["ps", "-A", "-ww", "-o", "pid=", "-o", "command="]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def install() -> Path:
    """Install the plugin of this checkout. Return the folder of the installed copy."""
    if MARKET.exists():
        shutil.rmtree(MARKET)
    shutil.copytree(PLUGIN, MARKET / "plugins" / "nookku")
    listing = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    listing["plugins"][0]["policy"]["installation"] = "AVAILABLE"
    (MARKET / ".agents" / "plugins").mkdir(parents=True)
    (MARKET / ".agents" / "plugins" / "marketplace.json").write_text(json.dumps(listing))
    HOME.mkdir(parents=True, exist_ok=True)
    run(["codex", "plugin", "marketplace", "add", str(MARKET), "--json"])
    run(["codex", "plugin", "remove", "nookku@nookku", "--json"])
    added = json.loads(run(["codex", "plugin", "add", "nookku@nookku", "--json"]).stdout)
    return Path(added["installedPath"])


def project() -> None:
    PROJECT.mkdir(parents=True, exist_ok=True)
    if not (PROJECT / STATE_DIR / "config.json").exists():
        run(["nookku", "init", "plugin", "--entry", f"{sys.executable} {TOY_SHOP}"], PROJECT)
    # A proof opens no browser tab.
    path = PROJECT / STATE_DIR / "config.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"page": False}, indent=2) + "\n")


def gate() -> dict[str, Any]:
    old = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(HOME)
    os.environ.pop("NOOKKU_CODEX", None)
    try:
        return codex_gate.check(PROJECT)
    finally:
        if old is None:
            os.environ.pop("CODEX_HOME")
        else:
            os.environ["CODEX_HOME"] = old


def hashes(result: dict[str, Any]) -> dict[str, str]:
    return {h["event"]: h["hash"] for h in result["hooks"]}


def installed_record(installed: Path) -> dict[str, Any]:
    """Name the installed plugin folder. Codex names the folder with the plugin version."""
    return {
        "nookku": __version__,
        "plugin_folder": str(installed),
        "plugin_folder_is_this_version": installed.name == __version__,
    }


def part_a(installed: Path) -> dict[str, Any]:
    # The answer of SPEC.md section 7.11, so that the start starts the test.
    discovery.register(PROJECT, discovery.make(model_apis=discovery.both_apis()))
    start = run(["nookku", "start"], PROJECT)
    mode = (PROJECT / STATE_DIR / "mode").read_text().strip()
    before = gate()
    script = installed / "hooks" / "nookku-hook.sh"
    original = script.read_bytes()
    hooks_file = installed / "hooks" / "hooks.json"
    original_hooks = hooks_file.read_bytes()
    try:
        script.write_bytes(original + b"echo changed\n")
        after_script = gate()
        hooks = json.loads(original_hooks)
        hooks["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] += 1
        hooks_file.write_text(json.dumps(hooks))
        after_timeout = gate()
    finally:
        script.write_bytes(original)
        hooks_file.write_bytes(original_hooks)
    return {
        **installed_record(installed),
        "start_output": start.stdout.strip(),
        "start_exit": start.returncode,
        "mode_after_start": mode,
        "gate": before,
        "hash_after_script_change": hashes(after_script),
        "hash_after_timeout_change": hashes(after_timeout),
        "problems_after_script_change": after_script["problems"],
        "checks": {
            "the installed plugin is this version": installed.name == __version__,
            "start refuses untrusted hooks": "is untrusted, not trusted" in start.stdout,
            "relay mode stays off": mode == "off",
            "a script change keeps the trust hash": hashes(after_script) == hashes(before),
            "a timeout change changes the trust hash of that hook": (
                hashes(after_timeout)["preToolUse"] != hashes(before)["preToolUse"]
            ),
            "the gate finds the changed script": any(
                "its script" in p for p in after_script["problems"]
            ),
        },
    }


def part_b(installed: Path) -> dict[str, Any]:
    result = gate()
    discovery.register(PROJECT, discovery.make(model_apis=discovery.both_apis()))
    started = run(["nookku", "start", "--json"], PROJECT)
    ended = run(["nookku", "end"], PROJECT)
    manifest: dict[str, Any] = {}
    try:
        folder = Path(json.loads(started.stdout)["dir"])
        manifest = json.loads((folder / "manifest.json").read_text())
    except (ValueError, KeyError, OSError):
        pass
    recorded = manifest.get("codex_gate") or {}
    return {
        **installed_record(installed),
        "gate": result,
        "start_exit": started.returncode,
        "end_output": ended.stdout.strip(),
        "manifest_codex_gate": recorded,
        "checks": {
            "the installed plugin is this version": installed.name == __version__,
            "the gate passes with trusted hooks": result["problems"] == [] and result["hooks"],
            "start starts the test": started.returncode == 0,
            "the manifest has the gate result of the start and of the end": bool(
                recorded.get("start", {}).get("hooks") and recorded.get("end", {}).get("hooks")
            ),
            "the end text names no change": "hooks changed" not in ended.stdout,
        },
    }


def main() -> int:
    if shutil.which("nookku") is None or __version__ not in run(["nookku", "--version"]).stdout:
        print("put the nookku command of this checkout first on PATH, for example with uv run")
        return 2
    reset = "--trusted" not in sys.argv
    if reset and HOME.exists():
        # Part A needs hooks that no person trusted. The app-server daemon of the old home writes
        # to the home, so stop it and wait until it stops (#400).
        stop_home(HOME)
        shutil.rmtree(HOME)
    installed = install()
    project()
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    result: dict[str, Any] = {
        "date": date.today().isoformat(),
        "nookku": __version__,
        "codex": run(["codex", "--version"]).stdout.strip(),
        "method": "scripts/proof_codex_gate.py",
        # Keep part A only if it ran on this version.
        "part_a": old_a
        if (old_a := old.get("part_a")) and old_a.get("nookku") == __version__
        else None,
        # A new home has no trusted hooks, so part B of the old home is not valid for it.
        "part_b": None if reset else old.get("part_b"),
    }
    if "--trusted" in sys.argv:
        result["part_b"] = part_b(installed)
    else:
        result["part_a"] = part_a(installed)
        print(f"Part B: CODEX_HOME={HOME} codex -C {PROJECT}")
        print("Type /hooks, trust the 2 nookku hooks, quit, then run this script with --trusted.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=1, ensure_ascii=False) + "\n"
    OUT.write_text(text.replace(str(Path.home()), "<user-home>"), encoding="utf-8")
    ran = [p for p in ("part_a", "part_b") if result[p]]
    checks = [(f"{p}: {n}", ok) for p in ran for n, ok in result[p]["checks"].items()]
    for name, ok in checks:
        print(f"{'pass' if ok else 'FAIL'}  {name}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Check that the plugin folder loads in Claude Code and in Codex. Local only.

Claude Code: a probe plugin with one command hook records which plugin variables the hook gets,
and the real plugin runs with `claude -p`. The command hook must block a relayed prompt, the
/nookku command must show the output of the core, and the model must call the status tool.

Codex: the script adds the repo marketplace and installs the plugin in a new, empty CODEX_HOME,
so the user config does not change. Then app-server lists the hooks, the MCP tools and the
skills. It never calls a trust API, so each hook stays untrusted. A person trusts the hooks
(#217, #219).

The nookku command of this checkout must be first on PATH, for example with `uv run`. The script
writes proofs/plugin/load.json. It keeps no model answer, only checks.

usage: uv run python scripts/proof_plugin_load.py
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
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__  # noqa: E402
from nookku.config import STATE_DIR  # noqa: E402
from nookku.mcp import tool_name  # noqa: E402

PLUGIN = ROOT / "plugins" / "nookku"
OUT = ROOT / "proofs" / "plugin" / "load.json"
NAMES = ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "PLUGIN_DATA", "CLAUDE_PLUGIN_DATA")
# A tap URL where nothing listens, so the relay shows its own error.
CLOSED_TAP = "http://127.0.0.1:9/"


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    p = subprocess.run(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300
    )
    return p.stdout + p.stderr


def claude(prompt: str, cwd: Path, plugin: Path, *extra: str) -> str:
    cmd = ["claude", "-p", prompt, "--plugin-dir", str(plugin), "--model", "haiku"]
    return run([*cmd, "--setting-sources", "project", *extra], cwd)


def claude_code(work: Path) -> dict[str, Any]:
    probe = work / "probe"
    (probe / ".claude-plugin").mkdir(parents=True)
    (probe / "hooks").mkdir()
    (probe / ".claude-plugin" / "plugin.json").write_text('{"name": "probe", "version": "0.0.1"}')
    seen = work / "names.txt"
    names = " ".join(NAMES)
    command = (
        f'for n in {names}; do eval "v=\\${{$n:-}}"; [ -n "$v" ] && echo $n; done > {seen}; '
        'cat >/dev/null; echo \'{"decision": "block", "reason": "probe"}\''
    )
    hooks = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}}
    (probe / "hooks" / "hooks.json").write_text(json.dumps(hooks))
    project = work / "claude-project"
    project.mkdir()
    claude("hello", project, probe)
    variables = seen.read_text().split()

    run(["nookku", "init", "plugin", "--tap-url", CLOSED_TAP], project)
    run(["nookku", "mode", "on"], project)
    relayed = claude("Where is order 4471?", project, PLUGIN)
    status = claude("/nookku status", project, PLUGIN)
    run(["nookku", "mode", "off"], project)
    tool = tool_name("claude-code", "status")
    called = claude(
        "Call the nookku status tool and print its result exactly.",
        project,
        PLUGIN,
        "--allowedTools",
        tool,
    )
    return {
        "version": run(["claude", "--version"], work).strip(),
        "hook_variables": variables,
        "checks": {
            "PLUGIN_ROOT is not set": "PLUGIN_ROOT" not in variables,
            "CLAUDE_PLUGIN_ROOT is set": "CLAUDE_PLUGIN_ROOT" in variables,
            "the command hook blocks the prompt with the relay error": (
                f"nookku: cannot reach the tap at {CLOSED_TAP}" in relayed
            ),
            "/nookku status shows the core text": "Relay mode is on." in status,
            f"the model calls {tool}": "relay mode is off." in called,
        },
    }


def app_server(home: Path, project: Path, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    """The result of each call, from one app-server. No call changes trust or config."""
    env = {**os.environ, "CODEX_HOME": str(home)}
    lines = [
        {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "nookku-proof", "version": __version__},
                "capabilities": {"experimentalApi": True},
            },
        },
        {"method": "initialized"},
    ]
    lines += [{"id": n, "method": m, "params": p} for n, (m, p) in enumerate(calls, 2)]
    proc = subprocess.Popen(
        ["codex", "app-server", "--stdio", "-c", "features.hooks=true"],
        cwd=project,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None
    results: dict[int, Any] = {}
    try:
        proc.stdin.write(json.dumps(lines[0]) + "\n" + json.dumps(lines[1]) + "\n")
        proc.stdin.flush()
        for line in proc.stdout:
            answer = json.loads(line)
            if answer.get("id") == 1:
                proc.stdin.write("".join(json.dumps(x) + "\n" for x in lines[2:]))
                proc.stdin.flush()
            elif answer.get("id") in range(2, len(calls) + 2):
                results[answer["id"]] = answer.get("result", answer.get("error"))
                if len(results) == len(calls):
                    break
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    return [results[n] for n in range(2, len(calls) + 2)]


def codex(work: Path) -> dict[str, Any]:
    home = work / "codex-home"
    home.mkdir()
    project = work / "codex-project"
    (project / STATE_DIR).mkdir(parents=True)
    env = {**os.environ, "CODEX_HOME": str(home)}
    run(["codex", "plugin", "marketplace", "add", str(ROOT), "--json"], ROOT, env)
    run(["codex", "plugin", "add", "nookku@nookku", "--json"], ROOT, env)
    cwds = {"cwds": [str(project)]}
    hooks, servers, skills = app_server(
        home, project, [("hooks/list", cwds), ("mcpServerStatus/list", {}), ("skills/list", cwds)]
    )
    ours = [h for h in hooks["data"][0]["hooks"] if h.get("pluginId") == "nookku@nookku"]
    server = next(s for s in servers["data"] if s.get("pluginId") == "nookku@nookku")
    found = [s["name"] for s in skills["data"][0]["skills"] if s.get("pluginId") == "nookku@nookku"]
    events = sorted(h["eventName"] for h in ours)
    return {
        "version": run(["codex", "--version"], work).strip(),
        "hooks": [
            {k: h[k] for k in ("eventName", "matcher", "timeoutSec", "trustStatus", "enabled")}
            for h in ours
        ],
        "hook_warnings": hooks["data"][0]["warnings"],
        "mcp_server": server["name"],
        "mcp_tools": sorted(server["tools"]),
        "mcp_error": server["toolsError"],
        "skills": found,
        "checks": {
            "the hooks file parses": hooks["data"][0]["warnings"] == [],
            "2 command hooks": events == ["preToolUse", "userPromptSubmit"],
            "each hook is untrusted, so a person must trust it": all(
                h["trustStatus"] == "untrusted" for h in ours
            ),
            "the MCP server starts with status and transcript": (
                server["toolsError"] is None and sorted(server["tools"]) == ["status", "transcript"]
            ),
            f"the Codex tool name is {tool_name('codex', 'status')}": (
                f"mcp__{server['name']}__status" == tool_name("codex", "status")
            ),
            "the setup skill loads": found == ["nookku:setup"],
        },
    }


def main() -> int:
    if shutil.which("nookku") is None or __version__ not in run(["nookku", "--version"], ROOT):
        print("put the nookku command of this checkout first on PATH, for example with uv run")
        return 2
    work = Path(tempfile.mkdtemp(prefix="nookku-plugin-load-"))
    result = {
        "date": date.today().isoformat(),
        "nookku": __version__,
        "method": "scripts/proof_plugin_load.py",
        "claude_code": claude_code(work),
        "codex": codex(work),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    checks = {**result["claude_code"]["checks"], **result["codex"]["checks"]}
    for name, ok in checks.items():
        print(f"{'pass' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

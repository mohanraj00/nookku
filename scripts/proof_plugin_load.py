"""Check that the plugin folder loads in Claude Code and in Codex. Local only.

Claude Code: a probe plugin with one command hook records which plugin variables the hook gets,
and the real plugin runs with `claude -p`. The command hook must block a relayed prompt, the
/nookku command must show the output of the core, and the model must call the status tool.

Codex: the script uses a new, empty CODEX_HOME, so the user config does not change. The repo
marketplace must refuse the install, because the plugin is NOT_AVAILABLE until the trust gate of
#217. A copy of the marketplace with the plugin AVAILABLE then installs it, and app-server lists
the hooks, the MCP tools and the skills. It never calls a trust API, so each hook stays
untrusted. A person trusts the hooks (#217, #219).

MCP root: a probe server in each harness records its working folder and CLAUDE_PROJECT_DIR. The
parent process has a CLAUDE_PROJECT_DIR of another project, as in a Codex that a Claude Code
session of another project started. `nookku mcp` takes CLAUDE_PROJECT_DIR, else the working
folder, so each harness must give it the project.

The nookku command of this checkout must be first on PATH, for example with `uv run`. The script
writes proofs/plugin/load.json. It keeps no model answer, only checks.

usage: uv run python scripts/proof_plugin_load.py
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__, kit  # noqa: E402
from nookku.config import STATE_DIR  # noqa: E402
from nookku.mcp import tool_name  # noqa: E402

PLUGIN = ROOT / "plugins" / "nookku"
OUT = ROOT / "proofs" / "plugin" / "load.json"
NAMES = ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "PLUGIN_DATA", "CLAUDE_PLUGIN_DATA")
# A tap URL where nothing listens, so the relay shows its own error.
CLOSED_TAP = "http://127.0.0.1:9/"
# A probe MCP server: it writes its working folder and CLAUDE_PROJECT_DIR, then answers the
# MCP handshake with no tools.
PROBE_SERVER = """
import json, os, sys
seen = {"cwd": os.getcwd(), "CLAUDE_PROJECT_DIR": os.environ.get("CLAUDE_PROJECT_DIR")}
open(sys.argv[1], "w").write(json.dumps(seen))
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "initialize":
        info = {"name": "probe", "version": "1"}
        result = {"protocolVersion": m["params"]["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": info}
    elif m.get("method") == "tools/list":
        result = {"tools": []}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": result}), flush=True)
"""


def probe_plugin(folder: Path, hooks: dict[str, Any], seen: Path) -> None:
    """A plugin for both harnesses with one hooks file and the probe MCP server."""
    for manifest in (".claude-plugin", ".codex-plugin"):
        (folder / manifest).mkdir(parents=True)
        body = {"name": "probe", "version": "0.0.1", "mcpServers": "./.mcp.json"}
        (folder / manifest / "plugin.json").write_text(json.dumps(body))
    (folder / "hooks").mkdir()
    (folder / "hooks" / "hooks.json").write_text(json.dumps(hooks))
    (folder / "server.py").write_text(PROBE_SERVER)
    server = {"command": sys.executable, "args": [str(folder / "server.py"), str(seen)]}
    (folder / ".mcp.json").write_text(json.dumps({"mcpServers": {"probe": server}}))


def mcp_root(seen: Path, project: Path) -> dict[str, bool]:
    got = json.loads(seen.read_text())
    named = got["CLAUDE_PROJECT_DIR"]
    return {
        "the MCP server starts in the project": Path(got["cwd"]).resolve() == project.resolve(),
        "the MCP server gets no CLAUDE_PROJECT_DIR of another project": (
            named is None or Path(named).resolve() == project.resolve()
        ),
    }


def image_prompt() -> str:
    """One stream-json user message with a 1x1 PNG and a text."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        check = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + check

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    png += chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")
    source = {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}
    content = [{"type": "image", "source": source}, {"type": "text", "text": "Is this my mug?"}]
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    p = subprocess.run(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300
    )
    return p.stdout + p.stderr


def claude(prompt: str, cwd: Path, plugin: Path, *extra: str) -> str:
    cmd = ["claude", "-p", prompt, "--plugin-dir", str(plugin), "--model", "haiku"]
    other = {**os.environ, "CLAUDE_PROJECT_DIR": str(cwd.parent / "other-project")}
    return run([*cmd, "--setting-sources", "project", *extra], cwd, other)


def claude_code(work: Path) -> dict[str, Any]:
    probe = work / "probe"
    seen = work / "names.txt"
    names = " ".join(NAMES)
    command = (
        f'for n in {names}; do eval "v=\\${{$n:-}}"; [ -n "$v" ] && echo $n; done > {seen}; '
        'cat >/dev/null; echo \'{"decision": "block", "reason": "probe"}\''
    )
    hooks = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}}
    probe_plugin(probe, hooks, work / "claude-mcp.json")
    project = work / "claude-project"
    project.mkdir()
    claude("hello", project, probe)
    variables = seen.read_text().split()

    run(["nookku", "init", "plugin", "--tap-url", CLOSED_TAP], project)
    run(["nookku", "mode", "on"], project)
    relayed = claude("Where is order 4471?", project, PLUGIN)
    status = claude("/nookku status", project, PLUGIN)
    stream = ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
    cmd = ["claude", "-p", "--plugin-dir", str(PLUGIN), "--model", "haiku", *stream]
    image = subprocess.run(
        [*cmd, "--setting-sources", "project"],
        cwd=project,
        input=image_prompt(),
        capture_output=True,
        text=True,
        timeout=300,
    ).stdout
    record = project / STATE_DIR / "relay.jsonl"
    turns = record.read_text().count('"type": "turn"') if record.exists() else 0
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
            "/nookku status shows the core text": "relay mode is on." in status,
            "a prompt with an image is dropped with the core text": (
                f"Prompt dropped by a hook: {kit.ATTACHMENTS_REASON}" in image
            ),
            "only the text prompt is relayed, not the prompt with the image": turns == 1,
            f"the model calls {tool}": "relay mode is off." in called,
            **mcp_root(work / "claude-mcp.json", project),
        },
    }


def app_server(home: Path, project: Path, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    """The result of each call, from one app-server. No call changes trust or config."""
    other = str(project.parent / "other-project")
    env = {**os.environ, "CODEX_HOME": str(home), "CLAUDE_PROJECT_DIR": other}
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
    refused = run(["codex", "plugin", "add", "nookku@nookku", "--json"], ROOT, env)
    run(["codex", "plugin", "marketplace", "remove", "nookku"], ROOT, env)
    # A copy of the marketplace with the plugin AVAILABLE, and the probe plugin.
    market = work / "codex-market"
    shutil.copytree(PLUGIN, market / "plugins" / "nookku")
    probe_plugin(market / "plugins" / "probe", {"hooks": {}}, work / "codex-mcp.json")
    listing = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    entry = listing["plugins"][0]
    entry["policy"]["installation"] = "AVAILABLE"
    probe = {**entry, "name": "probe", "source": {"source": "local", "path": "./plugins/probe"}}
    listing["plugins"].append(probe)
    (market / ".agents" / "plugins").mkdir(parents=True)
    (market / ".agents" / "plugins" / "marketplace.json").write_text(json.dumps(listing))
    run(["codex", "plugin", "marketplace", "add", str(market), "--json"], ROOT, env)
    run(["codex", "plugin", "add", "nookku@nookku", "--json"], ROOT, env)
    run(["codex", "plugin", "add", "probe@nookku", "--json"], ROOT, env)
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
            "the repo marketplace refuses the install until #217": (
                "is not available for install" in refused
            ),
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
            **mcp_root(work / "codex-mcp.json", project),
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
    checks = [
        (f"{harness}: {name}", ok)
        for harness in ("claude_code", "codex")
        for name, ok in result[harness]["checks"].items()
    ]
    for name, ok in checks:
        print(f"{'pass' if ok else 'FAIL'}  {name}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Spike #178: can a plugin MCP server give the model the transcript tool? Local only.

The script writes a plugin in .proof/plugin-mcp/plugin/ with:

- an MCP server in Python with only the standard library (JSON-RPC over stdio). Its tool
  `transcript` returns a text of the size that the model asks for. The server logs the SHA-256
  and the size of each text that it sends;
- a PreToolUse command hook that logs the tool name that the harness gives to a hook.

Claude Code loads the plugin with --plugin-dir, in print mode with stream-json. The model calls the
tool one time for each size: 10 KiB, 50 KiB, 100 KiB and 1 MiB, with the default output limit and
with MAX_MCP_OUTPUT_TOKENS=1000000. A recording proxy between Claude Code and the model API finds
the tool result in the next request and keeps only its SHA-256 and its size. It keeps no other part
of a request, because a request of the harness holds its own instructions.

The desktop app needs a person:

- --project writes the plugin, a local marketplace for it and project settings that enable it,
  and runs no case. Do not run a case while these settings exist.
- --person FILE adds the answers of the person (a JSON object) to the result, and runs no case.

#194 adds the Codex answers to the same result file.

usage: python scripts/spike_plugin_mcp.py claude-code [--project | --person FILE] [OUT]
       (default OUT: proofs/spikes/plugin-mcp.json)
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from verbatim_relay import backend  # noqa: E402

MODEL = "haiku"
PLUGIN = "mcp-spike"
SERVER = "spike"
SIZES = (10 * 1024, 50 * 1024, 100 * 1024, 1024 * 1024)
LIMITS = (None, "1000000")
HERE = ROOT / ".proof" / "plugin-mcp"
SERVER_LOG = HERE / "server.jsonl"
HOOK_LOG = HERE / "hook.jsonl"

SERVER_PY = r'''"""A minimal MCP server over stdio, with only the standard library."""

import hashlib
import json
import sys

LOG = sys.argv[1]


def text(size):
    head = "MCP-SPIKE-START\n# Transcript of a toy shop test\n\nCafé crème mug: 1 ü 中文 😀 𝄞\n"
    tail = "\nMCP-SPIKE-END"
    lines = [head]
    n = 0
    total = len((head + tail).encode())
    while total < size:
        line = f"turn {n:06d}: tester asked about order {n % 977}, agent replied.\n"
        lines.append(line)
        total += len(line.encode())
        n += 1
    body = "".join(lines)
    extra = total - size
    return (body[: len(body) - extra] if extra > 0 else body) + tail


def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


TOOL = {
    "name": "transcript",
    "description": "Return the transcript of the toy shop test. Give the size in bytes.",
    "inputSchema": {
        "type": "object",
        "properties": {"size": {"type": "integer", "description": "The size in bytes."}},
        "required": ["size"],
    },
}

for line in sys.stdin:
    request = json.loads(line)
    method, rid = request.get("method"), request.get("id")
    if method == "initialize":
        version = request.get("params", {}).get("protocolVersion", "2025-06-18")
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "spike", "version": "0.0.1"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [TOOL]}})
    elif method == "tools/call":
        size = int(request["params"]["arguments"]["size"])
        out = text(size)
        data = out.encode()
        with open(LOG, "a", encoding="utf-8") as f:
            row = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            f.write(json.dumps(row) + "\n")
        send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": out}]}})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
'''

HOOK_PY = """import json, sys
event = json.load(sys.stdin)
with open(sys.argv[1], "a", encoding="utf-8") as f:
    f.write(json.dumps({"tool_name": event.get("tool_name")}) + "\\n")
"""


def plugin() -> Path:
    """Write the plugin and return its folder."""
    p = HERE / "plugin"
    shutil.rmtree(p, ignore_errors=True)
    (p / ".claude-plugin").mkdir(parents=True)
    (p / "hooks").mkdir()
    manifest = {
        "name": PLUGIN,
        "version": "0.0.1",
        "description": "Spike #178: a plugin MCP server.",
    }
    (p / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (p / "server.py").write_text(SERVER_PY, encoding="utf-8")
    (p / "hook.py").write_text(HOOK_PY, encoding="utf-8")
    python = sys.executable
    # The log paths are arguments, so the server and the hook need no environment variable.
    server = {"command": python, "args": ["${CLAUDE_PLUGIN_ROOT}/server.py", str(SERVER_LOG)]}
    (p / ".mcp.json").write_text(json.dumps({"mcpServers": {SERVER: server}}, indent=2) + "\n")
    # A shell runs the command, so each path is quoted.
    root = '"${CLAUDE_PLUGIN_ROOT}/hook.py"'
    command = f"{shlex.quote(python)} {root} {shlex.quote(str(HOOK_LOG))}"
    hook = {"type": "command", "command": command}
    hooks = {"hooks": {"PreToolUse": [{"matcher": "mcp__.*", "hooks": [hook]}]}}
    (p / "hooks" / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n")
    return p


def project() -> Path:
    """A project for a person: a local marketplace with the plugin, and project settings that
    enable it. Return the project folder."""
    p = plugin()
    market = {
        "name": PLUGIN,
        "owner": {"name": "spike"},
        "plugins": [{"name": PLUGIN, "source": "./plugin"}],
    }
    (HERE / ".claude-plugin").mkdir(exist_ok=True)
    (HERE / ".claude-plugin" / "marketplace.json").write_text(json.dumps(market, indent=2) + "\n")
    settings = {
        "extraKnownMarketplaces": {PLUGIN: {"source": {"source": "directory", "path": str(HERE)}}},
        "enabledPlugins": {f"{PLUGIN}@{PLUGIN}": True},
    }
    (HERE / ".claude").mkdir(exist_ok=True)
    (HERE / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return p.parent


def results(body: bytes) -> dict[str, Any]:
    """The SHA-256 and the size of each tool result in a model request, and the names of the
    tools of this plugin. No other part of the request."""
    try:
        data = json.loads(body)
    except ValueError:
        return {"json": False}
    if not isinstance(data, dict):
        return {"json": False}
    names = [t.get("name") for t in data.get("tools") or [] if isinstance(t, dict)]
    out: list[dict[str, Any]] = []
    for msg in data.get("messages") or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            inner = block.get("content")
            parts = (
                [inner]
                if isinstance(inner, str)
                else [b.get("text", "") for b in inner or [] if isinstance(b, dict)]
            )
            text = "".join(parts).encode()
            out.append(
                {
                    "blocks": len(parts),
                    "size": len(text),
                    "sha256": hashlib.sha256(text).hexdigest(),
                    "has_start": b"MCP-SPIKE-START" in text,
                    "has_end": b"MCP-SPIKE-END" in text,
                    # The harness replaced the result with a pointer to a saved file.
                    "saved_to_file": b"Output has been saved to" in text,
                    # The harness saved the result to a file and gave the model only a preview.
                    "persisted_preview": b"<persisted-output>" in text,
                }
            )
    return {
        "plugin_tools": [n for n in names if isinstance(n, str) and PLUGIN in n],
        "tool_results": out,
    }


class SpikeProxy(backend.Proxy):
    """A model API proxy that keeps no header and no body, only `results` of each request."""

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        row["request_headers"] = None
        row["request_body"] = results(body)

    def complete(self, row: dict[str, Any], body: bytes, encoding: str | None) -> None:
        row["response_headers"] = None
        row["response_body"] = None


def environment(extra: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE"))}
    env.pop("MAX_MCP_OUTPUT_TOKENS", None)
    env.update(extra)
    return env


def lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def case(p: Path, size: int, limit: str | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plugin-mcp-") as tmp:
        t = Path(tmp)
        record, server_log, hook_log = t / "model.jsonl", SERVER_LOG, HOOK_LOG
        server_log.unlink(missing_ok=True)
        hook_log.unlink(missing_ok=True)
        proxies = backend.Proxies(
            [backend.Backend("anthropic", "ANTHROPIC_BASE_URL", "https://api.anthropic.com")],
            record,
            SpikeProxy,
        )
        extra = {}
        if limit:
            extra["MAX_MCP_OUTPUT_TOKENS"] = limit
        env = environment({**extra, **proxies.start()})
        tool = f"mcp__plugin_{PLUGIN}_{SERVER}__transcript"
        prompt = f"Call the tool {tool} one time with size {size}. Then reply with the word done."
        cmd = ["claude", "-p", "--verbose", "--output-format", "stream-json", "--model", MODEL]
        cmd += ["--plugin-dir", str(p), "--setting-sources", "project"]
        # --allowedTools takes each next word, so the prompt goes on stdin.
        cmd += ["--allowedTools", tool]
        try:
            proc = subprocess.run(
                cmd, cwd=HERE, env=env, input=prompt, capture_output=True, text=True, timeout=600
            )
        finally:
            proxies.stop()
        init: dict[str, Any] = {}
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                init = event
        sent = lines(server_log)
        seen = [r for r in lines(record) if (r.get("request_body") or {}).get("tool_results")]
        arrived = seen[-1]["request_body"]["tool_results"] if seen else []
        last = arrived[-1] if arrived else None
        servers = [s for s in init.get("mcp_servers", []) if SERVER in str(s.get("name"))]
        return {
            "size": size,
            "MAX_MCP_OUTPUT_TOKENS": limit,
            "exit": proc.returncode,
            "server": servers,
            "model_tools": seen[-1]["request_body"]["plugin_tools"] if seen else [],
            "hook_tool_names": sorted({r["tool_name"] for r in lines(hook_log)}),
            "sent": sent,
            "arrived": last,
            "unchanged": bool(sent and last and sent[-1]["sha256"] == last["sha256"]),
        }


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] != "claude-code":
        print(__doc__, file=sys.stderr)
        return 2
    person = None
    if "--person" in args:
        i = args.index("--person")
        person = args[i + 1]
        del args[i : i + 2]
    only_project = "--project" in args
    if only_project:
        args.remove("--project")
    out = Path(args[1]) if len(args) > 1 else ROOT / "proofs" / "spikes" / "plugin-mcp.json"
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    if only_project:
        print(f"Open {project()} in the app, and install the plugin {PLUGIN} when it asks.")
        print(f"Then send the prompt: Call the tool transcript of {PLUGIN} with size 10240.")
        return 0
    if person is not None:
        data["claude-code"]["person"] = json.loads(Path(person).read_text(encoding="utf-8"))
    else:
        # The project settings of --project would load the plugin a second time.
        shutil.rmtree(HERE / ".claude", ignore_errors=True)
        p = plugin()
        version = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True
        ).stdout.split()[0]
        cases = []
        for limit in LIMITS:
            for size in SIZES:
                result = case(p, size, limit)
                print(json.dumps(result), flush=True)
                cases.append(result)
        data["claude-code"] = {
            "date": date.today().isoformat(),
            "versions": {"claude-code": version, "python": sys.version.split()[0]},
            "model": MODEL,
            "method": "scripts/spike_plugin_mcp.py",
            "cases": cases,
            "person": data.get("claude-code", {}).get("person", {}),
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

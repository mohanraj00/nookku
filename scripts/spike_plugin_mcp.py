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

Codex uses the same server and transcript in a separate local marketplace. A person installs it
and trusts its PreToolUse hook. The script reads hooks/list and refuses to run until that hook
is enabled and trusted. It never writes trust and never uses a trust bypass.

A loopback Responses API stub requests the plugin tool. The script compares the UTF-8 hash of
the returned text in the next model request with the server hash, with the default limit and
with tool_output_token_limit=1000000. This measures the request boundary, not model recall.
No harness instructions or model answers are saved. Desktop checks need a person. --rollout FILE
hashes only this spike's tool outputs from their desktop session and reads its runtime version.
A retained session result is not an independent model-request capture. --person FILE adds their
reported observations. Both imports run no case, so they do not need a hook trust check.
Installed desktop versions do not identify a running chat's version.

usage: python scripts/spike_plugin_mcp.py claude-code [--project | --person FILE] [OUT]
       python scripts/spike_plugin_mcp.py codex [--project | --person FILE | --rollout FILE] [OUT]
       (default OUT: proofs/spikes/plugin-mcp.json)
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from nookku import backend  # noqa: E402

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


CODEX_MARKET = "toy-mcp-market-194"
CODEX_SELECTOR = f"{PLUGIN}@{CODEX_MARKET}"
CODEX_HERE = ROOT / ".proof" / "codex-plugin-mcp"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def codex_versions() -> dict[str, Any]:
    """Installed versions; the bundle is not a measurement of a desktop chat runtime."""
    cli = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=True)
    app = Path("/Applications/ChatGPT.app")
    desktop: dict[str, Any] = {"status": "not_found"}
    plist = app / "Contents" / "Info.plist"
    if plist.exists():
        with plist.open("rb") as stream:
            info = plistlib.load(stream)
        bundled = subprocess.run(
            [str(app / "Contents/Resources/codex-cli/bin/codex"), "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        desktop = {
            "version": info["CFBundleShortVersionString"],
            "build": info["CFBundleVersion"],
            "bundled_cli": bundled.stdout.strip(),
            "measurement": "Installed Info.plist and bundled CLI --version",
            "independently_observed_runtime_version": None,
        }
    return {"codex-cli": cli.stdout.strip(), "desktop": desktop, "python": sys.version.split()[0]}


def codex_project() -> Path:
    """Make a separate local marketplace. Do not install or write hook trust."""
    p = CODEX_HERE / "plugin"
    (p / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (p / "hooks").mkdir(exist_ok=True)
    write_json(
        p / ".codex-plugin/plugin.json",
        {
            "name": PLUGIN,
            "version": "0.0.1",
            "description": "Toy transcript MCP spike.",
            "mcpServers": "./.mcp.json",
        },
    )
    (p / "server.py").write_text(SERVER_PY, encoding="utf-8")
    (p / "hook.py").write_text(HOOK_PY, encoding="utf-8")
    write_json(
        p / ".mcp.json",
        {
            "mcpServers": {
                SERVER: {
                    "command": sys.executable,
                    "args": ["./server.py", str(CODEX_HERE / "server.jsonl")],
                    "cwd": ".",
                    "default_tools_approval_mode": "approve",
                }
            }
        },
    )
    command = (
        f'{shlex.quote(sys.executable)} "${{CLAUDE_PLUGIN_ROOT}}/hook.py" '
        f"{shlex.quote(str(CODEX_HERE / 'hook.jsonl'))}"
    )
    write_json(
        p / "hooks/hooks.json",
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "mcp__.*",
                        "hooks": [{"type": "command", "command": command, "timeout": 10}],
                    }
                ]
            }
        },
    )
    write_json(
        CODEX_HERE / ".agents/plugins/marketplace.json",
        {
            "name": CODEX_MARKET,
            "interface": {"displayName": "Toy transcript spike"},
            "plugins": [
                {
                    "name": PLUGIN,
                    "source": {"source": "local", "path": "./plugin"},
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    "category": "Productivity",
                }
            ],
        },
    )
    project = CODEX_HERE / "project"
    project.mkdir(exist_ok=True)
    return project


def codex_hooks() -> list[dict[str, Any]]:
    """Inspect the required hook without any trust mutation."""
    proc = subprocess.Popen(
        [
            "codex",
            "app-server",
            "--stdio",
            "-c",
            "features.hooks=true",
            "-c",
            f'plugins."{CODEX_SELECTOR}".enabled=true',
        ],
        cwd=CODEX_HERE / "project",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin is not None and proc.stdout is not None
    buffer = b""
    with selectors.DefaultSelector() as poll:
        poll.register(proc.stdout, selectors.EVENT_READ)

        def request(rid: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal buffer
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(
                (json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode()
            )
            proc.stdin.flush()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    value = json.loads(line)
                    if value.get("id") == rid:
                        if "error" in value:
                            raise RuntimeError(f"{method}: {value['error']}")
                        return dict(value["result"])
                if poll.select(timeout=1):
                    chunk = os.read(proc.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError(f"{method}: app-server closed")
                    buffer += chunk
            raise TimeoutError(f"{method}: no response; try the probe again")

        try:
            request(
                1,
                "initialize",
                {
                    "clientInfo": {"name": "toy-mcp-spike", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            proc.stdin.write(b'{"method":"initialized"}\n')
            proc.stdin.flush()
            found = request(2, "hooks/list", {"cwds": [str(CODEX_HERE / "project")]})
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    return [
        h for entry in found["data"] for h in entry["hooks"] if h.get("pluginId") == CODEX_SELECTOR
    ]


def fingerprint(value: str) -> dict[str, Any]:
    """Hash exact bytes. `truncated` is a text heuristic; only hashes prove byte equality."""
    raw = value.encode()
    return {
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "has_start": "MCP-SPIKE-START" in value,
        "has_end": "MCP-SPIKE-END" in value,
        "truncated": "truncat" in value.lower(),
    }


def codex_results(body: bytes) -> dict[str, Any]:
    """Only tool names and result hashes. Never keep harness instructions or replies."""
    data = json.loads(body)
    names: list[str] = []
    for tool in data.get("tools", []):
        if tool.get("type") == "namespace" and tool.get("name") == f"mcp__{SERVER}":
            names += [
                f"{tool['name']}.{child['name']}"
                for child in tool.get("tools", [])
                if child.get("name") == "transcript"
            ]
        elif tool.get("name") == f"mcp__{SERVER}__transcript":
            names.append(tool["name"])
    outputs = []
    for item in data.get("input", []):
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        value = item.get("output")
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        parts = []
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = None
        blocks = decoded.get("content", []) if isinstance(decoded, dict) else decoded
        for block in blocks if isinstance(blocks, list) else []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(fingerprint(block["text"]))
        outputs.append({"envelope": fingerprint(value), "text_parts": parts})
    return {"plugin_tools": sorted(set(names)), "tool_results": outputs}


class CodexModel(BaseHTTPRequestHandler):
    """A loopback model stub: request the observed tool, then finish. No real model call."""

    observations: ClassVar[list[dict[str, Any]]] = []
    size = 0

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        observation = codex_results(raw)
        self.observations.append(observation)
        names = observation["plugin_tools"]
        if len(self.observations) == 1 and names:
            item = {
                "type": "function_call",
                "id": "fc_spike194",
                "call_id": "call_spike194",
                "name": names[0].split(".")[-1],
                "arguments": json.dumps({"size": self.size}),
            }
            if "." in names[0]:
                item["namespace"] = names[0].rsplit(".", 1)[0]
        else:
            item = {
                "type": "message",
                "id": "msg_spike194",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "done", "annotations": []}],
            }
        self.respond(item)

    def respond(self, item: dict[str, Any]) -> None:
        events = [
            {"type": "response.created", "response": {"id": "resp_spike194"}},
            {"type": "response.output_item.added", "output_index": 0, "item": item},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_spike194",
                    "status": "completed",
                    "output": [item],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            },
        ]
        payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def codex_case(size: int, limit: int | None) -> dict[str, Any]:
    for name in ("server.jsonl", "hook.jsonl"):
        (CODEX_HERE / name).unlink(missing_ok=True)
    CodexModel.observations = []
    CodexModel.size = size
    server = ThreadingHTTPServer(("127.0.0.1", 0), CodexModel)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    settings = {
        "model": "toy-spike-model",
        "model_provider": "toy_mcp",
        "model_providers.toy_mcp.name": "Toy transcript loopback",
        "model_providers.toy_mcp.base_url": f"http://127.0.0.1:{server.server_port}/v1",
        "model_providers.toy_mcp.wire_api": "responses",
        "model_providers.toy_mcp.requires_openai_auth": False,
        f'plugins."{CODEX_SELECTOR}".enabled': True,
        "features.hooks": True,
        "features.code_mode": False,
        "features.code_mode_only": False,
    }
    if limit is not None:
        settings["tool_output_token_limit"] = limit
    cmd = ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-s", "read-only"]
    for key, value in settings.items():
        cmd += ["-c", f"{key}={json.dumps(value)}"]
    cmd += [
        "-C",
        str(CODEX_HERE / "project"),
        "Call the toy shop transcript tool, then reply done.",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    sent = lines(CODEX_HERE / "server.jsonl")
    arrived = [result for row in CodexModel.observations for result in row["tool_results"]]
    last = arrived[-1] if arrived else None
    matching = bool(
        sent
        and last
        and any(
            part["sha256"] == sent[-1]["sha256"] for part in [last["envelope"], *last["text_parts"]]
        )
    )
    return {
        "size": size,
        "surface": "codex_exec",
        "tool_output_token_limit": limit,
        "exit": proc.returncode,
        "model_tools": sorted({n for row in CodexModel.observations for n in row["plugin_tools"]}),
        "hook_tool_names": sorted({r["tool_name"] for r in lines(CODEX_HERE / "hook.jsonl")}),
        "sent": sent,
        "arrived": last,
        "unchanged": matching,
        "model_requests": len(CodexModel.observations),
    }


def codex_rollout(path: Path) -> dict[str, Any]:
    """Hash only this spike's tool outputs in a desktop rollout. Keep no other session text.

    A rollout is the harness's retained result, not an independent model-request capture.
    The person must first run the toy tool in the desktop app and provide that session's file.
    Logs are paired by order and size, not by call identity. The toy server returns the same
    bytes for each size, so another call of that size cannot change the hash comparison.
    """
    calls: dict[str, int] = {}
    cases: list[dict[str, Any]] = []
    runtime: dict[str, Any] = {}
    models: set[str] = set()
    tool = f"mcp__{SERVER}__transcript"
    pattern = re.compile(rf"{tool}\s*\(\s*\{{\s*(?:size|[\"']size[\"'])\s*:\s*(\d+)\s*\}}\s*\)")
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            payload = row.get("payload", {})
            if row.get("type") == "session_meta":
                runtime = {key: payload.get(key) for key in ("cli_version", "originator", "source")}
            if row.get("type") == "turn_context" and isinstance(payload.get("model"), str):
                models.add(payload["model"])
            kind = payload.get("type")
            call_id = payload.get("call_id")
            if kind == "custom_tool_call" and payload.get("name") == "exec":
                matches = pattern.findall(payload.get("input", ""))
                if len(matches) == 1 and int(matches[0]) in SIZES:
                    calls[call_id] = int(matches[0])
            elif kind == "function_call" and (
                payload.get("name") == tool
                or (
                    payload.get("namespace") == f"mcp__{SERVER}"
                    and payload.get("name") == "transcript"
                )
            ):
                arguments = json.loads(payload.get("arguments", "{}"))
                if arguments.get("size") in SIZES:
                    calls[call_id] = arguments["size"]
            elif kind in ("function_call_output", "custom_tool_call_output") and call_id in calls:
                # Reuse the reader on a single matched output. Do not pass the other session items.
                arrived = codex_results(
                    json.dumps(
                        {
                            "input": [
                                {"type": "function_call_output", "output": payload.get("output")}
                            ]
                        }
                    ).encode()
                )["tool_results"][0]
                cases.append({"size": calls.pop(call_id), "retained": arrived})
    if runtime.get("originator") != "Codex Desktop" or not cases:
        raise ValueError(
            "No toy desktop tool result found. Run the desktop check and give its rollout."
        )
    sent = lines(CODEX_HERE / "server.jsonl")[-len(cases) :]
    if [r["size"] for r in sent] != [r["size"] for r in cases]:
        raise ValueError(
            "The server log does not match the desktop calls. Run the desktop check again."
        )
    for case, recorded in zip(cases, sent, strict=True):
        case["sent"] = recorded
        retained = case["retained"]
        case["retained_text_unchanged"] = any(
            part["sha256"] == recorded["sha256"]
            for part in [retained["envelope"], *retained["text_parts"]]
        )
        case["wire_text_unchanged"] = None
    return {
        "date": date.today().isoformat(),
        "versions": codex_versions(),
        "runtime": runtime,
        "models": sorted(models),
        "method": "scripts/spike_plugin_mcp.py codex --rollout FILE; person drives the desktop",
        "evidence": "Server log and matched desktop tool outputs; no model-request proxy",
        "server_log_pairing": "Order and size; deterministic transcript per size; no call identity",
        "cases": cases,
        "hook_tool_names": sorted(
            {r["tool_name"] for r in lines(CODEX_HERE / "hook.jsonl") if r["tool_name"] == tool}
        ),
        "standard_library_only": True,
        "raised_output_limit": "not tested in desktop",
    }


def codex_answers(entry: dict[str, Any]) -> dict[str, Any]:
    """Give an explicit answer to each spike question, with the evidence boundary named."""
    cases = entry.get("cases", [])
    desktop = entry.get("desktop", {})
    desktop_cases = desktop.get("cases", [])
    cli_names = {name for case in cases for name in case.get("model_tools", [])}
    desktop_names = desktop.get("hook_tool_names", [])
    return {
        "codex_exec": {
            "plugin_server_starts": bool(cases) and all(c["sent"] for c in cases),
            "standard_library_only": entry.get("standard_library_only"),
            "tool_text_unchanged_at_request_boundary": {
                "default_limit": {
                    str(c["size"]): c["unchanged"]
                    for c in cases
                    if c["tool_output_token_limit"] is None
                },
                "raised_limit": {
                    str(c["size"]): c["unchanged"]
                    for c in cases
                    if c["tool_output_token_limit"] is not None
                },
            },
            "guard_tool_prefix": f"mcp__{SERVER}__",
            "prefix_has_plugin_identity": any(PLUGIN in name for name in cli_names)
            if cli_names
            else None,
        },
        "desktop": {
            "plugin_server_starts": bool(desktop_cases),
            "standard_library_only": desktop.get("standard_library_only"),
            "tool_text_unchanged_in_retained_session": {
                str(c["size"]): c["retained_text_unchanged"] for c in desktop_cases
            },
            "tool_text_unchanged_at_request_boundary": "not measured",
            "guard_tool_prefix": f"mcp__{SERVER}__",
            "prefix_has_plugin_identity": (
                any(PLUGIN in name for name in desktop_names) if desktop_names else None
            ),
        },
    }


def codex_main(args: list[str], out: Path, data: dict[str, Any]) -> int:
    if "--project" in args:
        p = codex_project()
        print(f"codex plugin marketplace add {shlex.quote(str(CODEX_HERE))}")
        print(f"codex plugin add {CODEX_SELECTOR}")
        print(f"codex --no-daemon -C {shlex.quote(str(p))} --enable hooks")
        print(
            "A person must inspect /hooks and trust the toy PreToolUse hook. Exit without a prompt."
        )
        print(f"Then run: python scripts/spike_plugin_mcp.py codex {shlex.quote(str(out))}")
        print(
            f"For the desktop check, open {p} in the app. Start a new chat with the plugin enabled."
        )
        print("Call transcript with size 10240, then 1048576.")
        print("Then import: python scripts/spike_plugin_mcp.py codex --rollout FILE [OUT]")
        return 0
    entry = data.setdefault("codex", {})
    if "--rollout" in args:
        entry["desktop"] = codex_rollout(Path(args[args.index("--rollout") + 1]))
    elif "--person" in args:
        entry["person"] = json.loads(
            Path(args[args.index("--person") + 1]).read_text(encoding="utf-8")
        )
    else:
        hooks = codex_hooks()
        if len(hooks) != 1 or not all(
            h.get("enabled") and h.get("trustStatus") == "trusted" for h in hooks
        ):
            print(
                "The toy PreToolUse hook is not enabled and trusted. A person must inspect /hooks.",
                file=sys.stderr,
            )
            return 1
        entry.update(
            date=date.today().isoformat(),
            versions=codex_versions(),
            method="scripts/spike_plugin_mcp.py codex",
            model="loopback Responses API stub; request boundary measured, no real model",
            standard_library_only=True,
            fixture={
                "manifest": ".codex-plugin/plugin.json",
                "mcp_file": ".mcp.json",
                "server_name": SERVER,
                "cwd": ".",
                "server_script": "./server.py",
                "default_tools_approval_mode": "approve",
                "hook": "hooks/hooks.json; a person must trust it",
            },
            hook_log_scope="Shared log can include other chats. Only the spike name is evidence.",
            hook_preflight=[
                {key: h.get(key) for key in ("pluginId", "eventName", "enabled", "trustStatus")}
                for h in hooks
            ],
        )
        entry.pop("answers", None)
        entry["cases"] = []
        for limit in (None, 1000000):
            for size in SIZES:
                result = codex_case(size, limit)
                print(json.dumps(result), flush=True)
                entry["cases"].append(result)
                write_json(out, data)
                if not result["sent"] or not result["arrived"] or result["exit"]:
                    print(
                        "The probe did not complete a tool call. Check MCP startup and approval.",
                        file=sys.stderr,
                    )
                    return 1
        entry.setdefault("person", {})
    entry["answers"] = codex_answers(entry)
    write_json(out, data)
    print(f"wrote {out}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] not in ("claude-code", "codex"):
        print(__doc__, file=sys.stderr)
        return 2
    if args[0] == "codex":
        rest = args[1:]
        if sum(flag in rest for flag in ("--project", "--person", "--rollout")) > 1:
            print("Choose --project, --person or --rollout, not more than one.", file=sys.stderr)
            return 2
        output_args = rest.copy()
        for flag in ("--person", "--rollout"):
            if flag in output_args:
                i = output_args.index(flag)
                if i + 1 >= len(output_args):
                    print(f"{flag} needs a file.", file=sys.stderr)
                    return 2
                del output_args[i : i + 2]
        if "--project" in output_args:
            output_args.remove("--project")
        if len(output_args) > 1 or any(a.startswith("--") for a in output_args):
            print("Use one output path and a supported option.", file=sys.stderr)
            return 2
        out = Path(output_args[0]) if output_args else ROOT / "proofs/spikes/plugin-mcp.json"
        data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        return codex_main(rest, out, data)
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

"""Spike #205. Local only. A person trusts hooks and operates the desktop app.

prepare creates a toy plugin in the primary checkout's ignored .proof folder.
inspect reads the tested CLI schema, plugin metadata and hook trust, with no model.
measure refuses untrusted hooks, then uses a loopback mock model in exec and the TUI.
desktop-start prints the human checks. desktop-finish imports observations from JSON.
desktop-refresh-start/finish record the event delta for a separate human button check.
No model request, model answer, terminal transcript or harness instruction is saved.
This local method supports macOS and Linux; the TUI probe uses Unix APIs.
Use Python with tomllib for this local method. It does not add a package dependency.
The script records only marker locations, event names and UI observations.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import plistlib
import pty
import re
import select
import selectors
import shlex
import struct
import subprocess
import sys
import termios
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parent.parent
PROOF = ROOT / "proofs/spikes/codex-display.json"
WORK = ROOT / ".proof/codex-display-205"
PLUGIN = WORK / "plugin"
PROJECT = WORK / "project"
MARKET = "toy-display-market-205"
NAME = "toy-display-spike-205"
SELECTOR = f"{NAME}@{MARKET}"
INVOCATION_OVERRIDES: list[str] = []
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
MARKERS = (
    *(
        f"DISPLAY_{kind}_{event}_205"
        for event in EVENTS
        for kind in ("STATUS", "WARNING", "CONTEXT")
    ),
    "DISPLAY_SKILL_BODY_205",
    "DISPLAY_MCP_TEXT_205",
    "DISPLAY_MCP_STRUCTURED_205",
    "DISPLAY_MCP_META_205",
    "DISPLAY_UI_205",
)
SOURCES = [
    "https://developers.openai.com/plugins/build/plugins",
    "https://learn.chatgpt.com/docs/hooks",
    "https://learn.chatgpt.com/docs/config-file/config-reference",
    "https://learn.chatgpt.com/docs/reference/slash-commands",
    "https://learn.chatgpt.com/docs/build-skills",
    "https://developers.openai.com/plugins/build/chatgpt-ui",
    "https://developers.openai.com/plugins/build/extensions",
    "https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/plugin/src/manifest.rs",
    "https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/config/src/hook_config.rs",
    "https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/tui/src/bottom_pane/status_line_setup.rs",
]

HOOK = """import json, pathlib, sys, time

event = json.load(sys.stdin)
project = pathlib.Path(event["cwd"])
if project.parts[-3:] != (".proof", "codex-display-205", "project"):
    sys.exit(0)
name = event["hook_event_name"]
with (project / "hooks.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"event": name}) + "\\n")
# Hold the transient status for observation, not to wait for another process.
time.sleep(1)
out = {"systemMessage": "DISPLAY_WARNING_" + name + "_205"}
if name != "Stop":
    out["hookSpecificOutput"] = {
        "hookEventName": name,
        "additionalContext": "DISPLAY_CONTEXT_" + name + "_205",
    }
print(json.dumps(out))
"""

HTML = """<!doctype html><html><body><h1>Toy shop order</h1>
<p>DISPLAY_UI_205</p><p id="order">Order ready.</p>
<button id="refresh">Refresh order</button><script>
let id = 1;
function send(method, params) {
  parent.postMessage({jsonrpc:"2.0", id:id++, method, params}, "*");
}
addEventListener("message", event => {
  const msg = event.data;
  if (msg.id === 1 && msg.result) {
    parent.postMessage({jsonrpc:"2.0", method:"ui/notifications/initialized"}, "*");
  }
  if (msg.result?.structuredContent) {
    document.getElementById("order").textContent = msg.result.structuredContent.status;
  }
});
document.getElementById("refresh").onclick = () =>
  send("tools/call", {name:"show_order", arguments:{}});
send("ui/initialize", {protocolVersion:"2026-01-26",
  appInfo:{name:"Toy shop",version:"0.0.1"},appCapabilities:{}});
</script></body></html>"""

SERVER = """import json, pathlib, sys

log = pathlib.Path(sys.argv[1])
html = pathlib.Path(__file__).with_name("order.html").read_text(encoding="utf-8")
uri = "ui://toy-shop/order.html"
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    params = msg.get("params", {})
    # Keep no tool arguments or host instructions.
    row = {"method": method}
    if method == "initialize":
        row["capability_keys"] = sorted(params.get("capabilities", {}))
        row["extension_keys"] = sorted(params.get("capabilities", {}).get("extensions", {}))
    if method == "tools/call":
        row["tool"] = params.get("name")
    if method == "resources/read":
        row["uri"] = params.get("uri")
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\\n")
    if "id" not in msg:
        continue
    if method == "initialize":
        result = {
            "protocolVersion": params["protocolVersion"],
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "toy-shop-display", "version": "0.0.1"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "show_order",
                    "description": "Show the toy shop order.",
                    "inputSchema": {"type": "object", "properties": {}},
                    "annotations": {"readOnlyHint": True},
                    "_meta": {
                        "ui": {"resourceUri": uri}, "openai/outputTemplate": uri,
                        "openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]},
                    },
                }
            ]
        }
    elif method == "tools/call":
        result = {
            "content": [{"type": "text", "text": "DISPLAY_MCP_TEXT_205"}],
            "structuredContent": {"status": "Order ready.", "marker": "DISPLAY_MCP_STRUCTURED_205"},
            "_meta": {
                "ui": {"resourceUri": uri},
                "openai/outputTemplate": uri,
                "display": "DISPLAY_MCP_META_205",
            },
        }
    elif method == "resources/list":
        result = {
            "resources": [
                {"uri": uri, "name": "Toy shop order", "mimeType": "text/html;profile=mcp-app"}
            ]
        }
    elif method == "resources/templates/list":
        result = {"resourceTemplates": []}
    elif method == "resources/read":
        result = {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/html;profile=mcp-app",
                    "text": html,
                    "_meta": {"ui": {"prefersBorder": True}},
                }
            ]
        }
    elif method == "ping":
        result = {}
    else:
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "error": {"code": -32601, "message": "Unknown method"},
                }
            ),
            flush=True,
        )
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""


def use_primary_checkout() -> None:
    """Resolve fixture paths when a command runs, not during test collection."""
    global WORK, PLUGIN, PROJECT
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    WORK = Path(common).parent / ".proof/codex-display-205"
    PLUGIN, PROJECT = WORK / "plugin", WORK / "project"


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def command(args: list[str]) -> str:
    return subprocess.run(
        args, capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()


def versions() -> dict[str, Any]:
    app = Path("/Applications/ChatGPT.app")
    desktop: dict[str, Any] = {"status": "not_found"}
    if (app / "Contents/Info.plist").exists():
        with (app / "Contents/Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        desktop = {
            "installed_version": info["CFBundleShortVersionString"],
            "installed_build": info["CFBundleVersion"],
            "bundled_cli": command(
                [str(app / "Contents/Resources/codex-cli/bin/codex"), "--version"]
            ),
            "runtime_version": None,
            "method": "Installed Info.plist and bundled binary --version; not runtime attribution.",
        }
    return {"cli": command(["codex", "--version"]), "desktop": desktop}


def reviewed_write(path: Path, text: str) -> None:
    """Do not silently replace the definition or executable a person reviewed."""
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise SystemExit(
            f"The reviewed fixture differs: {path}. Use a new fixture and human review."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_definition() -> str:
    hook_command = f'{shlex.quote(sys.executable)} "${{PLUGIN_ROOT}}/hook.py"'
    return (
        json.dumps(
            {
                "hooks": {
                    event: [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": hook_command,
                                    "timeout": 10,
                                    "statusMessage": f"DISPLAY_STATUS_{event}_205",
                                }
                            ]
                        }
                    ]
                    for event in EVENTS
                }
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def prepare() -> None:
    PROJECT.mkdir(parents=True, exist_ok=True)
    (PLUGIN / "hooks").mkdir(parents=True, exist_ok=True)
    skill = PLUGIN / "skills/toy-order"
    skill.mkdir(parents=True, exist_ok=True)
    write(
        PLUGIN / ".codex-plugin/plugin.json",
        {
            "name": NAME,
            "version": "0.0.1",
            "description": "Toy shop display spike.",
            "skills": "./skills/",
            "mcpServers": "./.mcp.json",
            "interface": {
                "displayName": "Toy shop display",
                "shortDescription": "Inspect a toy shop order.",
            },
        },
    )
    reviewed_write(PLUGIN / "hooks/hooks.json", fixture_definition())
    for filename, text in (("hook.py", HOOK), ("server.py", SERVER), ("order.html", HTML)):
        if filename == "hook.py":
            reviewed_write(PLUGIN / filename, text)
        else:
            (PLUGIN / filename).write_text(text, encoding="utf-8")
    skill.joinpath("SKILL.md").write_text(
        "---\nname: toy-order\ndescription: Check a toy shop order.\n---\n\n"
        "DISPLAY_SKILL_BODY_205\nUse the shell to print 'Toy order ready'.\n",
        encoding="utf-8",
    )
    write(
        PLUGIN / ".mcp.json",
        {
            "mcpServers": {
                "toy_display": {
                    "command": sys.executable,
                    "args": [str(PLUGIN / "server.py"), str(PROJECT / "mcp.jsonl")],
                    "default_tools_approval_mode": "approve",
                }
            }
        },
    )
    write(
        WORK / ".agents/plugins/marketplace.json",
        {
            "name": MARKET,
            "plugins": [
                {
                    "name": NAME,
                    "source": {"source": "local", "path": "./plugin"},
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    "category": "Productivity",
                }
            ],
        },
    )
    print(f"codex plugin marketplace add {shlex.quote(str(WORK))}")
    print(f"codex plugin add {SELECTOR}")
    print(f"codex --no-daemon -C {shlex.quote(str(PROJECT))} --enable hooks")
    print("A person must review the toy plugin hooks in /hooks. Do not trust unrelated hooks.")
    print("Do not submit a prompt. Exit after the trust step, then run measure.")


def overrides() -> list[str]:
    # Do not disable the trust check or ignore the config that holds human trust.
    values = {
        f"marketplaces.{MARKET}.source_type": '"local"',
        f"marketplaces.{MARKET}.source": json.dumps(str(WORK)),
        "features.hooks": "true",
        "features.code_mode": "false",
        "features.code_mode_only": "false",
    }
    # Disable other plugins for this invocation only. Leave saved user config untouched.
    plugin_states = {SELECTOR: True}
    config = Path.home() / ".codex/config.toml"
    if config.exists():
        import tomllib

        for name in tomllib.loads(config.read_text()).get("plugins", {}):
            if name != SELECTOR:
                plugin_states[name] = False
    values["plugins"] = (
        "{"
        + ", ".join(
            f"{json.dumps(name)}={{enabled={json.dumps(enabled)}}}"
            for name, enabled in plugin_states.items()
        )
        + "}"
    )
    return [
        *[arg for key, value in values.items() for arg in ("-c", f"{key}={value}")],
        *INVOCATION_OVERRIDES,
    ]


class AppServer:
    """A bounded read-only JSON-RPC client. No trust or turn API is called."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            ["codex", "app-server", "--stdio", *overrides()],
            cwd=PROJECT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.buffer = b""
        self.identifier = 0

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.identifier += 1
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(
            (
                json.dumps({"id": self.identifier, "method": method, "params": params}) + "\n"
            ).encode()
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                while b"\n" in self.buffer:
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    response = json.loads(line)
                    if response.get("id") == self.identifier:
                        if "error" in response:
                            raise RuntimeError(f"{method}: {response['error']}")
                        return response["result"]
                if selector.select(timeout=0.2):
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError(f"{method}: app-server closed")
                    self.buffer += chunk
        raise TimeoutError(f"{method}: no response; check app-server configuration")

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def isolate_invocation() -> None:
    """Disable unrelated hooks for this invocation; do not write trust or saved config."""
    server = AppServer()
    try:
        server.request(
            "initialize",
            {
                "clientInfo": {"name": "toy-display-205", "version": "0.0.1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        assert server.process.stdin is not None
        server.process.stdin.write(b'{"method":"initialized"}\n')
        server.process.stdin.flush()
        hooks = server.request("hooks/list", {"cwds": [str(PROJECT)]})["data"][0]["hooks"]
        if any(
            h.get("enabled") and h.get("pluginId") != SELECTOR and h.get("isManaged") for h in hooks
        ):
            raise SystemExit("A non-toy managed hook is enabled. The isolated probe cannot run.")
        disabled = [h["key"] for h in hooks if h.get("pluginId") != SELECTOR]
        state = ", ".join(f"{json.dumps(key)}={{enabled=false}}" for key in disabled)
        if disabled:
            INVOCATION_OVERRIDES.extend(["-c", "hooks.state={" + state + "}"])
    finally:
        server.close()


def metadata() -> dict[str, Any]:
    server = AppServer()
    try:
        server.request(
            "initialize",
            {
                "clientInfo": {"name": "toy-display-205", "version": "0.0.1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        assert server.process.stdin is not None
        server.process.stdin.write(b'{"method":"initialized"}\n')
        server.process.stdin.flush()
        hooks = server.request("hooks/list", {"cwds": [str(PROJECT)]})["data"][0]
        plugin = server.request(
            "plugin/read",
            {"pluginName": NAME, "marketplacePath": str(WORK / ".agents/plugins/marketplace.json")},
        )
        return {
            "hooks": hooks["hooks"],
            "errors": hooks["errors"],
            "warnings": hooks["warnings"],
            "plugin": plugin,
        }
    finally:
        server.close()


def safe(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False)
    for path, replacement in (
        (str(ROOT), "<worktree>"),
        (str(WORK), "<spike>"),
        (str(Path.home()), "<user-home>"),
    ):
        text = text.replace(path, replacement)
    return json.loads(text)


def inspect() -> None:
    target = WORK / "schema"
    command(["codex", "app-server", "generate-json-schema", "--experimental", "--out", str(target)])
    schema = read(target / "v2/PluginReadResponse.json")
    data = read(PROOF)
    data.update(
        {
            "issue": 205,
            "method": "scripts/spike_codex_display.py",
            "versions": versions(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "sources": SOURCES,
        }
    )
    data["inspection"] = safe(metadata())
    data["schema"] = {
        "method": "codex app-server generate-json-schema --experimental; tested binary, not main",
        "sha256": hashlib.sha256((target / "v2/PluginReadResponse.json").read_bytes()).hexdigest(),
        "definitions": {
            name: {"fields": sorted(value.get("properties", {})), "enum": value.get("enum")}
            for name, value in schema.get("definitions", {}).items()
            if name.startswith(("Plugin", "Hook"))
        },
    }
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
    if bundled.exists():
        bundle_target = WORK / "bundle-schema"
        command(
            [
                str(bundled),
                "app-server",
                "generate-json-schema",
                "--experimental",
                "--out",
                str(bundle_target),
            ]
        )
        bundle = read(bundle_target / "v2/PluginReadResponse.json")
        data["installed_bundle_schema"] = {
            "method": "Installed bundled CLI generate-json-schema; not the running chat process.",
            "version": command([str(bundled), "--version"]),
            "sha256": hashlib.sha256(
                (bundle_target / "v2/PluginReadResponse.json").read_bytes()
            ).hexdigest(),
            "definitions": {
                name: {"fields": sorted(value.get("properties", {})), "enum": value.get("enum")}
                for name, value in bundle.get("definitions", {}).items()
                if name in ("PluginDetail", "PluginInterface", "HookEventName")
            },
        }
    write(PROOF, data)
    print(f"Saved metadata to {PROOF}. No trust state was changed.")


def locations(body: bytes) -> dict[str, list[str]]:
    data = json.loads(body)
    found: dict[str, list[str]] = {}
    for marker in MARKERS:
        places = []
        for i, item in enumerate(data.get("input", [])):
            if marker in json.dumps(item):
                places.append(f"input[{i}].{item.get('role') or item.get('type')}")
        if marker in json.dumps(data) and not places:
            places.append("other")
        found[marker] = places
    return found


def toy_tools(data: dict[str, Any]) -> list[dict[str, str]]:
    names = []
    for tool in data.get("tools", []):
        if tool.get("type") == "namespace":
            for child in tool.get("tools", []):
                if child.get("name") == "show_order" and "toy_display" in tool["name"]:
                    names.append({"name": child["name"], "namespace": tool["name"]})
        elif "toy_display" in tool.get("name", "") and "show_order" in tool["name"]:
            names.append({"name": tool["name"]})
    return names


class Model(BaseHTTPRequestHandler):
    observations: ClassVar[list[dict[str, Any]]] = []
    case: ClassVar[str] = "hooks"

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        data = json.loads(raw)
        names = toy_tools(data)
        self.observations.append(
            {
                "found": locations(raw),
                "toy_tools": names,
                "tool_output_checks": [
                    {
                        "size": len(json.dumps(item.get("output", ""))),
                        "error_terms": [
                            word
                            for word in (
                                "error",
                                "failed",
                                "not found",
                                "timed out",
                                "permission",
                                "ui",
                                "render",
                                "structuredContent",
                                "content",
                            )
                            if word.lower() in json.dumps(item.get("output", "")).lower()
                        ],
                    }
                    for item in data.get("input", [])
                    if item.get("type") == "function_call_output"
                ],
            }
        )
        if len(self.observations) == 1 and self.case != "skill" and (self.case != "mcp" or names):
            name = "exec_command"
            arguments = {"cmd": "printf 'Toy order ready'"}
            item = {
                "type": "function_call",
                "id": "fc_205",
                "call_id": "call_205",
                "name": name,
                "arguments": json.dumps(arguments),
            }
            if self.case == "mcp":
                item.update(names[0])
                item["arguments"] = "{}"
        else:
            item = {
                "type": "message",
                "id": "msg_205",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Toy check done.", "annotations": []}],
            }
        events = [
            {"type": "response.created", "response": {"id": "resp_205"}},
            {"type": "response.output_item.added", "output_index": 0, "item": item},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_205",
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


def screen(raw: bytes) -> str:
    return re.sub(
        rb"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
        rb"|\x1b[()][0-9A-B]|\x1b[=>78]",
        b"",
        raw,
    ).decode("utf-8", "replace")


def tty(args: list[str], prompt: str) -> tuple[int | None, bytes]:
    pid, fd = pty.fork()
    if pid == 0:
        fcntl = __import__("fcntl")
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 140, 0, 0))
        os.chdir(PROJECT)
        os.execvpe(
            "codex",
            ["codex", "--no-daemon", "--no-alt-screen", *args],
            {**os.environ, "TERM": "xterm-256color"},
        )
    buf = bytearray()

    def pump(until: Any) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if until():
                return
            if select.select([fd], [], [], 0.2)[0]:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buf.extend(chunk)
                if b"\x1b[6n" in chunk:
                    os.write(fd, b"\x1b[1;1R")
        raise TimeoutError("CLI did not reach the next step. Check the toy plugin and /hooks.")

    try:
        pump(lambda: "Tip:" in screen(bytes(buf)))
        os.write(fd, b"\x1b[200~" + prompt.encode() + b"\x1b[201~")
        pump(lambda: "toy" in screen(bytes(buf)).lower())
        os.write(fd, b"\r")
        pump(lambda: "DISPLAY_WARNING_Stop_205" in screen(bytes(buf)))
        return None, bytes(buf)
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.kill(pid, 9)
        with contextlib.suppress(OSError):
            os.waitpid(pid, 0)


def verify_fixture(observed: dict[str, Any], pinned: list[dict[str, Any]]) -> dict[str, Any]:
    """Check all discovered hooks and the installed bytes before starting an endpoint."""
    discovered = observed["hooks"]
    if any(h.get("enabled") and h.get("pluginId") != SELECTOR for h in discovered):
        raise SystemExit(
            "Non-toy hooks are enabled. Disable them for this probe; no endpoint started."
        )
    hooks = [h for h in discovered if h.get("pluginId") == SELECTOR]
    expected = {event[0].lower() + event[1:]: event for event in EVENTS}
    if (
        observed.get("errors")
        or len(hooks) != len(EVENTS)
        or {h.get("eventName") for h in hooks} != set(expected)
        or not all(h.get("enabled") and h.get("trustStatus") == "trusted" for h in hooks)
    ):
        raise SystemExit(
            "The toy hooks are not all trusted. A person must review /hooks. "
            "No model endpoint started."
        )
    cache = Path.home() / ".codex/plugins/cache" / MARKET / NAME / "0.0.1"
    definition = fixture_definition().encode()
    executable = HOOK.encode()
    for root in (PLUGIN, cache):
        for relative, expected_bytes in (("hooks/hooks.json", definition), ("hook.py", executable)):
            path = root / relative
            try:
                matches = path.resolve() == path and path.read_bytes() == expected_bytes
            except OSError:
                matches = False
            if not matches:
                raise SystemExit(
                    "The toy fixture bytes or path differ. Use a new fixture and human review. "
                    "No model endpoint started."
                )
    hashes = {h["eventName"]: h.get("currentHash") for h in pinned if h.get("pluginId") == SELECTOR}
    for hook in hooks:
        event = expected[hook["eventName"]]
        fields = {
            "source": "plugin",
            "handlerType": "command",
            "sourcePath": str(cache / "hooks/hooks.json"),
            "command": f'{shlex.quote(sys.executable)} "{cache}/hook.py"',
            "async": False,
            "matcher": None,
            "timeoutSec": 10,
            "statusMessage": f"DISPLAY_STATUS_{event}_205",
            "additionalContextLimit": None,
        }
        current_hash = hook.get("currentHash")
        if (
            any(hook.get(k) != v for k, v in fields.items())
            or not isinstance(current_hash, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", current_hash)
            or hashes.get(hook["eventName"]) != current_hash
        ):
            raise SystemExit(
                "The toy fixture command, source or definition hash differs from the inspected "
                "fixture. Run inspect on the generated fixture and let a person review /hooks. "
                "No model endpoint started."
            )
    return {
        "hooks": hooks,
        "definition_sha256": hashlib.sha256(definition).hexdigest(),
        "executable_sha256": hashlib.sha256(executable).hexdigest(),
        "installed_root": str(cache),
        "method": "Generated bytes, exact command/source, and inspected hook definition hashes.",
    }


def pin_evidence(verified: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: v for k, v in verified.items() if k != "hooks"},
        "hook_hashes": {h["eventName"]: h["currentHash"] for h in verified["hooks"]},
    }


def measure(surface: str | None = None, only_case: str | None = None) -> None:
    data = read(PROOF)
    pinned = data.get("inspection", {}).get("hooks", [])
    verified = verify_fixture(metadata(), pinned)
    data["preflight"] = safe(verified["hooks"])
    data["fixture_pin"] = safe(pin_evidence(verified))
    runs = data.setdefault("runs", [])
    for run in runs:
        if (surface is None or run["surface"] == surface) and (
            only_case is None or run["case"] == only_case
        ):
            run["excluded_from_conclusions"] = True
    write(PROOF, data)
    for interactive in (False, True):
        if surface and surface != ("interactive_cli" if interactive else "codex_exec"):
            continue
        for case, prompt in (
            ("hooks", "Run the toy support check."),
            ("mcp", "Show the toy shop order."),
            ("skill", "Use $toy-display-spike-205:toy-order for the toy shop."),
        ):
            if only_case and only_case != case:
                continue
            verified = verify_fixture(metadata(), pinned)
            before_hooks, before_mcp = (
                len(rows(PROJECT / "hooks.jsonl")),
                len(rows(PROJECT / "mcp.jsonl")),
            )
            Model.observations, Model.case = [], case
            server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            values = {
                "model": '"toy-display"',
                "model_provider": '"toy_display"',
                "model_providers.toy_display.name": '"Toy display loopback"',
                "model_providers.toy_display.base_url": f'"http://127.0.0.1:{server.server_port}/v1"',
                "model_providers.toy_display.wire_api": '"responses"',
                "model_providers.toy_display.requires_openai_auth": "false",
            }
            args = [
                *overrides(),
                *[arg for k, v in values.items() for arg in ("-c", f"{k}={v}")],
                "-C",
                str(PROJECT),
                "-s",
                "read-only",
            ]
            try:
                if interactive:
                    exit_code, raw = tty(args, prompt)
                else:
                    completed = subprocess.run(
                        [
                            "codex",
                            "exec",
                            "--json",
                            "--ephemeral",
                            "--skip-git-repo-check",
                            *args,
                            prompt,
                        ],
                        capture_output=True,
                        timeout=90,
                    )
                    exit_code, raw = completed.returncode, completed.stdout + completed.stderr
                flat = re.sub(r"\s+", "", screen(raw))
                mcp_events = rows(PROJECT / "mcp.jsonl")[before_mcp:]
                if case == "mcp" and not any(
                    event.get("method") == "tools/call" and event.get("tool") == "show_order"
                    for event in mcp_events
                ):
                    raise SystemExit(
                        "The toy MCP tool did not run. Check plugin discovery. "
                        "No UI conclusion is valid."
                    )

                runs.append(
                    {
                        "surface": "interactive_cli" if interactive else "codex_exec",
                        "case": case,
                        "version": versions()["cli"],
                        "exit_code": exit_code,
                        "termination": "terminated after Stop warning"
                        if interactive
                        else "process exit",
                        "markers_in_output": {m: m in flat for m in MARKERS},
                        "model_requests": Model.observations,
                        "fixture_pin": safe(pin_evidence(verified)),
                        "hook_events": rows(PROJECT / "hooks.jsonl")[before_hooks:],
                        "mcp_events": mcp_events,
                    }
                )
                write(PROOF, data)
                print(f"Saved {runs[-1]['surface']} {case}.")
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)


def desktop_start() -> None:
    write(
        WORK / "desktop-baseline.json",
        {
            "hooks": len(rows(PROJECT / "hooks.jsonl")),
            "mcp": len(rows(PROJECT / "mcp.jsonl")),
            "versions": versions(),
        },
    )
    print(f"Open a new local desktop chat in {PROJECT}.")
    print("Enable Toy shop display. A person reviews any untrusted toy hooks.")
    print("Submit: Run the toy support check. Observe STATUS while hooks run and WARNING notices.")
    print("Submit: $toy-display-spike-205:toy-order. Check whether the skill starts a model turn.")
    print("Submit: Show the toy shop order. Use the show_order tool once, then stop.")
    print(
        "If an iframe shows DISPLAY_UI_205, click Refresh order. "
        "Observe whether it starts a model turn."
    )
    print("Do not run CLI measurements in this folder during the desktop check.")
    print(
        "Also check the app menu and chat side panel for Toy shop order. "
        "Record JSON: runtime_version, status_shown, warnings_shown, "
        "skill_started_turn, ui_rendered, refresh_started_turn, sidebar_entry, panel_entry, "
        "pane_location (left/right/inline/unknown), opening_path (tool/menu/unknown), "
        "refresh_click_count (none/once/several/unknown). Use booleans or null for checks."
    )


def desktop_refresh(start: bool) -> None:
    """Record events around a human button check, with no chat prompt or CLI run."""
    baseline_path = WORK / "desktop-refresh-baseline.json"
    if start:
        write(
            baseline_path,
            {
                "mcp": len(rows(PROJECT / "mcp.jsonl")),
                "hooks": len(rows(PROJECT / "hooks.jsonl")),
                "versions": versions(),
            },
        )
        print("Click Refresh order once in the existing desktop card. Send no chat prompt.")
        print("Then run desktop-refresh-finish and confirm whether a model turn started.")
        return
    baseline = read(baseline_path)
    if not baseline:
        raise SystemExit("Run desktop-refresh-start before the person clicks Refresh order.")
    events = rows(PROJECT / "mcp.jsonl")[baseline["mcp"] :]
    data = read(PROOF)
    data["desktop_refresh"] = {
        "method": "A person clicks between desktop-refresh-start and desktop-refresh-finish.",
        "mcp_events": events,
        "show_order_calls": sum(
            e.get("method") == "tools/call" and e.get("tool") == "show_order" for e in events
        ),
        "hook_events": rows(PROJECT / "hooks.jsonl")[baseline["hooks"] :],
        "versions_before": baseline["versions"],
        "versions_after": versions(),
        "limit": "Check concurrent actions and chat turns separately. No model-request capture.",
    }
    write(PROOF, safe(data))
    print(f"Recorded {data['desktop_refresh']['show_order_calls']} show_order calls.")


def desktop_finish(path: Path) -> None:
    observation = read(path)
    allowed = {
        "runtime_version",
        "status_shown",
        "warnings_shown",
        "skill_started_turn",
        "ui_rendered",
        "refresh_started_turn",
        "sidebar_entry",
        "panel_entry",
        "pane_location",
        "opening_path",
        "refresh_click_count",
    }
    if set(observation) - allowed or not allowed <= set(observation):
        raise SystemExit(
            "Use exactly the fields printed by desktop-start. Do not import a model answer."
        )
    checks = allowed - {"runtime_version", "pane_location", "opening_path", "refresh_click_count"}
    version = observation["runtime_version"]
    choices = {
        "pane_location": {"left", "right", "inline", "unknown"},
        "opening_path": {"tool", "menu", "unknown"},
        "refresh_click_count": {"none", "once", "several", "unknown"},
    }
    if (
        any(observation[k] is not None and type(observation[k]) is not bool for k in checks)
        or (
            version is not None
            and (
                not isinstance(version, str)
                or not re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,8}){1,3}", version)
            )
        )
        or any(
            not isinstance(observation[k], str) or observation[k] not in v
            for k, v in choices.items()
        )
    ):
        raise SystemExit(
            "Use bounded observations only. Do not import a model answer or free text."
        )
    baseline = read(WORK / "desktop-baseline.json")
    if not baseline:
        raise SystemExit("Run desktop-start before the person performs the check.")
    data = read(PROOF)
    data["desktop"] = {
        "method": "Person operates local desktop chat; imports report and toy event names only.",
        "versions_before": baseline["versions"],
        "versions_after": versions(),
        "human_observation": observation,
        "hook_events": rows(PROJECT / "hooks.jsonl")[baseline["hooks"] :],
        "mcp_events": rows(PROJECT / "mcp.jsonl")[baseline["mcp"] :],
        "model_request_capture": False,
    }
    write(PROOF, safe(data))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "prepare",
            "inspect",
            "measure",
            "desktop-start",
            "desktop-finish",
            "desktop-refresh-start",
            "desktop-refresh-finish",
        ),
    )
    parser.add_argument("observation", nargs="?", type=Path)
    parser.add_argument("--surface", choices=("codex_exec", "interactive_cli"))
    parser.add_argument("--case", choices=("hooks", "mcp", "skill"))
    args = parser.parse_args()
    use_primary_checkout()
    if args.operation in ("desktop-refresh-start", "desktop-refresh-finish"):
        desktop_refresh(args.operation == "desktop-refresh-start")
    elif args.operation == "measure":
        isolate_invocation()
        measure(args.surface, args.case)
    elif args.operation == "desktop-finish":
        if args.observation is None:
            parser.error("desktop-finish needs an observation JSON file")
        desktop_finish(args.observation)
    else:
        {
            "prepare": prepare,
            "inspect": inspect,
            "measure": measure,
            "desktop-start": desktop_start,
        }[args.operation]()


if __name__ == "__main__":
    main()

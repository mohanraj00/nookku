"""Measure the ids of the Codex tool results for an MCP call and a dynamic tool call (#551).

Local only. Run 1 turn of a `codex app-server` thread in a toy shop folder with the trusted
project-proof home and the native Codex OTLP log exporter. The thread has the dynamic tool
`lookup_order`, the toy MCP server `stock` (tests/toy_mcp_server.py) and a shell. Join the
`call_id` of each Codex tool_result log to the `call_id` of a response item or to the `id` of a
completed item in the rollout. Keep only ids, types, names and source lines. No model text,
tool output, instruction file, credential or personal telemetry attribute goes into the result.

usage: uv run python scripts/spike_codex_tool_ids.py [--home CODEX_HOME]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from proof_common import json_lines  # noqa: E402

from nookku import __version__, otlp  # noqa: E402
from nookku.stdio import start_in_thread  # noqa: E402

PROMPT = (
    "This is a toy shop tool test. Make these 3 tool calls, one at a time, in this order: "
    "lookup_order for the order 4471, then check_stock for the item blue mug, then the shell "
    "command `cat returns.txt`. Then reply with one word: done."
)
LOOKUP = {
    "type": "function",
    "name": "lookup_order",
    "description": "Look up a toy shop order by its number",
    "inputSchema": {
        "type": "object",
        "properties": {"order": {"type": "string"}},
        "required": ["order"],
    },
}
STOCK = {
    "command": sys.executable,
    "args": [str(ROOT / "tests" / "toy_mcp_server.py")],
    "default_tools_approval_mode": "approve",
}
CALL_TYPES = ("function_call", "custom_tool_call", "local_shell_call")
ITEM_TYPES = ("CommandExecution", "McpToolCall", "DynamicToolCall")


class AppServer:
    """A minimal client of `codex app-server`. It answers each dynamic tool call."""

    def __init__(self, args: list[str], env: dict[str, str]) -> None:
        self.p = subprocess.Popen(
            ["codex", "app-server", *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        self.n = 0
        self.dynamic_calls = 0

    def send(self, msg: dict[str, Any]) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def read(self) -> dict[str, Any]:
        assert self.p.stdout is not None
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("codex app-server stopped")
            msg = json.loads(line)
            if msg.get("method") != "item/tool/call" or "id" not in msg:
                return msg
            self.dynamic_calls += 1
            text = json.dumps({"item": "blue mug", "status": "delivered"})
            result = {"contentItems": [{"type": "inputText", "text": text}], "success": True}
            self.send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            msg = self.read()
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return dict(msg["result"])

    def turn(self, thread: str, text: str) -> bool:
        self.call("turn/start", {"threadId": thread, "input": [{"type": "text", "text": text}]})
        while True:
            msg = self.read()
            if msg.get("method") == "turn/completed":
                turn = (msg.get("params") or {}).get("turn") or {}
                return turn.get("status") in (None, "completed")

    def close(self) -> None:
        assert self.p.stdin is not None
        self.p.stdin.close()
        self.p.wait(timeout=30)


def rollout(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The tool calls of the response items and the completed tool items of a rollout file."""
    calls, items = [], []
    for line, row in enumerate(json_lines(path.read_text()), 1):
        payload = row.get("payload") or {}
        if row.get("type") == "response_item" and payload.get("type") in CALL_TYPES:
            calls.append(
                {
                    "line": line,
                    "type": payload["type"],
                    "call_id": payload.get("call_id"),
                    "name": payload.get("name"),
                    "namespace": payload.get("namespace"),
                }
            )
        item = payload.get("item") or {}
        if (
            row.get("type") == "event_msg"
            and payload.get("type") == "item_completed"
            and item.get("type") in ITEM_TYPES
        ):
            items.append(
                {
                    "line": line,
                    "type": item["type"],
                    "id": item.get("id"),
                    "name": item.get("tool") or None,
                    "server": item.get("server") or item.get("namespace") or None,
                }
            )
    return calls, items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=ROOT / ".proof/codex-hooks/codex-home")
    home = parser.parse_args().home.resolve()
    work = Path(tempfile.mkdtemp(prefix="nookku-tool-ids-"))
    (work / "returns.txt").write_text("Returns are free for 30 days.\n")
    record = work / "otel.jsonl"
    receiver = otlp.Receiver(("127.0.0.1", 0), record)
    start_in_thread(receiver)
    exporter = (
        f'otel.exporter={{otlp-http={{endpoint="{receiver.url}/v1/logs",protocol="binary"}}}}'
    )
    overrides = ["-c", exporter, "-c", "otel.log_user_prompt=false"]
    env = {**os.environ, **otlp.environment(receiver.url), "CODEX_HOME": str(home)}
    server = AppServer(overrides, env)
    try:
        client = {"name": "toy-shop", "version": "0"}
        server.call("initialize", {"clientInfo": client, "capabilities": {"experimentalApi": True}})
        server.send({"jsonrpc": "2.0", "method": "initialized"})
        params: dict[str, Any] = {"cwd": str(work), "sandbox": "read-only"}
        params |= {"approvalPolicy": "never", "dynamicTools": [LOOKUP]}
        params["config"] = {"mcp_servers": {"stock": STOCK}}
        thread = str(server.call("thread/start", params)["thread"]["id"])
        completed = server.turn(thread, PROMPT)
    finally:
        server.close()
        receiver.quiet(limit=5)
        receiver.shutdown()
        receiver.server_close()
    paths = list((home / "sessions").rglob(f"*{thread}.jsonl"))
    calls, items = rollout(paths[0]) if len(paths) == 1 else ([], [])
    logs = []
    for line, row in enumerate(json_lines(record.read_text()) if record.exists() else [], 1):
        if otlp.short(row.get("event_name")) != "tool_result":
            continue
        attrs = row["attributes"]
        call_id = attrs.get("call_id")
        logs.append(
            {
                "line": line,
                "attribute_names": sorted(attrs),
                "call_id": call_id,
                "tool_name": attrs.get("tool_name"),
                "call_lines": [c["line"] for c in calls if c["call_id"] == call_id],
                "item_lines": [i["line"] for i in items if i["id"] == call_id],
            }
        )
    kinds = {i["type"] for i in items}
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=30)
    checks = {
        "turn_completed": completed,
        "session_file_found": len(paths) == 1,
        "each_kind_ran": set(ITEM_TYPES) <= kinds,
        "dynamic_tool_answered": server.dynamic_calls >= 1,
        "each_result_has_a_call_id": bool(logs) and all(log["call_id"] for log in logs),
        "each_completed_item_has_a_result": bool(items)
        and all(any(log["call_id"] == i["id"] for log in logs) for i in items),
    }
    data = {
        "date": date.today().isoformat(),
        "method": "scripts/spike_codex_tool_ids.py",
        "versions": {"nookku": __version__, "codex": version.stdout.strip()},
        "prompt": PROMPT,
        "native_overrides": [v.replace(receiver.url, "<receiver URL>") for v in overrides],
        "session": thread,
        "calls": calls,
        "completed_items": items,
        "tool_result_logs": logs,
        "checks": checks,
        "pass": all(checks.values()),
    }
    out = ROOT / "proofs/spikes/codex-tool-ids.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1) + "\n")
    print(json.dumps(data, indent=1))
    return 0 if data["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

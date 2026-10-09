"""Measure if a transcript page of `nookku mcp` gets to the model unchanged (#215). Local only.

For each kind of text (English, text that is not English, JSON, emoji) and each page bound
(`page_tokens`), the script writes a toy shop project whose relay record holds turns of that kind.
Then the harness calls the real `nookku mcp` server for page 1 at that bound. The script computes
the expected tool text with `nookku.mcp.page`, and compares its SHA-256 with the text in the next
model request. It keeps only sizes and hashes, never a harness request.

- Claude Code: `claude -p` with the server in `--mcp-config`, through a recording proxy to the
  model API, with the default output limit.
- Codex: `codex exec` with the server in `-c mcp_servers.*`, and a loopback Responses API stub
  that requests the tool. No real model runs. The server is not a plugin and the run has no hook,
  so no trust step applies.

usage: python scripts/measure_transcript_pages.py [claude-code|codex|both] [OUT]
       (default OUT: proofs/mcp/transcript-pages.json)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from nookku import backend, kit, mcp  # noqa: E402
from nookku.record import Writer  # noqa: E402

MODEL = "haiku"
BOUNDS = (mcp.PAGE_TOKENS, 2 * mcp.PAGE_TOKENS, 4 * mcp.PAGE_TOKENS)
TOOL = "mcp__nookku__transcript"


def turns(kind: str) -> list[tuple[str, str]]:
    """Turns of one kind of text, more than the largest page."""
    if kind == "english":
        reply = "The teapot set ships in three days, and the mug ships today. " * 8
    elif kind == "non_ascii":
        reply = "ティーポットは三日で届きます。Kaffeetasse für Zoë, crème brûlée. " * 8
    elif kind == "json":
        reply = json.dumps(
            [{"id": n, "sku": f"T-{n}", "qty": n % 7, "ok": n % 2 == 0} for n in range(40)]
        )
    else:
        reply = "🫖☕️🍵🧁 " * 60
    return [(f"Question {n} about order {n}", reply) for n in range(60)]


def project(folder: Path, kind: str) -> str:
    """Write the relay record. Return the transcript text that the server pages."""
    record = folder / ".nookku" / "relay.jsonl"
    record.parent.mkdir(parents=True)
    for said, shown in turns(kind):
        row = {"type": "turn", "harness": "codex", "said": said, "shown": shown, "ok": True}
        Writer(record).append(row)
    return kit.transcript_text(folder)


def expected(text: str, bound: int) -> dict[str, Any]:
    body, _ = mcp.page(text, 1, bound)
    raw = body.encode()
    return {
        "bytes": len(raw),
        "characters": len(body),
        "estimate": mcp.estimate_tokens(body),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def fingerprint(text: str) -> dict[str, Any]:
    raw = text.encode("utf-8", errors="surrogatepass")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def server_command(folder: Path) -> list[str]:
    return [sys.executable, "-m", "nookku", "mcp", "--root", str(folder)]


# Claude Code ---------------------------------------------------------------------------------


def anthropic_results(body: bytes) -> list[dict[str, Any]]:
    """The size and the hash of each tool result in a request. No other part of the request."""
    try:
        data = json.loads(body)
    except ValueError:
        return []
    out = []
    for msg in data.get("messages") or [] if isinstance(data, dict) else []:
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
            out.append(fingerprint("".join(parts)))
    return out


class HashProxy(backend.Proxy):
    """A model API proxy that keeps no header and no body, only the tool result hashes."""

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        row["request_headers"] = None
        row["request_body"] = anthropic_results(body)

    def complete(self, row: dict[str, Any], body: bytes, encoding: str | None) -> None:
        row["response_headers"] = None
        row["response_body"] = None


def claude_case(folder: Path, bound: int) -> dict[str, Any]:
    config = {"mcpServers": {"nookku": {"command": server_command(folder)[0]}}}
    config["mcpServers"]["nookku"]["args"] = server_command(folder)[1:]
    (folder / "mcp.json").write_text(json.dumps(config))
    record = folder / "model.jsonl"
    proxies = backend.Proxies(
        [backend.Backend("anthropic", "ANTHROPIC_BASE_URL", "https://api.anthropic.com")],
        record,
        HashProxy,
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE"))}
    env.pop("MAX_MCP_OUTPUT_TOKENS", None)
    env.update(proxies.start())
    prompt = (
        f"Call the tool {TOOL} one time with page_tokens {bound}. Then reply with the word done."
    )
    cmd = ["claude", "-p", "--output-format", "json", "--model", MODEL]
    cmd += ["--mcp-config", str(folder / "mcp.json"), "--strict-mcp-config"]
    cmd += ["--setting-sources", "project", "--allowedTools", TOOL]
    try:
        proc = subprocess.run(
            cmd, cwd=folder, env=env, input=prompt, capture_output=True, text=True, timeout=600
        )
    finally:
        proxies.stop()
    rows = [json.loads(x) for x in record.read_text().splitlines()] if record.exists() else []
    arrived = [r for row in rows for r in row.get("request_body") or []]
    return {"exit": proc.returncode, "arrived": arrived[-1] if arrived else None}


# Codex ---------------------------------------------------------------------------------------


class CodexModel(BaseHTTPRequestHandler):
    """A loopback model stub: request the transcript tool one time, then finish."""

    requests: ClassVar[list[dict[str, Any]]] = []
    bound = 0

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        outputs = [
            item.get("output")
            for item in data.get("input", [])
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        names = []
        for tool in data.get("tools", []):
            if tool.get("type") == "namespace" and tool.get("name") == "mcp__nookku":
                names += [f"mcp__nookku.{c['name']}" for c in tool.get("tools", [])]
            elif isinstance(tool.get("name"), str) and tool["name"].startswith("mcp__nookku__"):
                names.append(tool["name"])
        self.requests.append({"outputs": [self.texts(o) for o in outputs], "tools": names})
        wanted = [n for n in names if n.endswith("transcript")]
        if len(self.requests) == 1 and wanted:
            item = {
                "type": "function_call",
                "id": "fc_215",
                "call_id": "call_215",
                "name": wanted[0].split(".")[-1],
                "arguments": json.dumps({"page_tokens": self.bound}),
            }
            if "." in wanted[0]:
                item["namespace"] = wanted[0].rsplit(".", 1)[0]
        else:
            item = {
                "type": "message",
                "id": "msg_215",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "done", "annotations": []}],
            }
        events = [
            {"type": "response.created", "response": {"id": "resp_215"}},
            {"type": "response.output_item.added", "output_index": 0, "item": item},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_215",
                    "status": "completed",
                    "output": [item],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            },
        ]
        payload = "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def texts(output: Any) -> list[dict[str, Any]]:
        """The hash of each text part of a tool output, and of the whole output."""
        value = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        found = [fingerprint(value)]
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = output if isinstance(output, list) else None
        blocks = decoded.get("content", []) if isinstance(decoded, dict) else decoded
        for block in blocks if isinstance(blocks, list) else []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                found.append(fingerprint(block["text"]))
        return found


def codex_case(folder: Path, bound: int) -> dict[str, Any]:
    CodexModel.requests = []
    CodexModel.bound = bound
    server = ThreadingHTTPServer(("127.0.0.1", 0), CodexModel)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    command = server_command(folder)
    settings: dict[str, Any] = {
        "model": "toy-215-model",
        "model_provider": "toy_215",
        "model_providers.toy_215.name": "Toy transcript loopback",
        "model_providers.toy_215.base_url": f"http://127.0.0.1:{server.server_port}/v1",
        "model_providers.toy_215.wire_api": "responses",
        "model_providers.toy_215.requires_openai_auth": False,
        "mcp_servers.nookku.command": command[0],
        "mcp_servers.nookku.args": command[1:],
        # The tools are read-only. codex exec has no person to approve a call.
        "mcp_servers.nookku.default_tools_approval_mode": "approve",
        "features.code_mode": False,
        "features.code_mode_only": False,
    }
    cmd = ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-s", "read-only"]
    for key, value in settings.items():
        cmd += ["-c", f"{key}={json.dumps(value)}"]
    cmd += ["-C", str(folder), "Call the transcript tool, then reply done."]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    arrived = [parts for r in CodexModel.requests for parts in r["outputs"]]
    return {
        "exit": proc.returncode,
        "tools": sorted({n for r in CodexModel.requests for n in r["tools"]}),
        "arrived": arrived[-1] if arrived else None,
    }


# ---------------------------------------------------------------------------------------------


def versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in ("claude", "codex"):
        try:
            p = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=30)
            out[name] = p.stdout.strip() or None
        except OSError:
            out[name] = None
    return out


def run(harness: str) -> list[dict[str, Any]]:
    rows = []
    for kind in ("english", "non_ascii", "json", "emoji"):
        for bound in BOUNDS:
            with tempfile.TemporaryDirectory(prefix="nookku-215-") as tmp:
                folder = Path(tmp)
                text = project(folder, kind)
                want = expected(text, bound)
                got = (
                    claude_case(folder, bound)
                    if harness == "claude-code"
                    else codex_case(folder, bound)
                )
                arrived = got.pop("arrived")
                parts = arrived if isinstance(arrived, list) else [arrived] if arrived else []
                unchanged = any(p and p["sha256"] == want["sha256"] for p in parts)
                rows.append(
                    {
                        "harness": harness,
                        "kind": kind,
                        "page_tokens": bound,
                        "sent": want,
                        "arrived": parts,
                        "unchanged": unchanged,
                        **got,
                    }
                )
                print(harness, kind, bound, want["bytes"], "unchanged" if unchanged else "CHANGED")
    return rows


def main() -> int:
    args = sys.argv[1:]
    which = args[0] if args and args[0] in ("claude-code", "codex", "both") else "both"
    rest = args[1:] if args and args[0] in ("claude-code", "codex", "both") else args
    out = Path(rest[0]) if rest else ROOT / "proofs" / "mcp" / "transcript-pages.json"
    harnesses = ["claude-code", "codex"] if which == "both" else [which]
    data = {
        "issue": 215,
        "date": date.today().isoformat(),
        "method": "scripts/measure_transcript_pages.py",
        "versions": versions(),
        "claude_model": MODEL,
        "page_tokens_default": mcp.PAGE_TOKENS,
        "estimate": "nookku.mcp.estimate_tokens",
        "cases": [row for h in harnesses for row in run(h)],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

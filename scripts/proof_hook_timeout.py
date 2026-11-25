"""Measure what Claude Code does with a prompt when a UserPromptSubmit hook times out (#642).

A toy Anthropic API runs on a local port. The script runs `claude -p` 2 times in a new project
with one `UserPromptSubmit` command hook in `.claude/settings.json`. The hook sleeps and then
exits with 2, which blocks the prompt.

- `in_time`: the hook sleeps 1 second, and its timeout is 30 seconds. This is the control.
- `timed_out`: the hook sleeps 20 seconds, and its timeout is 1 second.

ANTHROPIC_BASE_URL is that port, with a toy API key. The config folder is a new empty folder, so
no login of this machine goes to the toy API. For each call, the toy API records the method, the
path, the number of tools of the request and whether the body holds the prompt. It keeps no
body, because a harness call holds the harness's own instructions. It answers each call with
status 400. Thus no model gives an answer.

In print mode, Claude Code can send the first prompt in a request that makes the session title,
and a hook cannot stop this request (SPEC.md section 5). That request has no tool. Thus the
script counts a request with tools as a request of the turn.

The script writes proofs/hook-timeout/claude-code.json with the Claude Code version and the date.

usage: python scripts/proof_hook_timeout.py
"""

from __future__ import annotations

import json
import os
import platform
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
OUT = ROOT / "proofs" / "hook-timeout" / "claude-code.json"
KEY = "sk-toy-hook-k3y"
PROMPT = "Is the blue teapot in stock? toy-shop-marker-7Q2"
CALLS: list[dict[str, object]] = []
ERROR = b'{"type":"error","error":{"type":"invalid_request_error","message":"toy API"}}'
# The name of each run, with the seconds that the hook sleeps and its timeout in seconds.
RUNS = {"in_time": (1, 30), "timed_out": (20, 1)}


class ToyApi(BaseHTTPRequestHandler):
    def answer(self) -> None:
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size) if size else b""
        try:
            tools = json.loads(body).get("tools")
        except (ValueError, AttributeError):
            tools = None
        CALLS.append(
            {
                "method": self.command,
                "path": self.path.split("?")[0],
                "tools": len(tools) if isinstance(tools, list) else 0,
                "prompt_in_body": PROMPT.encode() in body,
            }
        )
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(ERROR)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(ERROR)

    do_HEAD = do_GET = do_POST = answer

    def log_message(self, *args: object) -> None:
        pass


def run(port: int, sleep: int, timeout: int) -> dict[str, Any]:
    """Run `claude -p` one time with the hook, and give the model calls of the run."""
    CALLS.clear()
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        (project / ".claude").mkdir(parents=True)
        hook = {"type": "command", "command": f"sleep {sleep}; exit 2", "timeout": timeout}
        settings = {"hooks": {"UserPromptSubmit": [{"hooks": [hook]}]}}
        (project / ".claude" / "settings.json").write_text(json.dumps(settings))
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDECODE"))
        }
        env.update(
            ANTHROPIC_BASE_URL=f"http://127.0.0.1:{port}",
            ANTHROPIC_API_KEY=KEY,
            CLAUDE_CONFIG_DIR=str(Path(tmp) / "config"),
        )
        args = ["claude", "-p", PROMPT, "--model", "haiku"]
        args += ["--setting-sources", "project", "--strict-mcp-config"]
        start = time.monotonic()
        done = subprocess.run(
            args, cwd=project, env=env, capture_output=True, text=True, timeout=300
        )
        seconds = round(time.monotonic() - start, 1)
    model = [c for c in CALLS if c["path"] == "/v1/messages" and c["method"] == "POST"]
    held = [c for c in model if c["prompt_in_body"]]
    return {
        "hook": hook,
        "exit": done.returncode,
        "seconds": seconds,
        "says_blocked": "operation blocked by hook" in done.stdout + done.stderr,
        "model_calls": len(model),
        "turn_calls_with_the_prompt": sum(1 for c in held if c["tools"]),
        "title_calls_with_the_prompt": sum(1 for c in held if not c["tools"]),
    }


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ToyApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    version = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    port = server.server_address[1]
    runs = {name: run(port, sleep, timeout) for name, (sleep, timeout) in RUNS.items()}
    server.shutdown()
    result: dict[str, Any] = {
        "date": date.today().isoformat(),
        "versions": {
            "claude-code": version,
            "python": platform.python_version(),
            "os": platform.system(),
        },
        "method": "scripts/proof_hook_timeout.py",
        "runs": runs,
        # A hook that ends in time blocks the prompt: no request of the turn has the prompt.
        "in_time_blocks_the_prompt": runs["in_time"]["turn_calls_with_the_prompt"] == 0,
        # After a timeout of the hook, the prompt goes to the model API.
        "timed_out_sends_the_prompt": runs["timed_out"]["turn_calls_with_the_prompt"] > 0,
    }
    result["pass"] = result["in_time_blocks_the_prompt"] and result["timed_out_sends_the_prompt"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

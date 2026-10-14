"""Measure the HEAD /api/hello call of Claude Code (SPEC.md section 7.7).

A toy Anthropic API runs on a local port. The script runs `claude -p` one time, with
ANTHROPIC_BASE_URL set to that port and a toy API key. The config folder is a new empty folder, so
no login of this machine goes to the toy API. For each call, the toy API records the method, the
path, the User-Agent and the size of the body. It keeps no other header and no body, because a
harness call holds the harness's own instructions. It answers /api/hello with status 200 and each
other call with status 400. Thus no model gives an answer. The script writes
proofs/model-api/hello.json with the Claude Code version and the date.

usage: python scripts/proof_api_hello.py
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "proofs" / "model-api" / "hello.json"
KEY = "sk-toy-hello-k3y"
CALLS: list[dict[str, object]] = []
ERROR = b'{"type":"error","error":{"type":"invalid_request_error","message":"toy API"}}'


class ToyApi(BaseHTTPRequestHandler):
    def answer(self) -> None:
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size) if size else b""
        CALLS.append(
            {
                "method": self.command,
                "path": self.path.split("?")[0],
                "user_agent": self.headers.get("User-Agent"),
                "content_length": self.headers.get("Content-Length"),
                "transfer_encoding": self.headers.get("Transfer-Encoding"),
                "body_size": len(body),
            }
        )
        hello = self.path.startswith("/api/hello")
        out = b"" if hello else ERROR
        self.send_response(200 if hello else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(out)

    do_HEAD = do_GET = do_POST = answer

    def log_message(self, *args: object) -> None:
        pass


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ToyApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    version = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDECODE"))
        }
        env.update(
            ANTHROPIC_BASE_URL=f"http://127.0.0.1:{server.server_address[1]}",
            ANTHROPIC_API_KEY=KEY,
            CLAUDE_CONFIG_DIR=str(Path(tmp) / "config"),
        )
        args = ["claude", "-p", "Hi, is the mug in stock?", "--model", "haiku"]
        args += ["--setting-sources", "", "--strict-mcp-config"]
        run = subprocess.run(args, cwd=tmp, env=env, capture_output=True, text=True, timeout=180)
    server.shutdown()
    hello = [c for c in CALLS if c["path"] == "/api/hello"]
    rest = [c for c in CALLS if c["path"] != "/api/hello"]
    # A User-Agent of a model call holds no secret. Keep only its first part, the product name.
    for c in rest:
        c["user_agent"] = str(c["user_agent"] or "").split(" ")[0]
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "claude-code": version,
            "python": platform.python_version(),
            "os": platform.system(),
        },
        "method": "scripts/proof_api_hello.py",
        "exit": run.returncode,
        "hello": hello,
        "other_calls": rest,
        "key_in_record": KEY in json.dumps(CALLS),
    }
    result["pass"] = bool(hello) and all(
        c["method"] == "HEAD" and c["body_size"] == 0 for c in hello
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

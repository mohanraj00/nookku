"""An entry for the toy shop HTTP agent. It starts the server, then sends each message to it.

The entry starts the server, so the server gets the environment of the test and its output goes
to app.log. Run it from the repo root, with a Python that has nooku:

    {"entry": [".venv/bin/python", "examples/toy-shop/http_entry.py"]}
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from nooku.agent import serve

PORT = int(os.environ.get("TOY_SHOP_PORT", "8700"))
URL = f"http://127.0.0.1:{PORT}/"
SERVER = Path(__file__).with_name("http_agent.py")


def start_server() -> subprocess.Popen[bytes]:
    """Start the server once, and wait until it accepts a connection. Its output goes to stderr.
    If it does not accept a connection in 30 s, stop it, so that no server stays after the entry."""
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
    except OSError:
        pass
    else:
        # Another process owns the port. Do not send the messages of the test to it.
        raise SystemExit(f"toy shop entry: port {PORT} is in use. Set TOY_SHOP_PORT.")
    server = subprocess.Popen([sys.executable, str(SERVER), str(PORT)], stdout=sys.stderr)
    # HTTPServer looks up the host name before it listens. On some machines this takes seconds.
    deadline = time.monotonic() + 30
    while True:
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
            if server.poll() is None:
                return server
            raise OSError(f"the server stopped: exit {server.returncode}")
        except OSError:
            if server.poll() is not None or time.monotonic() > deadline:
                server.kill()
                server.wait()
                raise
            time.sleep(0.1)


def reply(message: str, history: list[tuple[str, str]]) -> str:
    body = json.dumps({"text": message}).encode()
    request = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    # 200 s is less than the 240 s of the tap, so the tester gets this error and not a timeout.
    with urllib.request.urlopen(request, timeout=200) as response:
        text: str = json.loads(response.read())["reply"]
        return text


server = start_server()
try:
    serve(reply)
finally:
    server.terminate()
    server.wait()

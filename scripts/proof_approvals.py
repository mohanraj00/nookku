"""Proof that the trace finds an action with no approval (SPEC.md section 7.18, #521).

A toy shop app has a backend `shop` and a stdio MCP server `payments`. The server asks for the
approval of a refund with an MCP elicitation. The app spec says that a refund needs an accepted
elicitation of `payments`, and that the cancel of an order needs the message `yes` after an
interrupt. A test sends 5 messages:

1. A refund. The server asks, the app accepts, and the app calls the refund backend.
2. A refund with the planted defect: the app calls the refund backend and asks nobody.
3. A refund that the app declines. The app does not call the backend.
4. A cancel. The reply has an interrupt.
5. The message `yes`. The app calls the cancel backend.

The proof checks the elicitation, interrupt and resume items of the trace, the 1
`action_without_approval` finding of turn 2, the counts of the rows, the verdict and the seal.
It needs no model. The toy app plays its user: it accepts the refund of order 5120 and declines
the refund of order 5122.

usage: python scripts/proof_approvals.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import json_lines  # noqa: E402

from nookku import __version__, bridge, discovery, seal  # noqa: E402
from nookku.record import loads  # noqa: E402

OUT = ROOT / "proofs" / "approvals" / "results.json"
SPEC = """# Toy shop

## Approvals

| Action | Source | Approval | By | Interrupt |
|---|---|---|---|---|
| `shop POST /refund` | backend | `payments` | elicitation | |
| `shop POST /orders/cancel` | backend | `yes` | message | `interrupt.action` |

## Verdict

| Finding | Most |
|---|---|
| `action_without_approval` | 0 |
"""
MESSAGES = [
    "Refund order 5120.",
    "Refund order 5121.",
    "Refund order 5122.",
    "Cancel order 5120.",
    "yes",
]
# The turn with the planted defect.
PLANTED = 2

# The MCP server asks for an approval during its tool call, and gives the answer as its result.
SERVER = """
import json, sys

def send(message):
    sys.stdout.write(json.dumps(message) + "\\n")
    sys.stdout.flush()

for raw in sys.stdin:
    request = json.loads(raw)
    if "id" not in request:
        continue
    result = {}
    if request["method"] == "initialize":
        result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "payments", "version": "1"},
        }
    elif request["method"] == "tools/call":
        order = request["params"]["arguments"]["order"]
        schema = {"type": "object", "properties": {"approve": {"type": "boolean"}}}
        params = {"mode": "form", "message": f"Refund order {order}?", "requestedSchema": schema}
        send({"jsonrpc": "2.0", "id": f"e-{order}", "method": "elicitation/create",
              "params": params})
        answer = json.loads(sys.stdin.readline())
        result = {"content": [{"type": "text", "text": answer["result"]["action"]}]}
    send({"jsonrpc": "2.0", "id": request["id"], "result": result})
"""

# The app. It starts the MCP server from the command line in PAYMENTS_MCP, and it calls the
# backend at SHOP_URL. Order 5121 has the planted defect: a refund with no approval.
ENTRY = """
import json, os, shlex, subprocess, sys, urllib.request

USER = {"5120": "accept", "5122": "decline"}
server = subprocess.Popen(
    shlex.split(os.environ["PAYMENTS_MCP"]), stdin=subprocess.PIPE, stdout=subprocess.PIPE
)
count = 0

def send(message):
    server.stdin.write((json.dumps(message) + "\\n").encode())
    server.stdin.flush()

def call(method, params, order=None):
    global count
    count += 1
    send({"jsonrpc": "2.0", "id": count, "method": method, "params": params})
    while True:
        message = json.loads(server.stdout.readline())
        if message.get("method") == "elicitation/create":
            action = USER[order]
            result = {"action": action}
            if action == "accept":
                result["content"] = {"approve": True}
            send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        elif message.get("id") == count:
            return message["result"]

def post(path, order):
    data = json.dumps({"order": order}).encode()
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(os.environ["SHOP_URL"] + path, data, headers)
    urllib.request.urlopen(request, timeout=10).read()

client = {"elicitation": {"form": {}}}
info = {"name": "toy-shop", "version": "1"}
call("initialize", {"protocolVersion": "2025-11-25", "capabilities": client, "clientInfo": info})
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
waiting = None

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    text = request["message"]
    order = text.rstrip(".").split()[-1]
    if text.startswith("Refund") and order == "5121":
        post("/refund", order)
        reply = f"The refund of order {order} is sent."
    elif text.startswith("Refund"):
        arguments = {"name": "approve_refund", "arguments": {"order": order}}
        result = call("tools/call", arguments, order)
        if result["content"][0]["text"] == "accept":
            post("/refund", order)
            reply = f"The refund of order {order} is sent."
        else:
            reply = f"Order {order} gets no refund."
    elif text.startswith("Cancel"):
        waiting = order
        ask = {"action": "cancel", "order": order}
        reply = json.dumps({"reply": f"Do I cancel order {order}?", "interrupt": ask})
    elif text == "yes" and waiting:
        post("/orders/cancel", waiting)
        reply = json.dumps({"reply": f"Order {waiting} is cancelled."})
        waiting = None
    else:
        reply = "I can refund or cancel an order."
    sys.stdout.write(json.dumps({"v": 1, "id": request["id"], "reply": reply}) + "\\n")
    sys.stdout.flush()
"""


class Shop(BaseHTTPRequestHandler):
    """The toy backend. It accepts each POST."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        data = b'{"done": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> int:
    project = Path(tempfile.mkdtemp(prefix="nookku-approvals-")).resolve()
    (project / ".nookku").mkdir()
    (project / "entry.py").write_text(ENTRY)
    (project / "payments_mcp.py").write_text(SERVER)
    (project / "APP_SPEC.md").write_text(SPEC)
    config = {"entry": [sys.executable, "entry.py"], "models": [], "spec": ["APP_SPEC.md"]}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    shop = ThreadingHTTPServer(("127.0.0.1", 0), Shop)
    threading.Thread(target=shop.serve_forever, daemon=True).start()
    backend = {"name": "shop", "env": "SHOP_URL", "url": f"http://127.0.0.1:{shop.server_port}"}
    server = {
        "name": "payments",
        "transport": "stdio",
        "env": "PAYMENTS_MCP",
        "command": [sys.executable, str(project / "payments_mcp.py")],
        "url": None,
    }
    discovery.register(project, discovery.make(backends=[backend], mcp_servers=[server]))
    cur = bridge.start(project)
    replies = []
    try:
        for message in MESSAGES:
            shown, ok = bridge.send(cur, message)
            replies.append({"message": message, "reply": shown, "ok": ok})
    finally:
        bridge.end(project)
        shop.shutdown()
    folder = Path(cur["dir"])
    items = json_lines((folder / "trace.jsonl").read_text())
    findings = loads((folder / "findings.json").read_text())
    verdict = loads((folder / "verdict.json").read_text())
    shown_items = [
        {k: it[k] for k in ("turn", "harness", "kind", "session", "name", "input", "output")}
        for it in items
        if it["kind"] in ("elicitation", "interrupt", "resume")
        or (it["kind"] == "tool_call" and it["harness"] == "mcp")
        or it["kind"] == "http"
    ]
    for it in shown_items:
        if it["kind"] == "http":
            # The request headers name the port of the proxy. The proof keeps the body only.
            it["input"] = it["input"]["body"]
    found = [f for f in findings["findings"] if f["check"] == "action_without_approval"]
    classes = {c["check"]: c for c in verdict["classes"]}
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
        },
        "approvals": loads((folder / "manifest.json").read_text())["approvals"],
        "turns": replies,
        "items": shown_items,
        "counts": {k: v for k, v in findings["counts"].items() if v},
        "findings": [{k: f[k] for k in ("check", "turn", "detail", "harness")} for f in found],
        "rows": findings["approvals"],
        "verdict": verdict["verdict"],
        "verdict_class": classes["action_without_approval"],
        "seal_intact": seal.verify(folder)["intact"],
    }

    def kinds(kind: str) -> list[tuple[int, object]]:
        return [(it["turn"], it["output"]) for it in shown_items if it["kind"] == kind]

    refunds = [it["turn"] for it in shown_items if it["name"] == "POST /refund"]
    detail = "shop POST /refund (backend): no approval before it in this turn. "
    detail += "Approval: payments (elicitation)"
    checks = {
        "each reply came": all(r["ok"] for r in replies),
        "the elicitations are in the trace": kinds("elicitation")
        == [(1, "accept"), (3, "decline")],
        "the interrupt and the resume are in the trace": kinds("interrupt") == [(4, '"cancel"')]
        and kinds("resume") == [(5, "yes")],
        "the refunds are in turn 1 and turn 2": refunds == [1, PLANTED],
        "only the planted refund gives a finding": [(f["turn"], f["detail"]) for f in found]
        == [(PLANTED, detail)],
        "no other finding class has a count": result["counts"] == {"action_without_approval": 1},
        "the rows have their counts": [
            (r["actions"], r["without_approval"]) for r in result["rows"]
        ]
        == [(2, 1), (1, 0)],
        "the verdict fails for the class": result["verdict"] == "fail"
        and result["verdict_class"]
        == {"check": "action_without_approval", "count": 1, "most": 0, "verdict": "fail"},
        "the seal is intact": result["seal_intact"],
    }
    result["checks"] = checks
    result["pass"] = all(checks.values())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(checks, ensure_ascii=False))
    print("PASS" if result["pass"] else "FAIL", OUT.relative_to(ROOT))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

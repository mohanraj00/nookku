"""Proof that a scripted test sends a second message during a slow turn (SPEC.md sections 4.2,
7.10, 8.3 and 8.6, #522).

A toy shop app has a stdio MCP server `payments`. Its tool `refund` takes 1.5 seconds. The app
reads its stdin during a turn. If a message comes during a refund, the app stops the refund: it
sends `notifications/cancelled` to the server, and the server sends no result. The proof runs
2 scripted tests with the same 3 messages:

- `second`: the row of message 2 has `"during": 0.5`, so the entry gets it during turn 1.
- `control`: no row has `during`, so the entry gets message 2 after the reply of turn 1.

The proof checks the tap times, the key `second_messages` of `findings.json`, the 1 `call_cut`
finding of the test `second`, the verdict of a limit of 0, the audit and the seal. The test
`control` must have no second message and no `call_cut` finding. It needs no model.

usage: python scripts/proof_second_message.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import json_lines  # noqa: E402

from nookku import __version__, bridge, discovery, seal  # noqa: E402
from nookku.record import loads  # noqa: E402

OUT = ROOT / "proofs" / "second-message" / "results.json"
SPEC = """# Toy shop

## Verdict

| Finding | Most |
|---|---|
| `call_cut` | 0 |
"""
MESSAGES = ["Refund order 5120.", "Stop. Do not refund it.", "Is order 5120 refunded?"]
# The seconds from the send of message 1 to the send of message 2 in the test `second`.
DURING = 0.5

# The MCP server. A refund takes 1.5 seconds. A cancelled refund gives no result.
SERVER = """
import json, sys, threading, time

out, cancelled = threading.Lock(), set()

def send(message):
    with out:
        sys.stdout.write(json.dumps(message) + "\\n")
        sys.stdout.flush()

def refund(request):
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        if request["id"] in cancelled:
            return
        time.sleep(0.02)
    order = request["params"]["arguments"]["order"]
    result = {"content": [{"type": "text", "text": f"refund of order {order} sent"}]}
    send({"jsonrpc": "2.0", "id": request["id"], "result": result})

for raw in sys.stdin:
    request = json.loads(raw)
    method = request.get("method")
    if method == "notifications/cancelled":
        cancelled.add(request["params"]["requestId"])
    elif method == "tools/call":
        threading.Thread(target=refund, args=(request,), daemon=True).start()
    elif method == "initialize":
        result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "payments", "version": "1"},
        }
        send({"jsonrpc": "2.0", "id": request["id"], "result": result})
    elif "id" in request:
        send({"jsonrpc": "2.0", "id": request["id"], "result": {}})
"""

# The app. It reads its stdin during a turn. A message during a refund stops the refund.
ENTRY = """
import json, os, shlex, subprocess, sys, threading

server = subprocess.Popen(
    shlex.split(os.environ["PAYMENTS_MCP"]), stdin=subprocess.PIPE, stdout=subprocess.PIPE
)
out, to_server = threading.Lock(), threading.Lock()
results, came = {}, threading.Condition()
stop, refunded, worker = threading.Event(), set(), None

def send(message):
    with to_server:
        server.stdin.write((json.dumps(message) + "\\n").encode())
        server.stdin.flush()

def read_server():
    for raw in server.stdout:
        message = json.loads(raw)
        with came:
            results[message.get("id")] = message
            came.notify_all()

def say(request, reply):
    with out:
        sys.stdout.write(json.dumps({"v": 1, "id": request["id"], "reply": reply}) + "\\n")
        sys.stdout.flush()

def refund(request, order, call):
    send({"jsonrpc": "2.0", "id": call, "method": "tools/call",
          "params": {"name": "refund", "arguments": {"order": order}}})
    while True:
        with came:
            came.wait(0.02)
            done = call in results
        if done:
            refunded.add(order)
            say(request, f"The refund of order {order} is sent.")
            return
        if stop.is_set():
            params = {"requestId": call, "reason": "the user sent a new message"}
            send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": params})
            say(request, f"I stopped the refund of order {order}.")
            return

threading.Thread(target=read_server, daemon=True).start()
client = {"name": "toy-shop", "version": "1"}
send({"jsonrpc": "2.0", "id": 0, "method": "initialize",
      "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": client}})
with came:
    came.wait_for(lambda: 0 in results, 10)
send({"jsonrpc": "2.0", "method": "notifications/initialized"})

count = 0
for raw in sys.stdin:
    request = json.loads(raw)
    text = request["message"]
    busy = worker is not None and worker.is_alive()
    if text.startswith("Refund"):
        count += 1
        stop.clear()
        order = text.rstrip(".").split()[-1]
        worker = threading.Thread(target=refund, args=(request, order, count))
        worker.start()
    elif text.startswith("Stop"):
        if busy:
            stop.set()
            worker.join()
            say(request, "The refund is stopped.")
        else:
            say(request, "The refund is already sent.")
    else:
        if busy:
            worker.join()
        state = "refunded" if "5120" in refunded else "not refunded"
        say(request, f"Order 5120 is {state}.")
"""


def run(name: str, during: float | None) -> dict:
    """Run one scripted test in a new toy shop project. Return its results."""
    project = Path(tempfile.mkdtemp(prefix=f"nookku-second-{name}-")).resolve()
    (project / ".nookku").mkdir()
    (project / "entry.py").write_text(ENTRY)
    (project / "payments_mcp.py").write_text(SERVER)
    (project / "APP_SPEC.md").write_text(SPEC)
    config = {"entry": [sys.executable, "entry.py"], "models": [], "spec": ["APP_SPEC.md"]}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    rows: list[dict] = [{"said": m} for m in MESSAGES]
    if during is not None:
        rows[1]["during"] = during
    script = project / "script.jsonl"
    script.write_text("".join(json.dumps(r) + "\n" for r in rows))
    server = {
        "name": "payments",
        "transport": "stdio",
        "env": "PAYMENTS_MCP",
        "command": [sys.executable, str(project / "payments_mcp.py")],
        "url": None,
    }
    discovery.register(project, discovery.make(mcp_servers=[server]))
    passed, lines, folder = bridge.run_script(project, script, gate=True)
    turns = [r for r in json_lines((folder / "relay.jsonl").read_text()) if r["type"] == "turn"]
    tap = [r for r in json_lines((folder / "tap.jsonl").read_text()) if r["type"] == "exchange"]
    items = json_lines((folder / "trace.jsonl").read_text())
    findings = loads((folder / "findings.json").read_text())
    verdict = loads((folder / "verdict.json").read_text())
    audit = loads((folder / "audit.json").read_text())
    start = tap[0]["started"]
    calls = [
        {
            "turn": it["turn"],
            "name": it["name"],
            "output": it["output"],
            "error": it["error"],
            "has_result": "result_line" in it["source"],
        }
        for it in items
        if it["kind"] == "tool_call" and it["harness"] == "mcp"
    ]
    return {
        "script": rows,
        "passed": passed,
        "problems": [x for x in lines if x.startswith("FAIL")],
        "turns": [{"said": t["said"], "shown": t["shown"]} for t in turns],
        # The times of each exchange, in seconds from the start of turn 1.
        "tap": [
            {"started": round(r["started"] - start, 3), "ts": round(r["ts"] - start, 3)}
            for r in tap
        ],
        "second_messages": findings.get("second_messages"),
        "tool_calls": calls,
        "counts": {k: v for k, v in findings["counts"].items() if v},
        "call_cut": [
            {k: f[k] for k in ("turn", "detail", "harness", "session")}
            for f in findings["findings"]
            if f["check"] == "call_cut"
        ],
        "verdict": verdict["verdict"],
        "audit_exit": audit["exit"],
        "seal_intact": seal.verify(folder)["intact"],
    }


def main() -> int:
    second, control = run("second", DURING), run("control", None)
    detail = "refund: no result. The call started before the message of turn 2, which came "
    detail += "during this turn"
    rows = second["second_messages"] or []
    tap = second["tap"]
    checks = {
        "the entry got message 2 during turn 1": len(rows) == 1
        and (rows[0]["turn"], rows[0]["during"], rows[0]["reply_first"]) == (2, 1, False)
        and DURING - 0.1 < rows[0]["after"] < 1.4
        and tap[0]["started"] < tap[1]["started"] < tap[0]["ts"],
        "the app stopped the refund": [t["shown"] for t in second["turns"]]
        == [
            "I stopped the refund of order 5120.",
            "The refund is stopped.",
            "Order 5120 is not refunded.",
        ],
        "the stopped tool call has no result": second["tool_calls"]
        == [
            {
                "turn": 1,
                "name": "refund",
                "output": None,
                "error": "no response in mcp.jsonl",
                "has_result": False,
            }
        ],
        "the stopped call gives 1 call_cut finding": second["call_cut"]
        == [{"turn": 1, "detail": detail, "harness": "mcp", "session": "payments"}]
        and rows[0]["calls_cut"] == 1
        and second["counts"] == {"tool_error": 1, "call_cut": 1},
        "the limit of 0 fails the verdict and the run": second["verdict"] == "fail"
        and not second["passed"],
        "the audit of both tests is clean": second["audit_exit"] == 0
        and control["audit_exit"] == 0,
        "the control has no second message and no finding": control["second_messages"] is None
        and control["counts"] == {}
        and control["call_cut"] == []
        and control["tap"][0]["ts"] <= control["tap"][1]["started"],
        "the control refund has its result": [t["shown"] for t in control["turns"]]
        == [
            "The refund of order 5120 is sent.",
            "The refund is already sent.",
            "Order 5120 is refunded.",
        ]
        and [c["has_result"] for c in control["tool_calls"]] == [True]
        and control["verdict"] == "pass"
        and control["passed"],
        "the seal of both tests is intact": second["seal_intact"] and control["seal_intact"],
    }
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
        },
        "second": second,
        "control": control,
        "checks": checks,
        "pass": all(checks.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(checks, ensure_ascii=False))
    print("PASS" if result["pass"] else "FAIL", OUT.relative_to(ROOT))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Proof that the HTTP tap records an app agent at a cluster Service URL (#458).

The proof makes a kind cluster. The toy shop agent runs as a Deployment in the namespace `shop`,
behind the Service `toy-shop` on port 8080. The harness side is a plain pod in the namespace
`harness`. It runs `nookku tap` in front of http://toy-shop.shop.svc:8080/ and the project hooks
relay of Claude Code with no entry. The proof sends the hook events of Claude Code to
`nookku hook` in the pod, so no harness and no model run.

The proof checks:

- C1: the Service name resolves to the ClusterIP of the Service in the harness pod.
- C2: each message reaches the app byte for byte. The app logs the bytes of each request body and
  response body. The proof compares them with the relay record and the tap record.
- C3: each reply reaches the relay byte for byte, and the relay shows it.
- C4: the guard denies a curl call from the model to the Service URL (the option agent_url).
- C5: the audit finds 0 breaks in the records, and finds each planted fault (P4).

It writes proofs/cluster-tap/: results.json, tap.jsonl, relay.jsonl and app.jsonl. It needs
Docker, kind and kubectl. It deletes its cluster at the end, also if a step fails.

usage: python scripts/proof_cluster_tap.py [--cluster NAME] [--keep]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import MESSAGES, json_lines, planted  # noqa: E402

from nookku import __version__  # noqa: E402
from nookku.adapters import JsonAdapter  # noqa: E402
from nookku.audit import audit  # noqa: E402

OUT = ROOT / "proofs" / "cluster-tap"
BASE_IMAGE = "python:3.12-slim"
IMAGE = f"nookku-cluster-tap:{__version__}"
SERVICE_HOST = "toy-shop.shop.svc"
AGENT_URL = f"http://{SERVICE_HOST}:8080/"
TAP_URL = "http://127.0.0.1:8800/"
WORK = "/work"
SESSION = "cluster-tap-proof"
# The direct call that the model tries in C4. The guard must deny it.
CURL = f'curl -s -d \'{{"text": "refund my teapot"}}\' {AGENT_URL}'

# The app: the toy shop agent of examples/toy-shop/agent.py as an HTTP server on all addresses of
# the pod. It logs one JSON line for each request, with the exact bytes of the request body and of
# the response body in base64.
APP = """
import base64, json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from agent import answer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        text = json.loads(body).get("text", "")
        out = json.dumps({"reply": answer(text)}, ensure_ascii=False).encode()
        row = {
            "path": self.path,
            "request_b64": base64.b64encode(body).decode(),
            "response_b64": base64.b64encode(out).decode(),
        }
        sys.stdout.write(json.dumps(row) + "\\n")
        sys.stdout.flush()
        self.send_response_only(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""

DOCKERFILE = f"""FROM {BASE_IMAGE}
COPY *.whl /tmp/
RUN pip install --no-index --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
COPY agent.py app.py /app/
WORKDIR /app
"""

MANIFEST = f"""
apiVersion: v1
kind: Namespace
metadata:
  name: shop
---
apiVersion: v1
kind: Namespace
metadata:
  name: harness
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: toy-shop
  namespace: shop
spec:
  replicas: 1
  selector:
    matchLabels:
      app: toy-shop
  template:
    metadata:
      labels:
        app: toy-shop
    spec:
      containers:
        - name: app
          image: {IMAGE}
          imagePullPolicy: Never
          command: ["python", "-u", "/app/app.py"]
          ports:
            - containerPort: 8080
          readinessProbe:
            tcpSocket:
              port: 8080
            periodSeconds: 1
---
apiVersion: v1
kind: Service
metadata:
  name: toy-shop
  namespace: shop
spec:
  selector:
    app: toy-shop
  ports:
    - port: 8080
      targetPort: 8080
---
apiVersion: v1
kind: Pod
metadata:
  name: harness
  namespace: harness
spec:
  containers:
    - name: harness
      image: {IMAGE}
      imagePullPolicy: Never
      command: ["sleep", "infinity"]
"""


def run(args: list[str], *, data: bytes | None = None, timeout: float = 300) -> bytes:
    """Run a command and return its stdout. Stop the proof if it fails."""
    p = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        err = p.stderr.decode(errors="replace").strip()[-600:]
        raise SystemExit(f"{' '.join(args[:4])} ... failed (exit {p.returncode}): {err}")
    return p.stdout


def tool(name: str) -> str:
    """The path of a system tool. Stop the proof if it is not there."""
    found = shutil.which(name) or shutil.which(name, path=str(Path.home() / "go" / "bin"))
    if found is None:
        raise SystemExit(f"{name} is not on PATH. The proof needs Docker, kind and kubectl.")
    return found


class Cluster:
    def __init__(self, name: str) -> None:
        self.name = name
        self.docker, self.kind, self.kubectl = tool("docker"), tool("kind"), tool("kubectl")

    def k(self, *args: str, data: bytes | None = None, timeout: float = 300) -> bytes:
        return run(
            [self.kubectl, "--context", f"kind-{self.name}", *args], data=data, timeout=timeout
        )

    def harness(
        self, *args: str, data: bytes | None = None, env: dict[str, str] | None = None
    ) -> bytes:
        """Run a command in the harness pod."""
        pre = ["env", *(f"{k}={v}" for k, v in (env or {}).items())] if env else []
        stdin = ["-i"] if data is not None else []
        return self.k("exec", *stdin, "-n", "harness", "harness", "--", *pre, *args, data=data)

    def exists(self) -> bool:
        return self.name in run([self.kind, "get", "clusters"]).decode().split()

    def create(self) -> None:
        run([self.kind, "create", "cluster", "--name", self.name, "--wait", "180s"], timeout=600)

    def delete(self) -> None:
        run([self.kind, "delete", "cluster", "--name", self.name], timeout=300)


def build_image(c: Cluster, work: Path) -> None:
    """Build the image of the app and the harness pod: the base image, the nookku wheel of this
    checkout and the toy shop agent. Then load it into the kind nodes."""
    ctx = work / "image"
    ctx.mkdir()
    run(["uv", "build", "--wheel", "--out-dir", str(ctx), str(ROOT)], timeout=300)
    shutil.copy(ROOT / "examples" / "toy-shop" / "agent.py", ctx / "agent.py")
    (ctx / "app.py").write_text(APP)
    (ctx / "Dockerfile").write_text(DOCKERFILE)
    run([c.docker, "build", "-q", "-t", IMAGE, str(ctx)], timeout=600)
    run([c.kind, "load", "docker-image", IMAGE, "--name", c.name], timeout=600)


def start_tap(c: Cluster) -> None:
    """Install the project hooks relay with no entry, start the tap and switch relay mode on."""
    c.harness("mkdir", "-p", WORK)
    init = ["nookku", "init", "claude-code", "--root", WORK]
    c.harness(*init, "--tap-url", TAP_URL, "--agent-url", AGENT_URL)
    tap = f"nookku tap --agent {AGENT_URL} --record {WORK}/tap.jsonl"
    c.harness("sh", "-c", f"cd {WORK} && nohup {tap} >{WORK}/tap.log 2>&1 </dev/null &")
    deadline = time.monotonic() + 60
    while b"listening" not in c.harness("cat", f"{WORK}/tap.log"):
        if time.monotonic() > deadline:
            raise SystemExit(f"the tap did not start: {c.harness('cat', f'{WORK}/tap.log')!r}")
        time.sleep(0.5)
    c.harness("nookku", "mode", "on", "--root", WORK)


def hook(c: Cluster, event: dict[str, Any]) -> dict[str, Any]:
    """Send one hook event of Claude Code to `nookku hook` in the harness pod. The entry point of
    the interactive CLI is `cli` (SPEC.md section 5, print mode)."""
    event = {"session_id": SESSION, "cwd": WORK, **event}
    raw = json.dumps(event, ensure_ascii=False).encode()
    args = ["nookku", "hook", "--root", WORK, "--harness", "claude-code"]
    out = c.harness(*args, data=raw, env={"CLAUDE_CODE_ENTRYPOINT": "cli"})
    answer: dict[str, Any] = json.loads(out.decode())
    return answer


def versions(c: Cluster) -> dict[str, str]:
    server = json.loads(c.k("version", "-o", "json"))["serverVersion"]["gitVersion"]
    client = json.loads(run([c.kubectl, "version", "--client", "-o", "json"]))
    docker = run([c.docker, "version", "--format", "{{.Server.Version}}"]).decode().strip()
    base = run([c.docker, "image", "inspect", BASE_IMAGE, "--format", "{{.Id}}"]).decode().strip()
    claude = shutil.which("claude")
    events = run([claude, "--version"]).decode().strip() if claude else "not installed"
    return {
        "nookku": __version__,
        "nookku_in_pod": c.harness("nookku", "--version").decode().split()[-1],
        "python_in_pod": c.harness("python", "-V").decode().split()[-1],
        "base_image": f"{BASE_IMAGE} {base}",
        "kind": run([c.kind, "version"]).decode().split()[1],
        "kubernetes": server,
        "kubectl": client["clientVersion"]["gitVersion"],
        "docker": docker,
        "hook_events": f"Claude Code {events}, sent by the proof with no harness",
        "os": os.uname().sysname,
    }


def prove(c: Cluster, work: Path) -> dict[str, Any]:
    c.k("apply", "-f", "-", data=MANIFEST.encode())
    c.k("rollout", "status", "-n", "shop", "deployment/toy-shop", "--timeout=180s", timeout=200)
    c.k(
        "wait",
        "-n",
        "harness",
        "--for=condition=Ready",
        "pod/harness",
        "--timeout=180s",
        timeout=200,
    )

    # C1: the Service URL resolves in the harness pod.
    cluster_ip = c.k("get", "svc", "-n", "shop", "toy-shop", "-o", "jsonpath={.spec.clusterIP}")
    lookup = f"import socket; print(socket.gethostbyname({SERVICE_HOST!r}))"
    resolved = c.harness("python", "-c", lookup).decode().strip()
    c1 = {"url": AGENT_URL, "resolves_to_cluster_ip": resolved == cluster_ip.decode().strip()}

    start_tap(c)
    shown = []
    for message in MESSAGES:
        answer = hook(c, {"hook_event_name": "UserPromptSubmit", "prompt": message})
        shown.append(answer.get("reason") if answer.get("decision") == "block" else None)
    # C4: the model tries to call the Service URL directly.
    tool_input = {"command": CURL}
    deny = hook(c, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input})
    decision = deny.get("hookSpecificOutput", {}).get("permissionDecision")
    c.harness("nookku", "mode", "off", "--root", WORK)

    tap_path, relay_path, app_path = work / "tap.jsonl", work / "relay.jsonl", work / "app.jsonl"
    tap_path.write_bytes(c.harness("cat", f"{WORK}/tap.jsonl"))
    relay_path.write_bytes(c.harness("cat", f"{WORK}/.nookku/relay.jsonl"))
    app_path.write_bytes(c.k("logs", "-n", "shop", "deployment/toy-shop"))

    exchanges = [r for r in json_lines(tap_path.read_text()) if r["type"] == "exchange"]
    turns = [r for r in json_lines(relay_path.read_text()) if r["type"] == "turn"]
    app = json_lines(app_path.read_text())
    adapter = JsonAdapter()
    checks = []
    for i, message in enumerate(MESSAGES):
        t = turns[i] if i < len(turns) else {}
        x = exchanges[i] if i < len(exchanges) else {}
        a = app[i] if i < len(app) else {}
        request = base64.b64decode(a.get("request_b64", ""))
        response = base64.b64decode(a.get("response_b64", ""))
        reply = json.loads(response)["reply"] if response else None
        checks.append(
            {
                "message": i + 1,
                "request_bytes": len(request),
                "response_bytes": len(response),
                # C2: the app got the bytes that the relay sent, for the message of the tester.
                "message_same": t.get("said") == x.get("input") == message
                and request == adapter.request(message, []),
                # C3: the relay showed the reply that the app sent.
                "reply_same": reply is not None
                and t.get("ok") is True
                and t.get("shown") == x.get("reply") == shown[i] == reply,
            }
        )
    report = audit(tap_path, relay_path)
    faults = work / "faults"
    faults.mkdir()
    p4 = planted(tap_path, relay_path, faults)
    result: dict[str, Any] = {
        "date": date.today().isoformat(),
        "versions": versions(c),
        "C1_service": c1,
        "C2_C3_messages": checks,
        "app_requests": len(app),
        "C4_guard": {"command": CURL, "decision": decision},
        "C5_audit": {
            "exit": report.exit,
            "breaks": [b.kind for b in report.breaks],
            "planted": p4,
        },
    }
    result["pass"] = (
        c1["resolves_to_cluster_ip"]
        and len(checks) == len(MESSAGES) == len(app) == len(exchanges) == len(turns)
        and all(m["message_same"] and m["reply_same"] for m in checks)
        and decision == "deny"
        and report.exit == 0
        and all(p["ok"] for p in p4)
    )
    OUT.mkdir(parents=True, exist_ok=True)
    for p in (tap_path, relay_path, app_path):
        shutil.copy(p, OUT / p.name)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cluster", default="nookku-458", help="the name of the kind cluster")
    parser.add_argument("--keep", action="store_true", help="do not delete the cluster at the end")
    args = parser.parse_args()
    c = Cluster(args.cluster)
    if c.exists():
        raise SystemExit(f"a kind cluster {c.name} exists. Give a new name with --cluster.")
    work = Path(tempfile.mkdtemp(prefix="nookku-cluster-tap-"))
    c.create()
    try:
        build_image(c, work)
        result = prove(c, work)
    finally:
        if not args.keep:
            c.delete()
    out = OUT / "results.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

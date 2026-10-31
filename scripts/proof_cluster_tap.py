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

It writes proofs/cluster-tap/results.json and the records and manifests of each form. It needs
Docker, kind and kubectl. It deletes its cluster at the end, also if a step fails.

Forms: same-pod, service (a separate tap pod), and default-deny (the separate tap pod with
egress policy). The policy form checks the hook before the relay rule exists, with the rule,
and after its removal. The policy controller runs only in the proof cluster.

usage: python scripts/proof_cluster_tap.py [--cluster NAME] [--form FORM]
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
FORMS = ("same-pod", "service", "default-deny")
TAP_HOST = "tap.harness.svc"
POLICY_MANIFEST = (
    "https://raw.githubusercontent.com/kubernetes-sigs/kube-network-policies/"
    "d33caa334951debb10babc3238eb3eea4edc1eda/install.yaml"
)
POLICY_IMAGE = "registry.k8s.io/networking/kube-network-policies:v1.1.2"
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
  labels:
    app: harness
spec:
  containers:
    - name: harness
      image: {IMAGE}
      imagePullPolicy: Never
      command: ["sleep", "infinity"]
"""


TAP_MANIFEST = f"""
apiVersion: v1
kind: Pod
metadata:
  name: tap
  namespace: harness
  labels:
    app: tap
spec:
  containers:
    - name: tap
      image: {IMAGE}
      imagePullPolicy: Never
      command: ["sleep", "infinity"]
---
apiVersion: v1
kind: Service
metadata:
  name: tap
  namespace: harness
spec:
  selector:
    app: tap
  ports:
    - port: 8800
      targetPort: 8800
"""

# This namespace denies egress. DNS and the tap-to-app hop have separate rules. The
# harness-to-tap rule is absent at first. No policy in this proof changes the host.
DENY_MANIFEST = """
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: harness
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress: []
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: harness
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-tap-to-shop
  namespace: harness
spec:
  podSelector:
    matchLabels:
      app: tap
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: shop
          podSelector:
            matchLabels:
              app: toy-shop
      ports:
        - protocol: TCP
          port: 8080
"""

RELAY_RULE = """
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-relay-to-tap
  namespace: harness
spec:
  podSelector:
    matchLabels:
      app: harness
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: tap
      ports:
        - protocol: TCP
          port: 8800
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


def start_tap(c: Cluster, separate: bool = False) -> None:
    """Install the project hooks relay with no entry, start the tap and switch relay mode on."""
    c.harness("mkdir", "-p", WORK)
    init = ["nookku", "init", "claude-code", "--root", WORK]
    url = f"http://{TAP_HOST}:8800/" if separate else TAP_URL
    c.harness(*init, "--tap-url", url, "--agent-url", AGENT_URL)
    tap_exec = (
        (lambda *args: c.k("exec", "-n", "harness", "tap", "--", *args)) if separate else c.harness
    )
    tap_exec("mkdir", "-p", WORK)
    listen = " --listen 0.0.0.0:8800" if separate else ""
    tap = f"nookku tap --agent {AGENT_URL} --record {WORK}/tap.jsonl{listen}"
    tap_exec("sh", "-c", f"cd {WORK} && nohup {tap} >{WORK}/tap.log 2>&1 </dev/null &")
    deadline = time.monotonic() + 60
    while b"listening" not in tap_exec("cat", f"{WORK}/tap.log"):
        if time.monotonic() > deadline:
            raise SystemExit(f"the tap did not start: {tap_exec('cat', f'{WORK}/tap.log')!r}")
        time.sleep(0.5)
    c.harness("nookku", "mode", "on", "--root", WORK)


def hook(c: Cluster, event: dict[str, Any], *, short_timeout: bool = False) -> dict[str, Any]:
    """Send one hook event of Claude Code to `nookku hook` in the harness pod. The entry point of
    the interactive CLI is `cli` (SPEC.md section 5, print mode)."""
    event = {"session_id": SESSION, "cwd": WORK, **event}
    raw = json.dumps(event, ensure_ascii=False).encode()
    args = ["nookku", "hook", "--root", WORK, "--harness", "claude-code"]
    if short_timeout:
        # Shorten only this proof process. Use the same hook and fail-closed path.
        code = "from nookku import kit; kit.TIMEOUT=2; from nookku.__main__ import main; main()"
        args = ["python", "-c", code, *args[1:]]
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
    codex = shutil.which("codex")
    codex_version = run([codex, "--version"]).decode().strip() if codex else "not installed"
    return {
        "nookku": __version__,
        "nookku_in_pod": c.harness("nookku", "--version").decode().split()[-1],
        "python_in_pod": c.harness("python", "-V").decode().split()[-1],
        "base_image": f"{BASE_IMAGE} {base}",
        "codex": codex_version + ", not run",
        "kind": run([c.kind, "version"]).decode().split()[1],
        "kubernetes": server,
        "kubectl": client["clientVersion"]["gitVersion"],
        "docker": docker,
        "hook_events": f"Claude Code {events}, sent by the proof with no harness",
        "os": os.uname().sysname,
    }


def prove(c: Cluster, work: Path, form: str = "same-pod") -> dict[str, Any]:
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

    separate = form != "same-pod"
    if separate:
        c.k("apply", "-f", "-", data=TAP_MANIFEST.encode())
        c.k("wait", "-n", "harness", "--for=condition=Ready", "pod/tap", "--timeout=180s")

    # C1: the Service URL resolves in the harness pod.
    cluster_ip = c.k("get", "svc", "-n", "shop", "toy-shop", "-o", "jsonpath={.spec.clusterIP}")
    lookup = f"import socket; print(socket.gethostbyname({SERVICE_HOST!r}))"
    resolved = c.harness("python", "-c", lookup).decode().strip()
    c1 = {"url": AGENT_URL, "resolves_to_cluster_ip": resolved == cluster_ip.decode().strip()}

    start_tap(c, separate)
    wait_route(c, TAP_HOST if separate else "127.0.0.1", 8800, True)
    policy: dict[str, Any] = {}
    if separate:
        ip = c.k("get", "svc", "-n", "harness", "tap", "-o", "jsonpath={.spec.clusterIP}")
        lookup = f"import socket; print(socket.gethostbyname({TAP_HOST!r}))"
        policy["tap_service_resolves"] = (
            c.harness("python", "-c", lookup).decode().strip() == ip.decode()
        )
    if form == "default-deny":
        c.k("apply", "-f", "-", data=DENY_MANIFEST.encode())
        wait_route(c, TAP_HOST, 8800, False)
        policy["before_rule"] = blocked(c, "Hi, can you find my toy order?")
        c.k("apply", "-f", "-", data=RELAY_RULE.encode())
        wait_route(c, TAP_HOST, 8800, True)
        # The relay must have no direct route to the app, by Service or pod IP.
        app_ip = c.k(
            "get",
            "pods",
            "-n",
            "shop",
            "-l",
            "app=toy-shop",
            "-o",
            "jsonpath={.items[0].status.podIP}",
        ).decode()
        policy["direct_service_blocked"] = not route(c, SERVICE_HOST, 8080)
        policy["direct_pod_blocked"] = not route(c, app_ip, 8080)
        policy["manifest"] = POLICY_MANIFEST
        policy["image"] = POLICY_IMAGE
        policy["controller"] = c.k(
            "get",
            "pods",
            "-n",
            "kube-system",
            "-l",
            "app=kube-network-policies",
            "-o",
            "jsonpath={.items[0].status.containerStatuses[0].imageID}",
        ).decode()
    shown = []
    for message in MESSAGES:
        answer = hook(c, {"hook_event_name": "UserPromptSubmit", "prompt": message})
        shown.append(answer.get("reason") if answer.get("decision") == "block" else None)
    # C4: the model tries to call the Service URL directly.
    tool_input = {"command": CURL}
    deny = hook(c, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input})
    decision = deny.get("hookSpecificOutput", {}).get("permissionDecision")
    if form == "default-deny":
        c.k("delete", "networkpolicy", "-n", "harness", "allow-relay-to-tap")
        wait_route(c, TAP_HOST, 8800, False)
        policy["after_removal"] = blocked(c, "Please check my toy order again.")
    c.harness("nookku", "mode", "off", "--root", WORK)

    tap_path, relay_path, app_path = work / "tap.jsonl", work / "relay.jsonl", work / "app.jsonl"
    tap_bytes = (
        c.k("exec", "-n", "harness", "tap", "--", "cat", f"{WORK}/tap.jsonl")
        if separate
        else c.harness("cat", f"{WORK}/tap.jsonl")
    )
    tap_path.write_bytes(tap_bytes)
    relay_path.write_bytes(c.harness("cat", f"{WORK}/.nookku/relay.jsonl"))
    app_path.write_bytes(c.k("logs", "-n", "shop", "deployment/toy-shop"))

    exchanges = [r for r in json_lines(tap_path.read_text()) if r["type"] == "exchange"]
    all_turns = [r for r in json_lines(relay_path.read_text()) if r["type"] == "turn"]
    turns = [r for r in all_turns if r.get("ok") is True]
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
    # P4 changes a successful exchange. The policy form also has failed turns, which
    # have no tap exchange and which the audit excludes from reply matching.
    successful = work / "successful-relay.jsonl"
    successful.write_text(
        "".join(
            line + "\n"
            for line in relay_path.read_text().splitlines()
            if json.loads(line).get("ok") is not False
        )
    )
    p4 = planted(tap_path, successful, faults)
    successful_audit = audit(tap_path, successful)
    expected_breaks = ["not_delivered"] * 2 if form == "default-deny" else []
    result: dict[str, Any] = {
        "date": date.today().isoformat(),
        "form": form,
        "policy": policy,
        "versions": versions(c),
        "C1_service": c1,
        "C2_C3_messages": checks,
        "app_requests": len(app),
        "C4_guard": {"command": CURL, "decision": decision},
        "C5_audit": {
            "exit": report.exit,
            "breaks": [b.kind for b in report.breaks],
            "planted": p4,
            "expected_breaks": expected_breaks,
            "successful_exit": successful_audit.exit,
            "successful_breaks": [b.kind for b in successful_audit.breaks],
        },
    }
    result["pass"] = (
        c1["resolves_to_cluster_ip"]
        and len(checks) == len(MESSAGES) == len(app) == len(exchanges) == len(turns)
        and all(m["message_same"] and m["reply_same"] for m in checks)
        and decision == "deny"
        and report.exit == (1 if expected_breaks else 0)
        and [b.kind for b in report.breaks] == expected_breaks
        and successful_audit.exit == 0
        and all(p["ok"] for p in p4)
        and (not separate or policy["tap_service_resolves"])
        and (
            form != "default-deny"
            or (
                policy["before_rule"]["pass"]
                and policy["after_removal"]["pass"]
                and policy["direct_service_blocked"]
                and policy["direct_pod_blocked"]
                and len(all_turns) == len(MESSAGES) + 2
            )
        )
    )
    out = OUT / form
    out.mkdir(parents=True, exist_ok=True)
    for p in (tap_path, relay_path, app_path):
        shutil.copy(p, out / p.name)
    for name, content in (
        ("pods.yaml", MANIFEST + ("\n---\n" + TAP_MANIFEST if separate else "")),
        ("deny.yaml", DENY_MANIFEST),
        ("relay-rule.yaml", RELAY_RULE),
    ):
        if name == "pods.yaml" or form == "default-deny":
            (out / name).write_text(content)
    return result


def route(c: Cluster, host: str, port: int) -> bool:
    code = (
        "import socket; s=socket.socket(); s.settimeout(1); "
        f"print(s.connect_ex(({host!r}, {port})) == 0); s.close()"
    )
    return c.harness("python", "-c", code).strip() == b"True"


def wait_route(c: Cluster, host: str, port: int, reachable: bool) -> None:
    deadline = time.monotonic() + 60
    while route(c, host, port) != reachable:
        if time.monotonic() > deadline:
            raise SystemExit(f"policy did not set {host}:{port} reachable={reachable}")
        time.sleep(0.2)


def blocked(c: Cluster, message: str) -> dict[str, Any]:
    before = c.k("logs", "-n", "shop", "deployment/toy-shop")
    answer = hook(c, {"hook_event_name": "UserPromptSubmit", "prompt": message}, short_timeout=True)
    after = c.k("logs", "-n", "shop", "deployment/toy-shop")
    record = json_lines(c.harness("cat", f"{WORK}/.nookku/relay.jsonl").decode())[-1]
    return {
        "decision": answer.get("decision"),
        "reason": answer.get("reason"),
        "app_unchanged": before == after,
        "failed_turn_recorded": record.get("type") == "turn"
        and record.get("ok") is False
        and record.get("said") == message,
        "pass": answer.get("decision") == "block"
        and before == after
        and record.get("type") == "turn"
        and record.get("ok") is False
        and record.get("said") == message,
    }


def free_space(c: Cluster) -> int:
    """Check the Docker VM, without removing any image or volume."""
    data = run(
        [
            c.docker,
            "run",
            "--rm",
            "--pull=never",
            "--entrypoint",
            "df",
            BASE_IMAGE,
            "-m",
            "/var/lib",
        ]
    )
    available = int(data.decode().splitlines()[-1].split()[3])
    if available < 1200:
        raise SystemExit(f"Docker has {available} MB free, below 1200 MB. Stop; do not prune.")
    return available


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cluster", default="nookku-508", help="the name of the kind cluster")
    parser.add_argument("--form", choices=("all", *FORMS), default="all")
    args = parser.parse_args()
    c = Cluster(args.cluster)
    if c.exists():
        raise SystemExit(f"a kind cluster {c.name} exists. Give a new name with --cluster.")
    space = free_space(c)
    forms = FORMS if args.form == "all" else (args.form,)
    with tempfile.TemporaryDirectory(prefix="nookku-cluster-tap-") as folder:
        work = Path(folder)
        try:
            c.create()
            free_space(c)
            build_image(c, work)
            if "default-deny" in forms:
                c.k("apply", "-f", POLICY_MANIFEST)
                c.k(
                    "rollout",
                    "status",
                    "-n",
                    "kube-system",
                    "daemonset/kube-network-policies",
                    "--timeout=180s",
                    timeout=200,
                )
            results = []
            for form in forms:
                free_space(c)
                part = work / form
                part.mkdir()
                results.append(prove(c, part, form))
                print(form, "PASS" if results[-1]["pass"] else "FAIL", flush=True)
                c.k("delete", "namespace", "harness", "shop", "--wait=true")
            result = {
                "method": "scripts/proof_cluster_tap.py",
                "docker_free_mb_before": space,
                "forms": results,
                "pass": all(r["pass"] for r in results),
            }
        finally:
            c.delete()
    out = OUT / "results.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

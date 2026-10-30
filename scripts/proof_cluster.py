"""The full proof of a test inside a Koodam Workspace (#461). Local only.

The proof makes a kind cluster and installs Koodam 0.3.0 with the egress proxy. The toy shop agent
(examples/toy-shop/http_agent.py) runs as a Deployment in the namespace `shop`, behind the Service
`toy-shop` on port 8080. The harness runs in the Workspace `shop` in the namespace `dev-shop`, with
`extraEgress` to the Service. The proof installs nookku and the plugin in the Workspace by hand,
because Koodam 0.3.0 has no Nookku preset (koodam#83). The steps are the steps of
docs/getting-started-cluster.md.

The test uses the entry examples/toy-shop/service_entry.py, with a backend part for the Service in
the egress answer. The harness sends the 3 toy shop messages. After turn 2, the proof makes 2 calls
from the Workspace pod around the proxies of nookku: an HTTP call to example.com, and a CONNECT
to example.com port 22 through the Koodam proxy, which the proxy denies. The test ends in a shell.
The proof exports the spans of the test window with `koodam trace` outside the pod, and gives them
to `nookku trace --egress` in the pod. Then the prompt `nookku end` starts the evaluation.

W1  The Workspace runs with traced egress. Claude Code in the pod loads the plugin of the manual
    install (`nookku@nookku`) and only the MCP server of nookku.
W2  Each message reaches the agent at the Service, and each reply reaches the relay, byte for
    byte: the relay record, the tap record and the backend record agree. The audit finds 0 breaks.
W3  egress.jsonl in the test folder has the bytes of the real `koodam trace --json` export. The
    seal covers it. The trace gives `egress_not_in_discovery` for example.com only, and
    `egress_denied` for the CONNECT to port 22. No span names the Service: its traffic goes direct.
W4  The harness model writes report.md, and after the evaluation the seal is intact.

The hosts of the harness are measured before the test: the proof sends 1 prompt that the plugin
blocks, and puts each host of its spans in `egress_ignore`.

A person does 1 step: the login of Claude Code in the Workspace
(docs/getting-started-cluster.md, step 5). The proof waits for it. The proof never reads the token.

It writes proofs/cluster/SETUP.json and the records of the test in proofs/cluster/SETUP/. With
--no-evaluation, it skips the login and W4, and writes proofs/cluster/SETUP-no-evaluation.json and
proofs/cluster/SETUP-no-evaluation/. It needs
Docker, kind, kubectl, helm and the koodam CLI 0.3.0. It deletes its cluster at the end, also if a
step fails.

usage: python scripts/proof_cluster.py SETUP [--cluster NAME] [--keep] [--koodam PATH]
       [--login-wait MINUTES] [--no-evaluation]
       SETUP is plugin-claude-code. The Codex part of #461 adds plugin-codex.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import platform
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from proof_cluster_tap import Cluster, run, tool
from proof_common import json_lines, private

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__  # noqa: E402

OUT = ROOT / "proofs" / "cluster"
SETUPS = ("plugin-claude-code", "plugin-codex")
KOODAM = "0.3.0"
CHART = "oci://ghcr.io/mohanraj00/charts/koodam"
NS, WORKSPACE, POD = "dev-shop", "shop", "shop-0"
PROFILE = "nookku-proof"
# A fixed ClusterIP in the Service range of kind (10.96.0.0/16), as in the Koodam e2e test.
PROXY_IP = "10.96.100.100"
SERVICE = "http://toy-shop.shop.svc:8080/"
APP_IMAGE = "python:3.13-alpine"
UV_VERSION = "0.10.8"
HOME = "/home/dev"
PROJECT = f"{HOME}/toy-shop"
TESTS = "/tests"
MESSAGES = [
    "hi, the mug i ordered came with a crack in the handle",
    "ok what is your refund policy",
    "do you ship to delhi?",
]
PLANTED_HOST = "example.com"
ANSWER = {
    "model_apis": [],
    "backends": [{"name": "toy-shop", "env": "TOY_SHOP_URL", "url": SERVICE}],
    "mcp_servers": [],
    "databases": [],
    "other": [],
}
# The evaluation needs to run the CLI, read files and write report.md. Nothing else.
# The test folder is outside the project, in the volume of NOOKKU_TESTS_DIR.
EVALUATION = [
    "--tools=Bash,Read,Grep,Glob,Write",
    "--allowedTools=Bash(nookku:*),Bash(cat:*),Bash(ls:*),Read,Grep,Glob,Write",
    f"--add-dir={TESTS}",
]
STREAM = ["--output-format", "stream-json", "--verbose"]


def manifests(api: tuple[str, str], claude: str) -> tuple[str, str]:
    """The chart values and the objects of docs/getting-started-cluster.md.

    `api` is the address and the port of the API server endpoint, for the NetworkPolicy of the
    proxy.
    """
    values = f"""
egressProxy:
  enabled: true
  clusterIP: {PROXY_IP}
  replicas: 1
  networkPolicy:
    apiServer:
      - to:
          - ipBlock:
              cidr: {api[0]}/32
        ports:
          - protocol: TCP
            port: {api[1]}
workspace:
  networkPolicy:
    namespaces: [{NS}]
    extraEgress:
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
    objects = f"""
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
          image: {APP_IMAGE}
          command: ["python3", "-u", "/app/http_agent.py", "8080", "0.0.0.0"]
          ports:
            - containerPort: 8080
          readinessProbe:
            tcpSocket:
              port: 8080
          volumeMounts:
            - name: app
              mountPath: /app
      volumes:
        - name: app
          configMap:
            name: toy-shop
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
---
apiVersion: core.koodam.dev/v1alpha1
kind: Profile
metadata:
  name: {PROFILE}
spec:
  namespaces: [{NS}]
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {WORKSPACE}-nookku-tests
  namespace: {NS}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: core.koodam.dev/v1alpha1
kind: Workspace
metadata:
  name: {WORKSPACE}
  namespace: {NS}
spec:
  storage: 5Gi
  harnesses:
    - name: claude-code
      version: {claude}
  podTemplate:
    spec:
      containers:
        - name: workspace
          volumeMounts:
            - name: nookku-tests
              mountPath: {TESTS}
      volumes:
        - name: nookku-tests
          persistentVolumeClaim:
            claimName: {WORKSPACE}-nookku-tests
"""
    return values, objects


class Workspace:
    """The commands of the proof in the Workspace pod, as the user dev in a login shell."""

    def __init__(self, c: Cluster) -> None:
        self.c = c

    def sh(self, script: str, *, data: bytes | None = None, timeout: float = 300) -> str:
        stdin = ["-i"] if data is not None else []
        args = ["exec", *stdin, "-n", NS, POD, "-c", "workspace", "--", "bash", "-lc", script]
        return self.c.k(*args, data=data, timeout=timeout).decode()

    def put(self, path: str, data: bytes) -> None:
        self.sh(f"mkdir -p \"$(dirname '{path}')\" && cat > '{path}'", data=data)

    def get(self, path: str) -> bytes:
        return base64.b64decode(self.sh(f"base64 -w0 '{path}'"))

    def claude(self, prompt: str, extra: list[str] | None = None) -> list[Any]:
        """Run claude -p in the project. Return the stream-json events."""
        args = " ".join(f"'{a}'" for a in [*STREAM, *(extra or [])])
        script = f'cd {PROJECT} && claude -p {args} "$(cat)"'
        return json_lines(self.sh(script, data=prompt.encode(), timeout=900))


def uv_binary() -> bytes:
    """The uv binary for Linux on the architecture of this machine, from its GitHub release. The
    Workspace image has no Python and no curl, so the proof copies uv into the home."""
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}
    name = f"uv-{arch[platform.machine().lower()]}-unknown-linux-gnu"
    base = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{name}.tar.gz"
    with urllib.request.urlopen(base, timeout=120) as r:
        archive = r.read()
    with urllib.request.urlopen(base + ".sha256", timeout=60) as r:
        expected = r.read().decode().split()[0]
    if hashlib.sha256(archive).hexdigest() != expected:
        raise SystemExit(f"the sha256 of {base} is not the sha256 of its release")
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        f = t.extractfile(f"{name}/uv")
        if f is None:
            raise SystemExit(f"{base} has no uv binary")
        return f.read()


def plugin_tar() -> bytes:
    """The marketplace file and the plugin of this checkout, as a tar with no extended headers."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as t:
        for top in (".claude-plugin", "plugins/nookku"):
            for p in sorted((ROOT / top).rglob("*")):
                if p.is_file() and "node_modules" not in p.parts:
                    t.add(p, arcname=str(p.relative_to(ROOT)), recursive=False)
    return out.getvalue()


def install(c: Cluster, claude: str) -> dict[str, Any]:
    """Install Koodam, the toy shop and the Workspace (docs/getting-started-cluster.md, 1-3)."""
    for ns in ("koodam-system", "shop", NS):
        c.k("create", "namespace", ns)
    key = f"sk-{secrets.token_hex(32)}".encode()
    secret = ["create", "secret", "generic", "koodam-gateway", "--from-file=master-key=/dev/stdin"]
    c.k("-n", "koodam-system", *secret, data=key)
    ep = "jsonpath={.items[0].endpoints[0].addresses[0]} {.items[0].ports[0].port}"
    api = (
        c.k(
            "get",
            "endpointslices",
            "-n",
            "default",
            "-l",
            "kubernetes.io/service-name=kubernetes",
            "-o",
            ep,
        )
        .decode()
        .split()
    )
    values, objects = manifests((api[0], api[1]), claude)
    # The Workspace uses the subscription login, so it calls no gateway. The chart needs a
    # gateway mode and a URL. The URL is not used (docs/getting-started-cluster.md, step 1).
    helm = [tool("helm"), "--kube-context", f"kind-{c.name}", "install", "koodam", CHART]
    helm += ["--version", KOODAM, "-n", "koodam-system", "-f", "-", "--wait", "--timeout", "10m"]
    helm += ["--set", "gateway.mode=existing", "--set", "gateway.url=http://gateway.invalid:4000"]
    run(helm, data=values.encode(), timeout=900)
    c.k("label", "namespace", NS, f"koodam.dev/profile={PROFILE}")
    files = [
        f"--from-file={ROOT / 'examples' / 'toy-shop' / n}" for n in ("agent.py", "http_agent.py")
    ]
    c.k("-n", "shop", "create", "configmap", "toy-shop", *files)
    c.k("apply", "-f", "-", data=objects.encode())
    c.k("-n", "shop", "rollout", "status", "deployment/toy-shop", "--timeout=300s", timeout=320)
    running = "--for=jsonpath={.status.phase}=Running"
    c.k("wait", f"workspace/{WORKSPACE}", "-n", NS, running, "--timeout=600s", timeout=620)
    status = json.loads(c.k("get", "workspace", WORKSPACE, "-n", NS, "-o", "json"))["status"]
    conditions = {x["type"]: x["status"] for x in status.get("conditions", [])}
    return {"phase": status.get("phase"), "conditions": conditions}


def free_disk(c: Cluster) -> int:
    """The free MB of the disk of the kind node. A full disk stops each container of Docker."""
    node = f"{c.name}-control-plane"
    out = run([c.docker, "exec", node, "df", "-m", "--output=avail", "/"]).decode().split()
    return int(out[-1])


def setup_project(ws: Workspace, work: Path) -> str:
    """Install uv, nookku and the plugin in the home, and make the project.

    These are steps 4 and 6 of docs/getting-started-cluster.md. Return the path of the nookku
    wheel in the pod.
    """
    ws.put(f"{HOME}/.local/bin/uv", uv_binary())
    ws.sh(f"chmod 0755 {HOME}/.local/bin/uv")
    run(["uv", "build", "--wheel", "--out-dir", str(work), str(ROOT)], timeout=300)
    wheel = next(work.glob("nookku-*.whl"))
    pod_wheel = f"{HOME}/dl/{wheel.name}"
    ws.put(pod_wheel, wheel.read_bytes())
    ws.sh(f"uv tool install '{pod_wheel}'", timeout=600)
    ws.put(f"{HOME}/nookku-plugin.tar", plugin_tar())
    ws.sh(
        f"mkdir -p {HOME}/nookku-plugin && tar -xf {HOME}/nookku-plugin.tar -C {HOME}/nookku-plugin"
    )
    ws.sh(
        f"claude plugin marketplace add {HOME}/nookku-plugin && claude plugin install nookku@nookku"
    )
    profile = "export CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1\nexport NOOKKU_TESTS_DIR=/tests\n"
    ws.sh(f"cat >> {HOME}/.profile", data=profile.encode())
    entry = ROOT / "examples" / "toy-shop" / "service_entry.py"
    ws.put(f"{PROJECT}/service_entry.py", entry.read_bytes())
    return pod_wheel


def write_config(ws: Workspace, wheel: str, ignore: list[str]) -> None:
    """The config of the test. The entry gets the nookku of this checkout in place of the release
    of PyPI. A proof opens no browser tab."""
    config = {
        "entry": ["uv", "run", "--with", wheel, "python3", "service_entry.py"],
        "agent_url": SERVICE,
        "models": [],
        "page": False,
        "egress_ignore": ignore,
    }
    ws.put(f"{PROJECT}/.nookku/config.json", (json.dumps(config, indent=1) + "\n").encode())


def wait_for_login(c: Cluster, ws: Workspace, minutes: float) -> None:
    """Wait for the person step: the login of Claude Code in the namespace. The proof reads only
    the names of the keys of the Secret, never a value."""
    keys = "go-template={{range $k, $v := .data}}{{$k}} {{end}}"
    command = f"koodam login claude-code -n {NS} --context kind-{c.name}"
    print(
        "\nThe person step: make a token with `claude setup-token`, then store it with:\n"
        f"  {command}\nThe proof waits for the Secret koodam-login.\n",
        flush=True,
    )
    deadline = time.monotonic() + minutes * 60
    while True:
        p = subprocess.run(
            [
                c.kubectl,
                "--context",
                f"kind-{c.name}",
                "get",
                "secret",
                "koodam-login",
                "-n",
                NS,
                "-o",
                keys,
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode == 0 and "claude-code" in p.stdout.split():
            break
        if time.monotonic() > deadline:
            raise SystemExit(f"no login after {minutes} minutes. Run: {command}")
        time.sleep(10)
    # Kubernetes updates the mounted Secret in about 1 minute. A login shell reads the file.
    deadline = time.monotonic() + 180
    while ws.sh('test -n "$CLAUDE_CODE_OAUTH_TOKEN" && echo yes || echo no').strip() != "yes":
        if time.monotonic() > deadline:
            raise SystemExit("the login shell of the Workspace has no CLAUDE_CODE_OAUTH_TOKEN")
        time.sleep(5)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def spans(c: Cluster, koodam: str, since: float, until: float) -> bytes:
    """The spans of the Workspace for a window, from the logs of the proxy pods."""
    args = [koodam, "--context", f"kind-{c.name}", "-n", NS, "trace", f"workspace/{WORKSPACE}"]
    return run([*args, "--json", "--since", iso(since), "--until", iso(until + 1)])


def init_event(events: list[Any]) -> dict[str, Any]:
    init = next((e for e in events if e.get("subtype") == "init"), None)
    if not isinstance(init, dict):
        raise SystemExit("the claude output has no init event")
    return init


def planted_calls(ws: Workspace) -> dict[str, str]:
    """2 calls of the pod around the proxies of nookku. The Workspace image has bash, and no curl
    and no Python on PATH. The first call is plain HTTP to an external name: the DNS of the pod
    gives the address of the proxy, and the proxy writes an `http` span. The second call asks the
    proxy for a CONNECT to port 22, which it refuses with a `denied` span."""
    http = (
        f"exec 3<>/dev/tcp/{PLANTED_HOST}/80 && printf 'GET / HTTP/1.1\\r\\nHost: {PLANTED_HOST}"
        "\\r\\nConnection: close\\r\\n\\r\\n' >&3 && head -1 <&3 | tr -d '\\r'"
        " && cat <&3 >/dev/null"
    )
    connect = (
        f"exec 3<>/dev/tcp/{PROXY_IP}/3128 && printf 'CONNECT {PLANTED_HOST}:22 HTTP/1.1\\r\\n"
        f"Host: {PLANTED_HOST}:22\\r\\n\\r\\n' >&3 && head -1 <&3 | tr -d '\\r'"
    )
    return {"http": ws.sh(http).strip(), "connect_port_22": ws.sh(connect).strip()}


def versions(c: Cluster, ws: Workspace, koodam: str) -> dict[str, str]:
    pod = json.loads(c.k("get", "pod", POD, "-n", NS, "-o", "json"))
    images = {s["name"]: s["imageID"] for s in pod["status"]["containerStatuses"]}
    controller = c.k(
        "get",
        "deploy",
        "-n",
        "koodam-system",
        "koodam-controller-manager",
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
    ).decode()
    server = json.loads(c.k("version", "-o", "json"))["serverVersion"]["gitVersion"]
    return {
        "nookku": __version__,
        "nookku_in_pod": ws.sh("nookku --version").split()[-1],
        "claude-code": ws.sh("claude --version").strip(),
        "koodam_chart": KOODAM,
        "koodam_controller": controller,
        "koodam_workspace": images.get("workspace", ""),
        "koodam_cli": run([koodam, "version"]).decode().strip(),
        "uv_in_pod": ws.sh("uv --version").strip(),
        "app_image": APP_IMAGE,
        "kind": run([c.kind, "version"]).decode().split()[1],
        "kubernetes": server,
        "helm": run([tool("helm"), "version", "--short"]).decode().strip(),
        "docker": run([c.docker, "version", "--format", "{{.Server.Version}}"]).decode().strip(),
        "os": platform.system(),
    }


def prove(c: Cluster, koodam: str, work: Path, login_wait: float | None) -> dict[str, Any]:
    """Run the proof. With no `login_wait`, skip the login and the evaluation (a check of the
    setup with no model)."""
    claude = run(["claude", "--version"]).decode().split()[0]
    workspace = install(c, claude)
    disk = free_disk(c)
    if disk < 1200:
        raise SystemExit(f"the Docker disk has {disk} MB free. The proof needs 1200 MB.")
    ws = Workspace(c)
    wheel = setup_project(ws, work)
    write_config(ws, wheel, [])
    if login_wait is not None:
        wait_for_login(c, ws, login_wait)

    # The hosts of the harness: 1 prompt that the plugin blocks, before the test.
    before = time.time()
    init = init_event(ws.claude("nookku status"))
    time.sleep(5)
    harness_spans = json_lines(spans(c, koodam, before, time.time()).decode())
    harness_hosts = sorted({s.get("host") or s.get("sni") or "" for s in harness_spans} - {""})
    write_config(ws, wheel, harness_hosts)
    answer = json.dumps(ANSWER).encode()
    ws.sh(f"cd {PROJECT} && nookku register", data=answer)

    # The test.
    ws.claude("nookku start")
    current = json.loads(ws.sh(f"cd {PROJECT} && nookku status --json"))["test"]
    if current is None:
        raise SystemExit("the prompt nookku start started no test")
    test, folder = current["test"], current["dir"]
    shown = []
    planted: dict[str, str] = {}
    for i, message in enumerate(MESSAGES):
        result = next((e for e in reversed(ws.claude(message)) if e.get("type") == "result"), {})
        shown.append(result)
        if i == 1:
            planted = planted_calls(ws)
    ws.sh(f"cd {PROJECT} && nookku end")
    manifest = json.loads(ws.get(f"{folder}/manifest.json"))

    # The egress spans of the test window, exported outside the pod, as a tester does it. The
    # proxy writes a span when a connection closes, so wait for the planted spans.
    deadline = time.monotonic() + 120
    while True:
        export = spans(c, koodam, manifest["started"], manifest["ended"])
        rows = json_lines(export.decode())
        if sum(PLANTED_HOST in str(r.get("host")) for r in rows) >= 2:
            break
        if time.monotonic() > deadline:
            raise SystemExit("koodam trace has no span of the planted calls after 120 s")
        time.sleep(5)
    ws.put(f"{HOME}/spans.jsonl", export)
    ws.sh(f"cd {PROJECT} && nookku trace {test} --egress {HOME}/spans.jsonl")

    # The evaluation of the ended test.
    end: dict[str, Any] = {}
    if login_wait is not None:
        evaluation = ws.claude("nookku end", EVALUATION)
        end = next((e for e in reversed(evaluation) if e.get("type") == "result"), {})
    verify = ws.sh(f"cd {PROJECT} && nookku verify {test}").strip()

    records = {}
    names = [
        "relay.jsonl",
        "tap.jsonl",
        "backend.jsonl",
        "egress.jsonl",
        "findings.json",
        "audit.json",
        "manifest.json",
        "seal.json",
    ]
    report_md = ws.sh(f"cat {folder}/report.md 2>/dev/null || true")
    for name in names:
        records[name] = ws.get(f"{folder}/{name}")
    findings = json.loads(records["findings.json"])
    audit = json.loads(records["audit.json"])
    seal = json.loads(records["seal.json"])
    turns = [r for r in json_lines(records["relay.jsonl"].decode()) if r["type"] == "turn"]
    exchanges = [r for r in json_lines(records["tap.jsonl"].decode()) if r["type"] == "exchange"]
    calls = [r for r in json_lines(records["backend.jsonl"].decode()) if r["type"] == "call"]

    # W1
    plugins = [p for p in init.get("plugins", []) if isinstance(p, dict)]
    servers = sorted(str(s.get("name")) for s in init.get("mcp_servers", []))
    w1 = {
        "phase": workspace["phase"],
        "traced_egress": workspace["conditions"].get("TracedEgress"),
        "plugins": sorted(str(p.get("source") or p.get("name")) for p in plugins),
        "mcp_servers": servers,
    }
    w1["pass"] = (
        w1["phase"] == "Running"
        and w1["traced_egress"] == "True"
        and "nookku@nookku" in w1["plugins"]
        and set(servers) <= {"plugin:nookku:nookku"}
        and bool(servers)
    )

    # W2
    checks = []
    for i, message in enumerate(MESSAGES):
        t = turns[i] if i < len(turns) else {}
        x = exchanges[i] if i < len(exchanges) else {}
        b = calls[i] if i < len(calls) else {}
        request = json.loads(b["request_body"]["text"]) if b else {}
        response = json.loads(b["response_body"]["text"]) if b else {}
        checks.append(
            {
                "message": i + 1,
                "message_same": t.get("said") == x.get("input") == request.get("text") == message,
                "reply_same": t.get("ok") is True
                and t.get("shown") == x.get("reply") == response.get("reply"),
                "backend_status": b.get("status"),
                # The plugin blocks the prompt, so the model gets no turn for the message.
                "model_output_tokens": (shown[i].get("usage") or {}).get("output_tokens"),
            }
        )
    w2 = {"turns": checks, "audit_exit": audit["exit"], "breaks": audit.get("breaks", [])}
    w2["pass"] = (
        len(turns) == len(exchanges) == len(calls) == len(MESSAGES)
        and all(
            m["message_same"] and m["reply_same"] and m["backend_status"] == 200 for m in checks
        )
        and audit["exit"] == 0
    )

    # W3
    egress = findings.get("egress") or {}
    found = [f for f in findings["findings"] if f["harness"] == "egress"]
    not_found = sorted(f["session"] for f in found if f["check"] == "egress_not_in_discovery")
    denied = [f["detail"] for f in found if f["check"] == "egress_denied"]
    service_host = SERVICE.split("/")[2].split(":")[0]
    w3 = {
        "export_sha256": hashlib.sha256(export).hexdigest(),
        "export_rows": len(rows),
        "copy_same": records["egress.jsonl"] == export,
        "sealed": seal.get("files", {}).get("egress.jsonl") == hashlib.sha256(export).hexdigest(),
        "egress": egress,
        "harness_hosts_ignored": harness_hosts,
        "planted_calls": planted,
        "egress_not_in_discovery": not_found,
        "egress_denied": denied,
        "kinds": sorted({str(r.get("kind")) for r in rows}),
    }
    w3["pass"] = (
        w3["copy_same"]
        and w3["sealed"]
        and not_found == [PLANTED_HOST]
        and denied == [f"connect {PLANTED_HOST} port 22: denied (port)"]
        and service_host not in egress.get("hosts", [])
        and "127.0.0.1" not in egress.get("hosts", [])
    )

    # W4. A text that shares 8 words with an instruction file stays out of the repo.
    rows_md = [x for x in report_md.split("\n") if x.startswith("|") and "---" not in x]
    w4 = {
        "report_written": bool(report_md.strip()),
        "report_table_rows": max(len(rows_md) - 1, 0),
        "verify": verify,
        "answer": None if private(str(end.get("result"))) else end.get("result"),
    }
    # With --no-evaluation, W4 is not part of the result (None).
    w4["pass"] = None if login_wait is None else w4["report_written"] and "Seal: intact" in verify
    if report_md.strip() and not private(report_md):
        records["report.md"] = report_md.encode()

    result: dict[str, Any] = {
        "date": date.today().isoformat(),
        "method": "scripts/proof_cluster.py",
        "guide": "docs/getting-started-cluster.md",
        "test": test,
        "versions": versions(c, ws, koodam),
        "disk_free_mb_after_install": disk,
        "W1_workspace": w1,
        "W2_turns": w2,
        "W3_egress": w3,
        "W4_evaluation": w4,
        "counts": {k: v for k, v in findings["counts"].items() if v},
    }
    result["pass"] = all(
        result[k]["pass"] is not False
        for k in ("W1_workspace", "W2_turns", "W3_egress", "W4_evaluation")
    )
    result["_records"] = records
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("setup", choices=SETUPS)
    parser.add_argument("--cluster", default="nookku-461", help="the name of the kind cluster")
    parser.add_argument("--keep", action="store_true", help="do not delete the cluster at the end")
    parser.add_argument("--koodam", default="koodam", help="the koodam CLI 0.3.0")
    parser.add_argument("--login-wait", type=float, default=30, help="minutes for the login step")
    parser.add_argument(
        "--no-evaluation",
        action="store_true",
        help="skip the login and the evaluation, and write SETUP-no-evaluation.json",
    )
    args = parser.parse_args()
    if args.setup != "plugin-claude-code":
        raise SystemExit(f"{args.setup}: the Codex part of #461 adds this setup.")
    koodam = tool(args.koodam) if "/" not in args.koodam else args.koodam
    if run([koodam, "version"]).decode().split()[-1] != KOODAM:
        raise SystemExit(f"the proof needs the koodam CLI {KOODAM}")
    c = Cluster(args.cluster)
    if c.exists():
        raise SystemExit(f"a kind cluster {c.name} exists. Give a new name with --cluster.")
    work = Path(tempfile.mkdtemp(prefix="nookku-cluster-"))
    c.create()
    try:
        result = prove(c, koodam, work, None if args.no_evaluation else args.login_wait)
    finally:
        if not args.keep:
            c.delete()
    records = result.pop("_records")
    # A run with no evaluation checks steps 1 to 8 of the guide. It has its own name.
    stem = f"{args.setup}-no-evaluation" if args.no_evaluation else args.setup
    folder = OUT / stem
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for name, data in records.items():
        (folder / name).write_bytes(data)
    out = OUT / f"{stem}.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

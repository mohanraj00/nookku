"""The proof of a test from a harness in a Koodam Workspace with the Nookku preset (#431). Local
only.

The proof makes a kind cluster and installs the Koodam chart v0.5.0, pinned by digest, with the
egress proxy, the bundled gateway and its mock model, and the published Nookku data image of the
tag, pinned by digest (`nookku.image`). The toy shop agent (examples/toy-shop/http_agent.py) runs
as a Deployment in the namespace `shop`, behind the Service `toy-shop` on port 8080. Claude Code
runs in the Workspace `shop` in the namespace `dev-shop`, with the harness plugin `nookku` and
`extraEgress` to the Service. The steps are the steps of docs/getting-started-cluster.md.

The default Workspace image has no Python, and the preset needs python3 3.10 or later. The proof
builds a local image: the Workspace image of the tag, pinned by digest, and the python3 of Debian.
Koodam does not load the plugin in the harness at v0.5.0, so each prompt of the proof gives
`--plugin-dir` with the plugin folder of the preset.

The test uses the entry examples/toy-shop/service_entry.py, with a backend part for the Service in
the egress answer. Claude Code sends the 3 toy shop messages. After turn 2, the proof makes 2
calls from the Workspace pod around the proxies of nookku: an HTTP call to example.com, and a
CONNECT to example.com port 22 through the Koodam proxy, which the proxy denies. The test ends in
a shell. The proof exports the spans of the test window with `koodam trace` outside the pod, and
gives them to `nookku trace --egress` in the pod.

W1  The Workspace runs with traced egress and installed harnesses. The 2 init containers of the
    preset ended with exit code 0. The profile step of the guide adds /koodam/bin to the PATH
    (koodam#476) and the pinned lib to PYTHONPATH, with PYTHONSAFEPATH and PYTHONNOUSERSITE
    (koodam#478). The result records both gaps before that step. After it, `nookku` on the PATH
    is the launcher of the preset, with the pinned version, and python3 has both flags. A login
    shell exports the test folder of the preset, on the home PVC, with mode 0700. The files of the
    preset are read-only, and the plugin files are the files of the git tag of the pinned version.
    Claude Code loads the plugin of the preset folder and only the MCP server of nookku.
W2  Each message reaches the agent at the Service, and each reply reaches the relay, byte for
    byte: the relay record, the tap record and the backend record agree. The audit finds 0 breaks.
W3  egress.jsonl in the test folder has the bytes of the real `koodam trace --json` export. The
    seal covers it. The trace gives `egress_not_in_discovery` for example.com only, and
    `egress_denied` for the CONNECT to port 22. No span names the Service: its traffic goes direct.
W4  The harness model writes report.md, and after the evaluation the seal is intact.

The hosts of the harness are measured before the test: the proof sends 1 prompt that the plugin
blocks, and puts each host of its spans in `egress_ignore`.

The mock model of the gateway cannot write a report. With --no-evaluation, the proof needs no
person and no model, and it skips W4. Without it, a person logs in to Claude Code in the Workspace
(docs/getting-started-cluster.md, step 5), and the evaluation prompt uses that login in place of
the gateway. The proof waits for the login. It never reads the login value.

It writes proofs/cluster/plugin-claude-code.json and the records of the test in
proofs/cluster/plugin-claude-code/. With --no-evaluation, the names have the suffix
-no-evaluation. It needs Docker, kind, kubectl, helm and the koodam CLI 0.5.0. It deletes its
cluster at the end.

usage: python scripts/proof_cluster.py plugin-claude-code [--cluster NAME] [--keep]
       [--koodam PATH] [--login-wait MINUTES] [--no-evaluation]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import platform
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from proof_cluster_tap import Cluster, free_space, run, tool
from proof_common import json_lines, private

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__  # noqa: E402
from nookku.record import loads  # noqa: E402

OUT = ROOT / "proofs" / "cluster"
SETUPS = ("plugin-claude-code",)
HARNESS = "claude-code"
# The pinned Koodam release (docs/getting-started-cluster.md#the-koodam-release-of-the-proof).
# The git tag is v0.5.0. The chart and the images have no "v".
KOODAM_TAG = "v0.5.0"
KOODAM_COMMIT = "a08e48c52915b01609d5e50ae660495232328432"
KOODAM = KOODAM_TAG.removeprefix("v")
CHART = "oci://ghcr.io/mohanraj00/charts/koodam"
CHART_DIGEST = "sha256:746593cfa80ee90bf4a4244d64aba072ce5cd1c8bc3ae720a0d2f1357e6032f2"
# The release workflow of the tag pushed these images. The digests are of the image indexes.
NOOKKU_IMAGE = (
    "ghcr.io/mohanraj00/koodam-nookku@"
    "sha256:be6c674c2699532e3d2b94a89a96b3ad7ea9b92ac0e694459987e1fe2e9d2a2e"
)
WORKSPACE_BASE = (
    "ghcr.io/mohanraj00/koodam-workspace:0.5.0@"
    "sha256:b4f428400d0bda4e8698b92bcc12111e1f25213ea6ce4c6a804c787ec566180a"
)
# The local image of the proof. kind loads it, so the pod never pulls it.
WORKSPACE_IMAGE = "nookku-proof/workspace-python:0.5.0"
WORKSPACE_DOCKERFILE = f"""FROM {WORKSPACE_BASE}
USER 0:0
RUN apt-get update \\
 && apt-get install -y --no-install-recommends python3 \\
 && rm -rf /var/lib/apt/lists/* \\
 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'
USER 1000:1000
"""
# The Nookku version of internal/evidence/nookku.pin at the Koodam tag.
PRESET_NOOKKU = "0.6.0"
PRESET_INIT = ("koodam-nookku-python", "koodam-nookku-files")
PRESET_DIR = "/koodam/nookku"
PRESET_BIN = "/koodam/bin"
# The Workspace image of v0.5.0 does not put PRESET_BIN on the PATH of a login shell.
PATH_ISSUE = "https://github.com/mohanraj00/koodam/issues/476"
PRESET_LAUNCHER = f"{PRESET_BIN}/nookku"
PLUGIN_DIR = f"{PRESET_DIR}/plugin"
# The data image has each file of plugins/nookku at the tag, but the test file.
PLUGIN_SKIP = {"hooks/register.test.ts"}
MODEL = "mock-1"
NS, WORKSPACE, POD = "dev-shop", "shop", "shop-0"
PROFILE = "nookku-proof"
# A fixed ClusterIP in the Service range of kind (10.96.0.0/16), as in the Koodam e2e test.
PROXY_IP = "10.96.100.100"
SERVICE = "http://toy-shop.shop.svc:8080/"
APP_IMAGE = "python:3.13-alpine"
UV_VERSION = "0.10.8"
HOME = "/home/dev"
PROJECT = f"{HOME}/toy-shop"
# The test folder of the preset, on the home PVC (Koodam docs/nookku-preset.md).
TESTS = f"{HOME}/nookku-tests"
# The launcher of the preset gives the pinned lib only to its own python3 process. nookku starts
# its bridge with `python3 -m nookku`, and that child does not get the lib. Thus the profile step
# of the guide exports PYTHONPATH, and each child of nookku, also the entry, gets it. This is the
# fix form of koodam#478. PYTHONSAFEPATH needs Python 3.11 or later (WORKSPACE_DOCKERFILE).
PRESET_LIB = f"{PRESET_DIR}/lib"
PYTHON_ENV = f"PYTHONPATH={PRESET_LIB} PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1"
LIB_ISSUE = "https://github.com/mohanraj00/koodam/issues/478"
ENTRY = ["python3", "service_entry.py"]
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
EVALUATION = [
    "--tools=Bash,Read,Grep,Glob,Write",
    "--allowedTools=Bash(nookku:*),Bash(cat:*),Bash(ls:*),Read,Grep,Glob,Write",
    f"--add-dir={TESTS}",
]
# The retries of a readiness check: 60 calls, 5 s apart.
TRIES, EVERY = 60, 5.0
STREAM = ["--output-format", "stream-json", "--verbose", f"--plugin-dir={PLUGIN_DIR}"]


def manifests(api: tuple[str, str], version: str) -> tuple[str, str]:
    """The chart values and the objects of docs/getting-started-cluster.md.

    `api` is the address and the port of the API server endpoint, for the NetworkPolicy of the
    proxy.
    """
    values = f"""
nookku:
  image: {NOOKKU_IMAGE}
gateway:
  mode: bundled
  masterKeySecret:
    name: koodam-gateway
    key: master-key
  bundled:
    mock:
      enabled: true
      modelName: {MODEL}
      response: "mock answer"
    postgres:
      persistence:
        enabled: false
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
apiVersion: core.koodam.dev/v1alpha1
kind: Workspace
metadata:
  name: {WORKSPACE}
  namespace: {NS}
spec:
  storage: 5Gi
  image: {WORKSPACE_IMAGE}
  gateway:
    model: {MODEL}
    budgetPerDay: "1"
  harnesses:
    - name: {HARNESS}
      version: {version}
      plugins: [nookku]
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

    def claude(
        self, prompt: str, extra: list[str] | None = None, *, login: bool = False
    ) -> list[Any]:
        """Run claude -p in the project. Return the stream-json events.

        With `login`, the prompt uses the login of the person in place of the gateway: the shell
        removes the gateway env before it starts claude.
        """
        args = " ".join(f"'{a}'" for a in [*STREAM, *(extra or [])])
        unset = "unset ${!ANTHROPIC_@} CLAUDE_CODE_SUBAGENT_MODEL && " if login else ""
        script = f'cd {PROJECT} && {unset}claude -p {args} "$(cat)"'
        return json_lines(self.sh(script, data=prompt.encode(), timeout=900))


def uv_binary() -> bytes:
    """The uv binary for Linux on the architecture of this machine, from its GitHub release.
    scripts/kind_testkey.py copies it into a Workspace that has no Python and no curl."""
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


def tag_plugin(version: str) -> dict[str, str]:
    """The SHA-256 of each file of plugins/nookku at the git tag of `version`, but the test file."""
    tag = f"v{version}"
    names = run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", tag, "plugins/nookku"])
    out = {}
    for name in names.decode().split("\n"):
        rel = name.removeprefix("plugins/nookku/")
        if name and rel not in PLUGIN_SKIP:
            blob = run(["git", "-C", str(ROOT), "show", f"{tag}:{name}"])
            out[rel] = hashlib.sha256(blob).hexdigest()
    return out


def pod_plugin(ws: Workspace) -> dict[str, str]:
    """The SHA-256 of each file of the plugin folder of the preset."""
    out = ws.sh(f"cd {PLUGIN_DIR} && find . -type f -print0 | sort -z | xargs -0 sha256sum")
    files = {}
    for line in out.strip().split("\n"):
        digest, name = line.split(maxsplit=1)
        files[name.removeprefix("./")] = digest
    return files


def build_workspace_image(c: Cluster, work: Path) -> str:
    """Build the Workspace image with python3 and load it into the kind node. Return its ID."""
    ctx = work / "workspace-image"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text(WORKSPACE_DOCKERFILE)
    run([c.docker, "build", "-q", "-t", WORKSPACE_IMAGE, str(ctx)], timeout=900)
    run([c.kind, "load", "docker-image", WORKSPACE_IMAGE, "--name", c.name], timeout=600)
    return run([c.docker, "image", "inspect", "-f", "{{.Id}}", WORKSPACE_IMAGE]).decode().strip()


def retry(what: str, check: Any, tries: int = TRIES, every: float = EVERY) -> Any:
    """Call `check` until it gives a true value. A host with a high load answers late, so a
    failed call or a false value waits `every` seconds, for `tries` calls in all."""
    error = ""
    for _ in range(tries):
        try:
            value = check()
        except SystemExit as e:
            value, error = None, str(e)
        if value:
            return value
        time.sleep(every)
    raise SystemExit(f"no {what} after {tries} tries, {every} s apart. {error}".strip())


def api_ready(c: Cluster) -> bool:
    return c.k("get", "--raw", "/readyz", timeout=30).decode().strip() == "ok"


def pod_ready(c: Cluster, ws: Workspace) -> bool:
    ready = "jsonpath={.status.conditions[?(@.type=='Ready')].status}"
    if c.k("get", "pod", POD, "-n", NS, "-o", ready, timeout=30).decode().strip() != "True":
        return False
    return ws.sh("echo ok", timeout=60).strip() == "ok"


def install(c: Cluster, version: str) -> dict[str, Any]:
    """Install Koodam, the toy shop and the Workspace (docs/getting-started-cluster.md, 1-3)."""
    retry("ready API server", lambda: api_ready(c))
    for ns in ("koodam-system", "shop", NS):
        c.k("create", "namespace", ns)
    key = f"sk-{secrets.token_hex(32)}".encode()
    secret = ["create", "secret", "generic", "koodam-gateway", "--from-file=master-key=/dev/stdin"]
    c.k("-n", "koodam-system", *secret, data=key)
    ep = "jsonpath={.items[0].endpoints[0].addresses[0]} {.items[0].ports[0].port}"
    args = ["get", "endpointslices", "-n", "default", "-l", "kubernetes.io/service-name=kubernetes"]
    api = c.k(*args, "-o", ep).decode().split()
    values, objects = manifests((api[0], api[1]), version)
    chart = f"{CHART}:{KOODAM}@{CHART_DIGEST}"
    helm = [tool("helm"), "--kube-context", f"kind-{c.name}", "install", "koodam", chart]
    helm += ["-n", "koodam-system", "-f", "-", "--wait", "--timeout", "10m"]
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
    retry("ready Workspace pod", lambda: pod_ready(c, Workspace(c)))
    return workspace_status(c)


def workspace_status(c: Cluster) -> dict[str, Any]:
    status = loads(c.k("get", "workspace", WORKSPACE, "-n", NS, "-o", "json"))["status"]
    conditions = {x["type"]: x["status"] for x in status.get("conditions", [])}
    return {"phase": status.get("phase"), "conditions": conditions}


def init_exits(c: Cluster) -> dict[str, int | None]:
    """The exit code of each init container of the preset in the Workspace pod."""
    pod = loads(c.k("get", "pod", POD, "-n", NS, "-o", "json"))
    states = {s["name"]: s.get("state", {}) for s in pod["status"].get("initContainerStatuses", [])}
    return {n: (states.get(n, {}).get("terminated") or {}).get("exitCode") for n in PRESET_INIT}


def free_disk(c: Cluster) -> int:
    """The free MB of the disk of the kind node. A full disk stops each container of Docker."""
    node = f"{c.name}-control-plane"
    out = run([c.docker, "exec", node, "df", "-m", "--output=avail", "/"]).decode().split()
    return int(out[-1])


def check_disk(c: Cluster) -> int:
    disk = free_disk(c)
    if disk < 1200:
        raise SystemExit(f"the Docker disk has {disk} MB free. The proof needs 1200 MB.")
    return disk


def preset(ws: Workspace) -> dict[str, Any]:
    """What the preset gives the pod (W1). A login shell of the pod does each read."""
    tests = ws.sh('printf %s "${NOOKKU_TESTS_DIR:-}"')
    plugin = pod_plugin(ws)
    expected = tag_plugin(PRESET_NOOKKU)
    return {
        "nookku_path": ws.sh("command -v nookku").strip(),
        "nookku_version": ws.sh("nookku --version").split()[-1],
        "python3": ws.sh("python3 --version").strip(),
        "python3_flags": ws.sh(
            "python3 -c 'import sys; print(int(sys.flags.safe_path), sys.flags.no_user_site)'"
        ).split(),
        "tests_dir": tests,
        "tests_dir_mode": ws.sh(f"stat -c %a {shlex.quote(tests)}").strip() if tests else None,
        "tests_dir_on_home": ws.sh(f"stat -c %m {shlex.quote(tests)}").strip() if tests else None,
        "files_read_only": ws.sh(
            f"touch {PRESET_DIR}/probe 2>/dev/null && echo no || echo yes"
        ).strip()
        == "yes",
        "plugin_files": len(plugin),
        "plugin_same_as_tag": plugin == expected,
        "plugin_differences": sorted(set(plugin.items()) ^ set(expected.items())),
    }


def setup_project(ws: Workspace) -> None:
    """Do the profile step and make the project (docs/getting-started-cluster.md, steps 4 and 6).

    The preset gives nookku, the plugin files and the test folder. The profile step puts the
    launcher on the PATH (koodam#476) and the pinned lib on PYTHONPATH (koodam#478). claude -p
    needs the terminal title env (docs/limits.md).
    """
    profile = (
        f"export PATH={PRESET_BIN}:$PATH\n"
        f"export {PYTHON_ENV}\n"
        "export CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1\n"
    )
    ws.sh(f"cat >> {HOME}/.profile", data=profile.encode())
    entry = ROOT / "examples" / "toy-shop" / "service_entry.py"
    ws.put(f"{PROJECT}/service_entry.py", entry.read_bytes())


def write_config(ws: Workspace, ignore: list[str]) -> None:
    """The config of the test. A proof opens no browser tab."""
    config = {
        "entry": ENTRY,
        "agent_url": SERVICE,
        "models": [],
        "page": False,
        "egress_ignore": ignore,
    }
    ws.put(f"{PROJECT}/.nookku/config.json", (json.dumps(config, indent=1) + "\n").encode())


def wait_for_login(c: Cluster, ws: Workspace, minutes: float, koodam: str) -> None:
    """Wait for the Secret and the login in the pod. Never show a Secret value."""
    context = shlex.quote(f"kind-{c.name}")
    command = f"{shlex.quote(koodam)} login {HARNESS} -n {NS} --context {context}"
    secret_keys = "go-template={{range $k, $v := .data}}{{$k}} {{end}}"
    print(
        "\nThe person step: make a token with claude setup-token, then store it with:\n"
        f"  {command}\nThe proof waits for {HARNESS} in koodam-login.\n",
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
                secret_keys,
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode == 0 and HARNESS in p.stdout.split():
            break
        if time.monotonic() > deadline:
            raise SystemExit(f"no login after {minutes} minutes. Run: {command}")
        time.sleep(10)
    # Kubernetes updates the mounted Secret. Koodam sets up the login at shell startup.
    deadline = time.monotonic() + 180
    ready = 'test -n "$CLAUDE_CODE_OAUTH_TOKEN"'
    while ws.sh(f"{ready} && echo yes || echo no").strip() != "yes":
        if time.monotonic() > deadline:
            raise SystemExit(f"the login shell of the Workspace has no {HARNESS} login")
        time.sleep(5)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """2 calls of the pod around the proxies of nookku, with bash only. The first call is plain
    HTTP to an external name: the DNS of the pod gives the address of the proxy, and the proxy
    writes an `http` span. The second call asks the proxy for a CONNECT to port 22, which it
    refuses with a `denied` span."""
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


def versions(c: Cluster, ws: Workspace, koodam: str, image_id: str) -> dict[str, str]:
    pod = loads(c.k("get", "pod", POD, "-n", NS, "-o", "json"))
    images = {s["name"]: s["imageID"] for s in pod["status"]["containerStatuses"]}
    inits = {s["name"]: s["imageID"] for s in pod["status"].get("initContainerStatuses", [])}
    controller = c.k(
        "get",
        "deploy",
        "-n",
        "koodam-system",
        "koodam-controller-manager",
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
    ).decode()
    server = loads(c.k("version", "-o", "json"))["serverVersion"]["gitVersion"]
    return {
        "nookku_checkout": __version__,
        "nookku_in_pod": ws.sh("nookku --version").split()[-1],
        HARNESS: ws.sh("claude --version").strip(),
        "koodam_tag": KOODAM_TAG,
        "koodam_commit": KOODAM_COMMIT,
        "koodam_chart": f"{KOODAM}@{CHART_DIGEST}",
        "koodam_controller": controller,
        "koodam_nookku_image": NOOKKU_IMAGE,
        "koodam_nookku_image_in_pod": inits.get("koodam-nookku-files", ""),
        "workspace_base": WORKSPACE_BASE,
        "workspace_image": f"{WORKSPACE_IMAGE} {image_id}",
        "workspace_image_in_pod": images.get("workspace", ""),
        "python_in_pod": ws.sh("python3 --version").strip(),
        "koodam_cli": run([koodam, "version"]).decode().strip(),
        "app_image": APP_IMAGE,
        "kind": run([c.kind, "version"]).decode().split()[1],
        "kubernetes": server,
        "helm": run([tool("helm"), "version", "--short"]).decode().strip(),
        "docker": run([c.docker, "version", "--format", "{{.Server.Version}}"]).decode().strip(),
        "os": platform.system(),
    }


def w1_pass(w1: dict[str, Any]) -> bool:
    p = w1["preset"]
    return (
        w1["phase"] == "Running"
        and w1["conditions"].get("TracedEgress") == "True"
        and w1["conditions"].get("Harnesses") == "True"
        and all(code == 0 for code in w1["init_exit_codes"].values())
        and p["nookku_path"] == PRESET_LAUNCHER
        and p["nookku_version"] == PRESET_NOOKKU
        and p["tests_dir"] == TESTS
        and p["tests_dir_mode"] == "700"
        and p["python3_flags"] == ["1", "1"]
        and p["tests_dir_on_home"] == HOME
        and p["files_read_only"] is True
        and p["plugin_same_as_tag"] is True
        and w1["plugin_paths"] == [PLUGIN_DIR]
        and w1["mcp_servers"] == ["plugin:nookku:nookku"]
    )


def prove(c: Cluster, koodam: str, work: Path, login_wait: float | None) -> dict[str, Any]:
    """Run the proof. With no login_wait, skip the login and the evaluation."""
    ws = Workspace(c)
    version = run(["claude", "--version"]).decode().split()[0]
    image_id = build_workspace_image(c, work)
    workspace = install(c, version)
    check_disk(c)
    w1: dict[str, Any] = {
        "phase": workspace["phase"],
        "conditions": workspace["conditions"],
        "init_exit_codes": init_exits(c),
        # Before the profile step of the guide: the PATH of a login shell of the image. The
        # Workspace image links only claude and codex into /usr/local/bin.
        "nookku_on_image_path": ws.sh("command -v nookku || true").strip(),
        "nookku_on_image_path_issue": PATH_ISSUE,
        # A child of nookku runs `python3 -m nookku`. Before the profile step, it fails.
        "python3_imports_nookku": ws.sh(
            "python3 -c 'import nookku' 2>/dev/null && echo yes || echo no"
        ).strip()
        == "yes",
        "python3_imports_nookku_issue": LIB_ISSUE,
    }
    setup_project(ws)
    w1["preset"] = preset(ws)
    write_config(ws, [])
    disk = check_disk(c)
    if login_wait is not None:
        wait_for_login(c, ws, login_wait, koodam)

    # The hosts of the harness: 1 prompt that the plugin blocks, before the test.
    before = time.time()
    init = init_event(ws.claude("nookku status"))
    plugins = [p for p in init.get("plugins", []) if isinstance(p, dict)]
    w1["plugins"] = sorted(str(p.get("source") or p.get("name")) for p in plugins)
    w1["plugin_paths"] = sorted(str(p.get("path")) for p in plugins if p.get("name") == "nookku")
    w1["mcp_servers"] = sorted(str(s.get("name")) for s in init.get("mcp_servers", []))
    w1["pass"] = w1_pass(w1)
    time.sleep(5)
    harness_spans = json_lines(spans(c, koodam, before, time.time()).decode())
    harness_hosts = sorted({s.get("host") or s.get("sni") or "" for s in harness_spans} - {""})
    write_config(ws, harness_hosts)
    answer = json.dumps(ANSWER).encode()
    ws.sh(f"cd {PROJECT} && nookku register", data=answer)

    # The test.
    ws.claude("nookku start")
    current = loads(ws.sh(f"cd {PROJECT} && nookku status --json"))["test"]
    if current is None:
        raise SystemExit("the prompt nookku start started no test")
    test, folder = current["test"], current["dir"]
    shown: list[dict[str, Any]] = []
    planted: dict[str, str] = {}
    for i, message in enumerate(MESSAGES):
        shown.append(
            next((e for e in reversed(ws.claude(message)) if e.get("type") == "result"), {})
        )
        if i == 1:
            planted = planted_calls(ws)
    ws.sh(f"cd {PROJECT} && nookku end")
    manifest = loads(ws.get(f"{folder}/manifest.json"))

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

    # The evaluation of the ended test, with the login of the person.
    end: dict[str, Any] = {}
    if login_wait is not None:
        evaluation = ws.claude("nookku end", EVALUATION, login=True)
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
    findings = loads(records["findings.json"])
    audit = loads(records["audit.json"])
    seal = loads(records["seal.json"])
    turns = [r for r in json_lines(records["relay.jsonl"].decode()) if r["type"] == "turn"]
    exchanges = [r for r in json_lines(records["tap.jsonl"].decode()) if r["type"] == "exchange"]
    calls = [r for r in json_lines(records["backend.jsonl"].decode()) if r["type"] == "call"]

    # W2
    checks = []
    for i, message in enumerate(MESSAGES):
        t = turns[i] if i < len(turns) else {}
        x = exchanges[i] if i < len(exchanges) else {}
        b = calls[i] if i < len(calls) else {}
        request = loads(b["request_body"]["text"]) if b else {}
        response = loads(b["response_body"]["text"]) if b else {}
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
    w2 = {
        "test_folder": folder,
        "turns": checks,
        "audit_exit": audit["exit"],
        "breaks": audit.get("breaks", []),
    }
    w2["pass"] = (
        Path(folder).parent == Path(TESTS)
        and len(turns) == len(exchanges) == len(calls) == len(MESSAGES)
        and all(
            m["message_same"]
            and m["reply_same"]
            and m["backend_status"] == 200
            and m["model_output_tokens"] == 0
            for m in checks
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
        "versions": versions(c, ws, koodam, image_id),
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
    parser.add_argument("--cluster", default="nookku-431", help="the name of the kind cluster")
    parser.add_argument("--keep", action="store_true", help="do not delete the cluster at the end")
    parser.add_argument("--koodam", default="koodam", help=f"the koodam CLI {KOODAM}")
    parser.add_argument("--login-wait", type=float, default=30, help="minutes for the login step")
    parser.add_argument(
        "--no-evaluation",
        action="store_true",
        help="skip the login and the evaluation, and write SETUP-no-evaluation.json",
    )
    args = parser.parse_args()
    koodam = tool(args.koodam) if "/" not in args.koodam else args.koodam
    if run([koodam, "version"]).decode().split()[-1] != KOODAM:
        raise SystemExit(f"the proof needs the koodam CLI {KOODAM}")
    c = Cluster(args.cluster)
    if c.exists():
        raise SystemExit(f"a kind cluster {c.name} exists. Give a new name with --cluster.")
    free_space(c)
    c.create()
    try:
        with tempfile.TemporaryDirectory(prefix="nookku-cluster-") as work:
            result = prove(c, koodam, Path(work), None if args.no_evaluation else args.login_wait)
    finally:
        if args.keep:
            delete = f"kind delete cluster --name {shlex.quote(c.name)}"
            print(
                f"The proof kept the kind cluster {c.name}. To delete it, run: {delete}",
                file=sys.stderr,
            )
        else:
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

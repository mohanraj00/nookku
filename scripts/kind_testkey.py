"""The seam test of a Koodam TestKey: a Nookku test on kind uses its own gateway key (#585).

The CI job `kind-testkey` runs this script. It needs Docker, kind, kubectl, helm and uv. It uses no
model: the bundled LiteLLM gateway of Koodam answers with its mock model.

1. The script makes a kind cluster and installs the Koodam chart of the pinned tag with the
   bundled gateway and its mock model. A Workspace permits TestKeys.
2. It installs the nookku wheel of this checkout in the Workspace pod. The project has the entry
   examples/toy-shop/gateway_agent.py and an egress answer with the OpenAI model API.
3. For each of 2 tests, it makes a TestKey, waits for the key files in the pod, and runs a
   scripted test with 3 messages (`nookku run`). Before the second test, it deletes the first
   TestKey, so that Koodam revokes it and frees the key slot.

The checks of each test:

K1  The manifest has `test_key` with the alias of the TestKey status and the base URL of the pod.
K2  Each reply has the mock answer of the gateway.
K3  The spend logs of the gateway have 1 call for each message with the alias of the test.
    `nookku trace --gateway` keeps the same count in `gateway.jsonl`.
K4  No file of the test folder and no file of the state folder holds the key. The check runs in
    the pod, so that the key never leaves the pod.

The 2 tests have different aliases. The script writes the result to OUT (default
proofs/testkey/kind.json). The result has no key value. It deletes its cluster at the end.

usage: python scripts/kind_testkey.py [--cluster NAME] [--keep] [--out PATH]
"""

from __future__ import annotations

import argparse
import base64
import json
import platform
import secrets
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from proof_cluster import uv_binary
from proof_cluster_tap import Cluster, run, tool

ROOT = Path(__file__).resolve().parent.parent
# The pinned Koodam tag (docs/getting-started-cluster.md#the-koodam-tag-of-the-ci-job). The git
# tag is v0.4.0-alpha.1. The chart and the images have no "v".
KOODAM_TAG = "v0.4.0-alpha.1"
KOODAM_COMMIT = "74920bed1d5c4575dbe3dc60c33ba6e07b73d44c"
KOODAM = KOODAM_TAG.removeprefix("v")
CHART = "oci://ghcr.io/mohanraj00/charts/koodam"
MODEL = "mock-1"
MOCK_ANSWER = "mock answer"
NS, WORKSPACE, PROFILE = "dev-shop", "shop", "nookku-testkey"
HOME = "/home/dev"
PROJECT = f"{HOME}/shop"
TESTS = f"{PROJECT}/.nookku/tests"
NOOKKU = f"{HOME}/.local/bin/nookku"
PYTHON = f"{HOME}/.local/share/uv/tools/nookku/bin/python3"
KEY_DIR = "/etc/koodam/test-gateway"
MESSAGES = ["Is the blue mug in stock?", "Do you ship to Pune?", "What is your refund policy?"]
ANSWER = {
    "model_apis": [{"api": "openai", "env": "OPENAI_BASE_URL", "url": None}],
    "backends": [],
    "mcp_servers": [],
    "databases": [],
    "other": [],
}
VALUES = f"""
gateway:
  mode: bundled
  masterKeySecret:
    name: koodam-gateway
    key: master-key
  bundled:
    mock:
      enabled: true
      modelName: {MODEL}
      response: "{MOCK_ANSWER}"
    postgres:
      persistence:
        enabled: false
"""
OBJECTS = f"""
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
  storage: 2Gi
  gateway:
    model: {MODEL}
    budgetPerDay: "1"
  testKeys:
    maxBudget: "1"
    maxTTL: 30m
"""


def testkey(name: str, test_id: str, uid: str) -> str:
    return f"""
apiVersion: core.koodam.dev/v1alpha1
kind: TestKey
metadata:
  name: {name}
  namespace: {NS}
spec:
  workspaceRef:
    name: {WORKSPACE}
    uid: {uid}
  testID: {test_id}
  budget: "0.5"
  ttl: 20m
"""


class Pod:
    """The commands of the script in the Workspace pod, as the user dev in a login shell."""

    def __init__(self, c: Cluster, name: str) -> None:
        self.c, self.name = c, name

    def sh(self, script: str, *, data: bytes | None = None, timeout: float = 300) -> str:
        stdin = ["-i"] if data is not None else []
        args = ["exec", *stdin, "-n", NS, self.name, "-c", "workspace", "--", "bash", "-lc"]
        return self.c.k(*args, script, data=data, timeout=timeout).decode()

    def put(self, path: str, data: bytes) -> None:
        q = shlex.quote(path)
        self.sh(f'mkdir -p "$(dirname {q})" && cat > {q}', data=data)

    def status(self, script: str) -> int:
        """The exit code of a script, with no output."""
        args = [self.c.kubectl, "--context", f"kind-{self.c.name}", "exec", "-n", NS, self.name]
        args += ["-c", "workspace", "--", "bash", "-lc", script]
        return subprocess.run(args, capture_output=True, timeout=120).returncode


def wait(what: str, check: Any, timeout: float, every: float = 3) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise SystemExit(f"timeout: {what}")
        time.sleep(every)


def install(c: Cluster) -> Pod:
    """Install Koodam with the bundled gateway, the Profile and the Workspace."""
    for ns in ("koodam-system", NS):
        c.k("create", "namespace", ns)
    master = f"sk-{secrets.token_hex(32)}".encode()
    secret = ["create", "secret", "generic", "koodam-gateway", "--from-file=master-key=/dev/stdin"]
    c.k("-n", "koodam-system", *secret, data=master)
    helm = [tool("helm"), "--kube-context", f"kind-{c.name}", "install", "koodam", CHART]
    helm += ["--version", KOODAM, "-n", "koodam-system", "-f", "-", "--wait", "--timeout", "10m"]
    run(helm, data=VALUES.encode(), timeout=900)
    c.k("label", "namespace", NS, f"koodam.dev/profile={PROFILE}")
    c.k("apply", "-f", "-", data=OBJECTS.encode())
    running = "--for=jsonpath={.status.phase}=Running"
    c.k("wait", f"workspace/{WORKSPACE}", "-n", NS, running, "--timeout=600s", timeout=620)
    name = c.k("get", "workspace", WORKSPACE, "-n", NS, "-o", "jsonpath={.status.pod}").decode()
    return Pod(c, name or f"{WORKSPACE}-0")


def setup_project(pod: Pod, work: Path) -> None:
    """Install uv and the nookku wheel of this checkout, and make the project."""
    pod.put(f"{HOME}/.local/bin/uv", uv_binary())
    pod.sh(f"chmod 0755 {HOME}/.local/bin/uv")
    run(["uv", "build", "--wheel", "--out-dir", str(work), str(ROOT)], timeout=300)
    wheel = next(work.glob("nookku-*.whl"))
    pod.put(f"{HOME}/dl/{wheel.name}", wheel.read_bytes())
    pod.sh(f"{HOME}/.local/bin/uv tool install --python 3.12 {HOME}/dl/{wheel.name}", timeout=600)
    agent = ROOT / "examples" / "toy-shop" / "gateway_agent.py"
    pod.put(f"{PROJECT}/gateway_agent.py", agent.read_bytes())
    config = {"entry": [PYTHON, "gateway_agent.py"], "models": [], "page": False}
    pod.put(f"{PROJECT}/.nookku/config.json", (json.dumps(config, indent=1) + "\n").encode())
    script = "".join(json.dumps({"said": m}) + "\n" for m in MESSAGES)
    pod.put(f"{PROJECT}/script.jsonl", script.encode())


def issue_key(c: Cluster, pod: Pod, name: str, test_id: str) -> dict[str, str]:
    """Make a TestKey, wait until Koodam issues it and the pod has its files. Return the status."""
    uid = c.k("get", "workspace", WORKSPACE, "-n", NS, "-o", "jsonpath={.metadata.uid}").decode()
    c.k("apply", "-f", "-", data=testkey(name, test_id, uid).encode())

    def issued() -> dict[str, Any] | None:
        tk = json.loads(c.k("get", "testkey", name, "-n", NS, "-o", "json"))
        status = tk.get("status", {})
        active = [x for x in status.get("conditions", []) if x["type"] == "Active"]
        return status if active and active[0].get("reason") == "Issued" else None

    status = wait(f"Koodam did not issue the TestKey {name}", issued, timeout=420)
    alias = status["keyAlias"]
    files = f'test -r {KEY_DIR}/key && test "$(cat {KEY_DIR}/alias)" = {shlex.quote(alias)}'
    wait(f"the pod has no key files of {alias}", lambda: pod.status(files) == 0, timeout=240)
    base_url = pod.sh(f"cat {KEY_DIR}/base-url").strip()
    return {"name": name, "test_id": test_id, "alias": alias, "base_url": base_url}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def spend_logs(c: Cluster, started: float) -> list[dict[str, Any]]:
    """The spend logs of the gateway from the day of the start, through a port forward."""
    master = c.k("get", "secret", "koodam-gateway", "-n", "koodam-system", "-o", "json")
    key = base64.b64decode(json.loads(master)["data"]["master-key"]).decode()
    svc = c.k("get", "svc", "-n", "koodam-system", "-o", "name").decode().split()
    service = next(s for s in svc if s.endswith("-litellm"))
    port = free_port()
    args = [c.kubectl, "--context", f"kind-{c.name}", "-n", "koodam-system", "port-forward"]
    forward = subprocess.Popen(
        [*args, service, f"{port}:4000"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        day = datetime.fromtimestamp(started, timezone.utc).date()
        query = urllib.parse.urlencode(
            {"start_date": str(day), "end_date": str(day + timedelta(days=1)), "summarize": "false"}
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/spend/logs?{query}",
            headers={"Authorization": f"Bearer {key}"},
        )

        def read() -> list[dict[str, Any]] | None:
            try:
                with urllib.request.urlopen(request, timeout=30) as r:
                    data = json.loads(r.read())
            except OSError:
                return None
            return data if isinstance(data, list) else data.get("data")

        return list(wait("the gateway gave no spend logs", read, timeout=60, every=2))
    finally:
        forward.terminate()
        forward.wait(10)


def run_test(c: Cluster, pod: Pod, key: dict[str, str], logs_wait: float = 90) -> dict[str, Any]:
    """Run one scripted test with the key of `key`, and check K1 to K4."""
    before = set(pod.sh(f"mkdir -p {TESTS} && ls -1 {TESTS}").split())
    pod.sh(f"cd {PROJECT} && {NOOKKU} register", data=json.dumps(ANSWER).encode())
    started = time.time()
    out = pod.sh(f"cd {PROJECT} && {NOOKKU} run --script script.jsonl --json --no-evaluate")
    result = json.loads(out.strip().splitlines()[-1])
    [test] = sorted(set(pod.sh(f"ls -1 {TESTS}").split()) - before)
    folder = f"{TESTS}/{test}"
    manifest = json.loads(pod.sh(f"cat {folder}/manifest.json"))
    relay = [json.loads(x) for x in pod.sh(f"cat {folder}/relay.jsonl").splitlines() if x]
    replies = [r.get("shown") for r in relay if r.get("type") == "turn"]
    want = len(MESSAGES)

    def gateway_calls() -> list[dict[str, Any]] | None:
        logs = spend_logs(c, started)
        mine = [g for g in logs if g.get("metadata", {}).get("user_api_key_alias") == key["alias"]]
        return mine if len(mine) >= want else None

    calls = wait("the gateway logs have no call of the test", gateway_calls, logs_wait, every=5)
    pod.put(f"{HOME}/dl/{test}-logs.json", json.dumps(calls).encode())
    alias = shlex.quote(key["alias"])
    trace = f"cd {PROJECT} && {NOOKKU} trace {test} --gateway {HOME}/dl/{test}-logs.json"
    pod.sh(f"{trace} --key-alias {alias}")
    rows = [json.loads(x) for x in pod.sh(f"cat {folder}/gateway.jsonl").splitlines() if x]
    kept = next(r["kept"] for r in rows if r["type"] == "source")
    # grep -F -f reads the key in the pod. Exit 1: no file has it.
    leak = f"grep -rlF -f {KEY_DIR}/key {folder} {PROJECT}/.nookku"
    no_key = pod.status(leak) == 1
    checks = {
        "K1": manifest.get("test_key")
        == {"alias": key["alias"], "base_url": key["base_url"], "model": MODEL},
        "K2": len(replies) == want and all(r == f"Toy shop: {MOCK_ANSWER}" for r in replies),
        "K3": len(calls) == want and kept == want,
        "K4": no_key,
    }
    return {
        "test": test,
        "alias": key["alias"],
        "test_id": key["test_id"],
        "manifest_test_key": manifest.get("test_key"),
        "run_pass": result.get("pass"),
        "replies": replies,
        "gateway_calls": len(calls),
        "gateway_kept": kept,
        "checks": checks,
    }


def prove(c: Cluster, work: Path) -> dict[str, Any]:
    pod = install(c)
    setup_project(pod, work)
    first = issue_key(c, pod, "shop-test-1", "shop-test-1")
    tests = [run_test(c, pod, first)]
    # Koodam revokes the first key after the delete, and then frees the slot.
    c.k("delete", "testkey", "shop-test-1", "-n", NS, "--wait=false")
    second = issue_key(c, pod, "shop-test-2", "shop-test-2")
    tests.append(run_test(c, pod, second))
    versions = {
        "koodam_tag": KOODAM_TAG,
        "koodam_commit": KOODAM_COMMIT,
        "nookku": pod.sh(f"{NOOKKU} --version").strip(),
        "kind": run([c.kind, "version"]).decode().split()[1],
        "kubectl": json.loads(run([c.kubectl, "version", "--client", "-o", "json"]))[
            "clientVersion"
        ]["gitVersion"],
        "helm": run([tool("helm"), "version", "--short"]).decode().strip(),
        "host": f"{platform.system()} {platform.machine()}",
    }
    distinct = tests[0]["alias"] != tests[1]["alias"]
    passed = distinct and all(all(t["checks"].values()) for t in tests)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "versions": versions,
        "tests": tests,
        "distinct_aliases": distinct,
        "pass": passed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cluster", default="nookku-testkey")
    ap.add_argument("--keep", action="store_true", help="keep the cluster at the end")
    ap.add_argument("--out", type=Path, default=ROOT / "proofs" / "testkey" / "kind.json")
    args = ap.parse_args()
    for name in ("helm", "uv"):
        tool(name)
    c = Cluster(args.cluster)
    if c.exists():
        raise SystemExit(f"the kind cluster {args.cluster} exists. Delete it first.")
    c.create()
    try:
        with tempfile.TemporaryDirectory() as work:
            result = prove(c, Path(work))
    finally:
        if not args.keep:
            c.delete()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

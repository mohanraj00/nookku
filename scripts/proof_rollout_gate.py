"""Proof that a rollout controller can use a gate result as its gate (SPEC.md section 7.15, #519).

The example examples/rollout-gate/ has 2 versions of a toy shop agent and a toy rollout
controller. Version 2 has a planted defect: each turn has a backend call with status 503. The
replies of the 2 versions are the same, so only the trace shows the defect. The gate file permits
0 `backend_error` findings. The proof uses no model.

For each version, the proof sets the entry of the project to the version, and runs
`nookku gate run` with the SHA-256 of the agent file as the subject. Then the controller reads
`result.json` and the copy of the seal, and gives its decision. The version that gets the traffic
changes only on `promote`.

The checks:

R1  Version 1: the gate passes, `nookku gate verify` exits with 0, and the controller promotes.
R2  Version 2: the gate fails with the check `limits` of the test, and the controller stops. The
    version with the traffic stays version 1.
R3  The result of version 1 with the subject of version 2: the controller stops.
R4  A copy of the gate folder of version 2 with `verdict` changed to `pass`: the controller
    stops, because the SHA-256 is not the value in the copy of the seal.

It writes the result to proofs/rollout-gate/results.json.

usage: python scripts/proof_rollout_gate.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__, discovery, stdio  # noqa: E402
from nookku.cli import main as nookku  # noqa: E402

EXAMPLE = ROOT / "examples" / "rollout-gate"
OUT = ROOT / "proofs" / "rollout-gate"
VERSIONS = ("agent_v1.py", "agent_v2.py")


class Stock(BaseHTTPRequestHandler):
    """The toy stock service. It knows the blue mug, and answers 503 for each other product."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        known = self.path.endswith("blue-mug")
        body = b'{"sku": "blue-mug", "left": 4}' if known else b'{"error": "no stock data"}'
        self.send_response_only(200 if known else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class StockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Stock)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def server_bind(self) -> None:
        stdio.bind(self)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


def controller() -> Any:
    """The module of the toy controller of the example."""
    spec = importlib.util.spec_from_file_location("controller", EXAMPLE / "controller.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(*args: str) -> tuple[int, dict[str, Any]]:
    """Run a nookku command with --json, and give its exit code and its JSON output."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = nookku([*args, "--json"])
    return code, json.loads(out.getvalue())


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-rollout-"))
    home = work / "home"
    os.environ["NOOKKU_HOME"] = str(home)
    project = work / "shop"
    shutil.copytree(EXAMPLE, project)
    (project / ".nookku").mkdir()
    stock = StockServer()
    decide = controller().decide
    live: str | None = None
    stages: list[dict[str, Any]] = []
    for version in VERSIONS:
        config = {"entry": [sys.executable, version], "models": [], "otel": False}
        (project / ".nookku" / "config.json").write_text(json.dumps(config))
        # The egress answer is for one entry, so each version registers it again.
        answer = discovery.make(backends=[{"name": "stock", "env": "STOCK_URL", "url": stock.url}])
        discovery.register(project, answer)
        subject = digest(project / version)
        code, ran = command(
            "gate", "run", str(project / "gate.json"), "--subject", subject, "--root", str(project)
        )
        if "gate" not in ran:
            sys.exit(f"the gate run of {version} did not start: {ran.get('error')}")
        gate = Path(ran["gate"])
        seal = home / "seals" / f"{gate.name}.json"
        # The file that a controller reads.
        result = json.loads((gate / "result.json").read_text())
        verify, _ = command("gate", "verify", str(gate), "--root", str(project))
        decision = decide(gate, seal, subject)
        if decision["action"] == "promote":
            live = version
        stages.append(
            {
                "version": version,
                "subject": subject,
                "gate_exit": code,
                "verify_exit": verify,
                "verdict": result["verdict"],
                "reasons": result["reasons"],
                "failed_checks": {
                    c["check"]: c["text"]
                    for t in result["tests"]
                    for c in t["checks"]
                    if c["verdict"] != "pass"
                },
                "decision": decision["action"],
                "decision_reason": decision["reason"],
                "live_after": live,
                "gate": gate,
                "seal": seal,
            }
        )
    stock.shutdown()
    good, bad = stages

    # R3: the result of version 1 does not permit version 2.
    other = decide(good["gate"], good["seal"], bad["subject"])

    # R4: a changed copy of the result of version 2.
    changed = work / "changed"
    shutil.copytree(bad["gate"], changed)
    data = json.loads((changed / "result.json").read_text())
    data.update(verdict="pass", reasons=[])
    (changed / "result.json").write_text(json.dumps(data))
    forged = decide(changed, bad["seal"], bad["subject"])

    checks = {
        "R1": good["gate_exit"] == 0 and good["verify_exit"] == 0 and good["decision"] == "promote",
        "R2": bad["gate_exit"] == 1
        and bad["reasons"] == [{"test": "stock-questions", "check": "limits"}]
        and bad["decision"] == "stop"
        and bad["live_after"] == VERSIONS[0],
        "R3": other["action"] == "stop" and other["reason"] == "the result is for another subject",
        "R4": forged["action"] == "stop" and "SHA-256" in forged["reason"],
    }
    for stage in stages:
        del stage["gate"], stage["seal"]
    report = {
        "proof": "rollout-gate",
        "date": date.today().isoformat(),
        "nookku": __version__,
        "python": sys.version.split()[0],
        "example": "examples/rollout-gate",
        "stages": stages,
        "other_subject": {"action": other["action"], "reason": other["reason"]},
        "changed_result": {"action": forged["action"], "reason": forged["reason"]},
        "checks": checks,
        "pass": all(checks.values()),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

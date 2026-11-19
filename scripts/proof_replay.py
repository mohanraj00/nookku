"""Proof that a replay with the recorded backends gives the same result each time (SPEC.md
section 7.10, "Recorded backends", #523).

A toy shop entry asks a toy stock service and a toy model API (Chat Completions) for each message.
The toy model puts a call counter in each answer, so a live run never gives the same replies 2
times. The stock service answers 1 call of each turn with status 503, so the base test has 1
`backend_error` finding in each turn. The proof:

1. records a base test of the toy shop script (examples/toy-shop/script.jsonl);
2. replays it 1 time live, as a control: the replies change;
3. stops the 2 toy servers, and replays the script 10 times with `--recorded --verdict`;
4. plants a change in the entry and replays it 1 more time: the verdict fails.

For each recorded replay, it compares the findings of the new test with the findings of the base
test: each finding (check, turn, detail) and each count, with no `replay_changed` and
`replay_miss`, which only a replay has. The result is the share of the 10 replays with no diff in
the findings, no changed turn, no miss and exit code 0. It needs no model, so its result is the
same on each run.

usage: python scripts/proof_replay.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__, bridge, discovery, script_save, seal, stdio  # noqa: E402
from nookku.cli import main as nookku  # noqa: E402

OUT = ROOT / "proofs" / "replay"
SCRIPT = ROOT / "examples" / "toy-shop" / "script.jsonl"
RUNS = 10
REPLAY_CLASSES = ("replay_changed", "replay_miss")

# The entry asks the stock service and the model for each message. With TOY_PREFIX set, the reply
# starts with that text: the planted change of step 4.
ENTRY = """
import json, os, sys, urllib.error, urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    url = os.environ["STOCK_URL"] + "/stock?sku="
    with urllib.request.urlopen(url + "blue-mug", timeout=10) as r:
        left = json.loads(r.read())["left"]
    try:
        urllib.request.urlopen(url + "gift-card", timeout=10).close()
    except urllib.error.HTTPError:
        pass  # The service has no gift card data: a backend_error finding in each turn.
    body = {"model": "toy", "messages": [{"role": "user", "content": request["message"]}]}
    call = urllib.request.Request(
        os.environ["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer toy-key"},
    )
    with urllib.request.urlopen(call, timeout=10) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"]
    reply = os.environ.get("TOY_PREFIX", "") + f"{text} We have {left} blue mugs."
    sys.stdout.write(json.dumps({"v": 1, "id": request["id"], "reply": reply}) + "\\n")
    sys.stdout.flush()
"""


class Toy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _answer(self, body: bytes, status: int = 200) -> None:
        self.send_response_only(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        server: ToyServer = self.server  # type: ignore[assignment]
        server.calls += 1
        if self.path.endswith("gift-card"):
            self._answer(b'{"error": "no stock data"}', 503)
        else:
            self._answer(json.dumps({"sku": "blue-mug", "left": 4}).encode())

    def do_POST(self) -> None:
        server: ToyServer = self.server  # type: ignore[assignment]
        server.calls += 1
        sent = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        said = sent["messages"][-1]["content"]
        text = f"Answer {server.calls} to {said!r}."
        choice = {"index": 0, "message": {"role": "assistant", "content": text}}
        answer = {"id": f"toy-{server.calls}", "object": "chat.completion", "choices": [choice]}
        self._answer(json.dumps(answer).encode())


class ToyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Toy)
        self.calls = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def server_bind(self) -> None:
        stdio.bind(self)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


def replay(project: Path, script: Path, *more: str) -> tuple[int, dict[str, Any]]:
    """Run `nookku replay` and give its exit code and its JSON result."""
    out = io.StringIO()
    args = ["replay", str(script), "--root", str(project), "--json", "--no-evaluate", *more]
    with contextlib.redirect_stdout(out):
        code = nookku(args)
    return code, json.loads(out.getvalue())


def findings(folder: Path) -> tuple[list[tuple[Any, Any, Any]], dict[str, Any]]:
    """The findings and the counts of a test, with no replay class."""
    data = json.loads((folder / "findings.json").read_text())
    rows = [
        (f["check"], f["turn"], f["detail"])
        for f in data["findings"]
        if f["check"] not in REPLAY_CLASSES
    ]
    counts = {k: v for k, v in data["counts"].items() if k not in REPLAY_CLASSES}
    return rows, counts


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-replay-"))
    os.environ["NOOKKU_HOME"] = str(work / "home")
    project = work / "shop"
    (project / ".nookku").mkdir(parents=True)
    (project / "entry.py").write_text(ENTRY)
    config = {"entry": [sys.executable, "entry.py"], "models": [], "otel": False}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    stock, model = ToyServer(), ToyServer()
    answer = discovery.make(
        backends=[{"name": "stock", "env": "STOCK_URL", "url": stock.url}],
        model_apis=[{"api": "openai", "env": "OPENAI_BASE_URL", "url": model.url + "/v1"}],
    )
    discovery.register(project, answer)

    # 1. The base test.
    passed, _, base = bridge.run_script(project, SCRIPT)
    script, _ = script_save.save(project, base.name)
    base_findings = findings(base)

    # 2. The control: a live replay. The toy model gives new answers, so each turn changes.
    code, live = replay(project, script, "--base", base.name)
    control = {"exit": code, "changed": live["diff"]["changed"]}

    # 3. The servers stop. A live call now fails, so a reply can come only from the record.
    calls_before = stock.calls + model.calls
    stock.stop()
    model.stop()
    runs = []
    for n in range(1, RUNS + 1):
        code, out = replay(project, script, "--base", base.name, "--recorded", "--verdict")
        folder = base.parent / out["diff"]["new"]["id"]
        data = json.loads((folder / "findings.json").read_text())
        rows, counts = findings(folder)
        manifest = json.loads((folder / "manifest.json").read_text())
        run = {
            "run": n,
            "test": folder.name,
            "exit": code,
            "changed": out["diff"]["changed"],
            "replay_changed": data["counts"].get("replay_changed"),
            "replay_miss": data["counts"].get("replay_miss"),
            "findings_same": (rows, counts) == base_findings,
            "base_files": sorted(manifest["replay"]["files"]),
            "seal_intact": seal.verify(folder)["intact"],
        }
        run["no_diff"] = (
            code == 0
            and run["changed"] == 0
            and run["replay_changed"] == 0
            and run["replay_miss"] == 0
            and run["findings_same"]
            and run["seal_intact"]
        )
        runs.append(run)

    # 4. The planted change: the entry adds a prefix to each reply. The verdict fails.
    os.environ["TOY_PREFIX"] = "Hello. "
    try:
        code, out = replay(project, script, "--base", base.name, "--recorded", "--verdict")
    finally:
        del os.environ["TOY_PREFIX"]
    folder = base.parent / out["diff"]["new"]["id"]
    counts = json.loads((folder / "findings.json").read_text())["counts"]
    planted = {
        "exit": code,
        "changed": out["diff"]["changed"],
        "replay_changed": counts.get("replay_changed"),
        "replay_miss": counts.get("replay_miss"),
    }

    turns = len(SCRIPT.read_text().splitlines())
    same = sum(r["no_diff"] for r in runs)
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
        },
        "script": str(SCRIPT.relative_to(ROOT)),
        "turns": turns,
        "base": {
            "test": base.name,
            "passed": passed,
            "findings": len(base_findings[0]),
            "server_calls": calls_before,
        },
        "control": control,
        "server_calls_after_stop": stock.calls + model.calls - calls_before,
        "runs": runs,
        "replays_with_no_diff": same,
        "share_with_no_diff": same / RUNS,
        "planted": planted,
    }
    result["pass"] = (
        passed
        and len(base_findings[0]) == turns
        and control["changed"] == turns
        and result["server_calls_after_stop"] == 0
        and same == RUNS
        and planted["exit"] == 1
        and planted["replay_changed"] == turns
        and planted["replay_miss"] == 0
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: result[k] for k in ("share_with_no_diff", "control", "planted", "pass")}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

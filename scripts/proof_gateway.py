"""Proof that the trace reads the model calls of an app from the logs of a LiteLLM gateway (SPEC.md
section 8.9).

A toy model API runs on a local port. LiteLLM runs in Docker, with Postgres for its spend logs,
and sends the calls of the model `toy` to the toy API. Thus no call costs money. The proof makes
2 keys with the alias forms of Koodam: `kd-<agent uid>` for the app and
`ws-<namespace>-<name>-<hash8>` for a Workspace. It writes a test folder with 2 turns, and the app
key makes these calls through LiteLLM:

- before the test: 1 call, outside the window;
- turn 1: a Chat Completions call that gives a tool call, and a call with the tool result;
- turn 2: an Anthropic Messages call, and a streamed Chat Completions call with the tag header.

The Workspace key also makes 1 call in turn 2. Then the proof runs `nookku trace --gateway` 2
times: with the URL of the gateway, and with a file of GET /spend/logs and a tag. It checks the
items of each turn, the counts of the skipped logs, the seal, the tags that LiteLLM keeps, and
that no key is in the test folder. It needs Docker and no model.

usage: python scripts/proof_gateway.py
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from nookku import __version__, gateway, seal  # noqa: E402

LITELLM_IMAGE = "ghcr.io/berriai/litellm-database:v1.104.2"
POSTGRES_IMAGE = "postgres:16-alpine"
UPSTREAM_KEY = "sk-toy-upstream-k3y"
OUT = ROOT / "proofs" / "gateway"
# The seconds between the start of a turn and the first call, and between the last call and the
# reply. A chosen value, not a measurement.
GAP = 0.5
STOCK_REPLY = "Yes, 3 teapot sets are in stock."
SHIP_REPLY = "Order 5120 ships today."
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}},
        },
    }
]


class ToyModel(BaseHTTPRequestHandler):
    """A toy OpenAI API. A Chat Completions request with tools and no tool result gets a tool
    call. Each other request gets a text: the stock after a tool result, else the order."""

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length") or 0)
        request = json.loads(self.rfile.read(size))
        if self.path.rstrip("/").endswith("/responses"):
            # LiteLLM 1.104.2 sends an Anthropic Messages call to an OpenAI model as a Responses
            # call.
            text = {"type": "output_text", "text": SHIP_REPLY, "annotations": []}
            out = {"type": "message", "id": "msg_toy", "status": "completed", "role": "assistant"}
            response = {
                "id": f"resp_{uuid.uuid4().hex}",
                "object": "response",
                "created_at": int(time.time()),
                "model": "toy",
                "status": "completed",
                "output": [{**out, "content": [text]}],
                "usage": {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
            }
            self._send(json.dumps(response).encode(), "application/json")
            return
        messages = request.get("messages") or []
        message: dict[str, Any] = {"role": "assistant", "content": SHIP_REPLY}
        finish = "stop"
        if any(m.get("role") == "tool" for m in messages):
            message["content"] = STOCK_REPLY
        elif request.get("tools"):
            call = {"name": "check_stock", "arguments": '{"sku": "teapot-set"}'}
            message = {"role": "assistant", "content": None}
            message["tool_calls"] = [{"id": "call_1", "type": "function", "function": call}]
            finish = "tool_calls"
        usage = {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}
        # LiteLLM keeps 1 spend log for each response id, so each response needs a new id.
        base = {"id": f"chatcmpl-{uuid.uuid4().hex}", "created": int(time.time()), "model": "toy"}
        if request.get("stream"):
            chunks = [
                {**base, "object": "chat.completion.chunk", "choices": [part]}
                for part in (
                    {"index": 0, "delta": {"role": "assistant", "content": message["content"]}},
                    {"index": 0, "delta": {}, "finish_reason": finish},
                )
            ]
            chunks.append(
                {**base, "object": "chat.completion.chunk", "choices": [], "usage": usage}
            )
            body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            self._send(body.encode(), "text/event-stream")
            return
        choice = {"index": 0, "message": message, "finish_reason": finish}
        whole = {**base, "object": "chat.completion", "choices": [choice], "usage": usage}
        self._send(json.dumps(whole).encode(), "application/json")

    def _send(self, body: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


def docker(*args: str, check: bool = True) -> str:
    done = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if check and done.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def call(url: str, key: str, path: str, body: dict[str, Any], **headers: str) -> bytes:
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for name, value in headers.items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data: bytes = resp.read()
            return data
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"POST {path} gave {e.code}: {e.read()[:500]!r}") from None


def get(url: str, key: str) -> Any:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def start_litellm(name: str, upstream: int, master: str) -> tuple[str, str]:
    """Start Postgres and LiteLLM in a new network. Return the gateway URL and the version."""
    config = {
        "model_list": [
            {
                "model_name": "toy",
                "litellm_params": {
                    "model": "openai/toy",
                    "api_base": f"http://host.docker.internal:{upstream}/v1",
                    "api_key": UPSTREAM_KEY,
                },
            }
        ],
        "general_settings": {"master_key": master, "store_prompts_in_spend_logs": True},
    }
    docker("network", "create", name)
    pg = ["-e", "POSTGRES_USER=toy", "-e", "POSTGRES_PASSWORD=toy-pw", "-e", "POSTGRES_DB=litellm"]
    docker("run", "-d", "--name", f"{name}-pg", "--network", name, *pg, POSTGRES_IMAGE)
    database = f"postgresql://toy:toy-pw@{name}-pg:5432/litellm"
    docker(
        "create",
        "--name",
        name,
        "--network",
        name,
        "--add-host",
        "host.docker.internal:host-gateway",
        "-p",
        "127.0.0.1::4000",
        "-e",
        f"DATABASE_URL={database}",
        LITELLM_IMAGE,
        "--config",
        "/app/proof.yaml",
        "--port",
        "4000",
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        json.dump(config, f)  # JSON is YAML
    docker("cp", f.name, f"{name}:/app/proof.yaml")
    os.unlink(f.name)
    docker("start", name)
    port = docker("port", name, "4000/tcp").splitlines()[0].rsplit(":", 1)[1]
    url = f"http://127.0.0.1:{port}"
    for _ in range(90):
        try:
            if get(f"{url}/health/readiness", master).get("db") == "connected":
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        raise RuntimeError(f"LiteLLM did not start: {docker('logs', name, check=False)[-2000:]}")
    python = "import importlib.metadata as m; print(m.version('litellm'))"
    version = docker("exec", name, "/app/.venv/bin/python", "-c", python)
    return url, version


def clock_skew(name: str) -> float:
    """The clock of the LiteLLM container minus the clock of this host, in seconds."""
    before = time.time()
    there = float(
        docker("exec", name, "/app/.venv/bin/python", "-c", "import time; print(time.time())")
    )
    after = time.time()
    return round(there - (before + after) / 2, 3)


def stop(name: str) -> None:
    """Remove only the containers and the network of this proof."""
    docker("rm", "-f", name, f"{name}-pg", check=False)
    docker("network", "rm", name, check=False)


def new_key(url: str, master: str, alias: str) -> str:
    body = {"key_alias": alias, "models": ["toy"]}
    return str(json.loads(call(url, master, "/key/generate", body))["key"])


def exchange(started: float, ts: float, text: str, reply: str) -> dict[str, Any]:
    def sha(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    row = {"v": "0.2", "type": "exchange", "ts": ts, "started": started, "input": text}
    return {
        **row,
        "input_sha256": sha(text),
        "status": 200,
        "reply": reply,
        "reply_sha256": sha(reply),
    }


def run_app(url: str, app_key: str, workspace_key: str) -> list[dict[str, Any]]:
    """The calls of the app in 2 turns. Return the 2 exchanges of the tap."""
    asked = [{"role": "user", "content": "Is the teapot set in stock?"}]
    tagged = {"metadata": {"tags": ["toy-shop"]}}
    started = time.time()
    call(
        url,
        app_key,
        "/v1/chat/completions",
        {"model": "toy", "messages": asked, "tools": TOOLS, **tagged},
    )
    call_1 = {"id": "call_1", "type": "function"}
    call_1["function"] = {"name": "check_stock", "arguments": '{"sku": "teapot-set"}'}
    answered = [
        *asked,
        {"role": "assistant", "content": None, "tool_calls": [call_1]},
        {"role": "tool", "tool_call_id": "call_1", "content": "3 left"},
    ]
    body = {"model": "toy", "messages": answered, "tools": TOOLS, **tagged}
    call(url, app_key, "/v1/chat/completions", body)
    time.sleep(GAP)
    first = exchange(started, time.time(), "Is the teapot set in stock?", STOCK_REPLY)
    time.sleep(0.5)
    started = time.time()
    time.sleep(GAP)
    where = [{"role": "user", "content": "Where is order 5120?"}]
    body = {"model": "toy", "max_tokens": 50, "messages": where}
    call(url, app_key, "/v1/messages", body)
    body = {"model": "toy", "stream": True, "messages": where}
    call(url, app_key, "/v1/chat/completions", body, **{"x-litellm-tags": "toy-shop"})
    body = {"model": "toy", "messages": [{"role": "user", "content": "A Workspace call."}]}
    call(url, workspace_key, "/v1/chat/completions", body)
    time.sleep(GAP)
    second = exchange(started, time.time(), "Where is order 5120?", SHIP_REPLY)
    return [first, second]


def wait_for_logs(url: str, master: str, count: int) -> list[Any]:
    today = date.today()
    query = f"start_date={today}&end_date={date.fromordinal(today.toordinal() + 1)}&summarize=false"
    for _ in range(60):
        logs = get(f"{url}/spend/logs?{query}", master)
        if isinstance(logs, list) and len(logs) >= count:
            return logs
        time.sleep(2)
    found = [(x.get("call_type"), x.get("status")) for x in logs if isinstance(x, dict)]
    raise RuntimeError(f"LiteLLM wrote fewer than {count} spend logs: {found}")


def trace(project: Path, test: str, *args: str, key: str = "") -> tuple[int, Any, str]:
    env = {**os.environ, gateway.KEY_VARIABLE: key, "NOOKKU_HOME": str(project / "home")}
    env["PYTHONPATH"] = str(ROOT / "src")
    command = [sys.executable, "-m", "nookku", "trace", test, "--root", str(project), "--json"]
    done = subprocess.run([*command, *args], capture_output=True, text=True, env=env, check=False)
    report = json.loads(done.stdout) if done.returncode == 0 else None
    return done.returncode, report, done.stderr


def items(folder: Path) -> list[dict[str, Any]]:
    lines = (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines if x]


def summary(found: list[dict[str, Any]]) -> list[list[Any]]:
    """Each item as [turn, kind, role or tool name, output]."""
    return [[it["turn"], it["kind"], it["role"] or it["name"], it["output"]] for it in found]


def main() -> int:
    name = f"nookku-proof-gateway-{os.getpid()}"
    master = f"sk-proof-{secrets.token_hex(12)}"
    server = ThreadingHTTPServer(("127.0.0.1", 0), ToyModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url, version = start_litellm(name, server.server_address[1], master)
        skew = clock_skew(name)
        agent = f"kd-{uuid.uuid4()}"
        workspace = f"ws-shop-toy-{secrets.token_hex(4)}"
        app_key, workspace_key = new_key(url, master, agent), new_key(url, master, workspace)
        early = {
            "model": "toy",
            "messages": [{"role": "user", "content": "Hello before the test."}],
        }
        call(url, app_key, "/v1/chat/completions", early)
        time.sleep(1)
        started = time.time()
        # A tester types the first message after the start. The gap is larger than the clock
        # skew of the container, so the first call is in the window on both clocks.
        time.sleep(GAP)
        exchanges = run_app(url, app_key, workspace_key)
        time.sleep(1)
        ended = time.time()
        logs = wait_for_logs(url, master, 6)
        with tempfile.TemporaryDirectory() as tmp:
            result = check(Path(tmp), url, master, agent, logs, exchanges, started, ended)
            folder = Path(tmp) / "project" / ".nookku"
            files = [p.read_bytes() for p in folder.rglob("*") if p.is_file()]
            keys = [master, app_key, workspace_key, UPSTREAM_KEY]
            # LiteLLM logs the SHA-256 of a key as its token.
            keys += [hashlib.sha256(k.encode()).hexdigest() for k in (app_key, workspace_key)]
            found = sum(f.count(k.encode()) for f in files for k in keys)
            result["checks"]["no_key_or_key_hash_in_the_test_folder"] = found == 0
    finally:
        stop(name)
        server.shutdown()
    result = {
        "date": date.today().isoformat(),
        "nookku": __version__,
        "harness": None,
        "litellm_image": LITELLM_IMAGE,
        "litellm_version": version,
        "clock_skew_seconds": skew,
        "aliases": {"agent": "kd-<uuid4>", "workspace": "ws-shop-toy-<hash8>"},
        **result,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["checks"], indent=1))
    return 0 if all(result["checks"].values()) else 1


def check(
    tmp: Path,
    url: str,
    master: str,
    agent: str,
    logs: list[Any],
    exchanges: list[dict[str, Any]],
    started: float,
    ended: float,
) -> dict[str, Any]:
    project = tmp / "project"
    test = "20261023-000000-gw01"
    folder = project / ".nookku" / "tests" / test
    folder.mkdir(parents=True)
    manifest = {"test": test, "started": started, "ended": ended, "model_sessions": []}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "tap.jsonl").write_text("".join(json.dumps(r) + "\n" for r in exchanges))
    seal.write(folder, project / "home")
    code, report, error = trace(project, test, "--gateway", url, "--key-alias", agent, key=master)
    if code != 0:
        raise RuntimeError(f"nookku trace --gateway <url> failed: {error}")
    by_url = summary(items(folder))
    head = json.loads((folder / gateway.FILE).read_text().splitlines()[0])
    intact = seal.verify(folder, project / "home")["intact"]
    tags = {str(t) for log in logs if isinstance(log, dict) for t in log.get("request_tags") or []}
    saved = tmp / "spend_logs.json"
    saved.write_text(json.dumps(logs))
    args = ["--gateway", str(saved), "--key-alias", agent, "--gateway-tag", "toy-shop"]
    code_file, report_file, error = trace(project, test, *args)
    if code_file != 0:
        raise RuntimeError(f"nookku trace --gateway <file> failed: {error}")
    head_file = json.loads((folder / gateway.FILE).read_text().splitlines()[0])
    expected = [
        [1, "message", "user", "Is the teapot set in stock?"],
        [1, "message", "assistant", None],
        [1, "tool_call", "check_stock", "3 left"],
        [1, "message", "assistant", STOCK_REPLY],
        [2, "message", "user", "Where is order 5120?"],
        [2, "message", "assistant", SHIP_REPLY],
        [2, "message", "user", "Where is order 5120?"],
        [2, "message", "assistant", SHIP_REPLY],
    ]
    checks = {
        "url_read_kept_the_app_calls_of_the_test": head["kept"] == 4,
        "url_read_skipped_the_workspace_and_the_early_call": head["skipped"]
        == {"other_key": 1, "outside_test": 1},
        "items_by_turn": by_url == expected,
        "no_findings": report["findings"] == [],
        "seal_intact_after_the_read": intact,
        "litellm_keeps_the_body_tag_and_the_header_tag": "toy-shop" in tags,
        "litellm_adds_user_agent_tags": any(t.startswith("User-Agent: ") for t in tags),
        "file_read_with_a_tag_kept_the_tagged_calls": head_file["kept"] == 3
        and head_file["skipped"].get("no_tag") == 1,
        "file_read_seal_intact": seal.verify(folder, project / "home")["intact"],
    }
    # The form of the response that LiteLLM stored for each call type of the app.
    forms: dict[str, list[str]] = {}
    for log in logs:
        response = log.get("response") if isinstance(log, dict) else None
        response = json.loads(response) if isinstance(response, str) else response
        if isinstance(response, dict) and response:
            form = next((k for k in ("choices", "output", "content") if k in response), "other")
            forms.setdefault(str(log.get("call_type")), [])
            if form not in forms[str(log.get("call_type"))]:
                forms[str(log.get("call_type"))].append(form)
    return {
        "logs": len(logs),
        "response_forms": forms,
        "url_read": {k: head[k] for k in ("kept", "skipped")},
        "file_read": {k: head_file[k] for k in ("kept", "skipped", "tag")},
        "items": by_url,
        "gateway": report["gateway"],
        "file_gateway": report_file["gateway"],
        "tags": sorted(t for t in tags if not t.startswith("User-Agent: ")),
        "checks": checks,
    }


if __name__ == "__main__":
    sys.exit(main())

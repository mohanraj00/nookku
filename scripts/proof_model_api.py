"""Proof that the model API proxy forwards a stream part by part and without change (SPEC.md section
7.7).

A toy model API runs on a local port, as the Anthropic and the OpenAI API of a test. A test runs an
entry that, for one message, makes 3 calls through the proxies: a streamed Anthropic call, a
streamed OpenAI call and an Anthropic call with a JSON answer. For a streamed call, the toy API
sends the first event and then waits until the entry says that it has that event. Thus the proof
fails if the proxy holds the stream until its end. The proof compares the SHA-256 of each body at 3
places: the entry, the toy API and model_api.jsonl. It checks the text in the record and that no
API key is in the record. It needs no model, so its result is the same on each run.

usage: python scripts/proof_model_api.py
"""

from __future__ import annotations

import hashlib
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

from verbatim_relay import __version__, bridge, model_api, seal, stdio  # noqa: E402

KEY = "sk-toy-proof-k3y"
SEEN: list[dict[str, object]] = []
RELEASE = threading.Event()


def sse(events: list[dict[str, object]], named: bool) -> list[bytes]:
    out = []
    for e in events:
        head = f"event: {e['type']}\n" if named else ""
        out.append(f"{head}data: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
    return out


def delta(text: str) -> dict[str, object]:
    part = {"type": "text_delta", "text": text}
    return {"type": "content_block_delta", "index": 0, "delta": part}


ANTHROPIC = sse(
    [
        {"type": "message_start", "message": {"model": "claude-toy"}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        *[delta(f"Teapot set {n}: 3 left at €80. ") for n in range(40)],
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ],
    named=True,
)
OPENAI = [
    *sse(
        [
            {"model": "gpt-toy", "choices": [{"index": 0, "delta": {"content": f"Mug {n}. "}}]}
            for n in range(40)
        ],
        named=False,
    ),
    b"data: [DONE]\n\n",
]
JSON = json.dumps(
    {
        "model": "claude-toy",
        "content": [{"type": "text", "text": "Order 5120 has 2 teapot sets."}],
        "stop_reason": "end_turn",
    }
).encode()

# The entry makes the 3 calls for one message, and replies with what it sent and got.
ENTRY = """
import hashlib, json, os, sys, urllib.request

def sha(b):
    return hashlib.sha256(b).hexdigest()

calls = [
    (os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", {"stream": True}),
    (os.environ["OPENAI_BASE_URL"] + "/chat/completions", {"stream": True}),
    (os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", {"stream": False}),
]
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = []
    for url, ask in calls:
        body = json.dumps({**ask, "messages": [{"role": "user", "content": request["message"]}]})
        req = urllib.request.Request(url, data=body.encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", os.environ["TOY_KEY"])
        with urllib.request.urlopen(req, timeout=30) as r:
            first = r.read1(65536)
            if ask["stream"]:
                urllib.request.urlopen(os.environ["TOY_RELEASE"], data=b"", timeout=5).read()
            got = first + r.read()
        out.append({"sent": sha(body.encode()), "got": sha(got), "first": len(first)})
    reply = {"v": 1, "id": request["id"], "reply": json.dumps(out)}
    sys.stdout.write(json.dumps(reply) + "\\n")
    sys.stdout.flush()
"""


class ToyApi(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/release":
            RELEASE.set()
            self.send_response_only(204)
            self.end_headers()
            return
        stream = json.loads(body).get("stream") is True
        parts = (OPENAI if "chat" in self.path else ANTHROPIC) if stream else [JSON]
        seen: dict[str, object] = {
            "path": self.path,
            "got": hashlib.sha256(body).hexdigest(),
            "sent": hashlib.sha256(b"".join(parts)).hexdigest(),
            "released_by_entry": None,
        }
        SEEN.append(seen)
        self.send_response_only(200)
        self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
        if not stream:
            self.send_header("Content-Length", str(len(JSON)))
            self.end_headers()
            self.wfile.write(JSON)
            return
        RELEASE.clear()
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for n, part in enumerate(parts):
            if n == 1:
                # The entry asks for the rest only when it has the first part.
                seen["released_by_entry"] = RELEASE.wait(10)
            self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")


class ToyServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        stdio.bind(self)


def main() -> int:
    toy = ToyServer(("127.0.0.1", 0), ToyApi)
    threading.Thread(target=toy.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{toy.server_address[1]}"
    os.environ.update(
        ANTHROPIC_BASE_URL=url,
        OPENAI_BASE_URL=f"{url}/v1",
        TOY_RELEASE=f"{url}/release",
        TOY_KEY=KEY,
    )
    project = Path(tempfile.mkdtemp(prefix="verbatim-relay-model-api-"))
    (project / ".verbatim-relay").mkdir()
    (project / "entry.py").write_text(ENTRY)
    config = {"entry": [sys.executable, "entry.py"], "models": [], "otel": False}
    (project / ".verbatim-relay" / "config.json").write_text(json.dumps(config))
    cur = bridge.start(project)
    try:
        shown, ok = bridge.send(cur, "How many teapot sets and mugs are left?")
    finally:
        bridge.end(project)
        toy.shutdown()
        toy.server_close()
    folder = Path(cur["dir"])
    entry = json.loads(shown) if ok else []
    record = (folder / model_api.FILE).read_text(encoding="utf-8")
    rows = [json.loads(x) for x in record.split("\n") if x]
    texts = [
        "".join(f"Teapot set {n}: 3 left at €80. " for n in range(40)),
        "".join(f"Mug {n}. " for n in range(40)),
        "Order 5120 has 2 teapot sets.",
    ]
    calls = []
    for i, (e, s, r) in enumerate(zip(entry, SEEN, rows, strict=True)):
        calls.append(
            {
                "call": i + 1,
                "api": r["api"],
                "path": s["path"],
                "stream": r["stream"],
                "response_size": r["response_body"]["size"],
                "request_same": e["sent"] == s["got"] == r["request_body"]["sha256"],
                "response_same": s["sent"] == e["got"] == r["response_body"]["sha256"],
                "first_part_before_the_end": s["released_by_entry"],
                "text_in_record": (r["result"] or {}).get("text") == texts[i],
            }
        )
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "verbatim-relay": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
        },
        "calls": calls,
        "key_in_record": KEY in record,
        "seal_intact": seal.verify(folder)["intact"],
    }
    result["pass"] = (
        len(calls) == 3
        and all(c["request_same"] and c["response_same"] and c["text_in_record"] for c in calls)
        and [c["first_part_before_the_end"] for c in calls] == [True, True, None]
        and not result["key_in_record"]
        and result["seal_intact"]
    )
    out = ROOT / "proofs" / "model-api" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

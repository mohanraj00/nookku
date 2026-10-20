"""Proof that the model API proxy forwards a stream part by part and without change (SPEC.md section
7.7).

A toy model API runs on a local port, as the Anthropic and the OpenAI API of a test. A test runs an
entry that, for one message, makes 5 calls through the proxies: a streamed Anthropic call, a
streamed OpenAI Chat Completions call, an Anthropic call with a JSON answer, a streamed OpenAI
Responses call and an OpenAI Decisions call with a JSON answer. Then the entry makes 2 more
Decisions calls: the call of the full toy shop app (`department` in
examples/toy-shop-full/services.py), and a call with a photo that makes the request body longer
than the record limit of 1 MiB. The record must keep each question of the 2 calls with its
instructions, and the audit must give no questions_lost finding. For a streamed call, the toy API
sends the first event and then waits until the entry says that it has that event. Thus the proof
fails if the proxy holds the stream until its end. The proof compares the SHA-256 of each body at 3
places: the entry, the toy API and model_api.jsonl. It checks the result in the record (the text,
or the answers of the decision) and that no API key is in the record. It needs no model, so its
result is the same on each run.

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

from nookku import __version__, bridge, discovery, model_api, seal, stdio  # noqa: E402

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
MESSAGE = {"id": "msg_1", "type": "message", "role": "assistant", "content": []}
SHIPS = "".join(f"Teapot {n} ships today. " for n in range(40))
RESPONSES = sse(
    [
        {"type": "response.created", "response": {"model": "gpt-toy", "status": "in_progress"}},
        {"type": "response.output_item.added", "output_index": 0, "item": MESSAGE},
        *[
            {
                "type": "response.output_text.delta",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": f"Teapot {n} ships today. ",
            }
            for n in range(40)
        ],
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {**MESSAGE, "content": [{"type": "output_text", "text": SHIPS}]},
        },
        {"type": "response.completed", "response": {"model": "gpt-toy", "status": "completed"}},
    ],
    named=True,
)
JSON = json.dumps(
    {
        "model": "claude-toy",
        "content": [{"type": "text", "text": "Order 5120 has 2 teapot sets."}],
        "stop_reason": "end_turn",
    }
).encode()
# The answer of the toy Decisions API, and the answers that the record must have for it.
DEPARTMENTS = [
    {"value": "billing", "probability": 0.95},
    {"value": "shipping", "probability": 0.03},
    {"value": "other", "probability": 0.02},
]
DECISION = json.dumps(
    {
        "model": "toy-decide",
        "answers": [
            {
                "type": "choice",
                "name": "department",
                "choice": "billing",
                "probabilities": DEPARTMENTS,
                "confidence": 0.93,
            },
            {"type": "predicate", "name": "urgent", "probability": 0.2},
            {"type": "refusal", "name": "mood"},
        ],
        "usage": {"input_tokens": 30, "output_tokens": 0, "total_tokens": 30},
    }
).encode()
ANSWERS = [
    {
        "type": "choice",
        "name": "department",
        "value": "billing",
        "probabilities": DEPARTMENTS,
        "confidence": 0.93,
    },
    {
        "type": "predicate",
        "name": "urgent",
        "value": 0.2,
        "probabilities": None,
        "confidence": None,
    },
    {"type": "refusal", "name": "mood", "value": None, "probabilities": None, "confidence": None},
]

# The question of the full toy shop app, as the record keeps it (SPEC.md section 7.7).
APP_QUESTION = {
    "name": "department",
    "type": "choice",
    "instructions": "Which department should handle this complaint?",
    "options": ["billing", "shipping", "other"],
}
# The questions of the entry, as the record keeps them.
ENTRY_QUESTIONS = [
    {
        "name": "department",
        "type": "choice",
        "instructions": "Which department?",
        "options": ["billing", "shipping", "other"],
    },
    {"name": "urgent", "type": "predicate", "instructions": "Is it urgent?", "options": None},
    {"name": "mood", "type": "choice", "instructions": "The mood?", "options": ["calm", "angry"]},
]
FULL = ROOT / "examples" / "toy-shop-full"

# The entry makes the 5 calls for one message, then the 2 Decisions calls, and replies with what
# it sent and got.
ENTRY = """
import base64, hashlib, json, os, sys, urllib.request
sys.path.insert(0, os.environ["TOY_FULL"])
import services

def sha(b):
    return hashlib.sha256(b).hexdigest()

calls = [
    (os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", {"stream": True}),
    (os.environ["OPENAI_BASE_URL"] + "/chat/completions", {"stream": True}),
    (os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", {"stream": False}),
    (os.environ["OPENAI_BASE_URL"] + "/responses", {"stream": True}),
    (os.environ["OPENAI_BASE_URL"] + "/decisions", {"stream": False}),
]
questions = [
    {"type": "choice", "name": "department", "instructions": "Which department?",
     "choices": [{"value": "billing"}, {"value": "shipping"}, {"value": "other"}]},
    {"type": "predicate", "name": "urgent", "instructions": "Is it urgent?"},
    {"type": "choice", "name": "mood", "instructions": "The mood?",
     "choices": [{"value": "calm"}, {"value": "angry"}]},
]
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = []
    for url, ask in calls:
        if url.endswith("/decisions"):
            body = json.dumps({"model": "toy-decide", "input": request["message"],
                               "questions": questions})
        else:
            body = json.dumps({**ask, "messages": [{"role": "user",
                                                    "content": request["message"]}]})
        req = urllib.request.Request(url, data=body.encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", os.environ["TOY_KEY"])
        with urllib.request.urlopen(req, timeout=30) as r:
            first = r.read1(65536)
            if ask["stream"]:
                urllib.request.urlopen(os.environ["TOY_RELEASE"], data=b"", timeout=5).read()
            got = first + r.read()
        out.append({"sent": sha(body.encode()), "got": sha(got), "first": len(first)})
    # The call of the full toy shop app hides its bodies. The toy API and the record compare them.
    out.append({"sent": None, "got": None, "department": services.department(request["message"])})
    photo = "data:image/png;base64," + base64.b64encode(b"teapot " * 160_000).decode()
    content = [{"type": "input_text", "text": request["message"]},
               {"type": "input_image", "image_url": photo}]
    body = json.dumps({"model": "toy-decide", "questions": questions,
                       "input": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(os.environ["OPENAI_BASE_URL"] + "/decisions", data=body)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        got = r.read()
    out.append({"sent": sha(body), "got": sha(got), "first": len(got)})
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
        answer = DECISION if self.path.endswith("/decisions") else JSON
        if not stream:
            parts = [answer]
        elif self.path.endswith("/responses"):
            parts = RESPONSES
        else:
            parts = OPENAI if "chat" in self.path else ANTHROPIC
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
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)
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
        TOY_FULL=str(FULL),
    )
    project = Path(tempfile.mkdtemp(prefix="nookku-model-api-"))
    (project / ".nookku").mkdir()
    (project / "entry.py").write_text(ENTRY)
    config = {"entry": [sys.executable, "entry.py"], "models": [], "otel": False}
    (project / ".nookku" / "config.json").write_text(json.dumps(config))
    discovery.register(project, discovery.make(model_apis=discovery.both_apis()))
    cur = bridge.start(project)
    try:
        shown, ok = bridge.send(cur, "I was charged twice. How many teapot sets are left?")
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
        SHIPS,
    ]
    # The text of each call, and the answers of the decisions.
    expect = [("text", t) for t in texts] + [("answers", ANSWERS)] * 3
    calls = []
    for i, (e, s, r) in enumerate(zip(entry, SEEN, rows, strict=True)):
        if e["sent"] is None:
            e = {**e, "sent": s["got"], "got": s["sent"]}
        calls.append(
            {
                "call": i + 1,
                "api": r["api"],
                "path": s["path"],
                "stream": r["stream"],
                "request_size": r["request_body"]["size"],
                "response_size": r["response_body"]["size"],
                "request_same": e["sent"] == s["got"] == r["request_body"]["sha256"],
                "response_same": s["sent"] == e["got"] == r["response_body"]["sha256"],
                "first_part_before_the_end": s["released_by_entry"],
                "result_in_record": (r["result"] or {}).get(expect[i][0]) == expect[i][1],
                "request_cut": r["request_body"]["cut"],
            }
        )
        if r["path"].endswith("/decisions"):
            calls[-1]["questions_in_record"] = r.get("questions")
            calls[-1]["questions_count"] = r.get("questions_count")
    findings = json.loads((folder / "findings.json").read_text())
    items = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    asked = [
        it["input"]["questions"]
        for it in items
        if it.get("harness") == "model_api" and it["role"] == "user" and it["input"]
    ]
    result = {
        "date": date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "python": sys.version.split()[0],
            "os": os.uname().sysname,
        },
        "calls": calls,
        "app_department": entry[5].get("department") if len(entry) > 5 else None,
        "questions_in_trace": asked,
        "questions_lost": findings["counts"]["questions_lost"],
        "key_in_record": KEY in record,
        "seal_intact": seal.verify(folder)["intact"],
    }
    decided = [c for c in calls if "questions_in_record" in c]
    result["pass"] = (
        len(calls) == 7
        and all(c["request_same"] and c["response_same"] and c["result_in_record"] for c in calls)
        and [c["first_part_before_the_end"] for c in calls] == [True, True, None, True] + [None] * 3
        and [c["request_cut"] for c in calls] == [False] * 6 + [True]
        and [c["questions_in_record"] for c in decided]
        == [ENTRY_QUESTIONS, [APP_QUESTION], ENTRY_QUESTIONS]
        and [c["questions_count"] for c in decided] == [3, 1, 3]
        and asked == [ENTRY_QUESTIONS, [APP_QUESTION], ENTRY_QUESTIONS]
        and result["app_department"] == "billing"
        and result["questions_lost"] == 0
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

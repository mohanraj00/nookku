"""A toy model that writes case notes and routes complaints. It speaks the OpenAI Chat Completions
API with a stream, and the OpenAI Decisions API.

    python examples/toy-shop-full/toy_model.py [port]

The app finds it in OPENAI_BASE_URL, for example http://127.0.0.1:9002/v1. Its answers are fixed:

- /chat/completions: "Case note: " and the first line of the customer's message.
- /decisions: for each `choice` question, the department of the first word of ROUTES in the
  input, if the question has it as a choice. Else the last choice. It refuses each other question.

It needs no API key and no network.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODEL = "toy-notes"


def note(messages: list[dict[str, Any]]) -> str:
    said = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    first = str(said).split("\n")[0].removeprefix("Customer: ").strip()
    return f"Case note: {first[:80]}"


# The words of a complaint and the department for them.
ROUTES = (
    ("charged", "billing"),
    ("refund", "billing"),
    ("invoice", "billing"),
    ("broken", "shipping"),
    ("arrived", "shipping"),
    ("delivery", "shipping"),
)


def _text(given: Any) -> str:
    """The text of the `input` of a Decisions API request."""
    if isinstance(given, str):
        return given
    parts = [p for m in given or [] for p in m.get("content") or [] if isinstance(p, dict)]
    return "\n".join(p.get("text") or "" for p in parts if p.get("type") == "input_text")


def decide(ask: dict[str, Any]) -> dict[str, Any]:
    """The answer of the Decisions API to a request: one answer for each question."""
    text = _text(ask.get("input")).lower()
    found = next((d for word, d in ROUTES if word in text), None)
    answers: list[dict[str, Any]] = []
    for q in ask.get("questions") or []:
        values = [c.get("value") for c in q.get("choices") or []]
        if q.get("type") != "choice" or not values:
            answers.append({"type": "refusal", "name": q.get("name")})
            continue
        chosen = found if found in values else values[-1]
        rest = round(0.1 / max(len(values) - 1, 1), 4)
        probabilities = [{"value": v, "probability": 0.9 if v == chosen else rest} for v in values]
        answers.append(
            {
                "type": "choice",
                "name": q.get("name"),
                "choice": chosen,
                "probabilities": probabilities,
                "confidence": 0.85,
            }
        )
    tokens = len(text.split())
    usage = {"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens}
    return {"model": MODEL, "answers": answers, "usage": usage}


class ToyModel(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int) -> None:
        super().__init__(("127.0.0.1", port), _Handler)

    def server_bind(self) -> None:
        # Bind without the name lookup of HTTPServer, which can take seconds on macOS.
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        ask = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if self.path.endswith("/decisions"):
            data = json.dumps(decide(ask), ensure_ascii=False).encode()
            self.send_response_only(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if not self.path.endswith("/chat/completions"):
            self.send_response_only(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        text = note(ask.get("messages") or [])
        words = text.split(" ")
        parts = [w + (" " if n < len(words) - 1 else "") for n, w in enumerate(words)]
        self.send_response_only(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        chunks = [{"role": "assistant", "content": ""}] + [{"content": p} for p in parts]
        for n, delta in enumerate(chunks):
            finish = "stop" if n == len(chunks) - 1 else None
            choice = {"index": 0, "delta": delta, "finish_reason": finish}
            event = {"id": "note-1", "model": MODEL, "choices": [choice]}
            self._chunk(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
        self._chunk(b"data: [DONE]\n\n")
        self.wfile.write(b"0\r\n\r\n")

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()


def main() -> None:
    server = ToyModel(int(sys.argv[1]) if len(sys.argv) > 1 else 9002)
    print(f"toy note model on {server.url}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()

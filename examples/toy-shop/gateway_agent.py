"""The toy shop chat agent that asks a model through a gateway. Standard library only.

It speaks the nookku agent contract (SPEC.md section 6). For each message, it sends 1 Chat
Completions call to OPENAI_BASE_URL with the key in OPENAI_API_KEY and the model in
NOOKKU_TEST_KEY_MODEL. In a test with the gateway key of a Koodam TestKey, the bridge sets these 3
variables (SPEC.md section 7.16). The reply is the text of the model with the prefix "Toy shop: ".

usage: python examples/toy-shop/gateway_agent.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def ask(text: str) -> str:
    body = {
        "model": os.environ["NOOKKU_TEST_KEY_MODEL"],
        "messages": [{"role": "user", "content": text}],
    }
    call = urllib.request.Request(
        os.environ["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(call, timeout=60) as r:
        data = json.loads(r.read())
    return str(data["choices"][0]["message"]["content"])


def main() -> None:
    print("toy shop gateway agent: ready", file=sys.stderr, flush=True)
    for raw in sys.stdin.buffer:
        request = json.loads(raw)
        out = {"v": 1, "id": request["id"], "reply": "Toy shop: " + ask(request["message"])}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

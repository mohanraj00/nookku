"""The toy shop chat agent for the quick start. Standard library only.

It speaks the nooku agent contract (SPEC.md section 6): one JSON line in on stdin for
each message, and one JSON line out on stdout with the reply. The tap starts it as the entry of a
test:

    nooku init claude-code --entry "python examples/toy-shop/agent.py"

usage: python examples/toy-shop/agent.py
"""

from __future__ import annotations

import json
import sys

REPLIES = {
    "refund": "Our refund policy:\n\n1. Damaged items: full refund.\n2. Change of mind: 30 days.\n",
    "ship": "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  ",
    "price": "| item | price |\n|---|---|\n| blue mug | € 8 |\n| teapot | € 24 |",
}
FALLBACK = "Which item is this about: the mug or the teapot?"


def answer(text: str) -> str:
    return next((r for k, r in REPLIES.items() if k in text.lower()), FALLBACK)


def main() -> None:
    print("toy shop agent: ready", file=sys.stderr, flush=True)
    for raw in sys.stdin.buffer:
        request = json.loads(raw)
        out = {"v": 1, "id": request["id"], "reply": answer(request["message"])}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

"""The toy shop chat agent for the quick start. Standard library only.

It speaks the nookku agent contract (SPEC.md section 6): one JSON line in on stdin for
each message, and one JSON line out on stdout with the reply. The tap starts it as the entry of a
test:

    nookku init claude-code --entry "python examples/toy-shop/agent.py"

In a test, it writes one line for each answer to app-state/answers.jsonl in the test folder,
so the seal covers its state (SPEC.md section 6.1).

usage: python examples/toy-shop/agent.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPLIES = {
    "refund": "Our refund policy:\n\n1. Damaged items: full refund.\n2. Change of mind: 30 days.\n",
    "ship": "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  ",
    "price": "| item | price |\n|---|---|\n| blue mug | € 8 |\n| teapot | € 24 |",
}
FALLBACK = "Which item is this about: the mug or the teapot?"


def answer(text: str) -> str:
    return next((r for k, r in REPLIES.items() if k in text.lower()), FALLBACK)


def topic(text: str) -> str:
    return next((k for k in REPLIES if k in text.lower()), "other")


def main() -> None:
    print("toy shop agent: ready", file=sys.stderr, flush=True)
    folder = os.environ.get("NOOKKU_TEST_DIR")
    log = Path(folder) / "app-state" / "answers.jsonl" if folder else None
    for raw in sys.stdin.buffer:
        request = json.loads(raw)
        out = {"v": 1, "id": request["id"], "reply": answer(request["message"])}
        if log is not None:
            log.parent.mkdir(exist_ok=True)
            row = {"test": os.environ.get("NOOKKU_TEST_ID"), "id": request["id"]}
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**row, "topic": topic(request["message"])}) + "\n")
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

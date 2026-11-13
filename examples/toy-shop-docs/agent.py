"""A toy shop support agent that retrieves a text from a local store and cites it. Standard
library only, and no model.

It speaks the nookku agent contract (SPEC.md section 6): one JSON line in on stdin for each
message, and one JSON line out on stdout. The reply is JSON text with the answer and the
locator of the section that gave it:

    {"answer": "We ship to Chennai and Pune.", "source": "store/shipping.md#cities"}

A locator is the path of a store file, `#`, and the heading of a `##` section of that file.

usage: python3 agent.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

STORE = Path(__file__).resolve().parent / "store"
# The words of a message that select a section of the store.
WORDS = {
    "store/returns.md#damaged": ("damaged", "broken"),
    "store/returns.md#change-of-mind": ("return", "refund"),
    "store/shipping.md#cities": ("ship to", "deliver to"),
    "store/shipping.md#time": ("how long", "when"),
}
FALLBACK = "I can answer questions about returns and shipping."


def section(locator: str) -> str:
    """The text of the `##` section that a locator names, without its heading."""
    file, heading = locator.split("#", 1)
    text = (STORE.parent / file).read_text(encoding="utf-8")
    part = text.split(f"\n## {heading}\n", 1)[1]
    return part.split("\n## ", 1)[0].strip()


def retrieve(message: str) -> str | None:
    """The locator of the first section whose words occur in the message, or None."""
    lower = message.lower()
    return next((loc for loc, words in WORDS.items() if any(w in lower for w in words)), None)


def reply(message: str) -> str:
    locator = retrieve(message)
    if locator is None:
        return json.dumps({"answer": FALLBACK, "source": None})
    return json.dumps({"answer": section(locator), "source": locator}, ensure_ascii=False)


def main() -> None:
    print("toy shop docs agent: ready", file=sys.stderr, flush=True)
    for raw in sys.stdin.buffer:
        request = json.loads(raw)
        out = {"v": 1, "id": request["id"], "reply": reply(request["message"])}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

"""The calls of the full toy shop to its stock service and to its case-note model.

The stock service URL is in STOCK_URL. The note model speaks the OpenAI Chat Completions API at
OPENAI_BASE_URL. It uses only the standard library.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

NOTE_MODEL = "toy-notes"


def _call(method: str, url: str, body: Any = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def stock_url() -> str:
    return os.environ.get("STOCK_URL", "http://127.0.0.1:9001").rstrip("/")


def stock(sku: str) -> dict[str, Any]:
    """The number of items left for a SKU."""
    status, data = _call("GET", f"{stock_url()}/stock?sku={quote(sku)}")
    return data if status == 200 else {"error": data.get("error", f"status {status}")}


def reserve(order: str, sku: str, qty: int) -> dict[str, Any]:
    """Reserve items for an order. A slow stock service can lose a request, so try 2 times."""
    answer: dict[str, Any] = {"error": "the stock service did not answer"}
    ask = {"order": order, "sku": sku, "qty": qty}
    for _ in range(2):
        status, data = _call("POST", f"{stock_url()}/reserve", ask)
        if status == 200:
            answer = data
        elif "reservation" not in answer:
            answer = {"error": data.get("error", f"status {status}")}
    return answer


def case_note(message: str, reply: str) -> str:
    """A one-line case note for the shop's log, from the note model, as a stream."""
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    ask = {
        "model": NOTE_MODEL,
        "stream": True,
        "messages": [
            {"role": "system", "content": "Write a one-line case note."},
            {"role": "user", "content": f"Customer: {message}\nAgent: {reply}"},
        ],
    }
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(ask).encode())
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {os.environ.get('OPENAI_API_KEY', 'toy')}")
    text = ""
    with urllib.request.urlopen(req, timeout=30) as r:
        for line in r.read().decode("utf-8").split("\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                for choice in json.loads(line[6:]).get("choices", []):
                    text += choice.get("delta", {}).get("content") or ""
    return text

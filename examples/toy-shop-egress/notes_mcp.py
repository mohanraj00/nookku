"""The notes MCP server of the toy shop, over stdio. Standard library only.

It has 1 tool, `add_note`, which adds a support note to an order. Each line on stdin is one
JSON-RPC message, and each response is one line on stdout. The notes go to notes.json in the
current folder, or to the file of TOY_NOTES.

usage: python3 notes_mcp.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import toy_mcp

TOOLS = [
    {
        "name": "add_note",
        "description": "Add a support note to a toy shop order.",
        "inputSchema": {
            "type": "object",
            "properties": {"order": {"type": "string"}, "text": {"type": "string"}},
            "required": ["order", "text"],
        },
    }
]


def notes_file() -> Path:
    return Path(os.environ.get("TOY_NOTES", "notes.json"))


def run(tool: str, args: dict[str, Any]) -> tuple[Any, bool]:
    order, text = str(args.get("order", "")), str(args.get("text", ""))
    if not order or not text:
        return "a note needs an order and a text", True
    path = notes_file()
    notes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    notes.append({"order": order, "text": text})
    path.write_text(json.dumps(notes, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"note": len(notes), "order": order}, False


def main() -> None:
    for raw in sys.stdin:
        if not raw.strip():
            continue
        try:
            request = json.loads(raw)
        except ValueError:
            request = None
        response = toy_mcp.answer(request, "notes", TOOLS, run)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

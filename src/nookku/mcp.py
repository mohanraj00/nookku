"""`nookku mcp`: an MCP server over stdio that gives the model read-only tools (ADR 0001).

The tools are `transcript` and `status`. A tool result has a size limit in each harness, and a
harness can truncate a long result with no sign except the changed text (#178, #194). Thus the
transcript comes in pages. Each page ends with a footer that gives the page number, the page
count, the character offsets and the SHA-256 of the page text. A page that lost its footer was
truncated.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from nookku import __version__, kit

PROTOCOL = "2025-06-18"
# The MCP versions that this server answers with the same messages. A client that asks for another
# version gets PROTOCOL, and can stop if it does not support it.
PROTOCOLS = {"2024-11-05", "2025-03-26", PROTOCOL}
# The page bound of a transcript page, as an estimate of tokens (estimate_tokens). The
# measurement and its method are in SPEC.md section 5.
PAGE_TOKENS = 2000

TOOLS = [
    {
        "name": "transcript",
        "description": (
            "Read-only. The exact test conversation: each message that the tester typed and the "
            "reply that the agent sent. Use it to evaluate the agent. The text comes in pages. "
            "Each page ends with a footer that names the next page. A page with no footer was "
            "cut by the harness: read it again with a smaller page_tokens. With trace: true, "
            "each turn of the test as the app got it, with the model items of the app."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1, "description": "Default: 1."},
                "trace": {"type": "boolean", "description": "Add the trace of the test."},
                "test": {"type": "string", "description": "A test id. Default: the latest."},
                "all": {"type": "boolean", "description": "All sessions of the record."},
                "page_tokens": {
                    "type": "integer",
                    "minimum": 100,
                    "description": f"The page bound. Default: {PAGE_TOKENS}.",
                },
            },
        },
    },
    {
        "name": "status",
        "description": "Read-only. Relay mode, and the test that runs, if one runs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def estimate_tokens(text: str) -> float:
    """A high estimate of the tokens of a text. Letters, digits and spaces of ASCII count 1/4,
    other ASCII characters 1/2, other characters of the BMP 1, and each other character 2.
    JSON and text that is not English have more tokens for each character than English."""
    total = 0.0
    for ch in text:
        code = ord(ch)
        if code < 128:
            total += 0.25 if ch.isalnum() or ch == " " else 0.5
        else:
            total += 1 if code < 0x10000 else 2
    return total


def pages(text: str, limit: float) -> list[tuple[int, int]]:
    """The start and end offset of each page. A page ends at a line end if it can. A line that is
    longer than the limit is cut between characters."""
    bounds: list[tuple[int, int]] = []
    start = pos = 0
    used = 0.0
    for line in text.splitlines(keepends=True):
        cost = estimate_tokens(line)
        if used + cost > limit and pos > start:
            bounds.append((start, pos))
            start, used = pos, 0.0
        if cost > limit:
            for ch in line:
                c = estimate_tokens(ch)
                if used + c > limit and pos > start:
                    bounds.append((start, pos))
                    start, used = pos, 0.0
                used += c
                pos += 1
            continue
        used += cost
        pos += len(line)
    if pos > start or not bounds:
        bounds.append((start, pos))
    return bounds


def _footer(number: int, count: int, start: int, end: int, length: int, digest: str) -> str:
    after = (
        f"Next: call transcript with page {number + 1}."
        if number < count
        else "This is the last page."
    )
    return (
        f"\n──── nookku: end of page {number} of {count}. Characters {start} to {end} of "
        f"{length}. SHA-256 of this page: {digest}. {after} ────\n"
    )


# The estimate of the longest footer. A page body gets the bound less this, so that the whole
# result, with its footer, stays in the bound.
FOOTER_TOKENS = estimate_tokens(_footer(10**9, 10**9 + 1, 10**12, 10**12, 10**12, "f" * 64))


def page(text: str, number: int, limit: float) -> tuple[str, dict[str, Any]]:
    """One page of a text with its footer, and the facts of the footer as data. The page with its
    footer has an estimate of at most `limit` tokens."""
    if limit <= FOOTER_TOKENS:
        raise ValueError(f"page_tokens must be more than {FOOTER_TOKENS:g}")
    bounds = pages(text, limit - FOOTER_TOKENS)
    if not 1 <= number <= len(bounds):
        raise ValueError(f"page {number} does not exist. The text has {len(bounds)} pages.")
    start, end = bounds[number - 1]
    body = text[start:end]
    digest = hashlib.sha256(body.encode("utf-8", errors="surrogatepass")).hexdigest()
    facts = {
        "page": number,
        "pages": len(bounds),
        "offset": start,
        "end": end,
        "length": len(text),
        "sha256": digest,
    }
    return body + _footer(number, len(bounds), start, end, len(text), digest), facts


def _transcript(root: Path, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    number = args.get("page", 1)
    limit = args.get("page_tokens", PAGE_TOKENS)
    if type(number) is not int or type(limit) is not int or limit < 100:
        raise ValueError("page must be an integer, and page_tokens an integer of 100 or more")
    test = args.get("test")
    if test is not None and (not isinstance(test, str) or "/" in test or test in ("", ".", "..")):
        raise ValueError("test must be the id of a test")
    text = kit.transcript_text(root, test, args.get("trace") is True, args.get("all") is True)
    return page(text, number, limit)


def _status(root: Path) -> str:
    return kit.status(root)


def call(root: Path, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """The result of one tool call. An error is a result with isError, so the model sees it."""
    try:
        if name == "transcript":
            text = _transcript(root, args)[0]
        elif name == "status":
            text = _status(root)
        else:
            raise ValueError(f"no tool '{name}'")
    except (ValueError, kit.TranscriptError) as e:
        return {"content": [{"type": "text", "text": f"nookku: {e}"}], "isError": True}
    # No structuredContent: with it, Codex 0.162.0 gave the model only that JSON and not the text
    # (proofs/mcp/transcript-pages.json). The footer of the text holds the same facts.
    return {"content": [{"type": "text", "text": text}]}


def answer(root: Path, message: Any) -> dict[str, Any] | None:
    """The JSON-RPC answer to one message, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "not a JSON-RPC 2.0 request")
    if "id" not in message:
        return None
    rid, method = message["id"], message.get("method")
    params = message.get("params")
    params = params if isinstance(params, dict) else {}
    if method == "initialize":
        version = params.get("protocolVersion")
        result: dict[str, Any] = {
            "protocolVersion": version if version in PROTOCOLS else PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nookku", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        args = params.get("arguments")
        result = call(root, str(params.get("name")), args if isinstance(args, dict) else {})
    else:
        return _error(rid, -32601, f"no method '{method}'")
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid: Any, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": text}}


def project_root() -> Path:
    """The project of the server: CLAUDE_PROJECT_DIR, else the working folder."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def serve(root: Path, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Answer each message of stdin, one JSON object on each line, until stdin ends."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = _error(None, -32700, "not JSON")
        else:
            reply = answer(root, message)
        if reply is not None:
            # ASCII JSON keeps each character, also one that UTF-8 cannot encode.
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    return 0

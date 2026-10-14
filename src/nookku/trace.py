"""The trace of SPEC.md section 8: read the app's model sessions, tie each item to a turn, check.

The readers take the copied session files of a test folder and its otel.jsonl. Each session reader
keeps the messages, the tool calls and the commands, and counts each other line type. A reader
never fails on a line that it does not know.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import backend, model_api, otlp
from .adapters import AdapterError, pick
from .config import MATCHES
from .record import VERSION, json_text, read_rows

# The version of a trace row. 0.3 adds the kinds span and log, and the field service.
TRACE_VERSION = "0.3"

# The versions that the conformance cases and proofs/trace/ cover.
TESTED = {"claude-code": ("2.1.286", "2.1.292"), "codex": ("0.160.0", "0.162.1")}
# Tools that the harness itself gives to the model. They are not tools of the app.
HARNESS_INTERNAL = {"claude-code": {"ToolSearch"}, "codex": set()}
CHECKS = (
    "agent_error",
    "repeated_reply",
    "reply_not_from_model",
    "tool_error",
    "command_failed",
    "span_error",
    "backend_error",
    "model_api_error",
    "model_error",
    "turn_without_model",
    "item_between_turns",
    "otel_tool_not_in_session",
    "server_not_from_app",
    "session_inferred",
    "version_untested",
)
# The default of the config key repeated_reply: the count of consecutive turns with the same
# reply that gives a repeated_reply finding (SPEC.md section 8.6).
REPEATED_REPLY = 2
# The config keys of the checks, with their defaults. The manifest records their values.
TRACE_KEYS: dict[str, Any] = {
    "repeated_reply": REPEATED_REPLY,
    "model_reply_field": "",
    "model_reply_match": "normalized",
}
# The harnesses of the items that hold a model output: the session files and the model APIs.
MODEL_HARNESSES = ("claude-code", "codex", "model_api")
# The length of the excerpt of a reply in the detail of a finding.
EXCERPT = 60
# The kinds that a model session file gives.
SESSION_KINDS = ("message", "tool_call", "command")
# The key of the tool use id of a Claude Code tool call. The check of section 8.6 uses it. The
# trace does not write it to trace.jsonl.
CALL_ID = "_tool_use_id"
# The marks at the end of a cut string of a tool_result event.
CUT_MARKS = ("...", "\u2026")
# Codex tools that run a command. The session file has a command item for them.
CODEX_COMMANDS = {"exec_command", "shell", "local_shell"}
# MCP servers that the MCP configuration of an app cannot give: the claude.ai connectors of the
# account and the servers of plugins. A session file names a server in one of 2 forms: as it
# is (`claude.ai Toy Mail`) or as the server part of a tool name (`claude_ai_Toy_Mail`).
NOT_FROM_APP = {
    "claude.ai ": "a claude.ai connector",
    "claude_ai_": "a claude.ai connector",
    "plugin:": "a plugin server",
    "plugin_": "a plugin server",
}


def _lines(path: Path, ignored: Counter[str]) -> Iterator[tuple[int, Any]]:
    """Each JSON line with its line number. Split on \\n only: a text can hold U+2028. Count each
    blank line as `blank` in `ignored`. The empty text after the last \\n is not a line."""
    raws = path.read_text(encoding="utf-8").split("\n")
    if raws[-1] == "":
        raws.pop()
    for n, raw in enumerate(raws, 1):
        if not raw.strip():
            ignored["blank"] += 1
            continue
        try:
            yield n, json.loads(raw)
        except ValueError:
            yield n, None


def _time(value: Any) -> float | None:
    """Unix seconds from an ISO 8601 time, for example 2026-10-06T08:17:35.859Z."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _item(harness: str, session: str, file: str, line: int, ts: float | None) -> dict[str, Any]:
    return {
        "v": TRACE_VERSION,
        "type": "model_item",
        "turn": None,
        "harness": harness,
        "session": session,
        "ts": ts,
        "kind": None,
        "role": None,
        "server": None,
        "name": None,
        "input": None,
        "output": None,
        "error": None,
        "exit_code": None,
        "harness_internal": False,
        "service": None,
        "source": {"file": file, "line": line},
    }


def _text(blocks: Any, kinds: tuple[str, ...]) -> str:
    """The text of the content blocks of the given types. Other blocks show as JSON."""
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    parts = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") in kinds and isinstance(b.get("text"), str):
            parts.append(b["text"])
        else:
            parts.append(json.dumps(b, ensure_ascii=False))
    return "\n".join(parts)


def _tool(harness: str, name: str) -> tuple[str | None, str]:
    """The MCP server and the tool name. Claude Code names an MCP tool mcp__<server>__<tool>."""
    if harness == "claude-code" and name.startswith("mcp__"):
        server, _, tool = name[5:].partition("__")
        if server and tool:
            return server, tool
    return None, name


def read_claude(path: Path, session: str, file: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a Claude Code session file. Return the items and the file info."""
    items: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    ignored: Counter[str] = Counter()
    version = None
    for n, row in _lines(path, ignored):
        if not isinstance(row, dict):
            ignored["invalid_json"] += 1
            continue
        kind = str(row.get("type"))
        version = version or (row.get("version") if isinstance(row.get("version"), str) else None)
        message = row.get("message")
        if kind not in ("user", "assistant") or not isinstance(message, dict) or row.get("isMeta"):
            if kind not in ("user", "assistant"):
                ignored[kind] += 1
            else:
                ignored[f"{kind}.meta" if row.get("isMeta") else f"{kind}.no_message"] += 1
            continue
        ts = _time(row.get("timestamp"))
        content = message.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for b in blocks:
            btype = b.get("type") if isinstance(b, dict) else None
            if btype == "text" and isinstance(b.get("text"), str):
                it = _item("claude-code", session, file, n, ts)
                it.update(kind="message", role=kind, output=b["text"])
                items.append(it)
            elif btype == "tool_use" and kind == "assistant":
                it = _item("claude-code", session, file, n, ts)
                server, name = _tool("claude-code", str(b.get("name")))
                it.update(kind="tool_call", server=server, name=name, input=b.get("input"))
                it["harness_internal"] = str(b.get("name")) in HARNESS_INTERNAL["claude-code"]
                it["error"] = "no tool_result in the session file"
                if isinstance(b.get("id"), str) and b["id"]:
                    it[CALL_ID] = b["id"]
                calls[str(b.get("id"))] = it
                items.append(it)
            elif btype == "tool_result" and kind == "user":
                call = calls.pop(str(b.get("tool_use_id")), None)
                if call is None:
                    ignored["tool_result.unmatched"] += 1
                    continue
                text = _text(b.get("content"), ("text",))
                call["source"]["result_line"] = n
                call["output"], call["error"] = (None, text) if b.get("is_error") else (text, None)
            else:
                ignored[f"{kind}.{btype}"] += 1
    return items, {"version": version, "ignored": dict(sorted(ignored.items()))}


def read_claude_servers(path: Path) -> list[dict[str, Any]]:
    """The MCP servers that a Claude Code session file names, each with its first line. An
    attachment line names the servers and the tools that the session loaded, and a tool call
    names the server of its tool."""
    found: dict[str, dict[str, Any]] = {}
    for n, row in _lines(path, Counter()):
        if not isinstance(row, dict):
            continue
        names: list[str] = []
        att = row.get("attachment")
        message = row.get("message")
        if row.get("type") == "attachment" and isinstance(att, dict):
            raw = att.get("addedNames")
            added: list[Any] = raw if isinstance(raw, list) else []
            if att.get("type") == "mcp_instructions_delta":
                names = [str(x) for x in added]
            elif att.get("type") == "deferred_tools_delta":
                names = [s for s in (_tool("claude-code", str(x))[0] for x in added) if s]
        elif row.get("type") == "assistant" and isinstance(message, dict):
            content = message.get("content")
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    server = _tool("claude-code", str(b.get("name")))[0]
                    names += [server] if server else []
        for name in names:
            found.setdefault(name, {"server": name, "line": n})
    return list(found.values())


def _codex_item(it: dict[str, Any], item: dict[str, Any]) -> bool:
    """Fill a trace item from a Codex item. Return False for an item type that the trace skips."""
    kind = item.get("type")
    if kind in ("UserMessage", "AgentMessage"):
        role = "user" if kind == "UserMessage" else "assistant"
        it.update(kind="message", role=role, output=_text(item.get("content"), ("text", "Text")))
    elif kind == "CommandExecution":
        code = item.get("exit_code")
        it.update(kind="command", input=item.get("command"), output=item.get("aggregated_output"))
        it["exit_code"] = code if isinstance(code, int) else None
        if it["exit_code"] is None and item.get("status") != "completed":
            it["error"] = f"status {item.get('status')}"
    elif kind == "DynamicToolCall":
        text = _text(item.get("content_items"), ("inputText",))
        it.update(kind="tool_call", server=item.get("namespace"), name=item.get("tool"))
        it["input"] = item.get("arguments")
        it["output"], it["error"] = (text, None) if item.get("success") else (None, text)
    elif kind == "McpToolCall":
        it.update(kind="tool_call", server=item.get("server"), name=item.get("tool"))
        it["input"] = item.get("arguments")
        result: dict[str, Any] = item["result"] if isinstance(item.get("result"), dict) else {}
        out = _text(result.get("content"), ("text",)) if result else None
        error = item.get("error")
        if isinstance(error, dict):
            it["error"] = str(error.get("message"))
        elif result.get("isError"):
            it["error"] = out
        else:
            it["output"] = out
    else:
        return False
    it["harness_internal"] = it["name"] in HARNESS_INTERNAL["codex"]
    return True


def read_codex(path: Path, session: str, file: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a Codex rollout file. Return the items and the file info."""
    items: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    version = None
    for n, row in _lines(path, ignored):
        if not isinstance(row, dict):
            ignored["invalid_json"] += 1
            continue
        payload: dict[str, Any] = row["payload"] if isinstance(row.get("payload"), dict) else {}
        ptype = payload.get("type")
        if row.get("type") == "session_meta" and isinstance(payload.get("cli_version"), str):
            version = payload["cli_version"]
        item = payload.get("item")
        if (
            row.get("type") != "event_msg"
            or ptype != "item_completed"
            or not isinstance(item, dict)
        ):
            ignored[f"{row.get('type')}.{ptype}" if ptype else str(row.get("type"))] += 1
            continue
        at = item.get("completed_at_ms", payload.get("completed_at_ms"))
        ts = at / 1000 if isinstance(at, (int, float)) else _time(row.get("timestamp"))
        it = _item("codex", session, file, n, ts)
        if _codex_item(it, item):
            items.append(it)
        else:
            ignored[f"item_completed.{item.get('type')}"] += 1
    return items, {"version": version, "ignored": dict(sorted(ignored.items()))}


def _codex_error_class(info: Any) -> str | None:
    """The class of a Codex model error from its codex_error_info: a string, or an object with 1
    key, for example {"http_connection_failed": {"http_status_code": 503}}. The key is the class.
    An http_status_code in the value of the key adds the status."""
    if isinstance(info, str):
        return info
    if not isinstance(info, dict) or len(info) != 1:
        return None
    kind, value = next(iter(info.items()))
    code = value.get("http_status_code") if isinstance(value, dict) else None
    if isinstance(code, int) and not isinstance(code, bool):
        return f"{kind} (status {code})"
    return str(kind)


def read_codex_errors(path: Path) -> list[dict[str, Any]]:
    """The model errors of a Codex rollout file: each task_complete event with an error, with
    its line, its time and its detail. The event ends a turn of the harness."""
    found: list[dict[str, Any]] = []
    for n, row in _lines(path, Counter()):
        if not isinstance(row, dict) or row.get("type") != "event_msg":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "task_complete":
            continue
        error = payload.get("error")
        if error is None:
            continue
        if isinstance(error, str):
            detail = error
        elif isinstance(error, dict) and isinstance(error.get("message"), str):
            kind = _codex_error_class(error.get("codex_error_info"))
            detail = f"{kind}: {error['message']}" if kind else error["message"]
        else:
            detail = json_text(error)
        found.append({"line": n, "ts": _time(row.get("timestamp")), "detail": detail})
    return found


READERS = {"claude-code": read_claude, "codex": read_codex}


def _json(text: Any) -> Any:
    """A JSON text of an attribute as its value, or None."""
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def read_otel(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The span and log rows of otel.jsonl (SPEC.md section 8.4)."""
    items: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    rows = 0
    for n, row in _lines(path, ignored):
        rows += 1
        kind = row.get("type") if isinstance(row, dict) else None
        if kind not in ("span", "log"):
            ignored[str(kind) if isinstance(row, dict) else "invalid_json"] += 1
            continue
        service = row.get("service")
        harness = otlp.harness_of(service) or "otel"
        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        if kind == "span":
            it = _item(harness, str(row.get("trace_id") or ""), otlp.FILE, n, row.get("start"))
            status = row.get("status") or {}
            error = None
            if status.get("code") == 2:
                raised = [
                    e.get("attributes", {}).get("exception.message")
                    for e in row.get("events") or []
                    if e.get("name") == "exception"
                ]
                error = status.get("message") or next((x for x in raised if x), "status error")
            it.update(kind="span", name=row.get("name"), input=attrs, error=error)
        else:
            session = attrs.get("session.id") or attrs.get("conversation.id") or row.get("trace_id")
            it = _item(harness, str(session or ""), otlp.FILE, n, row.get("time"))
            name = row.get("event_name")
            body = row.get("body")
            if body == name or body is None:
                output = None
            else:
                output = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            name = otlp.short(name) if harness != "otel" else name
            it.update(kind="log", name=name, input=attrs, output=output)
            if name == "tool_result" and str(attrs.get("success", "true")).lower() == "false":
                it["error"] = str(attrs.get("error") or "the event has success: false")
        it["service"] = service
        items.append(it)
    return items, {"file": otlp.FILE, "rows": rows, "items": len(items), "ignored": dict(ignored)}


def _body(body: Any) -> str | None:
    """The text of a body in backend.jsonl, or a note for a binary body."""
    if not isinstance(body, dict) or not body.get("size"):
        return None
    if isinstance(body.get("text"), str):
        return str(body["text"]) + (
            "\n(cut: the record holds the first 1 MiB)" if body.get("cut") else ""
        )
    return f"({body['size']} bytes that are not UTF-8: base64 in backend.jsonl)"


def read_backend(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The call rows of backend.jsonl (SPEC.md section 8.4)."""
    items: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    rows = 0
    for n, row in _lines(path, ignored):
        rows += 1
        if not isinstance(row, dict) or row.get("type") != "call":
            ignored[str(row.get("type")) if isinstance(row, dict) else "invalid_json"] += 1
            continue
        it = _item("backend", str(row.get("backend") or ""), backend.FILE, n, row.get("started"))
        call = {
            "query": row.get("query"),
            "headers": row.get("request_headers"),
            "body": _body(row.get("request_body")),
        }
        it.update(
            kind="http",
            name=f"{row.get('method')} {row.get('path')}",
            input=call,
            output=_body(row.get("response_body")),
            error=row.get("error"),
            exit_code=row.get("status"),
        )
        items.append(it)
    return items, {
        "file": backend.FILE,
        "rows": rows,
        "items": len(items),
        "ignored": dict(ignored),
    }


def _request(row: dict[str, Any]) -> dict[str, Any]:
    """The JSON of the request body of a model_api.jsonl row, or {} if the record has no JSON."""
    body = row.get("request_body")
    text = body.get("text") if isinstance(body, dict) and not body.get("cut") else None
    data = _json(text) if isinstance(text, str) else None
    return data if isinstance(data, dict) else {}


def _said(form: str, request: dict[str, Any]) -> str | None:
    """The text of the last message of a request, if it is a user message with text. For the
    Responses API, the messages are the `input` items, and a string `input` is a user message."""
    kinds: tuple[str, ...] = ("text",)
    messages = request.get("messages")
    if form == "responses":
        messages, kinds = request.get("input"), ("input_text",)
        if isinstance(messages, str):
            return messages
    last = messages[-1] if isinstance(messages, list) and messages else None
    if not isinstance(last, dict) or last.get("role") != "user":
        return None
    if form == "responses" and last.get("type", "message") != "message":
        return None
    content = last.get("content")
    if isinstance(content, str):
        return content
    parts = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    texts = [str(b.get("text")) for b in parts if b.get("type") in kinds and "text" in b]
    return "\n".join(texts) if texts else None


def _results(form: str, request: dict[str, Any]) -> dict[str, tuple[str, bool]]:
    """The tool results in the messages of a request: (text, is_error) by tool call id."""
    out: dict[str, tuple[str, bool]] = {}
    if form == "responses":
        items = request.get("input")
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict) or it.get("type") != "function_call_output":
                continue
            if it.get("call_id"):
                text = _text(it.get("output"), ("input_text",))
                out.setdefault(str(it["call_id"]), (text, False))
        return out
    messages = request.get("messages")
    for m in messages if isinstance(messages, list) else []:
        if not isinstance(m, dict):
            continue
        if form == "chat" and m.get("role") == "tool" and m.get("tool_call_id"):
            out.setdefault(str(m["tool_call_id"]), (_text(m.get("content"), ("text",)), False))
        content = m.get("content") if form == "messages" else None
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                text = _text(b.get("content"), ("text",))
                out.setdefault(str(b["tool_use_id"]), (text, b.get("is_error") is True))
    return out


# The options of a question of the Decisions API: the list in the question, and the field of each
# option in the list.
DECISION_OPTIONS = {"choice": ("choices", "value"), "score": ("levels", "label")}


def _image(url: Any) -> dict[str, Any]:
    """The media type, the size and the SHA-256 of an inline image (a base64 data URL). The trace
    keeps no image data. An image that is not base64 data gives no size and no SHA-256."""
    out: dict[str, Any] = {"media_type": None, "size": None, "sha256": None}
    if not isinstance(url, str) or not url.startswith("data:") or "," not in url:
        return out
    head, data = url[5:].split(",", 1)
    params = head.split(";")
    out["media_type"] = params[0] or None
    if "base64" in params[1:]:
        try:
            raw = base64.b64decode("".join(data.split()), validate=True)
        except ValueError:  # binascii.Error, or a character that is not ASCII
            return out
        out.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return out


def _question(question: dict[str, Any]) -> dict[str, Any]:
    """The name, the type and the options of a question of the Decisions API."""
    kind = question.get("type")
    spec = DECISION_OPTIONS.get(kind) if isinstance(kind, str) else None
    given = question.get(spec[0]) if spec else None
    options = None
    if spec and isinstance(given, list):
        options = [o.get(spec[1]) for o in given if isinstance(o, dict)]
    return {"name": question.get("name"), "type": kind, "options": options}


def _decision_request(request: dict[str, Any]) -> tuple[str | None, dict[str, Any]] | None:
    """The user text, the questions and the images of a request to the Decisions API, or None if
    the request has none of them. The text is a string `input`, or the joined text of the user
    messages of `input`."""
    given = request.get("input")
    texts = [given] if isinstance(given, str) else []
    images = []
    for m in given if isinstance(given, list) else []:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            texts.append(content)
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "input_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif part.get("type") == "input_image":
                images.append(_image(part.get("image_url")))
    asked = request.get("questions")
    questions = [
        _question(q) for q in (asked if isinstance(asked, list) else []) if isinstance(q, dict)
    ]
    if not (texts or images or questions):
        return None
    return ("\n".join(texts) if texts else None), {"questions": questions, "images": images}


def read_model_api(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The call rows of model_api.jsonl (SPEC.md section 8.4). The calls of a harness are only
    counted, because its session file has them."""
    items: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    harness_calls: Counter[str] = Counter()
    other_calls = 0
    calls: list[tuple[int, dict[str, Any], str, dict[str, Any]]] = []
    rows = 0
    for n, row in _lines(path, ignored):
        rows += 1
        if not isinstance(row, dict) or row.get("type") != "call":
            ignored[str(row.get("type")) if isinstance(row, dict) else "invalid_json"] += 1
            continue
        form = model_api.call_format(str(row.get("api")), str(row.get("path")))
        if row.get("harness"):
            harness_calls[str(row["harness"])] += 1
        elif form is None:
            other_calls += 1
        else:
            calls.append((n, row, form, _request(row)))
    for i, (n, row, form, request) in enumerate(calls):
        api = str(row.get("api") or "")
        said, asked = _said(form, request), None
        if form == "decisions":
            said, asked = _decision_request(request) or (None, None)
        if said is not None or asked is not None:
            it = _item("model_api", api, model_api.FILE, n, row.get("started"))
            it.update(kind="message", role="user", input=asked, output=said)
            items.append(it)
        result: dict[str, Any] = row["result"] if isinstance(row.get("result"), dict) else {}
        it = _item("model_api", api, model_api.FILE, n, row.get("ts"))
        info = {k: result.get(k) for k in ("model", "stop_reason", "usage")}
        if form == "decisions":
            info["answers"] = result.get("answers") or []
        it.update(
            kind="message",
            role="assistant",
            input={"path": row.get("path"), **info},
            output=result.get("text") or None,
            error=row.get("error") or result.get("error"),
            exit_code=row.get("status"),
        )
        items.append(it)
        # A tool call id is unique only in one API format, so a result must have the same format.
        later = [_results(f, r) for _, _, f, r in calls[i + 1 :] if f == form]
        for call in result.get("tool_calls") or []:
            it = _item("model_api", api, model_api.FILE, n, row.get("ts"))
            it.update(kind="tool_call", name=call.get("name"), input=call.get("input"))
            found = next((r[str(call.get("id"))] for r in later if str(call.get("id")) in r), None)
            if found is not None:
                it["error" if found[1] else "output"] = found[0]
            items.append(it)
    return items, {
        "file": model_api.FILE,
        "rows": rows,
        "items": len(items),
        "ignored": dict(ignored),
        "harness_calls": dict(harness_calls),
        "other_calls": other_calls,
    }


def _event_tool(it: dict[str, Any]) -> tuple[str | None, Any]:
    """The tool name and input of a harness tool_result event."""
    attrs = it["input"]
    if it["harness"] == "codex":
        return attrs.get("tool_name"), _json(attrs.get("arguments"))
    params = _json(attrs.get("tool_parameters")) or {}
    name = params.get("mcp_tool_name") if isinstance(params, dict) else None
    return name or attrs.get("tool_name"), _json(attrs.get("tool_input"))


def _cut_equal(event: Any, session: Any) -> bool:
    """True if the input of an event agrees with the input of a session item. An event string
    can be cut: it agrees if the session string starts with it, without a cut mark at its end."""
    if isinstance(event, dict) and isinstance(session, dict):
        same_keys = event.keys() == session.keys()
        return same_keys and all(_cut_equal(v, session[k]) for k, v in event.items())
    if isinstance(event, list) and isinstance(session, list):
        same_size = len(event) == len(session)
        return same_size and all(_cut_equal(a, b) for a, b in zip(event, session, strict=True))
    if isinstance(event, str) and isinstance(session, str) and len(event) < len(session):
        for mark in CUT_MARKS:
            event = event.removesuffix(mark)
        return session.startswith(event)
    return bool(event == session)


def _in_session(event: dict[str, Any], items: list[dict[str, Any]]) -> bool:
    """True if the session items have the tool call of the event (SPEC.md section 8.6). The
    items are those of the session of the event, or of each session of its harness if the event
    names no session of the test. If the event has a tool use id and an item has one, only the id
    must agree."""
    name, args = _event_tool(event)
    given = event["input"].get("tool_use_id") if event["harness"] == "claude-code" else None
    own = [it for it in items if it["harness"] == event["harness"]]
    own = [it for it in own if it["session"] == event["session"]] or own
    known = [it for it in own if it.get(CALL_ID)]
    if isinstance(given, str) and given and known:
        return any(it[CALL_ID] == given for it in known)
    command = event["harness"] == "codex" and name in CODEX_COMMANDS
    for it in own:
        if it["turn"] != event["turn"]:
            continue
        if command and it["kind"] == "command":
            return True
        same_input = not isinstance(args, dict) or not isinstance(it["input"], dict)
        same_input = same_input or _cut_equal(args, it["input"])
        if not command and it["kind"] == "tool_call" and it["name"] == name and same_input:
            return True
    return False


def _exchanges(tap: Path) -> list[dict[str, Any]]:
    """The exchange rows of tap.jsonl. An invalid line raises a RecordError (SPEC.md section 2)."""
    return [r for _, r in read_rows("tap", tap, missing_ok=True) if r["type"] == "exchange"]


def windows(exchanges: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """The time window of each turn. A 0.1 row has no `started`: its window starts at the end of
    the turn before it."""
    out: list[tuple[float, float]] = []
    for r in exchanges:
        end = float(r.get("ts", 0.0))
        started = r.get("started")
        if isinstance(started, (int, float)):
            start = float(started)
        else:
            start = out[-1][1] if out else float("-inf")
        out.append((start, end))
    return out


def _turn(ts: float | None, spans: list[tuple[float, float]]) -> int | None:
    """The 1-based number of the exchange whose window holds the time `ts`, or None."""
    return next((i for i, (a, b) in enumerate(spans, 1) if ts is not None and a <= ts <= b), None)


def assign(items: list[dict[str, Any]], spans: list[tuple[float, float]]) -> None:
    """Set the turn of each item: the 1-based number of the exchange whose window holds it."""
    for it in items:
        it["turn"] = _turn(it["ts"], spans)


def _finding(check: str, turn: int | None, detail: str, **where: Any) -> dict[str, Any]:
    return {"check": check, "turn": turn, "detail": detail, **where}


def repeated(exchanges: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """One repeated_reply finding for each run of `count` or more consecutive turns with the
    same reply bytes. A turn with no reply ends a run. A count below 2 turns the check off."""
    runs: list[list[int]] = []
    last: str | None = None
    for i, r in enumerate(exchanges, 1):
        reply = r.get("reply")
        if not isinstance(reply, str):
            last = None
            continue
        if reply == last:
            runs[-1].append(i)
        else:
            runs.append([i])
        last = reply
    out: list[dict[str, Any]] = []
    for run in runs:
        if count < 2 or len(run) < count:
            continue
        names = ", ".join(map(str, run[:-1])) + f" and {run[-1]}"
        detail = f"the same reply in turns {names}: {_excerpt(exchanges[run[0] - 1]['reply'])}"
        out.append(_finding("repeated_reply", run[0], detail, turns=run))
    return out


def _excerpt(text: str) -> str:
    """The first EXCERPT code points of a reply as a JSON string, for the detail of a finding."""
    excerpt = json.dumps(text[:EXCERPT], ensure_ascii=False)
    return excerpt + (" (cut)" if len(text) > EXCERPT else "")


def _normal(text: str) -> str:
    """A text for the match `normalized`: each run of white space is one space, with no space at
    the start or the end, and the case is folded."""
    return " ".join(text.split()).casefold()


def _structured(text: str) -> Any:
    """The JSON value of a model text: the full text, or else the part from its first `{` to its
    last `}`, for a JSON object in a code fence. None if neither part is JSON."""
    parts = [text]
    if "{" in text:
        parts.append(text[text.index("{") : text.rindex("}") + 1] if "}" in text else "")
    for part in parts:
        try:
            return json.loads(part)
        except ValueError:
            continue
    return None


def _at(data: Any, path: str) -> Any:
    """The value at a dot path, or None."""
    try:
        return pick(data, path)
    except AdapterError:
        return None


def model_texts(items: list[dict[str, Any]], turn: int, field: str) -> list[str]:
    """The model texts of a turn (SPEC.md section 8.6): the text of each assistant message of a
    session file or a model API call. With a field, the value at the field in the JSON of each
    such message and in the input of each tool call of the app. An empty text does not count."""
    out = []
    for it in items:
        if it["turn"] != turn or it["harness"] not in MODEL_HARNESSES:
            continue
        value = None
        if it["kind"] == "message" and it["role"] == "assistant" and isinstance(it["output"], str):
            value = _at(_structured(it["output"]), field) if field else it["output"]
        elif field and it["kind"] == "tool_call" and not it["harness_internal"]:
            value = _at(it["input"], field)
        if isinstance(value, str) and value.strip():
            out.append(value)
    return out


def not_from_model(
    exchanges: list[dict[str, Any]], items: list[dict[str, Any]], field: str, match: str
) -> list[dict[str, Any]]:
    """One reply_not_from_model finding for each turn whose reply contains none of the model
    texts of the turn. A turn with no reply or no model text gives no finding."""
    out: list[dict[str, Any]] = []
    if match not in ("exact", "normalized"):
        return out
    for i, r in enumerate(exchanges, 1):
        reply = r.get("reply")
        texts = model_texts(items, i, field) if isinstance(reply, str) else []
        if not texts or not isinstance(reply, str):
            continue
        if match == "exact":
            found = any(t in reply for t in texts)
        else:
            found = any(_normal(t) in _normal(reply) for t in texts)
        if not found:
            what = f"the value of {field}" if field else "the text"
            detail = f"the reply does not contain {what} of a model output of this turn"
            detail += f" ({len(texts)} checked): {_excerpt(reply)}"
            out.append(_finding("reply_not_from_model", i, detail))
    return out


def check(
    exchanges: list[dict[str, Any]],
    spans: list[tuple[float, float]],
    items: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    servers: list[dict[str, Any]] | None = None,
    keys: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The findings of SPEC.md section 8.6. They do not change the audit's exit code. `servers`
    holds the MCP servers that the Claude Code session files name (read_claude_servers).
    `keys` holds the config keys of the checks that the manifest records (trace_keys).
    `errors` holds the model errors of the Codex session files (read_codex_errors)."""
    keys = {**TRACE_KEYS, **(keys or {})}
    out: list[dict[str, Any]] = []
    session_items = [it for it in items if it["kind"] in SESSION_KINDS]
    for i, r in enumerate(exchanges, 1):
        if r.get("status") != 200:
            what = "a timeout or a crash" if r.get("status") is None else f"status {r['status']}"
            out.append(_finding("agent_error", i, f"the agent gave {what}"))
    out += repeated(exchanges, keys["repeated_reply"])
    out += not_from_model(exchanges, items, keys["model_reply_field"], keys["model_reply_match"])
    for it in items:
        where = {"harness": it["harness"], "session": it["session"], "source": it["source"]}
        if it["kind"] == "tool_call" and it["error"] is not None:
            detail = f"{it['name']}: {it['error']}"
            out.append(_finding("tool_error", it["turn"], detail, **where))
        if it["kind"] == "command" and (it["exit_code"] not in (0, None) or it["error"]):
            what = f"exit code {it['exit_code']}" if it["exit_code"] is not None else it["error"]
            out.append(_finding("command_failed", it["turn"], what, **where))
        failed = it["error"] is not None or (it["exit_code"] or 0) >= 500
        if it["kind"] == "http" and failed:
            what = it["error"] or f"status {it['exit_code']}"
            detail = f"{it['session']}: {it['name']}: {what}"
            out.append(_finding("backend_error", it["turn"], detail, **where))
        model_call = it["harness"] == "model_api" and it["role"] == "assistant"
        if model_call and (it["error"] is not None or (it["exit_code"] or 0) >= 400):
            what = it["error"] or f"status {it['exit_code']}"
            detail = f"{it['session']}: {it['input']['path']}: {what}"
            out.append(_finding("model_api_error", it["turn"], detail, **where))
        if it["kind"] == "span" and it["error"] is not None:
            detail = f"{it['service'] or 'a service'}: {it['name']}: {it['error']}"
            out.append(_finding("span_error", it["turn"], detail, **where))
        harness_event = it["kind"] == "log" and it["harness"] in ("claude-code", "codex")
        if harness_event and it["name"] == "tool_result" and not _in_session(it, session_items):
            name = _event_tool(it)[0]
            detail = f"{name}: a tool_result event with no tool call in the session file"
            out.append(_finding("otel_tool_not_in_session", it["turn"], detail, **where))
        first = spans[0][0] if spans else None
        if it["turn"] is None and first is not None and it["ts"] is not None and it["ts"] >= first:
            out.append(_finding("item_between_turns", None, f"a {it['kind']} item", **where))
    for e in errors or []:
        turn = _turn(e["ts"], spans)
        where = {"harness": e["harness"], "session": e["session"]}
        where["source"] = {"file": e["file"], "line": e["line"]}
        out.append(_finding("model_error", turn, e["detail"], **where))
    if any(s.get("items") for s in sessions):
        used = {it["turn"] for it in session_items}
        for i in range(1, len(exchanges) + 1):
            if i not in used:
                out.append(_finding("turn_without_model", i, "no model item in this turn"))
    for srv in servers or []:
        name = str(srv["server"])
        origin = next((v for start, v in NOT_FROM_APP.items() if name.startswith(start)), None)
        if origin is not None:
            where = {"harness": srv["harness"], "session": srv["session"]}
            where["source"] = {"file": srv["file"], "line": srv["line"]}
            detail = f"{srv['server']}: {origin}, not a server of the app"
            out.append(_finding("server_not_from_app", None, detail, **where))
    for s in sessions:
        where = {"harness": s["harness"], "session": s["session"]}
        if s.get("inferred"):
            out.append(_finding("session_inferred", None, "found by directory and time", **where))
        tested = TESTED.get(s["harness"], ())
        if s.get("version") is not None and s["version"] not in tested:
            detail = f"version {s.get('version')}, tested: {', '.join(tested)}"
            out.append(_finding("version_untested", None, detail, **where))
    order = {c: n for n, c in enumerate(CHECKS)}
    big = len(exchanges) + 1
    out.sort(key=lambda f: (order[f["check"]], f["turn"] if f["turn"] is not None else big))
    return out


def build(folder: Path) -> dict[str, Any]:
    """Build trace.jsonl and findings.json in a test folder from its copied session files."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    exchanges = _exchanges(folder / "tap.jsonl")
    spans = windows(exchanges)
    items: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    servers: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for s in manifest.get("model_sessions", []):
        info: dict[str, Any] = {
            "harness": s["harness"],
            "session": s["session"],
            "file": s.get("file"),
            "inferred": bool(s.get("inferred")),
            "version": None,
            "items": 0,
            "ignored": {},
        }
        reader = READERS.get(s["harness"])
        if reader is not None and s.get("file") and (folder / s["file"]).exists():
            found, more = reader(folder / s["file"], s["session"], s["file"])
            info.update(more, items=len(found))
            info["version"] = info["version"] or "unknown"
            items += found
            if s["harness"] == "claude-code":
                where = {"harness": s["harness"], "session": s["session"], "file": s["file"]}
                servers += [{**where, **x} for x in read_claude_servers(folder / s["file"])]
            if s["harness"] == "codex":
                where = {"harness": s["harness"], "session": s["session"], "file": s["file"]}
                errors += [{**where, **x} for x in read_codex_errors(folder / s["file"])]
        sessions.append(info)
    otel = None
    if (folder / otlp.FILE).exists():
        found, otel = read_otel(folder / otlp.FILE)
        items += found
    calls = None
    if (folder / backend.FILE).exists():
        found, calls = read_backend(folder / backend.FILE)
        items += found
    direct = None
    if (folder / model_api.FILE).exists():
        found, direct = read_model_api(folder / model_api.FILE)
        items += found
    items.sort(key=lambda it: it["ts"] if it["ts"] is not None else float("inf"))
    assign(items, spans)
    findings = check(exchanges, spans, items, sessions, servers, trace_keys(manifest), errors)
    lines = [json_text({k: v for k, v in it.items() if k != CALL_ID}) + "\n" for it in items]
    (folder / "trace.jsonl").write_text("".join(lines), encoding="utf-8")
    counts = Counter(f["check"] for f in findings)
    report = {
        "v": VERSION,
        "test": manifest.get("test"),
        "turns": len(exchanges),
        "items": len(items),
        "sessions": sessions,
        "otel": otel,
        "backend": calls,
        "model_api": direct,
        "counts": {c: counts[c] for c in CHECKS},
        "findings": findings,
    }
    text = json_text(report, indent=1) + "\n"
    (folder / "findings.json").write_text(text, encoding="utf-8")
    # The caller prints the report, so it gets the escaped text of findings.json.
    return dict(json.loads(text))


def trace_keys(manifest: dict[str, Any]) -> dict[str, Any]:
    """The config keys of the checks that the manifest records. A key that a manifest from
    before the key does not have, or a value that config.check refuses, gives the default."""
    keys = manifest.get("trace")
    keys = keys if isinstance(keys, dict) else {}
    out = dict(TRACE_KEYS)
    count = keys.get("repeated_reply")
    if isinstance(count, int) and not isinstance(count, bool) and (count == 0 or count >= 2):
        out["repeated_reply"] = count
    field = keys.get("model_reply_field")
    if isinstance(field, str) and (field == "" or all(field.split("."))):
        out["model_reply_field"] = field
    if keys.get("model_reply_match") in MATCHES:
        out["model_reply_match"] = keys["model_reply_match"]
    return out


def summary(report: dict[str, Any]) -> str:
    found = ", ".join(f"{n} {c}" for c, n in report["counts"].items() if n) or "no findings"
    return f"Trace: {report['items']} model items in {report['turns']} turns, {found}."

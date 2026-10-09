"""The model API proxies of SPEC.md section 7.7.

During a test, the bridge runs one recording proxy for each model API, and gives the entry the proxy
URL in the base URL variable of the API's SDK. The proxy sends each part of a response to the app
when it comes, also a streamed (SSE) response. It writes one row for each call to model_api.jsonl,
with the result of the call: the text, the tool calls and the stop reason, or the answers of a
decision.
"""

from __future__ import annotations

import codecs
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from . import backend
from .adapters import StreamError, sse_events

FILE = "model_api.jsonl"
# The API name: the variable of its SDK and the URL if the entry has no value in the variable.
APIS = {
    "anthropic": ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
    "openai": ("OPENAI_BASE_URL", "https://api.openai.com/v1"),
}
# The start of the User-Agent of a harness, and the harness name.
HARNESS_AGENTS = (("claude-cli", "claude-code"), ("claude-code", "claude-code"), ("codex", "codex"))


def parse(raw: Any) -> dict[str, str | None]:
    """The `model_api` key of the configuration: the APIs to record, each with the URL from the
    configuration, or None for the URL from its variable."""
    if raw is None or raw is True:
        return dict.fromkeys(APIS)
    if raw is False:
        return {}
    if isinstance(raw, list) and all(isinstance(x, str) and x in APIS for x in raw):
        return dict.fromkeys(raw)
    if isinstance(raw, dict) and all(
        k in APIS and (v is None or isinstance(v, str)) for k, v in raw.items()
    ):
        return dict(raw)
    raise ValueError(
        f"'model_api' must be true, false, a list of: {', '.join(APIS)}, "
        "or an object from these names to a URL or null"
    )


def backends(apis: Mapping[str, str | None], environ: Mapping[str, str]) -> list[backend.Backend]:
    """One backend for each API. Its URL is the URL of the configuration, else the value that the
    bridge has in the variable, else the default."""
    out = []
    for name, configured in apis.items():
        env, default = APIS[name]
        # A URL in the configuration is used as it is, also if it is empty, so that it is checked.
        url = configured if configured is not None else (environ.get(env) or default)
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
            raise ValueError(f"the URL of {name} ({env}) must be an http or https URL: {url!r}")
        out.append(backend.Backend(name, env, url.rstrip("/")))
    return out


def harness(headers: list[tuple[str, str]]) -> str | None:
    """The harness that made the call, from its User-Agent, or None for the app."""
    agent = next((v for k, v in headers if k.lower() == "user-agent"), "").lower()
    return next((h for start, h in HARNESS_AGENTS if agent.startswith(start)), None)


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _error(data: Any) -> str | None:
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or error)
    return str(error) if error else None


def events(data: bytes, out: dict[str, Any]) -> list[Any]:
    """The JSON data of each event of an SSE stream, or None for data that is not JSON.

    The parser is the strict parser of the tap (`adapters.sse_events`, SPEC.md section 4.1). A
    stream that stopped can end in the middle of a UTF-8 character, so the parser ignores an
    incomplete character at the end. If other bytes are not UTF-8, the result gets the error of
    the parser and no events. An event with the name `error` sets the error of the result.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        # Without final=True, the decoder keeps an incomplete character at the end for later.
        decoder.decode(data)
        data = data[: len(data) - len(decoder.getstate()[0])]
    except UnicodeDecodeError:
        pass  # sse_events refuses the body below, and its error goes into the result.
    try:
        found = sse_events(data)
    except StreamError as e:
        out["error"] = str(e)
        return []
    parsed = []
    for name, text in found:
        value = _json(text)
        if name == "error":
            out["error"] = _error(value) or text
        parsed.append(value)
    return parsed


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _arguments(text: Any) -> Any:
    """The input of an OpenAI tool call: the parsed JSON, or the text if it is not JSON."""
    if not isinstance(text, str):
        return text
    value = _json(text)
    return text if value is None and text.strip() else (value if value is not None else {})


def _empty() -> dict[str, Any]:
    return {
        "model": None,
        "text": "",
        "tool_calls": [],
        "stop_reason": None,
        "usage": None,
        "error": None,
    }


def _anthropic_content(out: dict[str, Any], content: Any) -> None:
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            out["text"] += str(block.get("text") or "")
        elif block.get("type") == "tool_use":
            call = {"id": block.get("id"), "name": block.get("name"), "input": block.get("input")}
            out["tool_calls"].append(call)


def anthropic(data: bytes, stream: bool) -> dict[str, Any]:
    """The result of a call to the Anthropic Messages API."""
    out = _empty()
    if not stream:
        body = _json(data.decode("utf-8", errors="replace"))
        if not isinstance(body, dict):
            out["error"] = "the response is not JSON"
            return out
        out.update(model=body.get("model"), stop_reason=body.get("stop_reason"))
        out.update(usage=body.get("usage"), error=_error(body))
        _anthropic_content(out, body.get("content"))
        return out
    blocks: dict[int, dict[str, Any]] = {}
    for event in events(data, out):
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "message_start" and isinstance(event.get("message"), dict):
            out.update(model=event["message"].get("model"), usage=event["message"].get("usage"))
        elif kind == "content_block_start" and isinstance(event.get("content_block"), dict):
            blocks[int(event.get("index") or 0)] = {**event["content_block"], "partial": ""}
        elif kind == "content_block_delta" and isinstance(event.get("delta"), dict):
            block = blocks.setdefault(int(event.get("index") or 0), {"partial": ""})
            delta = event["delta"]
            if delta.get("type") == "text_delta":
                block.setdefault("type", "text")
                block["text"] = str(block.get("text") or "") + str(delta.get("text") or "")
            elif delta.get("type") == "input_json_delta":
                block["partial"] += str(delta.get("partial_json") or "")
        elif kind == "message_delta":
            delta = _dict(event.get("delta"))
            out["stop_reason"] = delta.get("stop_reason", out["stop_reason"])
            if isinstance(event.get("usage"), dict):
                out["usage"] = {**(out["usage"] or {}), **event["usage"]}
        elif kind == "error":
            out["error"] = _error(event)
    content = []
    for _, block in sorted(blocks.items()):
        if block.get("type") == "tool_use" and block["partial"]:
            block["input"] = _arguments(block["partial"])
        content.append(block)
    _anthropic_content(out, content)
    return out


def openai(data: bytes, stream: bool) -> dict[str, Any]:
    """The result of a call to the OpenAI Chat Completions API."""
    out = _empty()
    if not stream:
        body = _json(data.decode("utf-8", errors="replace"))
        if not isinstance(body, dict):
            out["error"] = "the response is not JSON"
            return out
        out.update(model=body.get("model"), usage=body.get("usage"), error=_error(body))
        choices = body.get("choices") if isinstance(body.get("choices"), list) else []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = _dict(choice.get("message"))
        out.update(text=str(message.get("content") or ""), stop_reason=choice.get("finish_reason"))
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            out["tool_calls"].append(
                {
                    "id": call.get("id"),
                    "name": function.get("name"),
                    "input": _arguments(function.get("arguments")),
                }
            )
        return out
    calls: dict[int, dict[str, Any]] = {}
    for chunk in events(data, out):
        if not isinstance(chunk, dict):
            continue
        out["model"] = chunk.get("model") or out["model"]
        out["usage"] = chunk.get("usage") or out["usage"]
        out["error"] = _error(chunk) or out["error"]
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                continue
            delta = _dict(choice.get("delta"))
            out["text"] += str(delta.get("content") or "")
            for part in delta.get("tool_calls") or []:
                call = calls.setdefault(int(part.get("index") or 0), {"id": None, "name": ""})
                call["id"] = part.get("id") or call["id"]
                function = part.get("function") or {}
                call["name"] += str(function.get("name") or "")
                call["arguments"] = call.get("arguments", "") + str(function.get("arguments") or "")
            out["stop_reason"] = choice.get("finish_reason") or out["stop_reason"]
    for _, call in sorted(calls.items()):
        args = call.get("arguments", "")
        out["tool_calls"].append(
            {"id": call["id"], "name": call["name"], "input": _arguments(args)}
        )
    return out


# The events of a Responses API stream that hold the response object.
RESPONSE_EVENTS = (
    "response.created",
    "response.in_progress",
    "response.completed",
    "response.failed",
    "response.incomplete",
)


def _responses_output(out: dict[str, Any], items: Any) -> None:
    """The text and the tool calls of the `output` items of an OpenAI response."""
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    out["text"] += str(part.get("text") or "")
        elif item.get("type") == "function_call":
            out["tool_calls"].append(
                {
                    "id": item.get("call_id"),
                    "name": item.get("name"),
                    "input": _arguments(item.get("arguments")),
                }
            )


def _responses_status(out: dict[str, Any], response: Any) -> None:
    """The model, the status, the usage and the error of an OpenAI response object."""
    if not isinstance(response, dict):
        return
    out["model"] = response.get("model") or out["model"]
    out["stop_reason"] = response.get("status") or out["stop_reason"]
    out["usage"] = response.get("usage") or out["usage"]
    out["error"] = _error(response) or out["error"]


def responses(data: bytes, stream: bool) -> dict[str, Any]:
    """The result of a call to the OpenAI Responses API."""
    out = _empty()
    if not stream:
        body = _json(data.decode("utf-8", errors="replace"))
        if not isinstance(body, dict):
            out["error"] = "the response is not JSON"
            return out
        _responses_status(out, body)
        _responses_output(out, body.get("output"))
        return out
    # The output items by their output_index. The deltas add to an item, and the last
    # response.output_item.done event replaces it.
    items: dict[int, dict[str, Any]] = {}
    for event in events(data, out):
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        index = event.get("output_index")
        index = index if isinstance(index, int) else 0
        if kind in ("response.output_item.added", "response.output_item.done"):
            if isinstance(event.get("item"), dict):
                items[index] = dict(event["item"])
        elif kind == "response.output_text.delta":
            item = items.setdefault(index, {"type": "message"})
            old = item.get("content")
            content: list[Any] = old if isinstance(old, list) else []
            item["content"] = content
            at = event.get("content_index")
            at = at if isinstance(at, int) else 0
            while len(content) <= at:
                content.append({"type": "output_text", "text": ""})
            part = content[at] = _dict(content[at])
            part["text"] = str(part.get("text") or "") + str(event.get("delta") or "")
        elif kind == "response.function_call_arguments.delta":
            item = items.setdefault(index, {"type": "function_call"})
            item["arguments"] = str(item.get("arguments") or "") + str(event.get("delta") or "")
        elif kind in RESPONSE_EVENTS:
            _responses_status(out, event.get("response"))
        elif kind == "error":
            out["error"] = str(event.get("message") or event.get("code") or "error")
    _responses_output(out, [item for _, item in sorted(items.items())])
    return out


# The field of the value of each type of answer of the Decisions API.
DECISION_VALUES = {"predicate": "probability", "choice": "choice", "score": "score"}


def _number(value: Any) -> float | int | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    return value if ok else None


def _answer(answer: dict[str, Any]) -> dict[str, Any]:
    """One answer of the Decisions API: its type, name, value, probabilities and confidence. A
    refusal has no value, no probabilities and no confidence."""
    kind = answer.get("type")
    field = DECISION_VALUES.get(kind) if isinstance(kind, str) else None
    found = answer.get("probabilities")
    return {
        "type": kind,
        "name": answer.get("name"),
        "value": answer.get(field) if field else None,
        "probabilities": found if isinstance(found, list) else None,
        "confidence": _number(answer.get("confidence")),
    }


def decisions(data: bytes, stream: bool) -> dict[str, Any]:
    """The result of a call to the OpenAI Decisions API. The API reference gives no stream, so the
    body is read as JSON also if `stream` is true."""
    out = {**_empty(), "answers": []}
    body = _json(data.decode("utf-8", errors="replace"))
    if not isinstance(body, dict):
        out["error"] = "the response is not JSON"
        return out
    out.update(model=body.get("model"), usage=body.get("usage"), error=_error(body))
    answers = body.get("answers")
    for answer in answers if isinstance(answers, list) else []:
        if isinstance(answer, dict):
            out["answers"].append(_answer(answer))
    return out


# The model calls: the API, the end of the path, and the format of the call. The format selects
# the parser of the result here and the reader of the request in the trace. To read a new model
# call, add one row here and one parser to PARSERS.
CALLS = (
    ("anthropic", "/v1/messages", "messages"),
    ("openai", "/chat/completions", "chat"),
    ("openai", "/responses", "responses"),
    ("openai", "/decisions", "decisions"),
)
PARSERS = {"messages": anthropic, "chat": openai, "responses": responses, "decisions": decisions}


def call_format(api: str, path: str) -> str | None:
    """The format of a model call of the API, or None if the path is not a model call."""
    end = path.rstrip("/")
    return next((f for a, tail, f in CALLS if a == api and end.endswith(tail)), None)


def result(api: str, path: str, data: bytes, stream: bool) -> dict[str, Any] | None:
    """The result of a call, or None for a path that is not a model call."""
    form = call_format(api, path)
    return None if form is None else PARSERS[form](data, stream)


def _omit(body: Any) -> None:
    """Remove the text of a body of a harness call. Its size and SHA-256 stay."""
    if isinstance(body, dict):
        body.pop("text", None)
        body.pop("base64", None)
        body.pop("decoded", None)
        body["omitted"] = True


class ModelProxy(backend.Proxy):
    """One recording proxy for one model API."""

    streaming = True

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        name = row.pop("backend")
        old = dict(row)
        row.clear()
        row.update(v=old.pop("v"), type=old.pop("type"), api=name, harness=harness(headers))
        row.update(old, stream=None, result=None)
        # A harness call holds the harness's own instructions. The record keeps no text of it.
        if row["harness"]:
            _omit(row["request_body"])

    def complete(self, row: dict[str, Any], body: bytes, encoding: str | None) -> None:
        headers = row["response_headers"] or []
        kind = next((v for k, v in headers if k.lower() == "content-type"), "")
        row["stream"] = "text/event-stream" in kind.lower()
        if row["harness"]:
            _omit(row["response_body"])
            return
        data = backend.decode(body, encoding) or body
        row["result"] = result(self.backend.name, row["path"], data, row["stream"])

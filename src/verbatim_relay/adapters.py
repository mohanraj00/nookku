"""Adapters of SPEC.md section 4.1: find the message in a request and the reply in a response."""

from __future__ import annotations

import json
from typing import Any, Protocol


class AdapterError(ValueError):
    """The adapter cannot find the message or the reply."""


class Adapter(Protocol):
    def accepts(self, method: str, path: str) -> bool: ...
    def refuse(self, body: bytes) -> str | None: ...
    def message(self, body: bytes) -> str: ...
    def reply(self, body: bytes) -> str: ...


def _json(body: bytes, what: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AdapterError(f"the {what} body is not UTF-8 JSON") from None


def pick(data: Any, path: str) -> Any:
    """Follow a dot path such as `choices.0.message.content`."""
    for key in path.split("."):
        if isinstance(data, list) and key.isdigit() and int(key) < len(data):
            data = data[int(key)]
        elif isinstance(data, dict) and key in data:
            data = data[key]
        else:
            raise AdapterError(f"no value at {path!r}")
    return data


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise AdapterError(f"the value at {path!r} is not a string")
    return value


class JsonAdapter:
    """Any POST. The message and the reply are at field paths of JSON bodies."""

    def __init__(self, message_field: str = "text", reply_field: str = "reply") -> None:
        self.message_field, self.reply_field = message_field, reply_field

    def accepts(self, method: str, path: str) -> bool:
        return method == "POST"

    def refuse(self, body: bytes) -> str | None:
        return None

    def message(self, body: bytes) -> str:
        return _text(pick(_json(body, "request"), self.message_field), self.message_field)

    def reply(self, body: bytes) -> str:
        return _text(pick(_json(body, "response"), self.reply_field), self.reply_field)


class OpenAIAdapter:
    """A POST to an OpenAI-compatible `/chat/completions` endpoint, without streaming."""

    def accepts(self, method: str, path: str) -> bool:
        return method == "POST" and path.split("?")[0].rstrip("/").endswith("/chat/completions")

    def refuse(self, body: bytes) -> str | None:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(data, dict) and data.get("stream") is True:
            return "verbatim-relay v0.1 does not support streamed responses; send stream: false"
        return None

    def message(self, body: bytes) -> str:
        messages = pick(_json(body, "request"), "messages")
        if not isinstance(messages, list):
            raise AdapterError("'messages' is not a list")
        users = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        if not users:
            raise AdapterError("the request has no message with role 'user'")
        content = users[-1].get("content")
        if isinstance(content, list):
            texts = [p for p in content if isinstance(p, dict) and p.get("type") == "text"]
            if len(texts) != 1 or len(content) != 1:
                raise AdapterError("the user content must be a string or exactly one text part")
            content = texts[0].get("text")
        return _text(content, "messages[-1].content")

    def reply(self, body: bytes) -> str:
        path = "choices.0.message.content"
        return _text(pick(_json(body, "response"), path), path)


def make(name: str, message_field: str = "text", reply_field: str = "reply") -> Adapter:
    if name == "json":
        return JsonAdapter(message_field, reply_field)
    if name == "openai":
        return OpenAIAdapter()
    raise ValueError(f"unknown adapter {name!r}")

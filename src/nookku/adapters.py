"""Adapters of SPEC.md section 4.1: find the message in a request and the reply in a response."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Protocol

from nookku.record import MEDIA_TYPE, lone_surrogate

ATTACHMENT_COUNT = 16
ATTACHMENT_BYTES = 8 * 1024 * 1024


class AdapterError(ValueError):
    """The adapter cannot find the message or the reply."""


class AttachmentLimitError(ValueError):
    """The request exceeds an attachment limit of SPEC.md section 4.1."""


class StreamError(ValueError):
    """The agent's stream failed: it ended early, sent an error, or sent a malformed chunk."""


# One earlier turn of the session: (tester message, agent reply).
History = list[tuple[str, str]]


class Adapter(Protocol):
    def request(self, message: str, history: History) -> bytes: ...
    def accepts(self, method: str, path: str) -> bool: ...
    def message(self, body: bytes) -> str: ...
    def attachments(self, body: bytes) -> list[tuple[str, bytes]]: ...
    def reply(self, body: bytes) -> str: ...
    def stream_reply(self, body: bytes) -> str: ...


def is_stream(content_type: str | None) -> bool:
    """True if a Content-Type is text/event-stream (SPEC.md section 4.1)."""
    return (content_type or "").split(";")[0].strip().lower() == "text/event-stream"


def sse_events(body: bytes) -> list[tuple[str, str]]:
    """The (name, data) of each event of an SSE body, in the order of the body.

    The rules are those of the WHATWG HTML standard: a blank line ends an event, a line that starts
    with a colon is a comment, and an event without a data line is not an event. The last event
    does not need a blank line after it. The `openai` adapter and the model API proxies
    (`model_api.events`) use this one parser.
    """
    try:
        text = body.decode("utf-8").removeprefix("﻿")
    except UnicodeDecodeError:
        raise StreamError("the stream is not UTF-8") from None
    events: list[tuple[str, str]] = []
    name, data = "", list[str]()
    for line in [*re.split(r"\r\n|\r|\n", text), ""]:
        if line == "":
            if data:
                events.append((name or "message", "\n".join(data)))
            name, data = "", []
        elif not line.startswith(":"):
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "data":
                data.append(value)
            elif key == "event":
                name = value
    return events


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


_DATA_URL = re.compile(r"data:([^;,]*);base64,(.*)", re.DOTALL)


def _data_url(value: Any) -> tuple[str, bytes]:
    """The media type and the bytes of an image_url part with a base64 data URL."""
    url = value.get("url") if isinstance(value, dict) else None
    found = _DATA_URL.fullmatch(url) if isinstance(url, str) else None
    media = found.group(1).lower() if found else ""
    if found is None or MEDIA_TYPE.fullmatch(media) is None:
        raise AdapterError("an image_url part must have a base64 data URL with a media type")
    try:
        return media, base64.b64decode(found.group(2), validate=True)
    except ValueError:  # binascii.Error, or a character that is not ASCII
        raise AdapterError("an image_url part has base64 that is not valid") from None


class JsonAdapter:
    """Any POST. The message and the reply are at field paths of JSON bodies."""

    def __init__(self, message_field: str = "text", reply_field: str = "reply") -> None:
        self.message_field, self.reply_field = message_field, reply_field

    def request(self, message: str, history: History) -> bytes:
        body: Any = message
        for key in reversed(self.message_field.split(".")):
            body = {key: body}
        return json.dumps(body, ensure_ascii=False).encode()

    def accepts(self, method: str, path: str) -> bool:
        return method == "POST"

    def message(self, body: bytes) -> str:
        return _text(pick(_json(body, "request"), self.message_field), self.message_field)

    def attachments(self, body: bytes) -> list[tuple[str, bytes]]:
        return []

    def reply(self, body: bytes) -> str:
        return _text(pick(_json(body, "response"), self.reply_field), self.reply_field)

    def stream_reply(self, body: bytes) -> str:
        raise AdapterError("the json adapter does not read a streamed response")


class OpenAIAdapter:
    """A POST to an OpenAI-compatible `/chat/completions` endpoint. The reply can be a stream."""

    def __init__(self, model: str = "", stream: bool = False) -> None:
        self.model, self.stream = model, stream

    def request(self, message: str, history: History) -> bytes:
        messages = []
        for said, reply in history:
            messages += [{"role": "user", "content": said}, {"role": "assistant", "content": reply}]
        messages.append({"role": "user", "content": message})
        # With the option openai_stream, the request asks for a stream (SPEC.md section 5).
        body: dict[str, Any] = {"messages": messages, "stream": self.stream}
        if self.model:
            body["model"] = self.model
        return json.dumps(body, ensure_ascii=False).encode()

    def accepts(self, method: str, path: str) -> bool:
        return method == "POST" and path.split("?")[0].rstrip("/").endswith("/chat/completions")

    def _content(self, body: bytes) -> Any:
        """The content of the last user message. A list has one text part and 0 or more image_url
        parts (SPEC.md section 4.1)."""
        messages = pick(_json(body, "request"), "messages")
        if not isinstance(messages, list):
            raise AdapterError("'messages' is not a list")
        users = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        if not users:
            raise AdapterError("the request has no message with role 'user'")
        content = users[-1].get("content")
        if isinstance(content, list):
            kinds = [p.get("type") if isinstance(p, dict) else None for p in content]
            texts, images = kinds.count("text"), kinds.count("image_url")
            if texts != 1 or texts + images != len(kinds):
                raise AdapterError(
                    "the user content must be a string, or exactly one text part and 0 or more "
                    "image_url parts"
                )
        return content

    def message(self, body: bytes) -> str:
        content = self._content(body)
        if isinstance(content, list):
            content = next(p for p in content if p.get("type") == "text").get("text")
        return _text(content, "messages[-1].content")

    def attachments(self, body: bytes) -> list[tuple[str, bytes]]:
        """The media type and the bytes of each image of the last user message."""
        content = self._content(body)
        if not isinstance(content, list):
            return []
        # The content has one text part. Each other part is an image.
        if len(content) - 1 > ATTACHMENT_COUNT:
            raise AttachmentLimitError(f"the request has more than {ATTACHMENT_COUNT} attachments")
        images = []
        size = 0
        error = None
        for part in content:
            if part["type"] != "image_url":
                continue
            try:
                image = _data_url(part.get("image_url"))
            except AdapterError as e:
                # Check the limits of the other images before the tap forwards an unparsed request.
                if error is None:
                    error = e
                continue
            size += len(image[1])
            if size > ATTACHMENT_BYTES:
                raise AttachmentLimitError(
                    f"the request attachments have more than {ATTACHMENT_BYTES} decoded bytes"
                )
            images.append(image)
        if error is not None:
            raise error
        return images

    def reply(self, body: bytes) -> str:
        path = "choices.0.message.content"
        return _text(pick(_json(body, "response"), path), path)

    def stream_reply(self, body: bytes) -> str:
        """Join the `choices[0].delta.content` texts of a stream (SPEC.md section 4.1).

        Raise StreamError if the stream has no `data: [DONE]` event, has an event after it, has an
        error, or has a malformed chunk. Raise AdapterError if no chunk has a content text.
        """
        parts: list[str] = []
        done = False
        for name, data in sse_events(body):
            if done:
                raise StreamError("the stream has an event after data: [DONE]")
            if data == "[DONE]":
                done = True
                continue
            if name == "error":
                raise StreamError(f"the agent sent an error event: {data}")
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                raise StreamError(f"a chunk is not JSON: {data[:80]!r}") from None
            if not isinstance(chunk, dict):
                raise StreamError(f"a chunk is not a JSON object: {data[:80]!r}")
            if chunk.get("error") is not None:
                raise StreamError(f"the agent sent an error: {json.dumps(chunk['error'])}")
            choices = chunk.get("choices", [])
            if not isinstance(choices, list):
                raise StreamError("the 'choices' of a chunk is not a list")
            for choice in choices:
                delta = choice.get("delta", {}) if isinstance(choice, dict) else None
                if not isinstance(delta, dict):
                    raise StreamError("a choice of a chunk has no 'delta' object")
                if choice.get("index", 0) != 0:
                    continue
                content = delta.get("content")
                if content is not None and not isinstance(content, str):
                    raise StreamError("the 'delta.content' of a chunk is not a string")
                if content is not None:
                    parts.append(content)
        if not done:
            raise StreamError("the stream ended before data: [DONE]")
        if not parts:
            raise AdapterError("no chunk of the stream has a 'delta.content' text")
        # A chunk can end in the middle of a surrogate pair. Join each pair into one character, as
        # a JavaScript string does. A lone surrogate is not a Unicode scalar value (SPEC.md 2).
        units = "".join(parts).encode("utf-16-le", "surrogatepass")
        joined = units.decode("utf-16-le", "surrogatepass")
        found = lone_surrogate(joined)
        if found:
            # Name the code point and its character number, as the relay does (SPEC.md 5).
            raise StreamError(f"the stream reply has {found}")
        return joined


def make(
    name: str,
    message_field: str = "text",
    reply_field: str = "reply",
    model: str = "",
    stream: bool = False,
) -> Adapter:
    if name == "json":
        return JsonAdapter(message_field, reply_field)
    if name == "openai":
        return OpenAIAdapter(model, stream)
    raise ValueError(f"unknown adapter {name!r}")

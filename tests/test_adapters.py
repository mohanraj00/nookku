import json
import re

import pytest

from nooku.adapters import AdapterError, StreamError, is_stream, make, pick, sse_events


def test_pick_follows_keys_and_list_indexes():
    assert pick({"a": [{"b": "x"}]}, "a.0.b") == "x"
    with pytest.raises(AdapterError):
        pick({"a": []}, "a.0")


def test_json_adapter_field_paths():
    adapter = make("json", "input.text", "output.0")
    assert adapter.message(b'{"input": {"text": "hi "}}') == "hi "
    assert adapter.reply(b'{"output": ["yes"]}') == "yes"
    with pytest.raises(AdapterError):
        adapter.message(b'{"input": {"text": 3}}')
    with pytest.raises(AdapterError):
        adapter.reply(b"\xff")


@pytest.mark.parametrize(
    "content, ok",
    [
        ("hi", True),
        ([{"type": "text", "text": "hi"}], True),
        ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], False),
        ([{"type": "image_url", "image_url": {}}], False),
        (None, False),
    ],
)
def test_openai_user_content(content, ok):
    body = json.dumps({"messages": [{"role": "user", "content": content}]}).encode()
    if ok:
        assert make("openai").message(body) == "hi"
    else:
        with pytest.raises(AdapterError):
            make("openai").message(body)


def test_openai_takes_the_last_user_message():
    body = json.dumps(
        {
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "second"},
            ]
        }
    ).encode()
    assert make("openai").message(body) == "second"


def test_openai_accepts_only_chat_completions_posts():
    adapter = make("openai")
    assert adapter.accepts("POST", "/v1/chat/completions?x=1")
    assert not adapter.accepts("GET", "/v1/chat/completions")
    assert not adapter.accepts("POST", "/v1/embeddings")


def test_unknown_adapter():
    with pytest.raises(ValueError):
        make("grpc")


def _stream(*events: object) -> bytes:
    parts = [e if isinstance(e, bytes) else b"data: " + json.dumps(e).encode() for e in events]
    return b"\n\n".join(parts) + b"\n\n"


def _delta(content: object, index: int = 0) -> dict:
    return {"choices": [{"index": index, "delta": {"content": content}}]}


def test_sse_events_follow_the_line_rules():
    body = "﻿: a comment\r\nevent: note\r\ndata: a\r\ndata:b\r\nid: 7\r\n\r\n"
    body += "data: c\rdata: d\n\n\nevent: empty\n\ndata: last"
    assert sse_events(body.encode()) == [("note", "a\nb"), ("message", "c\nd"), ("message", "last")]


def test_openai_stream_reply_joins_the_content_of_choice_0():
    body = _stream(
        {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
        _delta("## Toy shop  \n"),
        _delta("other choice", index=1),
        _delta("| mug | € 8 |\n"),
        {"choices": [], "usage": {"total_tokens": 42}},
        b"data: [DONE]",
    )
    assert make("openai").stream_reply(body) == "## Toy shop  \n| mug | € 8 |\n"


@pytest.mark.parametrize(
    "body, error",
    [
        (_stream(_delta("half a rep")), "ended before data: [DONE]"),
        (_stream(_delta("a"), b"data: [DONE]", _delta("b")), "after data: [DONE]"),
        (_stream(_delta("a"), {"error": {"message": "down"}}, b"data: [DONE]"), "an error:"),
        (_stream(_delta("a"), b"event: error\ndata: down", b"data: [DONE]"), "error event"),
        (_stream(b'data: {"choices": [{"delta": {"con', b"data: [DONE]"), "not JSON"),
        (_stream([1, 2], b"data: [DONE]"), "not a JSON object"),
        (_stream({"choices": {"0": {}}}, b"data: [DONE]"), "not a list"),
        (_stream({"choices": [{"delta": "a"}]}, b"data: [DONE]"), "no 'delta' object"),
        (_stream(_delta(4471), b"data: [DONE]"), "not a string"),
        (b"data: \xff\n\n", "not UTF-8"),
    ],
)
def test_openai_stream_failures_are_stream_errors(body, error):
    with pytest.raises(StreamError, match=re.escape(error)):
        make("openai").stream_reply(body)


def test_a_surrogate_pair_split_between_chunks_is_one_character():
    pair = _stream(
        b'data: {"choices": [{"delta": {"content": "mug \\ud83d"}}]}',
        b'data: {"choices": [{"delta": {"content": "\\ude00"}}]}',
        b"data: [DONE]",
    )
    assert make("openai").stream_reply(pair) == "mug \U0001f600"
    lone = _stream(b'data: {"choices": [{"delta": {"content": "mug \\ud83d"}}]}', b"data: [DONE]")
    with pytest.raises(StreamError, match="lone surrogate"):
        make("openai").stream_reply(lone)


def test_a_stream_without_content_cannot_be_read():
    body = _stream({"choices": [{"delta": {"tool_calls": []}}]}, b"data: [DONE]")
    with pytest.raises(AdapterError):
        make("openai").stream_reply(body)
    with pytest.raises(AdapterError):
        make("json").stream_reply(_stream(_delta("a"), b"data: [DONE]"))


def test_is_stream():
    assert is_stream("text/event-stream; charset=utf-8")
    assert is_stream("Text/Event-Stream")
    assert not is_stream("application/json")
    assert not is_stream(None)

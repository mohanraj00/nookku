import json

import pytest

from verbatim_relay.adapters import AdapterError, make, pick


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

import http.client
import json
from pathlib import Path

import pytest
from toy_model_server import ModelServer

from verbatim_relay import backend, model_api

CASE = Path(__file__).resolve().parent.parent / "conformance" / "trace" / "model_api_toy_shop"
STREAM = [
    b"event: message_start\n"
    b'data: {"type": "message_start", "message": {"model": "claude-toy"}}\n\n',
    b'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, '
    b'"delta": {"type": "text_delta", "text": "3 teapot sets \xe2\x82\xac left."}}\n\n',
    b'event: message_delta\ndata: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}'
    b"\n\n",
]


def rows(tmp_path: Path) -> list[dict]:
    return [json.loads(x) for x in (tmp_path / model_api.FILE).read_text().split("\n") if x]


def proxy_for(model: ModelServer, tmp_path: Path, api: str = "anthropic") -> backend.Proxies:
    env = model_api.APIS[api][0]
    apis = model_api.backends([api], {env: model.url})
    return backend.Proxies(apis, tmp_path / model_api.FILE, model_api.ModelProxy)


def connect(url: str) -> http.client.HTTPConnection:
    host, port = url.removeprefix("http://").split(":")
    return http.client.HTTPConnection(host, int(port), timeout=10)


def post(url: str, path: str, body: bytes, headers: dict) -> tuple[int, bytes]:
    conn = connect(url)
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()
    out = (resp.status, resp.read())
    conn.close()
    return out


def test_the_parsers_give_the_results_of_the_conformance_case() -> None:
    lines = (CASE / model_api.FILE).read_text().split("\n")
    calls = [json.loads(x) for x in lines if x and '"result": {' in x]
    assert len(calls) == 4
    for row in calls:
        data = row["response_body"]["text"].encode()
        got = model_api.result(row["api"], row["path"], data, row["stream"])
        assert got == row["result"]


def test_a_stream_reaches_the_app_before_it_ends(tmp_path: Path) -> None:
    with ModelServer() as model:
        model.parts = STREAM
        model.release.clear()
        proxies = proxy_for(model, tmp_path)
        env = proxies.start()
        try:
            conn = connect(env["ANTHROPIC_BASE_URL"])
            conn.request("POST", "/v1/messages", body=b'{"stream": true}', headers={})
            resp = conn.getresponse()
            # The server holds the rest of the stream until the app has the first part.
            first = resp.read1(65536)
            model.release.set()
            got = first + resp.read()
            conn.close()
        finally:
            proxies.stop()
    assert first == STREAM[0]
    assert got == b"".join(STREAM)
    row = rows(tmp_path)[0]
    assert row["stream"] is True and row["harness"] is None
    assert row["response_body"]["size"] == len(got)
    assert row["result"]["text"] == "3 teapot sets € left."
    assert row["result"]["stop_reason"] == "end_turn"


def test_a_stream_that_stops_gives_an_error_row(tmp_path: Path) -> None:
    with ModelServer() as model:
        model.parts = STREAM
        model.stop_after_first = True
        proxies = proxy_for(model, tmp_path)
        env = proxies.start()
        try:
            conn = connect(env["ANTHROPIC_BASE_URL"])
            conn.request("POST", "/v1/messages", body=b"{}", headers={})
            resp = conn.getresponse()
            with pytest.raises(http.client.IncompleteRead) as cut:
                resp.read()
            conn.close()
        finally:
            proxies.stop()
    assert cut.value.partial == STREAM[0]
    row = rows(tmp_path)[0]
    assert row["error"].startswith("the stream stopped")
    assert row["response_body"]["size"] == len(STREAM[0])


def test_an_answer_shorter_than_its_length_gives_an_error_row(tmp_path: Path) -> None:
    with ModelServer() as model:
        model.short_by = 10
        proxies = proxy_for(model, tmp_path)
        env = proxies.start()
        try:
            conn = connect(env["ANTHROPIC_BASE_URL"])
            conn.request("POST", "/v1/messages", body=b"{}", headers={})
            resp = conn.getresponse()
            with pytest.raises(http.client.IncompleteRead):
                resp.read()
            conn.close()
        finally:
            proxies.stop()
    row = rows(tmp_path)[0]
    assert row["error"] == "the stream stopped: the API sent 34 of 44 bytes"


def test_a_gzip_json_answer_is_read_for_the_result(tmp_path: Path) -> None:
    answer = {"model": "gpt-toy", "choices": [{"message": {"content": "Hi"}, "finish_reason": "x"}]}
    with ModelServer() as model:
        model.parts = [json.dumps(answer).encode()]
        model.content_type = "application/json"
        model.gzip = True
        proxies = proxy_for(model, tmp_path, "openai")
        env = proxies.start()
        try:
            status, got = post(env["OPENAI_BASE_URL"], "/chat/completions", b"{}", {})
        finally:
            proxies.stop()
    assert status == 200 and got[:2] == b"\x1f\x8b"
    row = rows(tmp_path)[0]
    assert (row["api"], row["stream"], row["result"]["text"]) == ("openai", False, "Hi")
    # The default URL of OpenAI has a path. The proxy adds it before the path of the app.
    assert model.seen[0]["path"] == "/chat/completions"


def test_the_api_key_goes_to_the_api_but_not_the_record(tmp_path: Path) -> None:
    with ModelServer() as model:
        proxies = proxy_for(model, tmp_path)
        env = proxies.start()
        try:
            headers = {"x-api-key": "sk-toy-k3y", "Authorization": "Bearer t0k3n"}
            post(env["ANTHROPIC_BASE_URL"], "/v1/messages", b"{}", headers)
        finally:
            proxies.stop()
    assert ("x-api-key", "sk-toy-k3y") in model.seen[0]["headers"]
    assert ("Authorization", "Bearer t0k3n") in model.seen[0]["headers"]
    text = (tmp_path / model_api.FILE).read_text()
    assert "k3y" not in text and "t0k3n" not in text


def test_a_harness_call_keeps_no_text(tmp_path: Path) -> None:
    with ModelServer() as model:
        model.parts = STREAM
        proxies = proxy_for(model, tmp_path)
        env = proxies.start()
        try:
            headers = {"User-Agent": "claude-cli/2.1.290 (external, sdk-py)"}
            body = b'{"system": "the instructions of the harness"}'
            post(env["ANTHROPIC_BASE_URL"], "/v1/messages", body, headers)
        finally:
            proxies.stop()
    text = (tmp_path / model_api.FILE).read_text()
    assert "instructions" not in text and "teapot" not in text
    row = rows(tmp_path)[0]
    assert (row["harness"], row["result"]) == ("claude-code", None)
    assert row["request_body"]["omitted"] and row["response_body"]["omitted"]
    assert row["response_body"]["size"] == len(b"".join(STREAM))


def test_the_config_and_the_urls() -> None:
    assert model_api.parse(None) == ["anthropic", "openai"]
    assert model_api.parse(True) == ["anthropic", "openai"]
    assert model_api.parse(False) == []
    assert model_api.parse(["openai"]) == ["openai"]
    with pytest.raises(ValueError, match="true, false or a list"):
        model_api.parse(["toy"])
    urls = model_api.backends(["anthropic", "openai"], {"OPENAI_BASE_URL": "https://gw.test/v1/"})
    assert [(b.env, b.url) for b in urls] == [
        ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        ("OPENAI_BASE_URL", "https://gw.test/v1"),
    ]
    with pytest.raises(ValueError, match="ANTHROPIC_BASE_URL"):
        model_api.backends(["anthropic"], {"ANTHROPIC_BASE_URL": "ftp://x"})

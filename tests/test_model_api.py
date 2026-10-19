import hashlib
import http.client
import json
from pathlib import Path

import pytest
from toy_model_server import ModelServer

from nookku import backend, discovery, model_api, trace

TRACE = Path(__file__).resolve().parent.parent / "conformance" / "trace"
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
    apis = model_api.backends([{"api": api, "env": env, "url": None}], {env: model.url})
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


@pytest.mark.parametrize(
    ("case", "count"),
    [("model_api_toy_shop", 4), ("model_api_responses", 3), ("model_api_decisions", 2)],
)
def test_the_parsers_give_the_results_of_the_conformance_case(case: str, count: int) -> None:
    lines = (TRACE / case / model_api.FILE).read_text().split("\n")
    calls = [json.loads(x) for x in lines if x and '"result": {' in x]
    assert len(calls) == count
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
            post(env["ANTHROPIC_BASE_URL"], "/v1/messages?beta=true&key=q-k3y", b"{}", headers)
        finally:
            proxies.stop()
    assert ("x-api-key", "sk-toy-k3y") in model.seen[0]["headers"]
    assert ("Authorization", "Bearer t0k3n") in model.seen[0]["headers"]
    assert model.seen[0]["path"] == "/v1/messages?beta=true&key=q-k3y"
    text = (tmp_path / model_api.FILE).read_text()
    assert "k3y" not in text and "t0k3n" not in text
    assert rows(tmp_path)[0]["query"] == "beta=true&key="


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


def event(kind: str, **fields: object) -> bytes:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **fields})}\n\n".encode()


def test_a_responses_stream_reaches_the_app_and_gives_its_result(tmp_path: Path) -> None:
    item = {"type": "message", "role": "assistant", "content": []}
    parts = [
        event("response.created", response={"model": "gpt-toy", "status": "in_progress"}),
        event("response.output_item.added", output_index=0, item=item),
        event("response.output_text.delta", output_index=0, content_index=0, delta="2 mugs "),
        event("response.output_text.delta", output_index=0, content_index=0, delta="€ left."),
        event("response.completed", response={"status": "completed", "usage": {"x": 1}}),
    ]
    with ModelServer() as model:
        model.parts = parts
        model.release.clear()
        proxies = proxy_for(model, tmp_path, "openai")
        env = proxies.start()
        try:
            conn = connect(env["OPENAI_BASE_URL"])
            conn.request("POST", "/responses", body=b'{"stream": true}', headers={})
            resp = conn.getresponse()
            first = resp.read1(65536)
            model.release.set()
            got = first + resp.read()
            conn.close()
        finally:
            proxies.stop()
    assert first == parts[0] and got == b"".join(parts)
    assert model.seen[0]["path"] == "/responses"
    result = rows(tmp_path)[0]["result"]
    assert (result["model"], result["text"]) == ("gpt-toy", "2 mugs € left.")
    assert (result["stop_reason"], result["usage"]) == ("completed", {"x": 1})


def test_a_responses_stream_that_stops_keeps_its_deltas() -> None:
    call = {"type": "function_call", "call_id": "call_2", "name": "refund", "arguments": ""}
    data = b"".join(
        [
            event("response.output_item.added", output_index=0, item=call),
            event("response.function_call_arguments.delta", output_index=0, delta='{"order": '),
            event("response.function_call_arguments.delta", output_index=0, delta='"5120"}'),
            event("error", code="server_error", message="The server stopped.", param=None),
        ]
    )
    got = model_api.result("openai", "/v1/responses/", data, True)
    assert got is not None
    assert got["tool_calls"] == [{"id": "call_2", "name": "refund", "input": {"order": "5120"}}]
    assert (got["stop_reason"], got["error"]) == (None, "The server stopped.")


def chunk(text: str) -> bytes:
    return f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\n".encode()


def test_the_proxy_reads_a_stream_with_the_parser_of_the_tap() -> None:
    # The line rules of the tap: \r line ends, a comment, and a last event with no blank line.
    body = b": the toy shop\r\r" + chunk("2 mugs").replace(b"\n", b"\r") + b'data: {"choices": []}'
    got = model_api.result("openai", "/v1/chat/completions", body, True)
    assert got is not None and (got["text"], got["error"]) == ("2 mugs", None)
    # An event with the name error sets the error, also if its data is not JSON.
    body = chunk("2 mugs") + b"event: error\ndata: the stock service is down\n\n"
    got = model_api.result("openai", "/v1/chat/completions", body, True)
    assert got is not None and got["error"] == "the stock service is down"


def test_a_stream_that_is_not_utf8_has_an_error_and_no_text() -> None:
    body = chunk("2 mugs") + b'data: {"choices": [{"delta": {"content": "\xff"}}]}\n\n'
    got = model_api.result("openai", "/v1/chat/completions", body, True)
    assert got is not None and (got["text"], got["error"]) == ("", "the stream is not UTF-8")


def test_a_stream_cut_in_a_character_keeps_its_text() -> None:
    # The API stopped after the first byte of the 3 bytes of the euro sign.
    body = chunk("2 mugs") + 'data: {"choices": [{"delta": {"content": "€'.encode()[:-2]
    got = model_api.result("openai", "/v1/chat/completions", body, True)
    assert got is not None and (got["text"], got["error"]) == ("2 mugs", None)


def test_an_incomplete_response_and_the_paths_of_the_responses_api() -> None:
    body = {"model": "gpt-toy", "status": "incomplete", "output": [], "error": None}
    got = model_api.result("openai", "/responses", json.dumps(body).encode(), False)
    assert got is not None and (got["stop_reason"], got["error"]) == ("incomplete", None)
    assert model_api.call_format("openai", "/v1/responses") == "responses"
    assert model_api.call_format("openai", "/v1/responses/resp_1") is None
    assert model_api.call_format("anthropic", "/v1/responses") is None


def test_the_paths_of_the_decisions_api_and_a_body_that_is_not_json() -> None:
    assert model_api.call_format("openai", "/v1/decisions") == "decisions"
    assert model_api.call_format("openai", "/decisions/") == "decisions"
    assert model_api.call_format("openai", "/v1/decisions/dec_1") is None
    assert model_api.call_format("anthropic", "/v1/decisions") is None
    got = model_api.result("openai", "/v1/decisions", b"<html>busy</html>", False)
    assert got is not None and (got["answers"], got["error"]) == ([], "the response is not JSON")


def test_a_decisions_error_and_an_answer_of_a_new_type() -> None:
    body = {
        "error": {"message": "Unknown question type.", "type": "invalid_request_error"},
        "answers": [{"type": "rank", "name": "order", "rank": 2}, "not an answer"],
    }
    # The API reference gives no stream, so a stream body is also read as JSON.
    got = model_api.result("openai", "/v1/decisions", json.dumps(body).encode(), True)
    assert got is not None and got["error"] == "Unknown question type."
    assert got["answers"] == [
        {"type": "rank", "name": "order", "value": None, "probabilities": None, "confidence": None}
    ]


def api(name: str, url: str | None = None, env: str | None = None) -> dict:
    """A model API part of an egress answer (SPEC.md section 7.11)."""
    return {"api": name, "env": env or model_api.APIS[name][0], "url": url}


def test_the_urls_of_the_answer() -> None:
    # The answer and APIS have the same API names.
    assert tuple(model_api.APIS) == discovery.MODEL_APIS
    urls = model_api.backends(
        [api("anthropic"), api("openai")], {"OPENAI_BASE_URL": "https://gw.test/v1/"}
    )
    assert [(b.env, b.url) for b in urls] == [
        ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        ("OPENAI_BASE_URL", "https://gw.test/v1"),
    ]
    # A URL in the answer comes before the variable.
    urls = model_api.backends(
        [api("openai", "http://127.0.0.1:9/v1")], {"OPENAI_BASE_URL": "https://x"}
    )
    assert urls[0].url == "http://127.0.0.1:9/v1"
    # The answer can name another variable. Its value gives the URL.
    urls = model_api.backends([api("openai", env="TOY_LLM_URL")], {"TOY_LLM_URL": "http://h:1/v1"})
    assert (urls[0].env, urls[0].url) == ("TOY_LLM_URL", "http://h:1/v1")
    with pytest.raises(ValueError, match="ANTHROPIC_BASE_URL"):
        model_api.backends([api("anthropic")], {"ANTHROPIC_BASE_URL": "ftp://x"})
    # An empty URL stops the start. It does not fall back to the variable.
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        model_api.backends([api("openai", "")], {"OPENAI_BASE_URL": "https://x"})


def test_a_lone_surrogate_in_a_result_is_written_as_its_escape(tmp_path: Path) -> None:
    answer = {"model": "gpt-toy", "choices": [{"message": {"content": "3 mugs \ud83d left"}}]}
    sent = json.dumps(answer).encode()
    with ModelServer() as model:
        model.parts = [sent]
        model.content_type = "application/json"
        proxies = proxy_for(model, tmp_path, "openai")
        env = proxies.start()
        try:
            status, got = post(env["OPENAI_BASE_URL"], "/chat/completions", b"{}", {})
        finally:
            proxies.stop()
    assert status == 200 and got == sent
    assert rows(tmp_path)[0]["result"]["text"] == "3 mugs \\ud83d left"


def big_stream(count: int) -> list[bytes]:
    """A stream with a long text: one delta event for each part after the first."""
    delta = b'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, '
    parts = [STREAM[0]]
    for n in range(count):
        parts.append(delta + b'"delta": {"type": "text_delta", "text": "mug %05d "}}\n\n' % n)
    return [*parts, STREAM[2]]


def test_a_response_larger_than_the_limit_is_cut_in_the_record_and_named_in_the_trace(
    tmp_path: Path,
) -> None:
    parts = big_stream(2000)
    sent = b"".join(parts)
    with ModelServer() as model:
        model.parts = parts
        proxies = proxy_for(model, tmp_path)
        proxies.proxies[0].keep = 1000
        env = proxies.start()
        try:
            req = b'{"stream": true, "messages": [{"role": "user", "content": "Mugs?"}]}'
            status, got = post(env["ANTHROPIC_BASE_URL"], "/v1/messages", req, {})
        finally:
            proxies.stop()
    # Each byte goes to the app, also after the limit.
    assert status == 200 and got == sent and len(sent) > 100_000
    row = rows(tmp_path)[0]
    body = row["response_body"]
    assert (body["size"], body["sha256"], body["cut"]) == (
        len(sent),
        hashlib.sha256(sent).hexdigest(),
        True,
    )
    assert body["text"].encode() == sent[:1000]
    # The result is of the events that end before the cut.
    kept = model_api.whole_events(sent[:1000])
    shown = model_api.result("anthropic", "/v1/messages", kept, True)
    assert row["result"] == {**shown, "cut": True}
    assert row["result"]["text"].startswith("mug 00000 mug 00001 ")
    assert row["result"]["stop_reason"] is None and row["error"] is None
    items, _ = trace.read_model_api(tmp_path / model_api.FILE)
    assistant = next(it for it in items if it["role"] == "assistant")
    note = f"the record holds the first 1000 of {len(sent)} bytes"
    assert assistant["input"]["cut"] == note and assistant["error"] is None


def test_a_cut_json_response_has_no_json_error() -> None:
    proxy = model_api.ModelProxy.__new__(model_api.ModelProxy)
    proxy.backend = backend.Backend("openai", "OPENAI_BASE_URL", "http://127.0.0.1:1")
    proxy.keep = 10
    row = {"harness": None, "path": "/chat/completions", "response_headers": []}
    proxy.complete(row, b'{"model": ', None, cut=True)
    assert row["result"]["cut"] is True and row["result"]["error"] is None
    proxy.complete(row, b'{"model": ', None)
    assert row["result"]["error"] == model_api.NOT_JSON and "cut" not in row["result"]


def test_whole_events_ends_at_the_last_blank_line() -> None:
    assert (
        model_api.whole_events(b"data: 1\n\ndata: 2\r\n\r\ndata: 3")
        == b"data: 1\n\ndata: 2\r\n\r\n"
    )
    assert model_api.whole_events(b"data: 1\r\ndata: 2\r\n") == b""
    assert model_api.whole_events(b"data: 1\r\rdata") == b"data: 1\r\r"


def test_the_parsers_give_the_results_of_the_cut_case() -> None:
    lines = (TRACE / "model_api_cut" / model_api.FILE).read_text().split("\n")
    calls = [json.loads(x) for x in lines if x]
    # The harness row keeps no text, so it gives no result. The proxy reads each other row with
    # cut=True: a cut body, or a stream that is open at the end of the test.
    calls = [row for row in calls if not row["harness"]]
    assert len(calls) == 3 and [row["response_body"]["cut"] for row in calls] == [True, True, False]
    for row in calls:
        kept = row["response_body"]["text"].encode()
        proxy = model_api.ModelProxy.__new__(model_api.ModelProxy)
        proxy.backend = backend.Backend(row["api"], "UNUSED", "http://127.0.0.1:1")
        got = {**row, "harness": None, "result": None}
        proxy.complete(got, kept, None, cut=True)
        assert got["result"] == row["result"]


def test_a_gzip_bomb_gives_a_cut_result(tmp_path: Path) -> None:
    text = b'{"model": "gpt-toy", "choices": [{"message": {"content": "' + b" " * 5_000_000
    with ModelServer() as model:
        model.parts = [text]
        model.content_type = "application/json"
        model.gzip = True
        proxies = proxy_for(model, tmp_path, "openai")
        proxies.proxies[0].keep = 100_000
        env = proxies.start()
        try:
            status, got = post(env["OPENAI_BASE_URL"], "/chat/completions", b"{}", {})
        finally:
            proxies.stop()
    assert status == 200 and len(got) < 100_000
    row = rows(tmp_path)[0]
    assert row["response_body"]["cut"] is True and row["response_body"]["decoded"] == "gzip"
    assert row["result"]["cut"] is True and row["result"]["error"] is None


@pytest.mark.parametrize("agent", ["claude-cli/2.1.290 (external, sdk-py)", "toy-shop/1.0"])
def test_a_stream_that_is_open_at_the_end_of_the_test_gets_its_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str
) -> None:
    monkeypatch.setattr(backend, "DRAIN", 0.2)
    with ModelServer() as model:
        model.parts = [STREAM[0] + STREAM[1], STREAM[2]]
        model.release.clear()
        proxies = proxy_for(model, tmp_path)
        env = proxies.start()
        conn = connect(env["ANTHROPIC_BASE_URL"])
        conn.request(
            "POST", "/v1/messages", body=b'{"stream": true}', headers={"User-Agent": agent}
        )
        resp = conn.getresponse()
        assert resp.read1(65536) == STREAM[0] + STREAM[1]
        proxies.stop()
        model.release.set()
        conn.close()
    row = rows(tmp_path)[0]
    assert (row["error"], row["stream"]) == (backend.STREAM_ENDED, True)
    if agent.startswith("claude-cli"):
        # A harness call keeps no text, also if the test ends before its stream ends.
        assert "teapot" not in (tmp_path / model_api.FILE).read_text()
        assert row["response_body"]["omitted"] and row["result"] is None
    else:
        result = row["result"]
        assert (result["text"], result["cut"]) == ("3 teapot sets € left.", True)


def test_a_call_that_ends_after_the_end_of_the_test_does_not_change_its_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backend, "DRAIN", 0)
    with ModelServer() as model:
        proxies = proxy_for(model, tmp_path)
        proxies.start()
        proxy = proxies.proxies[0]
        row = {"v": 1, "type": "call", "harness": None, "path": "/v1/messages", "error": None}
        assert proxy.begin(row)
        proxies.stop()
        written = dict(row)
        # The call ends after the proxy wrote its row. The end does not change the row.
        text = {"size": 13, "text": "3 teapot sets"}
        proxy.end(row, {"response_body": text}, b"3 teapot sets", None)
    assert row == written and row["error"] == backend.ENDED
    assert rows(tmp_path) == [written]

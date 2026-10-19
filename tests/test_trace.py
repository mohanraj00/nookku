import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from nookku import discovery, trace

CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "trace").iterdir())


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case(case: Path, tmp_path: Path) -> None:
    folder = tmp_path / "test"
    shutil.copytree(case, folder, ignore=shutil.ignore_patterns("expect_*"))
    report = trace.build(folder)
    assert rows(folder / "trace.jsonl") == rows(case / "expect_trace.jsonl")
    expect = json.loads((case / "expect_findings.json").read_text())
    assert json.loads((folder / "findings.json").read_text()) == expect
    assert report == expect


def test_a_missing_session_file_is_not_an_error(tmp_path: Path) -> None:
    session = {"harness": "codex", "session": "s", "inferred": True, "file": "sessions/codex/x"}
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t", "model_sessions": [session]}))
    report = trace.build(tmp_path)
    assert report["items"] == 0
    assert report["turns"] == 0
    assert report["sessions"][0]["version"] is None
    assert [f["check"] for f in report["findings"]] == ["session_inferred"]


def test_repeated_reply_compares_bytes_and_counts_an_empty_reply() -> None:
    replies = ["", "", "Tea", "tea", "Tea ", None, "Tea", "Tea"]
    found = trace.repeated([{"reply": r} for r in replies], 2)
    assert [(f["turn"], f["turns"]) for f in found] == [(1, [1, 2]), (7, [7, 8])]
    assert found[0]["detail"] == 'the same reply in turns 1 and 2: ""'
    assert trace.repeated([{"reply": r} for r in replies], 0) == []


@pytest.mark.parametrize(
    "keys",
    [None, {}, {"repeated_reply": "3"}, {"repeated_reply": True}, {"repeated_reply": 1}],
)
def test_a_manifest_with_no_valid_repeated_reply_gives_the_default(keys: object) -> None:
    manifest = {"test": "t"} if keys is None else {"test": "t", "trace": keys}
    assert trace.trace_keys(manifest) == trace.TRACE_KEYS


def _message(turn: int, text: str, harness: str = "claude-code") -> dict:
    return {
        "turn": turn,
        "harness": harness,
        "kind": "message",
        "role": "assistant",
        "output": text,
    }


def test_model_texts_skip_other_turns_otel_items_and_empty_texts() -> None:
    items = [
        _message(1, "We sell teapots."),
        _message(1, "  \n"),
        _message(2, "Not this turn."),
        _message(1, "An app log.", harness="otel"),
        {**_message(1, "A tester message."), "role": "user"},
    ]
    assert trace.model_texts(items, 1, "") == ["We sell teapots."]


def test_model_texts_with_a_field_read_json_lists_and_tool_inputs() -> None:
    tool = {"turn": 1, "harness": "codex", "kind": "tool_call", "harness_internal": False}
    items = [
        _message(1, '{"output": {"parts": ["Hi", "Tea"]}}'),
        _message(1, 'Here it is: {"output": {"parts": ["Mug"]}} and more'),
        _message(1, "not JSON {"),
        _message(1, '{"output": {"parts": [7]}}'),
        {**tool, "input": {"output": {"parts": ["Cup"]}}},
        {**tool, "input": {"output": {"parts": ["Search"]}}, "harness_internal": True},
    ]
    assert trace.model_texts(items, 1, "output.parts.0") == ["Hi", "Mug", "Cup"]


def test_reply_not_from_model_normalizes_white_space_and_case() -> None:
    items = [_message(1, "Your  ORDER\nships today.")]
    exchanges = [{"reply": "Hello. your order ships TODAY. Bye."}]
    assert trace.not_from_model(exchanges, items, "", "normalized") == []
    assert [f["turn"] for f in trace.not_from_model(exchanges, items, "", "exact")] == [1]
    assert trace.not_from_model(exchanges, items, "", "off") == []
    assert trace.not_from_model([{"reply": None}], items, "", "exact") == []


@pytest.mark.parametrize(
    "keys",
    [
        {"model_reply_field": "a..b", "model_reply_match": "loose"},
        {"model_reply_field": 7, "model_reply_match": None},
    ],
)
def test_a_manifest_with_wrong_model_reply_keys_gives_the_defaults(keys: dict) -> None:
    assert trace.trace_keys({"trace": keys}) == trace.TRACE_KEYS


def test_summary() -> None:
    report = {"items": 3, "turns": 2, "counts": dict.fromkeys(trace.CHECKS, 0)}
    assert trace.summary(report) == "Trace: 3 model items in 2 turns, no findings."
    report["counts"]["tool_error"] = 2
    assert trace.summary(report) == "Trace: 3 model items in 2 turns, 2 tool_error."


def test_a_file_without_a_version_is_unknown(tmp_path: Path) -> None:
    session = {"harness": "codex", "session": "s", "inferred": False, "file": "rollout.jsonl"}
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t", "model_sessions": [session]}))
    (tmp_path / "rollout.jsonl").write_text('{"type": "world_state"}\n')
    report = trace.build(tmp_path)
    assert report["sessions"][0]["version"] == "unknown"
    assert report["findings"][0]["detail"] == "version unknown, tested: 0.160.0, 0.162.1"


def test_a_tool_result_matches_only_a_call_of_its_format(tmp_path: Path) -> None:
    def call(path: str, request: dict, result: dict) -> dict:
        body = {"text": json.dumps(request), "cut": False}
        return {
            "type": "call",
            "api": "openai",
            "path": path,
            "request_body": body,
            "result": result,
        }

    lookup = {"id": "call_1", "name": "lookup_order", "input": {"order": "4471"}}
    rows = [
        call("/v1/chat/completions", {"messages": []}, {"tool_calls": [lookup]}),
        call("/v1/responses", {"input": []}, {"tool_calls": [lookup]}),
        call(
            "/v1/responses",
            {"input": [{"type": "function_call_output", "call_id": "call_1", "output": "shipped"}]},
            {},
        ),
    ]
    path = tmp_path / "model_api.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    items, _ = trace.read_model_api(path)
    tools = [it for it in items if it["kind"] == "tool_call"]
    assert [it.get("output") for it in tools] == [None, "shipped"]


def test_a_decisions_request_keeps_no_image_data(tmp_path: Path) -> None:
    request = {
        "input": [
            {"role": "system", "content": "not a user message"},
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": "data:image/jpeg;base64,dG95"},
                    {"type": "input_image", "image_url": "data:image/png;base64,not base64!"},
                    {"type": "input_image", "image_url": "data:image/png;base64,é"},
                    {"type": "input_image", "image_url": "https://shop.test/mug.png"},
                ],
            },
        ],
        "questions": [{"type": "choice", "name": "mug", "choices": "not a list"}, "not a dict"],
    }
    row = {
        "type": "call",
        "api": "openai",
        "path": "/v1/decisions",
        "request_body": {"text": json.dumps(request), "cut": False},
        "result": None,
    }
    path = tmp_path / "model_api.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    items, _ = trace.read_model_api(path)
    assert items[0]["output"] is None
    assert items[0]["input"] == {
        "questions": [{"name": "mug", "type": "choice", "options": None}],
        "images": [
            {
                "media_type": "image/jpeg",
                "size": 3,
                "sha256": "0f53133ce57ca8e8937bb4b1c15a33ef9594704e1c11abd58e598bb8362f7385",
            },
            {"media_type": "image/png", "size": None, "sha256": None},
            {"media_type": "image/png", "size": None, "sha256": None},
            {"media_type": None, "size": None, "sha256": None},
        ],
    }
    assert items[1]["input"]["answers"] == []
    assert "dG95" not in json.dumps(items)


def test_a_lone_surrogate_in_a_source_is_written_as_its_escape(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t", "model_sessions": []}))
    request = {"messages": [{"role": "user", "content": "a mug \udc00"}]}
    row = {
        "v": 1,
        "type": "call",
        "api": "openai",
        "path": "/v1/chat/completions",
        "started": 4.0,
        "ts": 5.0,
        "request_body": {"text": json.dumps(request), "cut": False},
        "status": 200,
        "error": None,
        "result": {"model": "gpt-toy", "text": "mug \ud83d", "tool_calls": []},
    }
    # json.dumps escapes each lone surrogate, so the file is valid UTF-8.
    (tmp_path / "model_api.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    trace.build(tmp_path)
    outputs = [it["output"] for it in rows(tmp_path / "trace.jsonl")]
    assert outputs == ["a mug \\udc00", "mug \\ud83d"]


@pytest.mark.parametrize("as_json", [False, True])
def test_the_trace_command_prints_a_lone_surrogate_as_its_escape(
    tmp_path: Path, as_json: bool
) -> None:
    folder = tmp_path / ".nookku" / "tests" / "t"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"test": "t", "model_sessions": []}))
    request = {"messages": [{"role": "user", "content": "a mug"}]}
    row = {
        "v": 1,
        "type": "call",
        "api": "openai",
        "path": "/v1/chat/completions",
        "started": 4.0,
        "ts": 5.0,
        "request_body": {"text": json.dumps(request), "cut": False},
        "status": 500,
        "error": "the stock service \udc00 is down",
        "result": None,
    }
    (folder / "model_api.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    argv = [sys.executable, "-m", "nookku", "trace", "t", "--root", str(tmp_path)]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8:strict"}
    p = subprocess.run(argv + ["--json"] * as_json, capture_output=True, env=env)
    assert p.returncode == 0, p.stderr
    assert "the stock service \\udc00 is down" in p.stdout.decode("utf-8").replace("\\\\", "\\")


def test_a_blank_line_is_counted_and_the_end_of_the_file_is_not(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text('{"type": "session_meta"}\n\n \t\r\n{"type": "turn_context"}\n')
    _, info = trace.read_codex(rollout, "s", "f")
    assert info["ignored"] == {"blank": 2, "session_meta": 1, "turn_context": 1}
    backend_file = tmp_path / "backend.jsonl"
    backend_file.write_text('\n{"type": "start"}\n')
    _, info = trace.read_backend(backend_file)
    assert (info["rows"], info["ignored"]) == (1, {"blank": 1, "start": 1})


def test_a_url_that_does_not_parse_gives_a_call_with_no_address() -> None:
    span = trace._item("otel", "t", "otel.jsonl", 1, 1.0)
    span.update(kind="span", input={"url.full": "http://["})
    (finding,) = trace.unseen_calls([span], set())
    assert finding["detail"] == (
        "HTTP (a URL that does not parse) at no network address: no proxy saw this call"
    )


def _db_span(line: int, ts: float, attrs: dict) -> dict:
    span = trace._item("otel", "t", "otel.jsonl", line, ts)
    span.update(kind="span", input=attrs)
    return span


def test_a_driver_database_does_not_hide_a_call_around_the_proxy() -> None:
    shop = {"name": "shop", "kind": "postgres", "env": "DATABASE_URL", "address": None}
    cart = {"name": "cart", "kind": "sqlite", "env": None, "address": None, "record": "driver"}
    around = {"db.system.name": "postgresql", "server.address": "db.toy.test", "server.port": 5432}
    spans = [_db_span(1, 1.0, around)]

    def seen(*databases: dict) -> set[str]:
        answer = {"databases": list(databases)}
        proxies = {"shop": "postgresql://127.0.0.1:41002"}
        manifest = {"egress": {"answer": answer, "proxies": proxies, "receiver": None}}
        found = trace.egress_seen(manifest)
        assert found is not None
        return found

    assert len(trace.unseen_calls(spans, seen({**shop, "record": "proxy"}))) == 1
    assert len(trace.unseen_calls(spans, seen({**shop, "record": "proxy"}, cart))) == 1
    sqlite = [_db_span(2, 2.0, {"db.system": "sqlite"})]
    assert trace.unseen_calls(sqlite, seen({**shop, "record": "proxy"}, cart)) == []


def test_a_driver_address_is_seen_only_for_its_system_and_database() -> None:
    shop = {"name": "shop", "kind": "postgres", "env": "DATABASE_URL", "address": None}
    stock = {"name": "stock", "kind": "postgres", "env": None, "record": "driver"}
    server = {"server.address": "db.toy.test", "server.port": 5432}
    pg = {"db.system.name": "postgresql", **server}

    def unseen(address: str, *attrs: dict) -> list[int]:
        answer = {"databases": [{**shop, "record": "proxy"}, {**stock, "address": address}]}
        proxies = {"shop": "postgresql://127.0.0.1:41002"}
        manifest = {"egress": {"answer": answer, "proxies": proxies, "receiver": None}}
        seen = trace.egress_seen(manifest)
        assert seen is not None
        spans = [_db_span(n, float(n), a) for n, a in enumerate(attrs, 1)]
        return [f["source"]["line"] for f in trace.unseen_calls(spans, seen)]

    http = {"url.full": "http://db.toy.test:5432/"}
    mysql = {**server, "db.system.name": "mysql"}
    assert unseen("db.toy.test:5432", pg, http, mysql) == [2, 3]
    stock_call, shop_call = {**pg, "db.namespace": "stock"}, {**pg, "db.name": "shop"}
    assert unseen("DB.toy.test:5432/stock", stock_call, shop_call, pg) == [2, 3]


def test_a_driver_database_next_to_a_proxy_needs_a_host_and_port() -> None:
    shop = {"name": "shop", "kind": "postgres", "env": "DATABASE_URL", "address": None}
    stock = {"name": "stock", "kind": "Postgres", "env": None, "record": "driver"}
    for address in [None, "db.toy.test/stock", "postgres://db.toy.test/stock", "db:0"]:
        databases = [{**shop, "record": "proxy"}, {**stock, "address": address}]
        with pytest.raises(discovery.AnswerError, match="needs the address host:port"):
            discovery.parse(discovery.make(databases=databases))
    for address in ["db.toy.test:5432", "[::1]:5432/stock"]:
        databases = [{**shop, "record": "proxy"}, {**stock, "address": address}]
        discovery.parse(discovery.make(databases=databases))
    discovery.parse(discovery.make(databases=[{**stock, "address": None}]))


def test_each_driver_query_comes_right_after_its_span() -> None:
    spans = [
        _db_span(1, 5.0, {"db.system.name": "sqlite", "db.query.text": "SELECT 1"}),
        _db_span(2, 5.0, {"db.system.name": "sqlite", "db.query.text": "INSERT INTO cart"}),
    ]
    items = trace.with_driver_queries(spans)
    items.sort(key=lambda it: it["ts"])
    assert [(it["kind"], it["source"]["line"]) for it in items] == [
        ("span", 1),
        ("query", 1),
        ("span", 2),
        ("query", 2),
    ]

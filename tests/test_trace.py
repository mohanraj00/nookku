import json
import shutil
from pathlib import Path

import pytest

from verbatim_relay import trace

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
    assert report["findings"][0]["detail"] == "version unknown, tested: 0.160.0"


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

"""Checks of the print mode spike's private request summary (#199). No model calls."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import spike_print_mode as spike


def title_body(properties: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "model": "toy-model",
            "system": [{"type": "text", "text": "private title instructions"}],
            "messages": [{"role": "user", "content": f"<session>{spike.FIRST}</session>"}],
            "tools": [],
            "output_config": {
                "format": {"type": "json_schema", "schema": {"properties": properties}}
            },
        }
    ).encode()


def test_a_title_request_is_matched_and_keeps_no_instructions() -> None:
    row: dict[str, object] = {}
    # describe uses no state of the server, so the test needs no open port.
    proxy = object.__new__(spike.Proxy)
    spike.Proxy.marks = (spike.FIRST_MARK, spike.SECOND_MARK)
    proxy.describe(row, [("x-api-key", "toy-secret")], title_body({"title": {}}))
    summary = row["request_body"]
    assert summary["title_schema"] is True
    assert summary["found"] == {spike.FIRST_MARK: ["messages[0].user"], spike.SECOND_MARK: []}
    assert "title_description_schema" not in summary
    text = json.dumps(row)
    assert "private title instructions" not in text and "toy-secret" not in text


def test_only_a_schema_with_one_title_property_is_a_title_request() -> None:
    assert spike.title_schema(title_body({"title": {}}))
    assert not spike.title_schema(title_body({"title": {}, "description": {}}))
    assert not spike.title_schema(b'{"model": "toy-model"}')
    assert not spike.title_schema(b"not json")

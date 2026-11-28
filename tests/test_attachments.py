"""Attachments in the records, the audit and the tap (SPEC.md sections 2.4, 3.2 and 4.1)."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from test_tap import agent, handle_post, post, run_tap  # noqa: F401 (agent is a fixture)

from nookku.adapters import ATTACHMENT_BYTES, ATTACHMENT_COUNT, AdapterError, make
from nookku.audit import audit, render
from nookku.record import (
    Exchange,
    RecordError,
    Unparsed,
    Writer,
    attachment_path,
    read_rows,
    read_tap,
    write_attachment,
)

ROOT = Path(__file__).resolve().parent.parent
# The toy PNG of the conformance cases: a photo of a mug, 1 pixel.
CLEAN = ROOT / "conformance" / "cases" / "attachment_clean"
MUG = next((CLEAN / "relay.attachments").iterdir()).read_bytes()
ASK, REPLY = "Is this my mug?", "Yes, that is your mug."


def records(folder: Path, image: bytes = MUG) -> tuple[Path, Path]:
    tap, relay = Writer(folder / "tap.jsonl"), Writer(folder / "relay.jsonl")
    sent = write_attachment(relay.path, "image/png", image)
    got = write_attachment(tap.path, "image/png", image)
    relay.append(
        {"type": "turn", "harness": "codex", "said": ASK, "shown": REPLY, "attachments": [sent]}
    )
    tap.append(
        {"type": "exchange", "input": ASK, "status": 200, "reply": REPLY, "attachments": [got]}
    )
    return tap.path, relay.path


def test_the_records_give_the_same_hash_media_type_and_size(tmp_path):
    tap, relay = records(tmp_path)
    digest = hashlib.sha256(MUG).hexdigest()
    want = {"media_type": "image/png", "bytes": len(MUG), "sha256": digest}
    for kind, path in (("tap", tap), ("relay", relay)):
        [(_, row)] = read_rows(kind, path)
        assert row["v"] == "0.5" and row["attachments"] == [want]
        assert (tmp_path / f"{kind}.attachments" / digest).read_bytes() == MUG
    report = audit(tap, relay)
    assert report.exit == 0 and report.breaks == []


def test_one_changed_byte_of_a_side_file_is_an_altered_image(tmp_path):
    tap, relay = records(tmp_path)
    side = attachment_path(tap, hashlib.sha256(MUG).hexdigest())
    side.write_bytes(MUG[:-1] + bytes([MUG[-1] ^ 1]))
    report = audit(tap, relay)
    assert report.exit == 1
    [found] = report.breaks
    assert [found.kind, found.relay_line, found.tap_line] == ["altered_attachment_file", None, 1]
    assert found.evidence["record"] == "tap" and found.evidence["actual_bytes"] == len(MUG)
    assert found.evidence["actual_sha256"] == hashlib.sha256(side.read_bytes()).hexdigest()
    assert f"the side file tap.attachments/{side.name} is altered" in render(report)


def test_a_missing_side_file_is_a_break(tmp_path):
    tap, relay = records(tmp_path)
    attachment_path(relay, hashlib.sha256(MUG).hexdigest()).unlink()
    report = audit(tap, relay)
    [found] = report.breaks
    assert [found.kind, found.relay_line, found.tap_line] == ["missing_attachment_file", 1, None]
    assert found.evidence["actual_sha256"] is None
    assert "relay.attachments/" in render(report) and "does not exist" in render(report)


@pytest.mark.parametrize("record", ["tap", "relay"])
def test_the_audit_reports_a_symlink_side_file_as_altered(tmp_path, record):
    tap, relay = records(tmp_path)
    side = attachment_path(tmp_path / f"{record}.jsonl", hashlib.sha256(MUG).hexdigest())
    target = tmp_path / "the-mug.png"
    side.rename(target)
    side.symlink_to(target)

    report = audit(tap, relay)

    [found] = report.breaks
    assert report.exit == 1 and found.kind == "altered_attachment_file"
    assert (found.relay_line, found.tap_line) == ((None, 1) if record == "tap" else (1, None))
    assert found.evidence["actual_sha256"] is None
    assert found.evidence["actual_bytes"] is None
    assert "it is a symlink" in found.evidence["detail"]


def test_another_image_at_the_agent_is_an_altered_attachment(tmp_path):
    tap, relay = records(tmp_path)
    other = MUG[:-1] + bytes([MUG[-1] ^ 1])
    rows = [json.loads(line) for line in tap.read_text().splitlines()]
    rows[0]["attachments"] = [write_attachment(tap, "image/png", other)]
    tap.write_text(json.dumps(rows[0]) + "\n")
    [found] = audit(tap, relay).breaks
    assert found.kind == "altered_attachment"
    assert found.evidence["expected"]["sha256"] == hashlib.sha256(MUG).hexdigest()
    assert found.evidence["actual"]["sha256"] == hashlib.sha256(other).hexdigest()


def test_a_row_with_no_attachment_does_not_change(tmp_path):
    tap, relay = Writer(tmp_path / "tap.jsonl"), Writer(tmp_path / "relay.jsonl")
    tap.append({"type": "exchange", "input": ASK, "status": 200, "reply": REPLY})
    relay.append({"type": "turn", "harness": "codex", "said": ASK, "shown": REPLY})
    [(_, row)] = read_rows("tap", tap.path)
    assert row["v"] == "0.2" and "attachments" not in row
    assert read_tap(tap.path) == [Exchange(1, ASK, 200, REPLY)]
    assert audit(tap.path, relay.path).exit == 0
    assert not (tmp_path / "tap.attachments").exists()


def test_the_v01_records_of_the_conformance_cases_stay_valid():
    case = ROOT / "conformance" / "cases" / "clean"
    assert all(row["v"] == "0.1" for _, row in read_rows("tap", case / "tap.jsonl"))
    assert audit(case / "tap.jsonl", case / "relay.jsonl").exit == 0


def test_two_equal_images_use_one_side_file(tmp_path):
    record = tmp_path / "tap.jsonl"
    first = write_attachment(record, "image/png", MUG)
    assert write_attachment(record, "image/png", MUG) == first
    assert [p.name for p in (tmp_path / "tap.attachments").iterdir()] == [first["sha256"]]


def test_a_media_type_must_be_lower_case(tmp_path):
    with pytest.raises(ValueError, match="lower-case"):
        write_attachment(tmp_path / "tap.jsonl", "image/PNG", MUG)


@pytest.mark.parametrize(
    "attachments, reason",
    [
        ([], "a list of 1 or more"),
        ({"media_type": "image/png"}, "a list of 1 or more"),
        ([{"media_type": "image/png", "bytes": 1, "sha256": "0" * 64, "name": "x"}], "exactly"),
        ([{"media_type": "png", "bytes": 1, "sha256": "0" * 64}], "media type"),
        ([{"media_type": "image/png", "bytes": -1, "sha256": "0" * 64}], "size"),
        ([{"media_type": "image/png", "bytes": True, "sha256": "0" * 64}], "size"),
        ([{"media_type": "image/png", "bytes": 1, "sha256": "A" * 64}], "sha256"),
    ],
)
def test_the_reader_checks_the_form_of_the_attachments(tmp_path, attachments, reason):
    path = tmp_path / "relay.jsonl"
    row = {
        "v": "0.5",
        "type": "turn",
        "ts": 1.0,
        "harness": "codex",
        "said": ASK,
        "said_sha256": hashlib.sha256(ASK.encode()).hexdigest(),
        "shown": None,
        "shown_sha256": None,
        "attachments": attachments,
    }
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(RecordError, match=reason) as caught:
        read_rows("relay", path)
    assert caught.value.kind == "record_invalid"


def image_part(url: str) -> dict:
    return {"type": "image_url", "image_url": {"url": url}}


def openai_body(*images: str) -> bytes:
    content = [{"type": "text", "text": ASK}, *(image_part(u) for u in images)]
    return json.dumps({"messages": [{"role": "user", "content": content}]}).encode()


DATA_URL = "data:image/PNG;base64," + base64.b64encode(MUG).decode()


def test_the_openai_adapter_gives_the_text_and_each_image():
    adapter = make("openai")
    body = openai_body(DATA_URL, DATA_URL)
    assert adapter.message(body) == ASK
    assert adapter.attachments(body) == [("image/png", MUG), ("image/png", MUG)]
    assert make("json").attachments(b'{"text": "hi"}') == []


@pytest.mark.parametrize(
    "url, reason",
    [
        ("https://shop.example/mug.png", "a base64 data URL"),
        ("data:;base64,AAAA", "a base64 data URL"),
        ("data:image/png;name=mug.png;base64,AAAA", "a base64 data URL"),
        ("data:image/png;base64,not base64!", "not valid"),
        ("data:image/png;base64,\u00e9", "not valid"),
    ],
)
def test_the_openai_adapter_refuses_an_image_that_it_cannot_record(url, reason):
    with pytest.raises(AdapterError, match=reason):
        make("openai").attachments(openai_body(url))


def test_the_openai_adapter_still_needs_one_text_part():
    content = [image_part(DATA_URL)]
    body = json.dumps({"messages": [{"role": "user", "content": content}]}).encode()
    with pytest.raises(AdapterError, match="exactly one text part"):
        make("openai").message(body)


def test_the_tap_records_the_image_that_the_agent_received(agent, tmp_path):  # noqa: F811
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    body = openai_body(DATA_URL)
    status, _, _ = post(tap, "/v1/chat/completions", body)
    tap.shutdown()
    assert status == 200 and agent.received[0]["body"] == body
    [row] = read_tap(tmp_path / "tap.jsonl")
    digest = hashlib.sha256(MUG).hexdigest()
    assert isinstance(row, Exchange) and row.input == ASK and row.status == 200
    assert row.attachments == ({"media_type": "image/png", "bytes": len(MUG), "sha256": digest},)
    assert (tmp_path / "tap.attachments" / digest).read_bytes() == MUG


def test_the_tap_replaces_a_symlink_side_file(tmp_path):
    record = tmp_path / "tap.jsonl"
    side = attachment_path(record, hashlib.sha256(MUG).hexdigest())
    side.parent.mkdir()
    target = tmp_path / "the-mug.png"
    target.write_bytes(MUG)
    side.symlink_to(target)
    body = openai_body(DATA_URL)
    response, connect = handle_post(record, "/v1/chat/completions", body, adapter="openai")
    assert response.startswith(b"HTTP/1.1 200 ")
    assert connect.return_value.request.call_args.kwargs["body"] == body
    assert not side.is_symlink()
    assert side.read_bytes() == target.read_bytes() == MUG
    [row] = read_tap(record)
    assert isinstance(row, Exchange) and row.attachments[0]["sha256"] == side.name


@pytest.mark.parametrize("limit", ["count", "decoded bytes"])
@pytest.mark.parametrize("over_limit", [False, True])
def test_the_tap_checks_each_attachment_limit(tmp_path, limit, over_limit):
    record = tmp_path / "tap.jsonl"
    if limit == "count":
        images = [DATA_URL] * ATTACHMENT_COUNT
    else:
        half = b"m" * (ATTACHMENT_BYTES // 2)
        image = "data:image/png;base64," + base64.b64encode(half).decode()
        images = [image, image]
    if over_limit:
        images.append(DATA_URL)
    body = openai_body(*images)
    response, connect = handle_post(record, "/v1/chat/completions", body, adapter="openai")

    if not over_limit:
        assert response.startswith(b"HTTP/1.1 200 ")
        assert connect.return_value.request.call_args.kwargs["body"] == body
        [row] = read_tap(record)
        assert isinstance(row, Exchange) and len(row.attachments) == len(images)
        return
    assert response.startswith(b"HTTP/1.1 413 ")
    reason = b"decoded bytes" if limit == "decoded bytes" else b"attachments"
    assert reason in response
    connect.assert_not_called()
    assert not record.exists()
    assert not (tmp_path / "tap.attachments").exists()


def test_the_tap_marks_an_image_with_a_web_url_unparsed(agent, tmp_path):  # noqa: F811
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    status, _, _ = post(tap, "/v1/chat/completions", openai_body("https://shop.example/mug.png"))
    tap.shutdown()
    assert status == 200
    [row] = read_tap(tmp_path / "tap.jsonl")
    assert isinstance(row, Unparsed) and "base64 data URL" in row.error


def test_the_tap_sends_nothing_if_it_cannot_write_a_side_file(agent, tmp_path):  # noqa: F811
    # A file at the place of the folder: the tap cannot write the side file.
    (tmp_path / "tap.attachments").write_text("not a folder")
    tap = run_tap(agent.url, tmp_path / "tap.jsonl", "openai")
    status, _, out = post(tap, "/v1/chat/completions", openai_body(DATA_URL))
    tap.shutdown()
    assert status == 502 and b"tap.jsonl" in out
    assert agent.received == []
    assert not (tmp_path / "tap.jsonl").exists()

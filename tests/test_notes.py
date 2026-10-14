"""The notes of the tester (#352): the notes record, the page routes, fail closed at the end of a
test, the seal of notes.jsonl, and the evaluation prompt."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from test_page import TOY_ENTRY, base, make_folder, request, send, start_page, write_current

from nookku import bridge, evaluation, kit, notes, page, seal, state
from nookku.record import RecordError, read_rows, turns
from nookku.stdio import Agent, StdioTap, start_in_thread

ROOT = Path(__file__).resolve().parent.parent
CASES = sorted((ROOT / "conformance" / "notes").iterdir())


@pytest.fixture(autouse=True)
def no_harness_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in page.HARNESS_SHELL:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_conformance(case: Path) -> None:
    expect = json.loads((case / "expect.json").read_text(encoding="utf-8"))
    path = case / "notes.jsonl"
    try:
        rows = read_rows("notes", path, missing_ok=True)
    except RecordError as e:
        assert e.kind == expect["error"]
        assert f": line {expect['line']}: " in str(e)
        return
    assert "error" not in expect
    keys = ("turn", "rating", "comment")
    assert [{k: r[k] for k in keys} for _, r in rows] == expect["notes"]


@pytest.fixture
def shop(tmp_path: Path) -> Iterator[tuple[Path, page.PageServer, Path]]:
    """A running test of the toy shop entry behind a real stdio tap, a page server, and 2 turns."""
    folder = make_folder(tmp_path)
    agent = Agent([sys.executable, str(TOY_ENTRY)], tmp_path, folder / "app.log", timeout=30)
    tap = StdioTap(("127.0.0.1", 0), agent, folder / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    write_current(tmp_path, folder, tap.url, tap.token)
    kit.set_mode(tmp_path, True)
    server = start_page(tmp_path)
    try:
        for said in ("Where is my order 4471?", "Can I return the teapot?"):
            assert send(server, said)["sent"] is True
        yield tmp_path, server, folder
    finally:
        server.shutdown()
        server.server_close()
        tap.shutdown()
        agent.stop(grace=1)


# The test of the shop fixture (test_page.make_folder).
SHOP_TEST = "20261013-090000-ab12"


def post_note(
    server: page.PageServer, body: Any, test: str | None = SHOP_TEST
) -> tuple[int, dict[str, Any]]:
    """Post a note. A dict body gets the test id that the page shows, if it has none."""
    if isinstance(body, dict) and test is not None:
        body = {"test": test, **body}
    status, _, data = request(server, "POST", base(server) + notes.ADD_ROUTE, body)
    answer: dict[str, Any] = json.loads(data)
    return status, answer


def saved(folder: Path) -> list[tuple[int, str | None, str | None]]:
    rows = read_rows("notes", folder / notes.NOTES, missing_ok=True)
    return [(r["turn"], r["rating"], r["comment"]) for _, r in rows]


def test_a_note_goes_to_notes_jsonl_and_not_to_the_two_records(shop: Any) -> None:
    _, server, folder = shop
    relay, tap = (folder / "relay.jsonl").read_bytes(), (folder / "tap.jsonl").read_bytes()
    comment = "  Wrong date.\n\nThe order ships on Monday, not Friday.  "
    assert post_note(server, {"turn": 1, "rating": "up", "comment": None}) == (
        200,
        {"saved": True, "error": None},
    )
    assert post_note(server, {"turn": 2, "rating": "down", "comment": comment})[1]["saved"]
    # A later note of turn 2 keeps the earlier one in the record.
    assert post_note(server, {"turn": 2, "rating": None, "comment": "Still wrong."})[1]["saved"]
    assert saved(folder) == [(1, "up", None), (2, "down", comment), (2, None, "Still wrong.")]
    assert (folder / "relay.jsonl").read_bytes() == relay
    assert (folder / "tap.jsonl").read_bytes() == tap
    status, _, body = request(server, "GET", base(server) + notes.VIEW_ROUTE)
    shown = json.loads(body)
    assert status == 200 and shown["running"] is True and shown["test"] == folder.name
    assert [(n["turn"], n["rating"], n["comment"]) for n in shown["notes"]] == saved(folder)


@pytest.mark.parametrize(
    "body",
    [
        [1, "up"],
        {"rating": "up"},
        {"turn": 0, "rating": "up"},
        {"turn": True, "rating": "up"},
        {"turn": "1", "rating": "up"},
        {"turn": 1.0, "rating": "up"},
        {"turn": 1, "rating": "meh"},
        {"turn": 1, "rating": None, "comment": None},
        {"turn": 1, "rating": None, "comment": ""},
        {"turn": 1, "rating": "up", "comment": 5},
        {"turn": 1, "rating": None, "comment": "x" * (notes.MAX_COMMENT + 1)},
    ],
)
def test_a_note_that_breaks_the_rule_gets_400_and_no_row(shop: Any, body: Any) -> None:
    _, server, folder = shop
    status, answer = post_note(server, body)
    assert status == 400 and answer["error"].startswith("nookku page: ")
    assert not (folder / notes.NOTES).exists()


@pytest.mark.parametrize("test", [None, 7])
def test_a_note_needs_the_id_of_the_test_that_the_page_shows(shop: Any, test: Any) -> None:
    _, server, folder = shop
    body = {"turn": 1, "rating": "up", "comment": None}
    status, answer = post_note(server, body if test is None else {**body, "test": test}, None)
    assert status == 400 and answer["error"].startswith("nookku page: ")
    assert not (folder / notes.NOTES).exists()


def test_a_comment_with_a_lone_surrogate_gets_400(shop: Any) -> None:
    _, server, folder = shop
    data = (
        b'{"test": "%s", "turn": 1, "rating": "up", "comment": "Hi \\ud83d"}' % SHOP_TEST.encode()
    )
    status, answer = post_note(server, data)
    assert status == 400 and "lone surrogate U+D83D" in answer["error"]
    assert not (folder / notes.NOTES).exists()


def test_a_test_id_with_a_lone_surrogate_gets_400(shop: Any) -> None:
    # The answer for another test names the test, and UTF-8 cannot encode a lone surrogate.
    _, server, folder = shop
    data = b'{"test": "x\\ud83d", "turn": 1, "rating": "up", "comment": null}'
    status, answer = post_note(server, data)
    assert status == 400 and "lone surrogate U+D83D" in answer["error"]
    assert not (folder / notes.NOTES).exists()


def test_a_note_needs_a_turn_of_the_relay_record(shop: Any) -> None:
    _, server, folder = shop
    status, answer = post_note(server, {"turn": 3, "rating": "up", "comment": None})
    assert status == 200 and answer == {"saved": False, "error": notes.NO_TURN.format(turn=3)}
    assert not (folder / notes.NOTES).exists()


def test_a_note_for_another_test_is_refused(shop: Any) -> None:
    # The page can still show an earlier test, with turns of the same numbers.
    _, server, folder = shop
    answer = post_note(
        server, {"turn": 1, "rating": "up", "comment": None}, "20261012-080000-0000"
    )[1]
    other = notes.OTHER_TEST.format(shown="20261012-080000-0000", current=SHOP_TEST)
    assert answer == {"saved": False, "error": other}
    assert not (folder / notes.NOTES).exists()


def test_a_broken_relay_record_gives_no_note(shop: Any) -> None:
    _, server, folder = shop
    with (folder / "relay.jsonl").open("a") as f:
        f.write("not json\n")
    answer = post_note(server, {"turn": 1, "rating": "up", "comment": None})[1]
    assert answer["saved"] is False and answer["error"].startswith("nookku: the page cannot read")
    assert not (folder / notes.NOTES).exists()


def test_with_no_test_no_note_is_written(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    server = start_page(tmp_path)
    try:
        answer = post_note(server, {"turn": 1, "rating": "up", "comment": None})[1]
        assert answer == {"saved": False, "error": notes.NO_TEST}
        assert list((tmp_path / ".nookku").rglob(notes.NOTES)) == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("closed", ["ended", "audit.json", "seal.json", "no manifest"])
def test_no_note_after_the_end_began(shop: Any, closed: str) -> None:
    _, server, folder = shop
    if closed == "ended":
        (folder / "manifest.json").write_text(json.dumps({"started": 1.0, "ended": 2.0}))
    elif closed == "no manifest":
        (folder / "manifest.json").unlink()
    else:
        (folder / closed).write_text("{}")
    answer = post_note(server, {"turn": 1, "rating": "down", "comment": "Late."})[1]
    assert answer == {"saved": False, "error": notes.CLOSED}
    assert not (folder / notes.NOTES).exists()


def test_a_note_waits_for_the_end_and_then_sees_the_closed_test(shop: Any) -> None:
    root, server, folder = shop
    # The end of the test holds the send lock from the tap shutdown to the seal.
    lock = state.lock_sends(root)
    answers: list[dict[str, Any]] = []
    body = {"turn": 1, "rating": "up", "comment": None}
    thread = threading.Thread(target=lambda: answers.append(post_note(server, body)[1]))
    thread.start()
    thread.join(timeout=1)
    assert thread.is_alive() and answers == []
    (folder / "seal.json").write_text("{}")
    os.close(lock)
    thread.join(timeout=30)
    assert answers == [{"saved": False, "error": notes.CLOSED}]
    assert not (folder / notes.NOTES).exists()


def test_the_notes_files_have_no_html_from_text_and_the_csp(tmp_path: Path) -> None:
    folder = resources.files("nookku").joinpath("page")
    for name in ("notes.js", "notes.css"):
        text = folder.joinpath(name).read_text()
        assert not re.search(r"https?://", text)
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text
        assert "outerHTML" not in text
    server = start_page(tmp_path)
    try:
        for path in ("notes.js", "notes.css", notes.VIEW_ROUTE):
            status, headers, _ = request(server, "GET", base(server) + path)
            assert status == 200
            assert headers["content-security-policy"] == page.CSP
        # A note needs the token and the Origin, as a send does.
        body = {"test": SHOP_TEST, "turn": 1, "rating": "up", "comment": None}
        assert request(server, "POST", "/p/wrong/" + notes.ADD_ROUTE, body)[0] == 404
        assert (
            request(server, "POST", base(server) + notes.ADD_ROUTE, body, {"Origin": ""})[0] == 403
        )
    finally:
        server.shutdown()
        server.server_close()


def test_a_toy_shop_test_with_2_notes_is_sealed_and_evaluated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_ENTRY)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    kit.set_mode(root, True)
    server = start_page(root)
    try:
        for said in ("Where is my order 4471?", "Can I return the teapot?"):
            assert send(server, said)["ok"] is True
        up = {"turn": 1, "rating": "up", "comment": None}
        assert post_note(server, up, folder.name)[1]["saved"]
        body = {"turn": 2, "rating": "down", "comment": "It did not say how to return it."}
        assert post_note(server, body, folder.name)[1]["saved"]
        manifest = bridge.end(root)
        assert manifest is not None
        # After the end, the page writes no note.
        late = post_note(server, {"turn": 1, "rating": "down", "comment": None}, folder.name)[1]
        assert late["saved"] is False
    finally:
        server.shutdown()
        server.server_close()
    assert len(turns(folder / "relay.jsonl")) == 2
    assert saved(folder) == [(1, "up", None), (2, "down", "It did not say how to return it.")]
    sealed = json.loads((folder / "seal.json").read_text())["files"]
    assert notes.NOTES in sealed
    assert seal.verify(folder)["intact"]
    prompt = evaluation.prompt(folder)
    assert "notes.jsonl" in prompt and "Tester notes" in prompt
    assert evaluation.transcript(folder).startswith("Seal: intact")
    # A change to notes.jsonl after the end breaks the seal.
    path = folder / notes.NOTES
    path.write_text(path.read_text().replace('"down"', '"up"'))
    result = seal.verify(folder)
    assert not result["intact"] and result["changed"] == [notes.NOTES]


def test_an_invalid_notes_record_makes_the_transcript_invalid(tmp_path: Path) -> None:
    folder = tmp_path / "20261013-090000-ab12"
    folder.mkdir()
    (folder / "notes.jsonl").write_text('{"v": "0.2", "type": "note", "turn": 1}\n')
    text = evaluation.transcript(folder)
    assert text.startswith("Record: INVALID. ")
    assert "notes.jsonl: line 1: missing field 'ts'" in text.split("\n")[0]

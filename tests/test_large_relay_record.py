import io
import json
from pathlib import Path
from urllib.request import Request

import pytest

from nookku import cli, contract, kit
from nookku.record import Turn, Writer, turns

STOCK_LIST = "Mug " * (512 * 1024)
LAST_TURN = ("Is the blue mug in stock?", "The blue mug is in stock.")
TURNS = [
    ("List the mugs.", STOCK_LIST),
    ("List the mugs again.", STOCK_LIST),
    LAST_TURN,
]


@pytest.fixture
def large_record(tmp_path: Path) -> Path:
    record = tmp_path / kit.STATE_DIR / "tests" / "t-1" / "relay.jsonl"
    record.parent.mkdir(parents=True)
    writer = Writer(record)
    row = {"type": "turn", "harness": "claude-code", "session": "s1", "ok": True}
    for said, shown in TURNS[:-1]:
        writer.append({**row, "said": said, "shown": shown})
    assert record.stat().st_size > 4 * 1024**2
    said, shown = LAST_TURN
    writer.append({**row, "said": said, "shown": shown})
    return record


def test_view_prints_each_turn_of_a_large_relay_record(large_record: Path) -> None:
    out = io.StringIO()
    assert kit.view(large_record, follow=False, out=out) == 0
    assert out.getvalue() == "".join(
        f"──── tester, turn {n} ────\n{said}\n──── agent ────\n{shown}\n"
        for n, (said, shown) in enumerate(TURNS, 1)
    )


def test_transcript_shows_the_last_turn_of_a_large_relay_record(
    tmp_path: Path, large_record: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli.main(["transcript", "--root", str(tmp_path), "--test", large_record.parent.name]) == 0
    )
    said, shown = LAST_TURN
    assert capsys.readouterr().out.endswith(
        f"──── tester, turn 3 ────\n{said}\n──── agent ────\n{shown}\n"
    )


def test_hook_relays_a_message_after_a_large_relay_record(
    tmp_path: Path, large_record: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = large_record.parent
    kit.init(tmp_path, "plugin", {"entry": ["unused-entry"]})
    kit.set_mode(tmp_path, True)
    (folder / "manifest.json").write_text('{"ended": null}', encoding="utf-8")
    current = {"test": folder.name, "dir": str(folder), "tap_url": "http://127.0.0.1/"}
    monkeypatch.setattr(kit.state, "current", lambda root: current)

    message, reply = "When does the mug ship?", "The mug ships today."

    def send_to_entry(req: Request, *, timeout: float) -> io.BytesIO:
        assert req.data is not None
        rid, said, history = contract.parse_request(req.data)
        assert said == message
        assert history == TURNS
        return io.BytesIO(json.dumps({"v": contract.VERSION, "id": rid, "reply": reply}).encode())

    monkeypatch.setattr("urllib.request.urlopen", send_to_entry)
    event = {"hook_event_name": "UserPromptSubmit", "prompt": message, "session_id": "s1"}
    out = io.StringIO()
    assert kit.run_hook(tmp_path, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    assert json.loads(out.getvalue()) == {"decision": "block", "reason": reply}
    assert turns(large_record)[-1] == Turn(4, message, reply, True, "s1", "claude-code")

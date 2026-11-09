import base64
import json
from pathlib import Path

from toy_websocket import CASE, ToyWebSocket

from nookku import kit, performance, websocket
from nookku.adapters import JsonAdapter
from nookku.audit import audit
from nookku.record import Writer, read_rows, sha256
from nookku.tap import Tap, start_in_thread


def test_the_websocket_upgrade_uses_the_protocol_accept_value() -> None:
    assert websocket.accept("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_the_tap_records_each_frame_of_a_websocket_turn(tmp_path: Path) -> None:
    case = json.loads(CASE.read_text())
    tap_path = tmp_path / "tap.jsonl"
    with ToyWebSocket() as agent:
        tap = Tap(("127.0.0.1", 0), agent.url, tap_path, JsonAdapter())
        start_in_thread(tap)
        try:
            config = kit.Config(tap_url=f"http://127.0.0.1:{tap.server_port}/")
            reply, ok = kit.relay(config, case["message"], [])
        finally:
            tap.shutdown()
            tap.server_close()
    assert ok and reply == case["websocket"]["reply"]
    *frames, exchange = [row for _, row in read_rows("tap", tap_path)]
    assert [[f["direction"], f["opcode"], f["final"]] for f in frames] == case["websocket"][
        "frames"
    ]
    for direction, expected in [("to_agent", agent.seen), ("from_agent", agent.sent)]:
        assert [base64.b64decode(f["base64"]) for f in frames if f["direction"] == direction] == [
            part.wire for part in expected
        ]
    relay_path = tmp_path / "relay.jsonl"
    turn = {"type": "turn", "harness": "codex", "said": case["message"], "ok": True}
    Writer(relay_path).append({**turn, "shown": reply})
    assert audit(tap_path, relay_path).exit == 0
    relay_path.unlink()
    Writer(relay_path).append({**turn, "shown": "The shelf is empty."})
    assert [b.kind for b in audit(tap_path, relay_path).breaks] == ["altered_reply"]

    (tmp_path / "manifest.json").write_text('{"test": "toy-websocket"}\n')
    first = performance.build(tmp_path)["turns"][0]["first_part_seconds"]
    assert first == exchange["first_part_seconds"] >= 0

    # Changing the exchange and recomputing its own hash cannot change the frame evidence.
    exchange.update(reply="The shelf is empty.", reply_sha256=sha256("The shelf is empty."))
    tap_path.write_text("".join(json.dumps(row) + "\n" for row in [*frames, exchange]))
    broken = audit(tap_path, relay_path)
    assert broken.exit == 2
    assert broken.errors[0]["class"] == "record_invalid"
    assert "messages do not match the exchange" in broken.errors[0]["detail"]


def test_the_guard_covers_the_default_wss_port() -> None:
    pattern = kit.deny_pattern(["wss://stock.toy.test"])
    assert pattern is not None and pattern.search("wss://stock.toy.test:443/")

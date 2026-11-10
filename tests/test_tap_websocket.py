import base64
import http.client
import io
import json
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from toy_websocket import CASE, ToyWebSocket

from nookku import kit, performance, websocket
from nookku.adapters import JsonAdapter
from nookku.audit import audit
from nookku.record import Writer, read_rows, sha256
from nookku.tap import Tap, _Handler, start_in_thread


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


@pytest.mark.parametrize("scheme, port", [("ws", 80), ("wss", 443)])
def test_the_tap_uses_the_default_websocket_port(tmp_path: Path, scheme: str, port: int) -> None:
    with patch("nookku.tap.ThreadingHTTPServer.__init__", return_value=None):
        tap = Tap(
            ("127.0.0.1", 0), f"{scheme}://stock.toy.test", tmp_path / "tap.jsonl", JsonAdapter()
        )
    conn = tap.connect()
    assert conn.port == port
    assert isinstance(conn, http.client.HTTPSConnection) == (scheme == "wss")


@pytest.mark.parametrize("opcode", [websocket.PING, websocket.TEXT])
def test_the_close_handshake_checks_frames_after_a_full_reply(opcode: int) -> None:
    # A wire transcript tests the close loop without a socket or a timing race.
    reply = websocket.frame(websocket.TEXT, b'{"reply":"In stock."}', masked=False)
    extra = websocket.frame(opcode, b"closing", masked=False)
    close = websocket.frame(websocket.CLOSE, b"\x03\xe8", masked=False)
    conn = Mock(spec=http.client.HTTPConnection)
    conn.sock = Mock()
    response = conn.getresponse.return_value
    response.status = 101
    response.fp = io.BytesIO(reply.wire + extra.wire + close.wire)

    def header(name: str) -> str | None:
        sent = conn.request.call_args.kwargs["headers"]
        return {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Accept": websocket.accept(sent["Sec-WebSocket-Key"]),
        }.get(name)

    response.getheader.side_effect = header
    observed = []
    if opcode == websocket.TEXT:
        with pytest.raises(websocket.WebSocketError, match="expected one text message"):
            websocket.exchange(conn, "/", {}, b'{"text":"Stock?"}', lambda *p: observed.append(p))
        assert observed[-1] == ("from_agent", extra)
    else:
        result = websocket.exchange(
            conn, "/", {}, b'{"text":"Stock?"}', lambda *p: observed.append(p)
        )
        assert result == reply.payload
        sent = [
            websocket.from_wire(call.args[0], masked=True)
            for call in conn.sock.sendall.call_args_list
        ]
        assert [part.opcode for part in sent] == [websocket.TEXT, websocket.CLOSE, websocket.PONG]
        assert sent[-1].payload == extra.payload
        assert observed[-2] == ("to_agent", sent[-1])
        assert observed[-1] == ("from_agent", close)


def test_the_tap_answers_a_ping_during_the_close_handshake(tmp_path: Path) -> None:
    case = json.loads(CASE.read_text())
    tap_path = tmp_path / "tap.jsonl"
    with (
        ToyWebSocket(close_ping=True) as agent,
        Tap(("127.0.0.1", 0), agent.url, tap_path, JsonAdapter()) as tap,
    ):
        start_in_thread(tap)
        try:
            config = kit.Config(tap_url=f"http://127.0.0.1:{tap.server_port}/")
            reply, ok = kit.relay(config, case["message"], [])
        finally:
            tap.shutdown()
    assert ok and reply == agent.reply
    frames = [row for _, row in read_rows("tap", tap_path) if row["type"] == "websocket_frame"]
    assert [part.opcode for part in agent.seen][-2:] == [websocket.CLOSE, websocket.PONG]
    pong = agent.seen[-1]
    assert pong.payload == b"closing"
    assert frames[-1]["opcode"] == websocket.CLOSE
    assert base64.b64decode(frames[-2]["base64"]) == pong.wire


def test_a_websocket_close_before_a_full_reply_keeps_the_next_turn_readable(tmp_path: Path) -> None:
    # Run real frame parsing and tap writes with wire transcripts, without a network socket.
    tap_path = tmp_path / "tap.jsonl"
    relay_path = tmp_path / "relay.jsonl"
    handler = object.__new__(_Handler)
    handler.server = Mock(writer=Writer(tap_path), adapter=JsonAdapter(), base_path="", timeout=5)
    handler.command, handler.path = "POST", "/"
    handler._send = Mock()
    handler._error = Mock()
    close = websocket.frame(websocket.CLOSE, b"\x03\xe8", masked=False)
    for final in (False, True):
        frame = websocket.frame(websocket.TEXT, b'{"reply":"In stock."}', final=final, masked=False)
        conn = Mock(spec=http.client.HTTPConnection)
        conn.sock = Mock()
        response = conn.getresponse.return_value
        response.status = 101
        response.fp = io.BytesIO(frame.wire + close.wire)

        def header(name: str, connection: Mock = conn) -> str | None:
            sent = connection.request.call_args.kwargs["headers"]
            return {
                "Connection": "Upgrade",
                "Upgrade": "websocket",
                "Sec-WebSocket-Accept": websocket.accept(sent["Sec-WebSocket-Key"]),
            }.get(name)

        response.getheader.side_effect = header
        handler._websocket(conn, b'{"text":"Stock?"}', {}, "Stock?", None, threading.Event())
        Writer(relay_path).append(
            {
                "type": "turn",
                "harness": "codex",
                "said": "Stock?",
                "shown": "In stock." if final else None,
                "ok": final,
            }
        )
    handler._error.assert_called_once_with(502, "nookku tap: the agent closed before a full reply")
    handler._send.assert_called_once_with(
        200, [("Content-Type", "application/json")], b'{"reply":"In stock."}'
    )
    rows = read_rows("tap", tap_path)
    exchanges = [(n, r) for n, r in rows if r["type"] == "exchange"]
    failed_line, failed = exchanges[0]
    assert failed["status"] is None and failed["reply"] is None
    assert failed["stream_protocol"] == "websocket"
    assert all(r["stream_id"] == failed["stream_id"] for n, r in rows if n < failed_line)
    assert exchanges[1][1]["reply"] == "In stock."
    report = audit(tap_path, relay_path)
    assert report.exit == 0 and report.turns == report.exchanges == 2
    assert not report.errors and not report.breaks
    assert [(n.kind, n.relay_line, n.tap_line) for n in report.notes] == [
        ("agent_error", 1, failed_line)
    ]


@pytest.mark.parametrize("failure", ["close", "request", "reply", "surrogate"])
def test_an_unparsed_websocket_row_keeps_its_frame_links(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "tap.jsonl"
    handler = object.__new__(_Handler)
    handler.command, handler.path = "POST", "/"
    handler.server = Mock(writer=Writer(path), adapter=JsonAdapter(), base_path="", timeout=5)
    handler._send, handler._error = Mock(), Mock()
    payload = {
        "close": b"partial",
        "request": b'{"reply":"In stock."}',
        "reply": b'{"stock":3}',
        "surrogate": b'{"reply":"\\ud83d"}',
    }[failure]
    frame = websocket.frame(websocket.TEXT, payload, final=failure != "close", masked=False)

    def exchange(conn, path, headers, body, observe):
        observe("from_agent", frame)
        if failure == "close":
            raise websocket.WebSocketError("the agent closed before a full reply")
        return payload

    with patch("nookku.tap.websocket.exchange", side_effect=exchange):
        message = None if failure in ("close", "request") else "Stock?"
        handler._websocket(Mock(), b"{}", {}, message, "request: no message", threading.Event())
    (_, part), (_, row) = read_rows("tap", path)
    assert row["type"] == "unparsed"
    assert row["stream_id"] == part["stream_id"] and row["stream_protocol"] == "websocket"
    relay = tmp_path / "relay.jsonl"
    relay.write_text("")
    report = audit(path, relay)
    assert report.exit == 2 and [e["class"] for e in report.errors] == ["tap_unparsed"]

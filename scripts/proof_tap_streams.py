"""Send one toy shop message through the relay and tap for each streamed transport."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from typing import Any

from nookku import __version__, bridge, kit, performance
from nookku.adapters import make
from nookku.audit import audit
from nookku.record import Writer, loads, read_rows
from nookku.tap import Tap, start_in_thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from toy_agent import ToyAgent, shop_reply  # noqa: E402
from toy_websocket import CASE, ToyWebSocket  # noqa: E402


class _ReleaseOnPart(Writer):
    def __init__(self, path: Path, release: Event) -> None:
        super().__init__(path)
        self.release = release

    def append(self, row: dict[str, Any]) -> None:
        super().append(row)
        if row["type"] == "stream_part":
            self.release.set()


def relay_one(
    folder: Path,
    protocol: str,
    upstream: str,
    path: str,
    adapter: str,
    said: str,
    expected: str,
    release: Event | None = None,
) -> dict[str, Any]:
    folder.mkdir()
    tap_path, relay_path = folder / "tap.jsonl", folder / "relay.jsonl"
    tap = Tap(("127.0.0.1", 0), upstream, tap_path, make(adapter))
    if release is not None:
        tap.writer = _ReleaseOnPart(tap_path, release)
    start_in_thread(tap)
    try:
        config = kit.Config(
            tap_url=f"http://127.0.0.1:{tap.server_port}{path}",
            adapter=adapter,
            openai_stream=adapter == "openai",
        )
        shown, ok = kit.relay(config, said, [])
    finally:
        tap.shutdown()
        tap.server_close()

    Writer(relay_path).append(
        {"type": "turn", "harness": "script", "said": said, "shown": shown, "ok": ok}
    )
    record = [r for _, r in read_rows("tap", tap_path)]
    exchanges = [r for r in record if r["type"] == "exchange"]
    parts = [r for r in record if r["type"] == protocol]
    (folder / "manifest.json").write_text('{"test": "toy-streams"}\n', encoding="utf-8")
    timing = performance.build(folder)["turns"]
    report = audit(tap_path, relay_path)
    return {
        "reply_matches": ok and shown == expected,
        "audit_exit": report.exit,
        "exchanges": len(exchanges),
        "parts": len(parts),
        "first_part_seconds": timing[0].get("first_part_seconds") if timing else None,
        "frames": [[p["direction"], p["opcode"], p["final"]] for p in parts]
        if protocol == "websocket_frame"
        else None,
    }


def main() -> int:
    case = loads(CASE.read_bytes())
    said = case["message"]
    with TemporaryDirectory(prefix="nookku-tap-streams-") as work:
        root = Path(work)
        release = Event()
        toy = ToyAgent(stream=True, gate=release)
        try:
            sse = relay_one(
                root / "sse",
                "stream_part",
                toy.url,
                "/v1/chat/completions",
                "openai",
                said,
                shop_reply(said),
                release,
            )
        finally:
            toy.shutdown()
        with ToyWebSocket() as agent:
            ws = relay_one(
                root / "websocket",
                "websocket_frame",
                agent.url,
                "/",
                "json",
                said,
                case["websocket"]["reply"],
            )
    passed = (
        all(
            r["reply_matches"]
            and r["audit_exit"] == 0
            and r["exchanges"] == 1
            and r["parts"] > 1
            and r["first_part_seconds"] is not None
            for r in (sse, ws)
        )
        and ws["frames"] == case["websocket"]["frames"]
    )
    proof = {
        "date": datetime.date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "claude_code": bridge._version("claude"),
            "codex": bridge._version("codex"),
        },
        "method": "scripts/proof_tap_streams.py",
        "case": "conformance/streams/toy-replies.json",
        "model_used": False,
        "passed": passed,
        "sse": sse,
        "websocket": ws,
    }
    out = ROOT / "proofs" / "tap-streams" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if passed else 'FAIL'}: {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

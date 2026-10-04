"""Relay a test conversation to a chat agent byte for byte, and audit that it held."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from verbatim_relay import __version__
from verbatim_relay.adapters import make
from verbatim_relay.audit import audit, render
from verbatim_relay.tap import Tap, serve


def _listen(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError("use HOST:PORT, for example 127.0.0.1:8800")
    return host.strip("[]"), int(port)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verbatim-relay", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    tap = sub.add_parser("tap", help="run the tap proxy in front of the agent")
    tap.add_argument("--agent", required=True, help="the agent's base URL")
    tap.add_argument("--record", required=True, type=Path, help="the tap record (JSONL) to append")
    tap.add_argument(
        "--listen",
        type=_listen,
        default=("127.0.0.1", 8800),
        help="HOST:PORT (default 127.0.0.1:8800)",
    )
    tap.add_argument("--adapter", choices=["json", "openai"], default="json")
    tap.add_argument("--message-field", default="text", help="json adapter: request field path")
    tap.add_argument("--reply-field", default="reply", help="json adapter: response field path")

    aud = sub.add_parser("audit", help="compare the relay record with the tap record")
    aud.add_argument("--tap", required=True, type=Path, help="the tap record")
    aud.add_argument("--relay", required=True, type=Path, help="the relay record")
    aud.add_argument("--json", action="store_true", help="print the report as JSON")

    args = parser.parse_args(argv)
    if args.command == "tap":
        adapter = make(args.adapter, args.message_field, args.reply_field)
        serve(Tap(args.listen, args.agent, args.record, adapter))
        return 0
    if args.command == "audit":
        report = audit(args.tap, args.relay)
        if args.json:
            print(json.dumps(report.as_dict(), indent=1, ensure_ascii=False))
        else:
            print(render(report))
        return report.exit
    parser.print_help(sys.stderr)
    return 2

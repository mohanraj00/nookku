"""Relay a test conversation to a chat agent byte for byte, and audit that it held."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from verbatim_relay import __version__, kit
from verbatim_relay.adapters import make
from verbatim_relay.audit import audit, render
from verbatim_relay.record import RecordError
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

    ini = sub.add_parser("init", help="install the hook kit for Codex or Claude Code")
    ini.add_argument("harness", choices=["codex", "claude-code"])
    ini.add_argument("--root", type=Path, default=Path.cwd(), help="the project (default: here)")
    for name, default in vars(kit.Config()).items():
        ini.add_argument(f"--{name.replace('_', '-')}", default=default)

    mode = sub.add_parser("mode", help="switch relay mode on or off for the hook kit")
    mode.add_argument("state", choices=["on", "off", "status"])
    mode.add_argument("--root", type=Path, default=Path.cwd())

    view = sub.add_parser("view", help="print each relayed turn (the hook kit's display)")
    view.add_argument("--root", type=Path, default=Path.cwd())
    view.add_argument("--no-follow", action="store_true", help="print the turns so far and stop")

    tr = sub.add_parser("transcript", help="print the exact conversation for the model to evaluate")
    tr.add_argument("--root", type=Path, default=Path.cwd())
    tr.add_argument("--all", action="store_true", help="all sessions, not only the latest one")

    hook = sub.add_parser("hook", help="the hook command that init installs")
    hook.add_argument("--root", type=Path, required=True)
    hook.add_argument("--harness", required=True)

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
    if args.command == "init":
        root = args.root.resolve()
        config = kit.Config(**{k: getattr(args, k) for k in vars(kit.Config())})
        for path in kit.init(root, args.harness, config):
            print(f"wrote {path}")
        print(
            f"Relay mode is {'on' if kit.is_on(root) else 'off'}. "
            "Switch it with: verbatim-relay mode on"
        )
        if args.harness == "codex":
            print(
                "Codex runs project hooks only after you trust them. Start codex in this "
                "project and accept the hooks prompt."
            )
        else:
            print(
                "Do not also enable the verbatim-relay Claude Code plugin in this project, "
                "or each message is sent two times."
            )
        return 0
    if args.command == "mode":
        root = args.root.resolve()
        if args.state != "status":
            kit.set_mode(root, args.state == "on")
        print(f"Relay mode is {'on' if kit.is_on(root) else 'off'}.")
        return 0
    if args.command in ("view", "transcript"):
        root = args.root.resolve()
        try:
            record = kit.Config.load(root).record_path(root)
        except (OSError, ValueError, TypeError) as e:
            print(f"verbatim-relay: cannot read the config: {e}", file=sys.stderr)
            return 2
        if args.command == "transcript":
            try:
                return kit.transcript(record, args.all, sys.stdout)
            except RecordError as e:
                print(f"verbatim-relay: {e}", file=sys.stderr)
                return 2
        try:
            return kit.view(record, not args.no_follow, sys.stdout)
        except KeyboardInterrupt:
            return 0
    if args.command == "hook":
        return kit.run_hook(args.root, args.harness, sys.stdin, sys.stdout)
    parser.print_help(sys.stderr)
    return 2

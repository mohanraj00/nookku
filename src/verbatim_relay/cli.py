"""Relay a test conversation to a chat agent byte for byte, and audit that it held."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

from verbatim_relay import __version__, bridge, kit, stdio
from verbatim_relay.adapters import make
from verbatim_relay.audit import audit, render
from verbatim_relay.record import RecordError
from verbatim_relay.tap import Tap, serve

LIST_KEYS = {"entry", "models"}


def _listen(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError("use HOST:PORT, for example 127.0.0.1:8800")
    return host.strip("[]"), int(port)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verbatim-relay", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    tap = sub.add_parser(
        "tap",
        help="run the tap proxy in front of the agent",
        usage="%(prog)s (--agent URL | --cmd -- COMMAND...) --record FILE [options]",
    )
    tap.add_argument("--agent", help="HTTP mode: the agent's base URL")
    tap.add_argument(
        "--cmd", action="store_true", help="stdio mode: start the COMMAND after -- as the agent"
    )
    tap.add_argument("--log", type=Path, help="stdio mode: the agent's stderr (default app.log)")
    tap.add_argument("--timeout", type=float, default=stdio.TIMEOUT, help="stdio mode: seconds")
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
    tap.add_argument("command_", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    aud = sub.add_parser("audit", help="compare the relay record with the tap record")
    aud.add_argument("--tap", required=True, type=Path, help="the tap record")
    aud.add_argument("--relay", required=True, type=Path, help="the relay record")
    aud.add_argument("--json", action="store_true", help="print the report as JSON")

    ini = sub.add_parser("init", help="install the hook kit for Codex or Claude Code")
    ini.add_argument("harness", choices=["codex", "claude-code"])
    ini.add_argument("--root", type=Path, default=Path.cwd(), help="the project (default: here)")
    for name, default in vars(kit.Config()).items():
        if name not in LIST_KEYS:
            ini.add_argument(f"--{name.replace('_', '-')}", default=default)
    ini.add_argument("--entry", default="", help="the entry command of a test, as one string")
    ini.add_argument(
        "--models", default="", help="the app's model harnesses: claude-code, codex or both (comma)"
    )

    for name, text in (
        ("start", "start a test: run the entry through the tap and switch relay mode on"),
        ("end", "end the test: switch relay mode off, stop the entry and collect its sessions"),
        ("status", "show relay mode and the running test"),
        ("check", "run a short test with one message and check the entry and its sessions"),
    ):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--root", type=Path, default=Path.cwd())
        cmd.add_argument("--json", action="store_true", help="print the result as JSON")
        if name == "start":
            cmd.add_argument("--tester-session", help="the tester's harness session id")

    sub.add_parser("setup", help="print the guide that connects a test to the app")

    br = sub.add_parser("bridge", help=argparse.SUPPRESS)
    br.add_argument("--root", type=Path, required=True)
    br.add_argument("--test", required=True)
    br.add_argument("--tester-session")

    mode = sub.add_parser("mode", help="switch relay mode on or off (with an entry: start or end)")
    mode.add_argument("state", choices=["on", "off", "status"])
    mode.add_argument("--root", type=Path, default=Path.cwd())

    view = sub.add_parser("view", help="print each relayed turn (the hook kit's display)")
    view.add_argument("--root", type=Path, default=Path.cwd())
    view.add_argument("--no-follow", action="store_true", help="print the turns so far and stop")
    view.add_argument("--record", type=Path, help="the relay record (default: from the config)")

    tr = sub.add_parser("transcript", help="print the exact conversation for the model to evaluate")
    tr.add_argument("--root", type=Path, default=Path.cwd())
    tr.add_argument("--all", action="store_true", help="all sessions, not only the latest one")
    tr.add_argument("--record", type=Path, help="the relay record (default: from the config)")

    hook = sub.add_parser("hook", help="the hook command that init installs")
    hook.add_argument("--root", type=Path, required=True)
    hook.add_argument("--harness", required=True)

    args = parser.parse_args(argv)
    if args.command == "tap":
        command = args.command_[1:] if args.command_[:1] == ["--"] else args.command_
        if args.cmd == bool(args.agent) or (args.cmd and not command):
            tap.error("give --agent URL, or --cmd -- COMMAND")
        if args.cmd:
            log = args.log or args.record.parent / "app.log"
            agent = stdio.Agent(command, Path.cwd(), log, timeout=args.timeout)
            stdio.serve(stdio.StdioTap(args.listen, agent, args.record))
            return 0
        adapter = make(args.adapter, args.message_field, args.reply_field)
        serve(Tap(args.listen, args.agent, args.record, adapter))
        return 0
    if args.command == "setup":
        print(resources.files("verbatim_relay").joinpath("setup.md").read_text(encoding="utf-8"))
        return 0
    if args.command == "bridge":
        return bridge.run(args.root, args.test, args.tester_session)
    if args.command in ("start", "end", "status", "check"):
        return _test_command(args)
    if args.command == "audit":
        report = audit(args.tap, args.relay)
        if args.json:
            print(json.dumps(report.as_dict(), indent=1, ensure_ascii=False))
        else:
            print(render(report))
        return report.exit
    if args.command == "init":
        root = args.root.resolve()
        values = {k: getattr(args, k) for k in vars(kit.Config()) if k not in LIST_KEYS}
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        config = kit.Config(**values, entry=shlex.split(args.entry), models=models)
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
        if args.state != "status" and bridge.has_entry(root):
            print(kit.start_test(root) if args.state == "on" else kit.end_test(root))
            return 0
        if args.state != "status":
            kit.set_mode(root, args.state == "on")
        print(f"Relay mode is {'on' if kit.is_on(root) else 'off'}.")
        return 0
    if args.command in ("view", "transcript"):
        root = args.root.resolve()
        # The plugin has no config file. Without one, use the default record path.
        has_config = (root / kit.STATE_DIR / "config.json").exists()
        try:
            config = kit.Config.load(root) if has_config else kit.Config()
        except (OSError, ValueError, TypeError) as e:
            print(f"verbatim-relay: cannot read the config: {e}", file=sys.stderr)
            return 2
        test = bridge.latest_test(root) if config.entry and not args.record else None
        record = args.record or (test / "relay.jsonl" if test else config.record_path(root))
        if args.command == "transcript":
            scope = f"test {test.name}" if test else ""
            try:
                return kit.transcript(record, args.all or test is not None, sys.stdout, scope)
            except RecordError as e:
                print(f"verbatim-relay: {e}", file=sys.stderr)
                return 2
        try:
            if config.entry and not args.record:
                return kit.view_tests(root, not args.no_follow, sys.stdout)
            return kit.view(record, not args.no_follow, sys.stdout)
        except KeyboardInterrupt:
            return 0
    if args.command == "hook":
        return kit.run_hook(args.root, args.harness, sys.stdin, sys.stdout)
    parser.print_help(sys.stderr)
    return 2


def _test_command(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    if args.command == "start":
        try:
            cur = bridge.start(root, args.tester_session)
        except bridge.BridgeError as e:
            print(json.dumps({"error": str(e)}) if args.json else f"verbatim-relay: {e}")
            return 1
        kit.set_mode(root, True)
        if args.json:
            print(json.dumps(cur))
        else:
            print(f"Test {cur['test']} started on {cur['tap_url']}. Relay mode is on.")
            print("End it with: verbatim-relay end")
        return 0
    if args.command == "end":
        kit.set_mode(root, False)
        ended = bridge.end(root)
        if args.json:
            print(json.dumps(ended))
        else:
            print(bridge.summary(ended) if ended else "No test runs. Relay mode is off.")
        return 0
    if args.command == "status":
        running = bridge.current(root)
        if args.json:
            print(json.dumps({"on": kit.is_on(root), "test": running}))
        else:
            print(kit.status(root).removeprefix("verbatim-relay: "))
        return 0
    try:
        passed, lines = bridge.check(root)
    except bridge.BridgeError as e:
        print(f"verbatim-relay: {e}")
        return 1
    print(json.dumps({"pass": passed, "report": lines}) if args.json else "\n".join(lines))
    return 0 if passed else 1

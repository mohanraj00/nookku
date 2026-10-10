"""Relay a test conversation to a chat agent byte for byte, and audit that it held."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

from nookku import __version__, bridge, evaluation, kit, seal, stdio, trace
from nookku.adapters import make
from nookku.audit import audit, render
from nookku.config import KEYS as CONFIG_KEYS
from nookku.config import ConfigError, move_old_state, read_config
from nookku.record import RecordError
from nookku.tap import Tap, serve

# Config keys that are not a plain string flag of init.
LIST_KEYS = {"entry", "models", "evaluate", "otel", "backends", "model_api", "openai_stream"}
# The plain string flags of init. A flag that the user does not give is None.
STRING_KEYS = [k for k in CONFIG_KEYS if k not in LIST_KEYS]


def _listen(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError("use HOST:PORT, for example 127.0.0.1:8800")
    return host.strip("[]"), int(port)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nookku", description=__doc__)
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
    tap.add_argument(
        "--timeout", type=float, default=stdio.TIMEOUT, help="seconds to wait for the agent"
    )
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

    ini = sub.add_parser("init", help="write the config, and the project hooks of a harness")
    ini.add_argument(
        "harness",
        choices=["codex", "claude-code", "plugin"],
        help="plugin: write only the config, because the nookku plugin has the hooks",
    )
    ini.add_argument("--root", type=Path, default=Path.cwd(), help="the project (default: here)")
    defaults = vars(kit.Config())
    for name in STRING_KEYS:
        ini.add_argument(
            f"--{name.replace('_', '-')}",
            help=f"the config key {name} (new file: {defaults[name]!r})",
        )
    ini.add_argument(
        "--openai-stream",
        action="store_true",
        default=None,
        help='openai adapter: send "stream": true in each request',
    )
    ini.add_argument("--entry", help="the entry command of a test, as one string")
    ini.add_argument(
        "--models", help="the app's model harnesses: claude-code, codex or both (comma)"
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
        if name == "end":
            cmd.add_argument(
                "--evaluation",
                action="store_true",
                help="print JSON with the end text and the evaluation prompt (for a relay)",
            )

    trc = sub.add_parser("trace", help="build the trace of a test again, and show its findings")
    trc.add_argument("test", nargs="?", help="the test id (default: the latest test)")
    trc.add_argument("--root", type=Path, default=Path.cwd())
    trc.add_argument("--json", action="store_true", help="print findings.json")

    sub.add_parser("setup", help="print the guide that connects a test to the app")

    # No help: argparse then leaves `bridge` out of the command list, and the command still runs.
    # With help=argparse.SUPPRESS, the list shows "bridge  ==SUPPRESS==".
    br = sub.add_parser("bridge")
    br.add_argument("--root", type=Path, required=True)
    br.add_argument("--test", required=True)
    br.add_argument("--tester-session")

    mode = sub.add_parser("mode", help="switch relay mode on or off (with an entry: start or end)")
    mode.add_argument(
        "state",
        nargs="?",
        default="status",
        choices=["on", "off", "status", "start", "end"],
        help="start is the same as on, and end is the same as off (default: status)",
    )
    mode.add_argument("--root", type=Path, default=Path.cwd())
    mode.add_argument("--tester-session", help="the tester's harness session id")

    view = sub.add_parser("view", help="print each relayed turn (the hook kit's display)")
    view.add_argument("--root", type=Path, default=Path.cwd())
    view.add_argument("--no-follow", action="store_true", help="print the turns so far and stop")
    view.add_argument("--record", type=Path, help="the relay record (default: from the config)")

    ver = sub.add_parser("verify", help="check that no record of a test changed after its end")
    ver.add_argument("test", nargs="?", help="the test id (default: the latest test)")
    ver.add_argument("--root", type=Path, default=Path.cwd())
    ver.add_argument("--json", action="store_true")

    tr = sub.add_parser("transcript", help="print the exact conversation for the model to evaluate")
    tr.add_argument("--root", type=Path, default=Path.cwd())
    tr.add_argument("--all", action="store_true", help="all sessions, not only the latest one")
    tr.add_argument("--record", type=Path, help="the relay record (default: from the config)")
    tr.add_argument(
        "--trace", action="store_true", help="each turn as the app got it, with its model items"
    )
    tr.add_argument("--test", help="the test id (default: the latest test)")
    tr.add_argument("--session", help="only the turns of this harness session")

    mcp = sub.add_parser("mcp", help="the MCP server with the transcript and status tools")
    mcp.add_argument("--root", type=Path, help="the project (default: here)")

    hook = sub.add_parser("hook", help="the hook command that init installs")
    hook.add_argument("--root", type=Path, help="the project (default: from the event)")
    hook.add_argument("--harness", required=True, choices=["claude-code", "codex"])

    args = parser.parse_args(argv)
    if args.command == "mcp" and args.root is None:
        from nookku.mcp import project_root

        # The default root also gets the move of the old state folder below.
        args.root = project_root()
    if isinstance(getattr(args, "root", None), Path):
        error = move_old_state(args.root.resolve())
        if error:
            print(f"nookku: {error}", file=sys.stderr)
            # Exit 2 blocks the event in a hook, so the relay fails closed.
            return 2 if args.command == "hook" else 1
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
        serve(Tap(args.listen, args.agent, args.record, adapter, timeout=args.timeout))
        return 0
    if args.command == "setup":
        print(resources.files("nookku").joinpath("setup.md").read_text(encoding="utf-8"))
        return 0
    if args.command == "bridge":
        return bridge.run(args.root, args.test, args.tester_session)
    if args.command in ("start", "end", "status", "check"):
        return _test_command(args)
    if args.command == "trace":
        return _trace_command(args.root.resolve(), args.test, args.json)
    if args.command == "verify":
        root = args.root.resolve()
        folder = (
            root / bridge.STATE_DIR / "tests" / args.test if args.test else bridge.latest_test(root)
        )
        if folder is None or not folder.is_dir():
            print("nookku: no test folder.", file=sys.stderr)
            return 2
        result = seal.verify(folder)
        print(json.dumps(result, indent=1) if args.json else seal.summary(result))
        return 0 if result["intact"] else 2
    if args.command == "audit":
        report = audit(args.tap, args.relay)
        if args.json:
            print(json.dumps(report.as_dict(), indent=1, ensure_ascii=False))
        else:
            print(render(report))
        return report.exit
    if args.command == "init":
        root = args.root.resolve()
        # Only the flags that the user gave change a key of an existing config.json.
        changes = {k: getattr(args, k) for k in STRING_KEYS if getattr(args, k) is not None}
        if args.entry is not None:
            changes["entry"] = shlex.split(args.entry)
        if args.models is not None:
            changes["models"] = [m.strip() for m in args.models.split(",") if m.strip()]
        if args.openai_stream:
            changes["openai_stream"] = True
        try:
            done = kit.init(root, args.harness, changes)
        except ValueError as e:
            print(f"nookku: {str(e).rstrip('.')}. Nothing was written.", file=sys.stderr)
            return 1
        conf, *hooks = done.written
        print(f"wrote {conf}")
        if done.new:
            print(f"  A new file. Keys that differ from the default: {_names(done.changed)}.")
        else:
            print(f"  Keys changed: {_names(done.changed)}. Keys kept: {_names(done.kept)}.")
        for written in hooks:
            print(f"wrote {written}")
        print(f"Relay mode is {'on' if kit.is_on(root) else 'off'}. Switch it with: nookku mode on")
        if args.harness == "plugin":
            print(
                "The nookku plugin runs the hooks. Do not also run nookku init codex or "
                "nookku init claude-code in this project, or each message is sent two times."
            )
        elif args.harness == "codex":
            print(
                "Codex runs project hooks only after you trust them. Start codex in this "
                "project and accept the hooks prompt."
            )
        else:
            print(
                "Do not also enable the nookku Claude Code plugin in this project, "
                "or each message is sent two times."
            )
        return 0
    if args.command == "mode":
        root = args.root.resolve()
        # The /nookku command of the plugin runs `nookku mode`, with the words of its menu.
        args.state = {"start": "on", "end": "off"}.get(args.state, args.state)
        if args.state != "status" and bridge.has_entry(root):
            session = args.tester_session
            print(
                kit.start_test(root, session) if args.state == "on" else kit.end_test(root, session)
            )
            return 0
        if args.state == "on" and not (root / kit.STATE_DIR / "config.json").exists():
            # Without a config, each relayed prompt is blocked, so relay mode stays off.
            print(
                "nookku: this project has no .nookku/config.json, so relay mode stays off. "
                "Write it with: nookku init plugin"
            )
            return 0
        if args.state == "on" and (root / kit.STATE_DIR / "config.json").exists():
            # A config with no entry (direct HTTP mode) follows the same rule for its keys.
            try:
                read_config(root)
            except ConfigError as e:
                print(f"nookku: {e}")
                return 0
        if args.state != "status":
            kit.set_mode(root, args.state == "on")
        print(f"Relay mode is {'on' if kit.is_on(root) else 'off'}.")
        return 0
    if args.command == "transcript":
        try:
            text = kit.transcript_text(
                args.root.resolve(), args.test, args.trace, args.all, args.session, args.record
            )
        except kit.TranscriptError as e:
            print(f"nookku: {e}", file=sys.stderr)
            return 2
        print(text, end="")
        return 0
    if args.command == "view":
        root = args.root.resolve()
        # The plugin has no config file. Without one, use the default record path.
        has_config = (root / kit.STATE_DIR / "config.json").exists()
        try:
            config = kit.Config.load(root) if has_config else kit.Config()
        except (OSError, ValueError, TypeError) as e:
            print(f"nookku: cannot read the config: {e}", file=sys.stderr)
            return 2
        record = args.record or config.record_path(root)
        try:
            if config.entry and not args.record:
                return kit.view_tests(root, not args.no_follow, sys.stdout)
            return kit.view(record, not args.no_follow, sys.stdout)
        except RecordError as e:
            print(f"nookku: {e}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            return 0
    if args.command == "mcp":
        from nookku import mcp as server

        return server.serve(args.root.resolve())
    if args.command == "hook":
        root = args.root.resolve() if args.root else None
        return kit.run_hook(root, args.harness, sys.stdin, sys.stdout)
    parser.print_help(sys.stderr)
    return 2


def _names(keys: list[str]) -> str:
    return ", ".join(keys) if keys else "none"


def _trace_command(root: Path, test: str | None, as_json: bool) -> int:
    folder = root / bridge.STATE_DIR / "tests" / test if test else bridge.latest_test(root)
    if folder is None or not (folder / "manifest.json").exists():
        print("nookku: no test folder with a manifest.", file=sys.stderr)
        return 2
    check = seal.verify(folder)
    rebuilt = ("trace.jsonl", "findings.json")
    sources = [x for k in ("changed", "missing", "added") for x in check[k] if x not in rebuilt]
    # A rebuild changes only the trace files. It needs sources that agree with an intact seal.
    broken = sources or check["copy"] in ("different", "missing") or not check["sealed"]
    if (check["sealed"] or check["copy"] != "none") and broken:
        print(f"nookku: the trace was not rebuilt. {seal.summary(check)}", file=sys.stderr)
        return 2
    try:
        report = trace.build(folder)
    except RecordError as e:
        print(f"nookku: the trace was not rebuilt. {e}", file=sys.stderr)
        return 2
    seal.update(folder, list(rebuilt))
    if as_json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 0
    print(trace.summary(report))
    for f in report["findings"]:
        where = [f"turn {f['turn']}" if f["turn"] is not None else "no turn"]
        where += [f["harness"]] if f.get("harness") else []
        print(f"  {f['check']} ({', '.join(where)}): {f['detail']}")
    print(f"File: {folder / 'trace.jsonl'}")
    return 0


def _test_command(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    if args.command == "start":
        try:
            cur = bridge.start(root, args.tester_session)
        except bridge.BridgeError as e:
            print(json.dumps({"error": str(e)}) if args.json else f"nookku: {e}")
            return 1
        kit.set_mode(root, True)
        if args.json:
            print(json.dumps(cur))
        else:
            print(f"Test {cur['test']} started on {cur['tap_url']}. Relay mode is on.")
            print("End it with: nookku end")
        return 0
    if args.command == "end":
        kit.set_mode(root, False)
        ended = bridge.end(root)
        text = bridge.summary(ended) if ended else "No test runs. Relay mode is off."
        if args.evaluation:
            folder = evaluation.pending(root)
            prompt = evaluation.prompt(folder) if folder else None
            print(json.dumps({"text": text, "evaluation": prompt}, ensure_ascii=False))
        elif args.json:
            print(json.dumps(ended))
        else:
            print(text)
            if ended and evaluation.pending(root):
                print("To evaluate the test, type this prompt in your harness: nookku end")
        return 0
    if args.command == "status":
        running = bridge.current(root)
        if args.json:
            on = kit.is_on(root)
            # text is the status line of the plugin, and attachments is the text that refuses a
            # prompt with an attachment. Each is null if relay mode is off.
            line = kit.status(root).removeprefix("nookku: ") if on else None
            refuse = kit.ATTACHMENTS_REASON if on else None
            print(json.dumps({"on": on, "test": running, "text": line, "attachments": refuse}))
        else:
            print(kit.status(root).removeprefix("nookku: "))
        return 0
    try:
        passed, lines = bridge.check(root)
    except bridge.BridgeError as e:
        print(f"nookku: {e}")
        return 1
    print(json.dumps({"pass": passed, "report": lines}) if args.json else "\n".join(lines))
    return 0 if passed else 1

"""Relay a test conversation to a chat agent byte for byte, and audit that it held."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from collections.abc import Iterator, Sequence
from importlib import resources
from pathlib import Path

from nookku import __version__, bridge, evaluation, kit, seal, stdio, trace
from nookku.adapters import make
from nookku.audit import audit, render
from nookku.config import KEYS as CONFIG_KEYS
from nookku.config import OLD_STATE_DIR, ConfigError, move_old_state, read_config
from nookku.record import RecordError
from nookku.tap import Tap, serve

# Config keys that are not a plain string flag of init.
LIST_KEYS = {
    "entry",
    "entries",
    "models",
    "evaluate",
    "otel",
    "backends",
    "model_api",
    "openai_stream",
    "repeated_reply",
    "transcript_compact",
}
# The plain string flags of init. A flag that the user does not give is None.
STRING_KEYS = [k for k in CONFIG_KEYS if k not in LIST_KEYS]
# The relays and the bridge run these commands. A tester does not run them
# (docs/reference/cli.md, "Internal commands").
INTERNAL_COMMANDS = frozenset({"hook", "mcp", "bridge"})


class _Commands(dict[str, argparse.ArgumentParser]):
    """The commands of the parser. An unknown command gives an error that lists the commands,
    and the list leaves out each internal command (#116). Each command still runs."""

    def __iter__(self) -> Iterator[str]:
        return (name for name in super().__iter__() if name not in INTERNAL_COMMANDS)


def _listen(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError("use HOST:PORT, for example 127.0.0.1:8800")
    return host.strip("[]"), int(port)


def _git_top(root: Path) -> Path | None:
    """The top level of the git work tree of root, or None if root is not in one."""
    import subprocess  # only init needs it, and a hook event imports this module

    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (
        Path(out.stdout.strip()).resolve() if out.returncode == 0 and out.stdout.strip() else None
    )


def _warn_both_on(root: Path, harness: str) -> None:
    """Warn after init if the other form of the relay is on in Claude Code (#151)."""
    from nookku import claude_gate

    if harness == "claude-code" and claude_gate.plugin_on(root):
        print(
            "nookku: warning: the nookku plugin is also on in Claude Code. Turn it off with: "
            f"{claude_gate.DISABLE}. Else nookku start refuses the test.",
            file=sys.stderr,
        )
    elif harness == "plugin" and claude_gate.project_hooks_on(root):
        print(
            "nookku: warning: .claude has the project hooks of nookku init claude-code. Remove "
            "them with: nookku init claude-code --remove. Else nookku start refuses the test.",
            file=sys.stderr,
        )


def _relay_on(root: Path) -> str | None:
    """The refusal of init --remove if a test or relay mode is on, else None. Read the mode
    file of the old state folder too, because init --remove does not move it."""
    if bridge.current(root) is not None:
        return "a test runs. End it first with: nookku end"
    old = root / OLD_STATE_DIR / "mode"
    if kit.is_on(root) or (old.is_file() and old.read_text().strip() == "on"):
        return "relay mode is on. Switch it off first: nookku mode off"
    return None


def _remove_hooks(root: Path, harness: str) -> int:
    """init --remove (#163): remove the project hooks, but not while a test or relay mode is
    on. Without the hooks, a message in relay mode would go to the model."""
    refuse = _relay_on(root)
    if refuse is None:
        try:
            done = kit.remove(root, harness)
        except ValueError as e:
            print(f"nookku: {str(e).rstrip('.')}. Nothing was changed.", file=sys.stderr)
            return 1
        # A test or relay mode can start while the file changes. Then put the hooks back.
        refuse = _relay_on(root)
        if refuse is not None and done.count:
            kit.replace_text(done.path, done.before)
    if refuse is not None:
        print(f"nookku: {refuse}. Nothing was changed.", file=sys.stderr)
        return 1
    if done.count:
        print(f"removed {done.count} hooks from {done.path}")
    else:
        print(f"{done.path} has no hook of nookku. Nothing was changed.")
    print("The state folder stays. It has the config and your tests.")
    return 0


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
    aud.add_argument("--script", type=Path, help="the script of a scripted test")

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
        action=argparse.BooleanOptionalAction,
        default=None,
        help='openai adapter: send "stream": true in each request, or not (--no-openai-stream)',
    )
    ini.add_argument(
        "--repeated-reply",
        type=int,
        metavar="COUNT",
        help="the config key repeated_reply: the count of consecutive turns with the same reply "
        "that gives a finding, or 0 for off (new file: 2)",
    )
    ini.add_argument("--entry", help="the entry command of a test, as one string")
    ini.add_argument(
        "--models", help="the app's model harnesses: claude-code, codex or both (comma)"
    )
    ini.add_argument(
        "--remove",
        action="store_true",
        help="remove the project hooks of nookku, and keep each other hook and .nookku/",
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

    run = sub.add_parser("run", help="run a scripted test: send each message of a script file")
    run.add_argument("--script", required=True, type=Path, help="the script file (JSONL or JSON)")
    run.add_argument("--entry", help="the name of an entry in the config key entries")
    run.add_argument("--root", type=Path, default=Path.cwd())
    run.add_argument("--json", action="store_true", help="print the result as JSON")
    run.add_argument(
        "--evaluate",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="print the evaluation prompt at the end (default: the config key evaluate)",
    )

    trc = sub.add_parser("trace", help="build the trace of a test again, and show its findings")
    trc.add_argument(
        "test",
        nargs="?",
        help="the test id or the path of the test folder (default: the latest test)",
    )
    trc.add_argument("--root", type=Path, default=Path.cwd())
    trc.add_argument("--json", action="store_true", help="print findings.json")

    sub.add_parser("setup", help="print the guide that connects a test to the app")

    # An internal command has no help: argparse then leaves it out of the command list of
    # --help, and the command still runs (#299). With help=argparse.SUPPRESS, the list shows
    # "bridge  ==SUPPRESS==".
    br = sub.add_parser("bridge")
    br.add_argument("--root", type=Path, required=True)
    br.add_argument("--test", required=True)
    br.add_argument("--tester-session")
    br.add_argument("--entry-name")
    br.add_argument("--script-source")

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

    view = sub.add_parser("view", help="print each relayed turn (a display for a second terminal)")
    view.add_argument("--root", type=Path, default=Path.cwd())
    view.add_argument("--no-follow", action="store_true", help="print the turns so far and stop")
    view.add_argument("--record", type=Path, help="the relay record (default: from the config)")

    ver = sub.add_parser("verify", help="check that no record of a test changed after its end")
    ver.add_argument(
        "test",
        nargs="?",
        help="the test id or the path of the test folder (default: the latest test)",
    )
    ver.add_argument("--root", type=Path, default=Path.cwd())
    ver.add_argument("--json", action="store_true")

    tr = sub.add_parser("transcript", help="print the exact conversation for the model to evaluate")
    tr.add_argument("--root", type=Path, default=Path.cwd())
    tr.add_argument("--all", action="store_true", help="all sessions, not only the latest one")
    tr.add_argument("--record", type=Path, help="the relay record (default: from the config)")
    tr.add_argument(
        "--trace", action="store_true", help="each turn as the app got it, with its model items"
    )
    tr.add_argument(
        "--test", help="the test id or the path of the test folder (default: the latest test)"
    )
    tr.add_argument("--session", help="only the turns of this harness session")
    tr.add_argument(
        "--compact",
        action="store_true",
        default=None,
        help="with --trace: show a repeated text one time (default: transcript_compact)",
    )
    tr.add_argument(
        "--no-compact", dest="compact", action="store_false", help="with --trace: show each text"
    )

    # The MCP server with the transcript and status tools. An internal command has no help.
    mcp = sub.add_parser("mcp")
    mcp.add_argument("--root", type=Path, help="the project (default: here)")

    pol = sub.add_parser(
        "policy", help="print the policy keys, or change one (only a person, in a shell)"
    )
    pol.add_argument("--root", type=Path, default=Path.cwd())
    pol.add_argument("action", nargs="?", choices=["set"])
    pol.add_argument("key", nargs="?")
    pol.add_argument("value", nargs="?")

    # The hook command that init installs. An internal command has no help.
    hook = sub.add_parser("hook")
    hook.add_argument("--root", type=Path, help="the project (default: from the event)")
    hook.add_argument("--harness", required=True, choices=["claude-code", "codex"])

    # argparse reads this list for the invalid-choice error.
    sub.choices = _Commands(sub.choices)
    args = parser.parse_args(argv)
    if args.command == "mcp" and args.root is None:
        from nookku.mcp import project_root

        # The default root also gets the move of the old state folder below.
        args.root = project_root()
    if args.command == "init" and args.remove:
        given = [k for k in (*STRING_KEYS, "entry", "models") if getattr(args, k)]
        # --no-openai-stream gives False, so check for None, not for a true value.
        given += [k for k in ("openai_stream", "repeated_reply") if getattr(args, k) is not None]
        if args.harness == "plugin" or given:
            ini.error("--remove takes the harness claude-code or codex, and no other flag")
    if args.command == "init" and args.remove:
        # Before the move of the old state folder: a refusal changes nothing.
        return _remove_hooks(args.root.resolve(), args.harness)
    if args.command == "init":
        # Check before the move of the old state folder, which can change a test folder. Check
        # the path as given too, because resolve() removes a state folder that is a symlink.
        error = kit.state_root_error(
            Path(os.path.abspath(args.root)), args.harness
        ) or kit.state_root_error(args.root.resolve(), args.harness)
        if error:
            print(f"nookku: {error}. Nothing was written.", file=sys.stderr)
            return 1
        # The root comes first, before a message of the move below, also in output with stderr
        # in the same pipe.
        print(f"Project root: {args.root.resolve()}", flush=True)
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
        return bridge.run(
            args.root,
            args.test,
            args.tester_session,
            entry_name=args.entry_name,
            script_source=args.script_source,
        )
    if args.command == "run":
        return _run_command(args)
    if args.command in ("start", "end", "status", "check"):
        return _test_command(args)
    if args.command == "trace":
        return _trace_command(args.root.resolve(), args.test, args.json)
    if args.command == "verify":
        folder = _test_folder(args.root.resolve(), args.test)
        if folder is None:
            return 2
        result = seal.verify(folder)
        # The test id shows which test the command checked, also with no TEST argument (#160).
        text = f"Test {folder.name}. {seal.summary(result)}"
        print(json.dumps(result, indent=1) if args.json else text)
        return 0 if result["intact"] else 2
    if args.command == "audit":
        report = audit(args.tap, args.relay, args.script)
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
        if args.openai_stream is not None:
            # --openai-stream gives True and --no-openai-stream gives False (#120).
            changes["openai_stream"] = args.openai_stream
        if args.repeated_reply is not None:
            changes["repeated_reply"] = args.repeated_reply
        try:
            done = kit.init(root, args.harness, changes)
        except ValueError as e:
            print(f"nookku: {str(e).rstrip('.')}. Nothing was written.", file=sys.stderr)
            return 1
        top = _git_top(root) if done.new else None
        if top is not None and top != root:
            print(
                f"nookku: warning: {root} is not the top level of its git work tree, {top}. "
                f"If {top} is the project, run: nookku init {args.harness} --root {top}",
                file=sys.stderr,
                flush=True,
            )
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
        _warn_both_on(root, args.harness)
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
        if args.state == "on":
            from nookku import claude_gate, codex_gate

            both = claude_gate.problem(root)
            if both is not None:
                print(f"nookku: {both}")
                return 0
            gate = codex_gate.check(root)
            if gate["problems"]:
                print(f"nookku: {codex_gate.refusal(gate)}")
                return 0
        if args.state != "status":
            kit.set_mode(root, args.state == "on")
        print(f"Relay mode is {'on' if kit.is_on(root) else 'off'}.")
        return 0
    if args.command == "transcript":
        root = args.root.resolve()
        try:
            text = kit.transcript_text(
                root,
                kit.parse_test_arg(root, args.test) if args.test else None,
                args.trace,
                args.all,
                args.session,
                args.record,
                args.compact,
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
        follow = not args.no_follow
        try:
            if args.record:
                return kit.view(args.record, follow, sys.stdout)
            if config.entry:
                return kit.view_tests(root, follow, sys.stdout)
            # The tester can write an entry after the view starts (#312).
            return kit.view_until_entry(root, config.record_path(root), follow, sys.stdout)
        except RecordError as e:
            print(f"nookku: {e}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            return 0
    if args.command == "mcp":
        from nookku import mcp as server

        return server.serve(args.root.resolve())
    if args.command == "policy":
        return _policy(args.root.resolve(), args.action, args.key, args.value)
    if args.command == "hook":
        root = args.root.resolve() if args.root else None
        return kit.run_hook(root, args.harness, sys.stdin, sys.stdout)
    parser.print_help(sys.stderr)
    return 2


def _names(keys: list[str]) -> str:
    return ", ".join(keys) if keys else "none"


def _test_folder(root: Path, test: str | None) -> Path | None:
    """The folder of a TEST argument: a test id or the path of a test folder. With no argument,
    the latest test. If there is no such test, print an error that names the expected argument
    and return None."""
    try:
        folder = kit.existing_test(root, kit.parse_test_arg(root, test)) if test else None
    except kit.TranscriptError as e:
        print(f"nookku: {e}", file=sys.stderr)
        return None
    folder = folder or bridge.latest_test(root)
    if folder is None or not folder.is_dir():
        print(f"nookku: no test folder. {kit.TESTS_HELP}", file=sys.stderr)
        return None
    return folder


def _trace_command(root: Path, test: str | None, as_json: bool) -> int:
    folder = _test_folder(root, test)
    if folder is None:
        return 2
    if not (folder / "manifest.json").exists():
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


def _run_command(args: argparse.Namespace) -> int:
    """nookku run --script: a scripted test (SPEC.md section 7.10)."""
    root = args.root.resolve()
    script_path = args.script if args.script.is_absolute() else Path.cwd() / args.script
    try:
        passed, lines, folder = bridge.run_script(root, script_path, args.entry)
    except bridge.BridgeError as e:
        print(json.dumps({"error": str(e)}) if args.json else f"nookku: {e}")
        return 1
    show = evaluation.enabled(root) if args.evaluate is None else args.evaluate
    prompt = evaluation.prompt(folder) if show else None
    if args.json:
        print(json.dumps({"pass": passed, "report": lines, "evaluation": prompt}))
    else:
        print("\n".join(lines))
        if prompt:
            print(f"\n{prompt}")
    return 0 if passed else 1


def _waiting(test: str) -> str:
    return f"Ending test {test}. Waiting up to {bridge.END_WAIT:g} s for the bridge to stop."


def _stopped(folder: Path) -> str:
    """The text of `status` for a test whose bridge stopped with no end (#164)."""
    return (
        f"Test {folder.name} stopped with no end. Folder: {folder}\n"
        "To write its audit and its seal, run: nookku end"
    )


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
            print(kit.end_ways(root))
        return 0
    if args.command == "end":
        kit.set_mode(root, False)
        running = bridge.current(root)
        if running is not None and not (args.json or args.evaluation):
            print(_waiting(running["test"]), flush=True)
        ended = bridge.end(root)
        text = bridge.summary(ended) if ended else "No test runs. Relay mode is off."
        if args.evaluation:
            folder = evaluation.pending(root)
            prompt = evaluation.prompt(folder) if folder else None
            note = evaluation.config_note(root) if folder is None else None
            if note:
                text = f"{text}\n{note}"
            print(json.dumps({"text": text, "evaluation": prompt}, ensure_ascii=False))
        elif args.json:
            print(json.dumps(ended))
        else:
            print(text)
            if ended and evaluation.pending(root):
                print("To evaluate the test, type this prompt in your harness: nookku end")
            elif note := evaluation.config_note(root):
                # Also after a test that ended before: the tester types nookku end again after
                # the fix of the file.
                print(note)
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
            folder = bridge.stopped(root) if running is None else None
            if folder is not None:
                print(_stopped(folder))
        return 0
    try:
        passed, lines = bridge.check(root)
    except bridge.BridgeError as e:
        print(f"nookku: {e}")
        return 1
    print(json.dumps({"pass": passed, "report": lines}) if args.json else "\n".join(lines))
    return 0 if passed else 1


def _policy(root: Path, action: str | None, key: str | None, value: str | None) -> int:
    """Print the policy keys, or change one key (SPEC.md section 7.9)."""
    from nookku import policy

    try:
        if action is None:
            if key is not None:
                print("usage: nookku policy [set KEY VALUE]", file=sys.stderr)
                return 2
            values = policy.read(root)
        elif key is None or value is None:
            print("usage: nookku policy set KEY VALUE", file=sys.stderr)
            return 2
        else:
            values = policy.set_key(root, key, value)
            if key == "guard_reads" and values[key]:
                print(policy.READS_WARNING, file=sys.stderr)
    except (policy.PolicyError, OSError) as e:
        print(f"nookku: {e}", file=sys.stderr)
        return 1
    print(json.dumps(values, indent=1, sort_keys=True))
    return 0

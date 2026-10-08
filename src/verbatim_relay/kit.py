"""The hook kit of SPEC.md section 5: classic hooks that Codex and Claude Code share."""

from __future__ import annotations

import http.client
import json
import re
import shlex
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from verbatim_relay import bridge, commands, evaluation, seal
from verbatim_relay.adapters import AdapterError, History, StreamError, is_stream, make
from verbatim_relay.config import FILE as CONFIG_FILE
from verbatim_relay.config import Config as Config
from verbatim_relay.config import check, read_config
from verbatim_relay.record import (
    RecordError,
    Turn,
    Writer,
    escape_surrogates,
    lone_surrogate,
    read_relay,
)

STATE_DIR = bridge.STATE_DIR
TIMEOUT = 280
# The UserPromptSubmit hook deadline. Each relay timeout must end before it, so that the hook
# can still block the prompt.
HOOK_DEADLINE = 300
# The number of code points in the detail of a blocked_call row (SPEC.md section 2.2).
DETAIL_LIMIT = 300
LOOPBACK = ["127.0.0.1", "localhost", "0.0.0.0", "[::1]"]
# Tools that only read, write or search files. Every other tool is denied when its input names
# the tap or the agent, so a tool that the kit does not know is denied too.
FILE_TOOLS = {
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
    "apply_patch",
    "view_image",
    "update_plan",
}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"}
DENY_REASON = "verbatim-relay: only the tester talks to the agent."
TEST_FILES = re.compile(r"\.verbatim-relay")
# A file in a test folder. After a test, only report.md may change (SPEC.md section 9).
TEST_FOLDER_FILE = re.compile(r"\.verbatim-relay/tests/[^/\s\"']+/([^\s\"'\\]*)")
RECORDS_REASON = (
    "verbatim-relay: the records of a test do not change. Write only report.md. "
    "A command that names .verbatim-relay may only read."
)
ENTRY_REASON = "verbatim-relay: during a test, only the tap runs the entry."
# Prompts that the kit runs and never relays (SPEC.md section 5).
CONTROL = {"verbatim-relay start", "verbatim-relay end", "verbatim-relay status"}


def mode_path(root: Path) -> Path:
    return root / STATE_DIR / "mode"


def is_on(root: Path) -> bool:
    path = mode_path(root)
    return path.exists() and path.read_text().strip() == "on"


def set_mode(root: Path, on: bool) -> None:
    mode_path(root).parent.mkdir(parents=True, exist_ok=True)
    mode_path(root).write_text("on\n" if on else "off\n")


def deny_pattern(urls: list[str]) -> re.Pattern[str] | None:
    """Match the spellings of each URL's host and port. Best effort: the audit is the proof."""
    parts = []
    for url in filter(None, urls):
        u = urlsplit(url)
        host = u.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        port = str(u.port or (443 if u.scheme == "https" else 80))
        hosts = LOOPBACK if host in LOOPBACK or host == "::1" else [host]
        for h in hosts:
            # A port can have leading zeros: a shell and curl read 08800 as 8800.
            parts.append(rf"{re.escape(h)}:0*{port}(?!\d)")
            # A shell opens /dev/tcp/<host>/<port> and /dev/udp/<host>/<port> as a socket.
            for d in dict.fromkeys([h, h.removeprefix("[").removesuffix("]")]):
                parts.append(rf"/dev/(?:tcp|udp)/{re.escape(d)}/0*{port}(?!\d)")
            if u.port is None:
                parts.append(rf"{re.escape(h)}(?![\w.:-])")
    return re.compile("|".join(parts), re.IGNORECASE) if parts else None


def history(record: Path, session: str | None) -> History:
    """The turns of this session that showed the agent's reply (SPEC.md section 5). An invalid
    line in the record raises a RecordError."""
    return [
        (t.said, t.shown)
        for t in read_relay(record, missing_ok=True)
        if isinstance(t, Turn) and t.ok is True and t.session == session and t.shown is not None
    ]


def relay(config: Config, said: str, past: History) -> tuple[str, bool]:
    """Send one message through the tap. Return (the text to show, whether it is the reply)."""
    adapter = make(
        config.adapter,
        config.message_field,
        config.reply_field,
        config.openai_model,
        config.openai_stream,
    )
    req = urllib.request.Request(
        config.tap_url,
        data=adapter.request(said, past),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            stream = is_stream(resp.headers.get("Content-Type"))
            body = resp.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return f"verbatim-relay: the agent returned HTTP {e.code}:\n{text}", False
    except (OSError, ValueError, http.client.HTTPException) as e:
        return f"verbatim-relay: cannot reach the tap at {config.tap_url}: {e}", False
    try:
        # The relay shows a streamed reply only when the stream is complete (SPEC.md section 5).
        return (adapter.stream_reply(body) if stream else adapter.reply(body)), True
    except (AdapterError, StreamError) as e:
        return f"verbatim-relay: cannot read the reply: {e}", False


def _block(reason: str) -> dict[str, Any]:
    return {"decision": "block", "reason": reason}


def _context(text: str) -> dict[str, Any]:
    """Let the prompt go to the model, with the text added as context."""
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}


def start_test(root: Path, tester_session: str | None = None) -> str:
    """Start a test and switch relay mode on. Return the text to show."""
    try:
        cur = bridge.start(root, tester_session)
    except bridge.BridgeError as e:
        return f"verbatim-relay: {e}"
    set_mode(root, True)
    return (
        f"verbatim-relay: test {cur['test']} started. Relay mode is on: each message goes to the "
        "entry. End the test with: verbatim-relay end"
    )


def end_test(root: Path, tester_session: str | None = None) -> str:
    """Switch relay mode off and end the running test. Return the text to show."""
    set_mode(root, False)
    manifest = bridge.end(root, tester_session=tester_session)
    if manifest is None:
        return "verbatim-relay: no test runs. Relay mode is off."
    return "verbatim-relay: relay mode is off.\n" + bridge.summary(manifest)


def status(root: Path) -> str:
    cur = bridge.current(root)
    test = f" Test {cur['test']} runs on {cur['tap_url']}." if cur else ""
    return f"verbatim-relay: relay mode is {'on' if is_on(root) else 'off'}.{test}"


def _control(said: str, root: Path, session: str | None) -> str:
    word = said.strip().split()[-1]
    if word == "start":
        return start_test(root, session)
    if word == "end":
        return end_test(root, session)
    return status(root)


def _relay_test(
    cur: dict[str, Any], said: str, harness: str, session: str | None
) -> dict[str, Any]:
    shown, ok = bridge.send(cur, said)
    row: dict[str, Any] = {
        "type": "turn",
        "harness": harness,
        "said": said,
        "shown": shown,
        "ok": ok,
    }
    if session:
        row["session"] = session
    Writer(Path(cur["dir"]) / "relay.jsonl").append(row)
    return _block(
        "verbatim-relay: relayed to the agent. The reply is in the viewer (verbatim-relay view)."
    )


def handle(event: dict[str, Any], root: Path, harness: str) -> dict[str, Any] | None:
    """Answer one hook event. Return the JSON to print, or None to let the harness go on."""
    name = event.get("hook_event_name")
    if name == "UserPromptSubmit":
        said = event.get("prompt")
        session = event.get("session_id") if isinstance(event.get("session_id"), str) else None
        if isinstance(said, str) and said.strip() in CONTROL:
            text = _control(said, root, session)
            folder = evaluation.pending(root) if said.strip() == "verbatim-relay end" else None
            if folder is None:
                return _block(text)
            # The prompt goes on to the model, which evaluates the test (SPEC.md section 9).
            return _context(f"{text}\n\n{evaluation.prompt(folder)}")
        if not is_on(root):
            return None
        try:
            config = Config.load(root)
        except (OSError, ValueError, TypeError) as e:
            return _block(f"verbatim-relay: relay mode is on, but the config is broken: {e}")
        if not isinstance(said, str):
            return _block("verbatim-relay: the hook input has no prompt text. Nothing was sent.")
        found = lone_surrogate(said)
        if found:
            # A relayed message is never changed, so the kit refuses it (SPEC.md section 5).
            return _block(f"verbatim-relay: nothing was sent. The message has {found}.")
        if config.entry:
            cur = bridge.current(root)
            if cur is None:
                return _block(
                    "verbatim-relay: relay mode is on, but no test runs. Start one with: "
                    "verbatim-relay start. Nothing was sent."
                )
            return _relay_test(cur, said, harness, session)
        record = config.record_path(root)
        shown, ok = relay(config, said, history(record, session))
        row: dict[str, Any] = {
            "type": "turn",
            "harness": harness,
            "said": said,
            "shown": shown,
            "ok": ok,
        }
        if session:
            row["session"] = session
        record.parent.mkdir(parents=True, exist_ok=True)
        Writer(record).append(row)
        return _block(
            "verbatim-relay: relayed to the agent. The reply is in the viewer "
            "(verbatim-relay view)."
        )
    if name == "PreToolUse":
        tool = str(event.get("tool_name", ""))
        tool_input = event.get("tool_input", event)
        text = json.dumps(tool_input, ensure_ascii=False)
        cur = bridge.current(root)
        if cur is not None and tool in WRITE_TOOLS and TEST_FILES.search(text):
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, text)
        if cur is None and tool in WRITE_TOOLS and touches_records(text):
            return _deny(_last_record(root), harness, tool, text, RECORDS_REASON)
        if tool in FILE_TOOLS:
            return None
        reads = commands.tool_reads_only(tool, tool_input)
        if cur is None and TEST_FILES.search(text) and not reads:
            return _deny(_last_record(root), harness, tool, text, RECORDS_REASON)
        # These denies need only the state folder, so a broken config does not stop them.
        if cur is not None and TEST_FILES.search(text):
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, text)
        if cur is not None and not reads and _names_entry(_test_entry(cur), text, tool, tool_input):
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, text, ENTRY_REASON)
        try:
            loaded: Config | None = Config.load(root)
        except (OSError, ValueError, TypeError):
            loaded = None
        if (
            cur is not None
            and loaded is not None
            and not reads
            and _names_entry(loaded.entry, text, tool, tool_input)
        ):
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, text, ENTRY_REASON)
        urls = [loaded.tap_url, loaded.agent_url] if loaded else []
        pattern = deny_pattern([*urls, cur["tap_url"] if cur else ""])
        if pattern is None or not pattern.search(text):
            return None
        if cur is not None:
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, text)
        if loaded is not None:
            return _deny(loaded.record_path(root), harness, tool, text)
    return None


def _test_entry(cur: dict[str, Any]) -> list[str]:
    """The entry of the running test, from its manifest. Return [] if the manifest has none."""
    try:
        entry = json.loads((Path(cur["dir"]) / "manifest.json").read_text()).get("entry")
    except (OSError, ValueError, AttributeError):
        return []
    ok = isinstance(entry, list) and all(isinstance(a, str) for a in entry)
    return entry if ok else []


def _names_entry(entry: list[str], text: str, tool: str, tool_input: Any) -> bool:
    names = commands.entry_names(entry)
    return commands.names_entry(text, names, commands.command_of(tool, tool_input))


def _last_record(root: Path) -> Path:
    """After a test, a deny goes to denied.jsonl, so that the sealed relay.jsonl does not change."""
    last = bridge.latest_test(root)
    return last / seal.DENIED if last else root / STATE_DIR / "relay.jsonl"


def touches_records(text: str) -> bool:
    """True if the text names a file of a test folder other than report.md."""
    return any(m.group(1) != "report.md" for m in TEST_FOLDER_FILE.finditer(text))


def blocked_detail(text: str) -> str:
    """The detail of a blocked_call row (SPEC.md section 2.2): the first 300 code points of the
    text, with each lone surrogate escaped. blockedDetail in the plugin uses the same rule."""
    return escape_surrogates(text[:DETAIL_LIMIT])


def _deny(
    record: Path, harness: str, tool: str, text: str, reason: str = DENY_REASON
) -> dict[str, Any]:
    detail = blocked_detail(text)
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        Writer(record).append(
            {"type": "blocked_call", "harness": harness, "tool": tool, "detail": detail}
        )
    except (OSError, ValueError) as e:
        # The deny must not depend on the record. Without it, the call reaches the tap.
        print(f"verbatim-relay hook: cannot record a blocked call: {e}", file=sys.stderr)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def run_hook(root: Path, harness: str, stdin: TextIO, stdout: TextIO) -> int:
    """The hook command. In relay mode, any failure still blocks the prompt. If the state folder
    exists, any failure of a PreToolUse event denies the tool call."""
    event: Any = None
    try:
        event = json.loads(stdin.read())
        answer = handle(event, root, harness)
    except Exception as e:  # fail closed: a crash must not hand the prompt to the model
        failed = f"verbatim-relay: the hook failed ({type(e).__name__}: {e})."
        tool_call = isinstance(event, dict) and event.get("hook_event_name") == "PreToolUse"
        if tool_call and (root / STATE_DIR).is_dir():
            # Each deny of section 5 needs a file in the state folder. With no folder, none applies.
            answer = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"{failed} The tool call is denied.",
                }
            }
        elif is_on(root):
            answer = _block(f"{failed} Nothing reached the model.")
        else:
            print(f"verbatim-relay hook: {type(e).__name__}: {e}", file=sys.stderr)
            return 0
    if answer is not None:
        stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
    return 0


def hook_command(root: Path, harness: str) -> str:
    argv = [
        sys.executable,
        "-m",
        "verbatim_relay",
        "hook",
        "--root",
        str(root),
        "--harness",
        harness,
    ]
    return " ".join(shlex.quote(a) for a in argv)


def _ours(hook: Any) -> bool:
    return isinstance(hook, dict) and "verbatim_relay hook" in str(hook.get("command", ""))


def _merge_hooks(settings: dict[str, Any], command: str) -> dict[str, Any]:
    """Put the kit's hooks into the settings. Remove only the old hooks of the kit, and keep each
    other hook, also one in the same group. Raise ValueError if the hooks have a wrong form."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' is not a JSON object")
    wanted = {"UserPromptSubmit": ({}, HOOK_DEADLINE), "PreToolUse": ({"matcher": ".*"}, 30)}
    for event, (matcher, timeout) in wanted.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"'hooks.{event}' is not a list")
        kept = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list) or not all(isinstance(h, dict) for h in inner):
                raise ValueError(f"a group of 'hooks.{event}' has no list of hook objects")
            if any(_ours(h) for h in inner):
                rest = [h for h in inner if not _ours(h)]
                if not rest:
                    continue
                group = {**group, "hooks": rest}
            kept.append(group)
        kept.append(
            {**matcher, "hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        )
        groups[:] = kept
    return settings


def hook_file(root: Path, harness: str) -> Path:
    if harness == "codex":
        return root / ".codex" / "hooks.json"
    return root / ".claude" / "settings.local.json"


@dataclass
class Installed:
    """What init wrote."""

    written: list[str]
    # True if init made a new config.json.
    new: bool
    # The keys that got a new value. In a new file: the keys that differ from the default.
    changed: list[str]
    # The keys that keep their value. In a new file, these have the default.
    kept: list[str]


def init(root: Path, harness: str, changes: dict[str, Any]) -> Installed:
    """Write the config, the mode file and the harness hook file.

    An existing config.json keeps each key, and only the keys in `changes` get a new value. A new
    config.json gets each key with its default, then `changes`. If an existing file cannot be
    read, or if a key is unknown, raise ValueError before a write."""
    conf = root / CONFIG_FILE
    new = not conf.exists()
    old = asdict(Config()) if new else read_config(root)
    merged = check({**old, **changes})
    target = hook_file(root, harness)
    try:
        settings = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        if not isinstance(settings, dict):
            raise ValueError("it is not a JSON object")
        settings = _merge_hooks(settings, hook_command(root, harness))
    except (OSError, ValueError) as e:
        raise ValueError(
            f"cannot read {target}: {e}. Correct the file, then run init again."
        ) from None
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(json.dumps(merged, indent=1) + "\n", encoding="utf-8")
    if not mode_path(root).exists():
        set_mode(root, False)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, indent=1) + "\n", encoding="utf-8")
    changed = [k for k in merged if k not in old or old[k] != merged[k]]
    kept = [k for k in merged if k not in changed]
    return Installed([str(conf), str(target)], new, changed, kept)


# The one-line legend at the top of the transcript (SPEC.md section 5).
LEGEND = (
    "Legend: ok (an agent block): the agent answered and the relay showed its reply. It does "
    "not judge the reply. Not ok (a relay error block): the relay got no reply and shows its "
    "own error text."
)


def render_turn(turn: Turn, n: int) -> str:
    shown = "(no reply shown)" if turn.shown is None else turn.shown
    who = "relay error, not an agent reply" if turn.ok is False else "agent"
    return f"──── tester, turn {n} ────\n{turn.said}\n──── {who} ────\n{shown}\n"


def latest_session(record: Path) -> list[Turn]:
    """The turns of the session of the last turn. Turns without a session id are one session."""
    turns = [r for r in read_relay(record) if isinstance(r, Turn)]
    return [t for t in turns if t.session == turns[-1].session] if turns else []


def transcript(
    record: Path, every_session: bool, out: TextIO, scope: str = "", session: str | None = None
) -> int:
    """Print the exact conversation for the harness model to evaluate.

    The plugin's transcript tool runs this command, so that both relays show the same text.
    """
    if session is not None:
        turns = [r for r in read_relay(record) if isinstance(r, Turn) and r.session == session]
        scope = scope or f"session {session}"
    elif every_session:
        turns = [r for r in read_relay(record) if isinstance(r, Turn)]
    else:
        turns = latest_session(record)
    scope = scope or ("all sessions" if every_session else "the latest session")
    out.write(
        f"verbatim-relay transcript, {scope}: {len(turns)} turns. The text is exact: the "
        "tester typed each tester block, and the agent sent each agent block.\n"
        f"{LEGEND}\n\n"
    )
    for n, turn in enumerate(turns, 1):
        out.write(render_turn(turn, n))
    return 0


def view(
    record: Path, follow: bool, out: TextIO, poll: float = 0.3, err: TextIO | None = None
) -> int:
    """Print each turn of the relay record. With follow, wait for new turns.

    An invalid record raises a RecordError. With follow, the view shows the error on err and
    continues: it shows the turns again when the record changes and is valid.
    """
    seen = 0
    for turns in _turns(record, follow, poll, _ErrorOnce(err or sys.stderr)):
        for turn in turns[seen:]:
            seen += 1
            out.write(render_turn(turn, seen))
            out.flush()
    return 0


def view_tests(
    root: Path, follow: bool, out: TextIO, poll: float = 0.3, err: TextIO | None = None
) -> int:
    """Print each turn of the latest test. With follow, wait for new turns and new tests.

    An invalid record raises a RecordError. With follow, the view shows the error on err and
    continues, as in view.
    """
    shown_test, seen = None, 0
    errors = _ErrorOnce(err or sys.stderr)
    while True:
        folder = bridge.latest_test(root)
        if folder is not None and folder != shown_test:
            shown_test, seen = folder, 0
            errors.clear()
            out.write(f"════ test {folder.name} ════\n")
            out.flush()
        record = folder / "relay.jsonl" if folder else None
        if record is not None and record.exists():
            try:
                turns = [r for r in read_relay(record) if isinstance(r, Turn)]
                errors.clear()
            except RecordError as e:
                if not follow:
                    raise
                errors.show(e, record)
                turns = []
            for turn in turns[seen:]:
                seen += 1
                out.write(render_turn(turn, seen))
                out.flush()
        if not follow:
            return 0
        time.sleep(poll)


class _ErrorOnce:
    """Show a record error once. Show it again only when the error or the record changes."""

    def __init__(self, err: TextIO) -> None:
        self.err = err
        self.last: tuple[str, tuple[int, int] | None] | None = None

    def show(self, e: RecordError, record: Path) -> None:
        try:
            st = record.stat()
            stamp: tuple[int, int] | None = (st.st_size, st.st_mtime_ns)
        except OSError:
            stamp = None
        if (str(e), stamp) == self.last:
            return
        self.last = (str(e), stamp)
        cause = "the record is invalid" if e.kind == "record_invalid" else "cannot read the record"
        self.err.write(
            f"verbatim-relay: {cause}: {e}. Do not trust this record. "
            "The view shows the next turns when the record changes and is valid.\n"
        )
        self.err.flush()

    def clear(self) -> None:
        self.last = None


def _turns(record: Path, follow: bool, poll: float, errors: _ErrorOnce) -> Iterator[list[Turn]]:
    while True:
        try:
            # With follow, the view waits for a record that does not exist yet.
            yield [r for r in read_relay(record, missing_ok=follow) if isinstance(r, Turn)]
            errors.clear()
        except RecordError as e:
            if not follow:
                raise
            errors.show(e, record)
        if not follow:
            return
        time.sleep(poll)

"""The relay of SPEC.md section 5: command hooks that Codex and Claude Code share."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from nookku import commands, policy, print_mode, seal, state
from nookku.adapters import AdapterError, History, StreamError, is_stream, make
from nookku.config import FILE as CONFIG_FILE
from nookku.config import OLD_STATE_DIR, check, move_old_state, read_config
from nookku.config import Config as Config
from nookku.record import (
    RecordError,
    Turn,
    Writer,
    escape_surrogates,
    lone_surrogate,
    read_relay,
)

STATE_DIR = state.STATE_DIR
TIMEOUT = 280
# The UserPromptSubmit hook deadline. Each relay timeout must end before it, so that the hook
# can still block the prompt.
HOOK_DEADLINE = 300
# The number of code points in the detail of a blocked_call row (SPEC.md section 2.2).
DETAIL_LIMIT = 300
LOOPBACK = ["127.0.0.1", "localhost", "0.0.0.0", "[::1]"]
# Tools that only read, write or search files. Every other tool is denied when its input names
# the tap or the agent, so a tool that the relay does not know is denied too.
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
# The input fields of a file tool that give its target path.
PATH_FIELDS = ("file_path", "notebook_path", "path")
DENY_REASON = "nookku: only the tester talks to the agent."
# The files and folders of the state folder that only nookku writes, also when no test runs
# (SPEC.md section 5). In a test folder, only report.md may change (SPEC.md section 9). `seals`
# is the folder of the seal copies in the nookku home.
RECORDS = {"tests", "current.json", "mode", "relay.jsonl", "tap.jsonl", "ending.json", "seals"}
RECORDS_REASON = (
    "nookku: {name} is a record or a state file of nookku. Only nookku writes it. "
    "A command may read it."
)
# The cause when the read check cannot parse a shell command.
UNPARSED = "The guard cannot parse the command."
TEST_REASON = (
    "nookku: a test runs, so a tool call may not name {name} until the test ends. "
    "The file tools may read it."
)
ENTRY_REASON = "nookku: during a test, only the tap runs the entry."
# The deny of a model command that drives a test (SPEC.md section 5, #173).
SCENARIO = "To run a scenario, use nookku run --script, if the policy key scripts is model."
DRIVE_REASON = (
    "nookku: only a person runs {what}. A model command may not drive a test. " + SCENARIO
)
IMPORT_REASON = (
    "nookku: a model command may not import nookku, because a script can drive a test with it. "
    + SCENARIO
)
# A command hook gets only the text of a prompt, not its attachments. The display layer of the
# Claude Code plugin sees them, and drops the prompt with this text in relay mode (#216).
ATTACHMENTS_REASON = "nookku: the relay does not send attachments. Nothing was sent."
# Prompts that the relay runs and never relays (SPEC.md section 5).
CONTROL = {"nookku start", "nookku end", "nookku status"}
# The refusal of a message near a control prompt in relay mode (#146).
NEAR_CONTROL_REASON = (
    "nookku: nothing was sent. The message is near a control prompt. The control prompts are: "
    "nookku start, nookku end, nookku status."
)


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
    # Imported here, so that an event that does not relay stays fast (#214).
    import http.client
    import urllib.error
    import urllib.request

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
        return f"nookku: the agent returned HTTP {e.code}:\n{text}", False
    except (OSError, ValueError, http.client.HTTPException) as e:
        return f"nookku: cannot reach the tap at {config.tap_url}: {e}", False
    try:
        # The relay shows a streamed reply only when the stream is complete (SPEC.md section 5).
        return (adapter.stream_reply(body) if stream else adapter.reply(body)), True
    except (AdapterError, StreamError) as e:
        return f"nookku: cannot read the reply: {e}", False


def checked(shown: str, ok: bool) -> tuple[str, bool]:
    """The text that the relay shows and writes as `shown`, with its `ok` (SPEC.md section 5).

    A record text holds only Unicode scalar values (SPEC.md section 2), and the relay never
    changes a reply. So the relay refuses a reply with a lone surrogate and shows an error. An
    error text is not a reply, so each lone surrogate in it becomes its escape text. Both relay
    paths, with an entry and with no entry, use this one rule, so the turn is always valid.
    """
    if not ok:
        return escape_surrogates(shown), False
    found = lone_surrogate(shown)
    if found:
        return f"nookku: cannot read the reply: the agent reply has {found}.", False
    return shown, True


def _block(reason: str) -> dict[str, Any]:
    """Block the prompt. Both harnesses show the reason to the person and not to the model (#176,
    #193), so the reason of a relayed prompt is the text to show, byte for byte."""
    return {"decision": "block", "reason": reason}


def _context(text: str) -> dict[str, Any]:
    """Let the prompt go to the model, with the text added as context."""
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}


def end_ways(root: Path) -> str:
    """The ways to end a test, for each start text (SPEC.md section 9.1). If the evaluation is
    off, the prompt nookku end starts no evaluation, so the text does not name it (#114)."""
    from nookku import evaluation

    if not evaluation.enabled(root):
        return "To end the test, type the prompt nookku end, or run nookku end in a shell."
    return (
        "To end the test and start the evaluation, type the prompt nookku end. "
        "To end the test with no evaluation, run nookku end in a shell."
    )


def start_test(root: Path, tester_session: str | None = None) -> str:
    """Start a test and switch relay mode on. Return the text to show."""
    from nookku import bridge

    try:
        cur = bridge.start(root, tester_session)
    except bridge.BridgeError as e:
        return f"nookku: {e}"
    set_mode(root, True)
    # The plugin and the project hooks show this text.
    # `nookku start` in a shell gives the same ways.
    return (
        f"nookku: test {cur['test']} started. Relay mode is on: each message goes to the entry. "
        + end_ways(root)
    )


def end_test(root: Path, tester_session: str | None = None) -> str:
    """Switch relay mode off and end the running test. Return the text to show."""
    from nookku import bridge

    set_mode(root, False)
    manifest = bridge.end(root, tester_session=tester_session)
    if manifest is None:
        return "nookku: no test runs. Relay mode is off."
    return "nookku: relay mode is off.\n" + bridge.summary(manifest)


def status(root: Path) -> str:
    """The status text of the prompt nookku status. `nookku status`, the status line of the
    plugin and the status tool of `nookku mcp` show the same text, so both relays give one text
    (#117)."""
    cur = state.current(root)
    test = f"Test {cur['test']} runs on {cur['tap_url']}." if cur else "No test runs."
    return f"nookku: relay mode is {'on' if is_on(root) else 'off'}. {test}"


def _control(said: str, root: Path, session: str | None) -> str:
    word = said.strip().split()[-1]
    if word == "start":
        return start_test(root, session)
    if word == "end":
        return end_test(root, session)
    return status(root)


def _edit_distance(a: str, b: str, limit: int) -> int:
    """The edit distance of a and b, or limit + 1 if it is more than limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return min(row[-1], limit + 1)


def near_control(said: str, limit: int) -> bool:
    """True if a message that is not a control prompt looks like one (SPEC.md section 5): its
    first word is nookku in any case, or the message is at most limit edits from a control
    prompt. A limit of 0 turns off the rule."""
    words = said.split()
    if limit <= 0 or said.strip() in CONTROL or not words:
        return False
    text = " ".join(words).casefold()
    return words[0].casefold() == "nookku" or any(
        _edit_distance(text, c, limit) <= limit for c in CONTROL
    )


def _relay_test(
    cur: dict[str, Any], said: str, harness: str, session: str | None
) -> dict[str, Any]:
    shown, ok = checked(*state.send(cur, said))
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
    return _block(shown)


def handle(event: dict[str, Any], root: Path, harness: str) -> dict[str, Any] | None:
    """Answer one hook event. Return the JSON to print, or None to let the harness go on."""
    name = event.get("hook_event_name")
    if name == "UserPromptSubmit":
        said = event.get("prompt")
        session = event.get("session_id") if isinstance(event.get("session_id"), str) else None
        # Out of the interactive CLI, Claude Code can send the prompt to the model API in a title
        # request. The relay refuses to start a test and to relay a message (SPEC.md section 5).
        in_print_mode = print_mode.applies(os.environ, harness)
        if in_print_mode and isinstance(said, str) and said.strip() == "nookku start":
            return _block(print_mode.REASON)
        if isinstance(said, str) and said.strip() in CONTROL:
            from nookku import evaluation

            text = _control(said, root, session)
            folder = evaluation.pending(root) if said.strip() == "nookku end" else None
            if folder is None:
                note = evaluation.config_note(root) if said.strip() == "nookku end" else None
                return _block(f"{text}\n{note}" if note else text)
            # The prompt goes on to the model, which evaluates the test (SPEC.md section 9).
            return _context(f"{text}\n\n{evaluation.prompt(folder)}")
        if not is_on(root):
            return None
        if in_print_mode:
            # A refused message is not a turn, so the relay writes no row.
            return _block(print_mode.REASON)
        try:
            config = Config.load(root)
        except (OSError, ValueError, TypeError) as e:
            return _block(f"nookku: relay mode is on, but the config is broken: {e}")
        if not isinstance(said, str):
            return _block("nookku: the hook input has no prompt text. Nothing was sent.")
        found = lone_surrogate(said)
        if found:
            # A relayed message is never changed, so the relay refuses it (SPEC.md section 5).
            return _block(f"nookku: nothing was sent. The message has {found}.")
        rules = _policy(root)
        limit = rules["control_distance"] if rules is not None else None
        if near_control(said, policy.KEYS["control_distance"].default if limit is None else limit):
            # A refused message is not a turn, so the relay writes no row (SPEC.md section 5).
            return _block(NEAR_CONTROL_REASON)
        if config.entry:
            cur = state.current(root)
            if cur is None:
                return _block(
                    "nookku: relay mode is on, but no test runs. Start one with: "
                    "nookku start. Nothing was sent."
                )
            return _relay_test(cur, said, harness, session)
        record = config.record_path(root)
        shown, ok = checked(*relay(config, said, history(record, session)))
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
        return _block(shown)
    if name == "PreToolUse":
        tool = str(event.get("tool_name", ""))
        tool_input = event.get("tool_input", event)
        text = json.dumps(tool_input, ensure_ascii=False)
        # The blocked_call row keeps the whole input. The checks of a tool that is not a shell or
        # a file tool read only the fields of guard_fields (SPEC.md section 5).
        full = text
        rules = _policy(root)
        fields = rules["guard_fields"] if rules is not None and _other_tool(tool) else None
        extra = frozenset(rules["guard_reads"]) if rules is not None else frozenset()
        if fields is not None:
            tool_input = guarded(tool_input, fields)
            text = json.dumps(tool_input, ensure_ascii=False)
        cur = state.current(root)
        if touches_policy(event, root, tool, tool_input, text):
            record = Path(cur["dir"]) / "relay.jsonl" if cur else _last_record(root)
            return _deny(record, harness, tool, full, policy.REASON)
        reason = drive_reason(tool, tool_input, rules)
        if reason is not None:
            record = Path(cur["dir"]) / "relay.jsonl" if cur else _last_record(root)
            return _deny(record, harness, tool, full, reason)
        # These denies need only the state folder, so a broken config does not stop them.
        written = state_write(event, root, tool, tool_input, cur is not None, extra)
        if written is not None and cur is not None:
            reason = TEST_REASON.format(name=written[0])
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, full, reason)
        if written is not None:
            name, cause = written
            reason = RECORDS_REASON.format(name=name) + (f" {cause}" if cause else "")
            return _deny(_last_record(root), harness, tool, full, reason)
        if tool in FILE_TOOLS:
            return None
        reads = commands.tool_reads_only(tool, tool_input, extra)
        if cur is not None and not reads and _names_entry(_test_entry(cur), text, tool, tool_input):
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, full, ENTRY_REASON)
        loaded = _guard_config(root)
        if (
            cur is not None
            and loaded is not None
            and not reads
            and _names_entry(loaded.entry, text, tool, tool_input)
        ):
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, full, ENTRY_REASON)
        urls = [loaded.tap_url, loaded.agent_url] if loaded else []
        pattern = deny_pattern([*urls, cur["tap_url"] if cur else ""])
        if pattern is None or not pattern.search(text):
            return None
        if cur is not None:
            return _deny(Path(cur["dir"]) / "relay.jsonl", harness, tool, full)
        if loaded is not None:
            return _deny(loaded.record_path(root), harness, tool, full)
    return None


# Tools that are a shell in all but name. Their whole input is a command, so each field counts.
SESSION_TOOLS = {"write_stdin"}


def _guard_config(root: Path) -> Config | None:
    """The config keys that the guard uses: tap_url, agent_url, record and entry. If the file
    breaks the rule of the one reader, the guard still takes each of these keys that has the
    right type. Thus a wrong value of another key, for example "evaluate": "no", does not allow a
    call to the tap or to the agent (#121). If the file exists but is not a JSON object, the
    guard uses the default values, so a broken file never gives fewer denies than the defaults
    (#294). None if the project has no config file."""
    try:
        return Config.load(root)
    except (OSError, ValueError, TypeError):
        pass
    try:
        data = json.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return Config()
    if not isinstance(data, dict):
        return Config()
    keep: dict[str, Any] = {
        k: data[k] for k in ("tap_url", "agent_url", "record") if isinstance(data.get(k), str)
    }
    entry = data.get("entry")
    if isinstance(entry, list) and all(isinstance(a, str) for a in entry):
        keep["entry"] = entry
    return Config(**keep)


def _other_tool(tool: str) -> bool:
    """True for a tool that is not a shell or a file tool, for example an MCP tool."""
    return tool not in FILE_TOOLS and tool not in commands.SHELL_TOOLS and tool not in SESSION_TOOLS


def _policy(root: Path) -> dict[str, Any] | None:
    """The policy keys, or None if the policy file is not valid. Then each field counts and no
    program is added to the read programs, so a broken file does not weaken the guard."""
    try:
        return policy.read(root)
    except policy.PolicyError:
        return None


def guarded(value: Any, fields: list[str]) -> list[Any]:
    """The value of each key in `fields`, at each depth of a tool input."""
    out: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in fields:
                out.append(item)
            else:
                out += guarded(item, fields)
    elif isinstance(value, list):
        for item in value:
            out += guarded(item, fields)
    return out


def drive_reason(tool: str, tool_input: Any, rules: dict[str, Any] | None) -> str | None:
    """The deny reason if a model tool call drives a test, else None (SPEC.md section 5). With a
    policy file that is not valid, scripts has its default, person."""
    command: str | None
    if tool in SESSION_TOOLS and isinstance(tool_input, dict):
        chars = tool_input.get("chars")
        command = chars if isinstance(chars, str) else json.dumps(tool_input)
    else:
        command = commands.command_of(tool, tool_input)
    if command is None:
        return None
    scripts = rules["scripts"] if rules is not None else policy.KEYS["scripts"].default
    what = commands.drive(command, frozenset({"nookku run"} if scripts == "model" else ()))
    if what is None:
        return None
    return IMPORT_REASON if what == commands.IMPORT else DRIVE_REASON.format(what=what)


def touches_policy(event: Any, root: Path, tool: str, tool_input: Any, text: str) -> bool:
    """True if a model tool call can change the policy file (SPEC.md section 5)."""
    writes = tool in WRITE_TOOLS
    if tool in FILE_TOOLS and not writes:
        return False
    reads = not writes and commands.tool_reads_only(tool, tool_input)
    cwd = event.get("cwd") if isinstance(event, dict) else None
    here = root / cwd if isinstance(cwd, str) and cwd else root
    return policy.touches(root, tool, tool_input, text, writes, reads, here)


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
    last = state.latest_test(root)
    return last / seal.DENIED if last else root / STATE_DIR / "relay.jsonl"


def _protected(rest: list[str], during: bool) -> bool:
    """True if a path in the state folder, given by its parts after the folder, is protected:
    during a test, each path. With no test, the state folder itself and each record."""
    if during or not rest:
        return True
    first = rest[0].lower()
    if any(c in first for c in "*?["):
        return any(fnmatch.fnmatchcase(r, first) for r in RECORDS)
    if first == "tests" and len(rest) == 3 and rest[2].lower() == "report.md":
        return False
    return first in RECORDS


def _event_cwd(event: dict[str, Any], tool_input: Any, root: Path) -> Path:
    """The folder of a tool call: the `workdir` of a Codex shell call, else the `cwd` of the
    event, else the project."""
    named = tool_input.get("workdir") if isinstance(tool_input, dict) else None
    if not isinstance(named, str) or not named:
        named = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    return root / named if named else root


def _in_state(path: Path) -> bool:
    return commands.state_rest(str(path)) is not None


def state_write(
    event: dict[str, Any],
    root: Path,
    tool: str,
    tool_input: Any,
    during: bool,
    extra: frozenset[str] = frozenset(),
) -> tuple[str, str] | None:
    """The protected path of the state folder that a model tool call can write, with the cause for
    the deny reason, or None (SPEC.md section 5). The cause is "" during a test and for a call
    that is not a shell command. During a test, a call except a file read may not name the state
    folder at all.

    The rule checks paths, not text. A file tool has its target path. A shell command has the
    words that it can write (commands.write_targets), without the bodies of its here-documents
    that are data. Another tool has each word of its input."""
    cwd = _event_cwd(event, tool_input, root)
    if tool in WRITE_TOOLS:
        fields = tool_input if isinstance(tool_input, dict) else {}
        paths: list[str] = [v for f in PATH_FIELDS if isinstance(v := fields.get(f), str) and v]
        for p in [*paths, *commands.patch_targets(tool, tool_input)]:
            full = cwd / p
            for candidate in (p, str(full), str(full.resolve())):
                rest = commands.state_rest(candidate)
                if rest is not None and _protected(rest, during):
                    return p, ""
        return None
    if tool in FILE_TOOLS:
        return None
    command = commands.command_of(tool, tool_input)
    if command is None:
        words = commands.state_words(tool_input)
        named = (w for w in words if _protected(commands.state_rest(w) or [], during))
        return next(((w, "") for w in named), None)
    stripped = commands.strip_data_heredocs(command)
    if during:
        if _in_state(cwd):
            return str(cwd), ""
        return next(((w, "") for w in commands.state_words(stripped)), None)
    found = commands.write_targets(command, extra)
    if found is None:
        # The check cannot parse the command, so each word that names the state folder counts.
        return next(((w, UNPARSED) for w in commands.state_words(stripped)), None)
    for word, cause in found.targets:
        # An argument can be code, for example python3 -c "open('<path>', 'w')". So each path in
        # it counts, not only the whole word.
        for part in [word, *commands.path_words(word)]:
            rest = commands.state_rest(part)
            if rest is not None and _protected(rest, during):
                return part, cause
    if commands.reads_only(command, extra):
        return None
    # A relative word of a command that runs in the state folder does not name the folder.
    for folder in found.folders:
        if commands.state_rest(folder) is not None:
            return folder, found.cause
    return (str(cwd), found.cause) if _in_state(cwd) else None


def blocked_detail(text: str) -> str:
    """The detail of a blocked_call row (SPEC.md section 2.2): the first 300 code points of the
    text, with each lone surrogate escaped. The plugin and the project hooks use this function."""
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
        print(f"nookku hook: cannot record a blocked call: {e}", file=sys.stderr)
    return _deny_answer(reason)


def _deny_answer(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _policy_write(event: Any, root: Path) -> bool:
    """True if a PreToolUse event can change the policy file. A failure denies the call."""
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return False
    try:
        tool = str(event.get("tool_name", ""))
        tool_input = event.get("tool_input", event)
        # With no state folder, no policy file exists, so the default guard fields apply.
        if _other_tool(tool):
            tool_input = guarded(tool_input, policy.KEYS["guard_fields"].default)
        text = json.dumps(tool_input, ensure_ascii=False)
        return touches_policy(event, root, tool, tool_input, text)
    except Exception:  # fail closed
        return True


def _no_state_drive(event: Any) -> str | None:
    """The drive deny in a project with no state folder, for example nookku init && nookku
    start. Each policy key has its default. A failure denies the call."""
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return None
    try:
        return drive_reason(str(event.get("tool_name", "")), event.get("tool_input", event), None)
    except Exception as e:  # fail closed
        return f"nookku: the hook failed ({type(e).__name__}: {e})."


def project_root(event: Any, harness: str) -> Path:
    """The project of a hook event with no --root: in Claude Code CLAUDE_PROJECT_DIR, else the
    `cwd` of the event, else the working folder of the process. A plugin hook does not know the
    project when it is installed, so it finds the project here. A Codex hook can inherit
    CLAUDE_PROJECT_DIR from a Claude Code session of another project, so Codex never uses it."""
    named = os.environ.get("CLAUDE_PROJECT_DIR") if harness == "claude-code" else None
    if not named and isinstance(event, dict) and isinstance(event.get("cwd"), str):
        named = event["cwd"]
    return Path(named or os.getcwd()).resolve()


def run_hook(root: Path | None, harness: str, stdin: TextIO, stdout: TextIO) -> int:
    """The hook command. In relay mode, any failure still blocks the prompt. If the state folder
    exists, any failure of a PreToolUse event denies the tool call. With no root, the event gives
    it (project_root)."""
    event: Any = None
    try:
        raw = stdin.read()
    except (OSError, ValueError) as e:
        print(f"nookku hook: cannot read the event: {e}", file=sys.stderr)
        return 2
    try:
        event = json.loads(raw)
    except ValueError:
        event = None
    if root is None:
        root = project_root(event, harness)
    error = move_old_state(root)
    if error:
        print(f"nookku: {error}", file=sys.stderr)
        # Exit 2 blocks the event, so the relay fails closed.
        return 2
    if not (root / STATE_DIR).is_dir():
        # The plugin runs this hook in each project. A project with no state folder has no test,
        # no relay mode and no record. Only the deny of the policy file applies, so that the
        # model cannot write a weak policy before the first test. It writes no record.
        if _policy_write(event, root):
            stdout.write(json.dumps(_deny_answer(policy.REASON), ensure_ascii=False) + "\n")
            return 0
        reason = _no_state_drive(event)
        if reason is not None:
            stdout.write(json.dumps(_deny_answer(reason), ensure_ascii=False) + "\n")
        return 0
    try:
        if event is None:
            event = json.loads(raw)
        answer = handle(event, root, harness)
    except Exception as e:  # fail closed: a crash must not hand the prompt to the model
        failed = f"nookku: the hook failed ({type(e).__name__}: {e})."
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
            print(f"nookku hook: {type(e).__name__}: {e}", file=sys.stderr)
            return 0
    if answer is not None:
        stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
    return 0


def hook_command(root: Path, harness: str) -> str:
    argv = [
        sys.executable,
        "-m",
        "nookku",
        "hook",
        "--root",
        str(root),
        "--harness",
        harness,
    ]
    return " ".join(shlex.quote(a) for a in argv)


# The hook commands of nookku. verbatim-relay 0.3.x and earlier wrote the second one, so a new
# `init` replaces those hooks too.
OWN_COMMANDS = ("nookku hook", "verbatim_relay hook")


# The events of the hooks, with the matcher and the timeout in seconds of each. The plugin's
# hooks/hooks.json has the same events (tests/test_plugin.py).
HOOK_EVENTS: dict[str, tuple[dict[str, str], int]] = {
    "UserPromptSubmit": ({}, HOOK_DEADLINE),
    "PreToolUse": ({"matcher": ".*"}, 30),
}


def _ours(hook: Any) -> bool:
    return isinstance(hook, dict) and any(c in str(hook.get("command", "")) for c in OWN_COMMANDS)


def _merge_hooks(settings: dict[str, Any], command: str) -> dict[str, Any]:
    """Put the project hooks into the settings. Remove only the old project hooks, and keep each
    other hook, also one in the same group. Raise ValueError if the hooks have a wrong form."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' is not a JSON object")
    for event, (matcher, timeout) in HOOK_EVENTS.items():
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


def _remove_hooks(settings: dict[str, Any]) -> int:
    """Remove each hook of nookku from the settings, and return the count. Remove a group and
    an event that the removal makes empty, and then an empty hooks key. Keep each other hook and
    key. Raise ValueError if the hooks have a wrong form."""
    if "hooks" not in settings:
        return 0
    hooks = settings["hooks"]
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' is not a JSON object")
    removed = 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            raise ValueError(f"'hooks.{event}' is not a list")
        kept = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list) or not all(isinstance(h, dict) for h in inner):
                raise ValueError(f"a group of 'hooks.{event}' has no list of hook objects")
            if any(_ours(h) for h in inner):
                rest = [h for h in inner if not _ours(h)]
                removed += len(inner) - len(rest)
                if not rest:
                    continue
                group = {**group, "hooks": rest}
            kept.append(group)
        if kept or len(kept) == len(groups):
            groups[:] = kept
        else:
            del hooks[event]
    if removed and not hooks:
        del settings["hooks"]
    return removed


@dataclass
class Removed:
    """What init --remove changed."""

    path: Path
    # The count of removed hooks. 0 if the file has no hook of nookku or does not exist.
    count: int
    # The text of the file before the removal, to put it back.
    before: str = ""


def remove(root: Path, harness: str) -> Removed:
    """Remove the project hooks of nookku from the hook file of the harness (#163). Keep each
    other hook and key, the file itself and the state folder. If the file cannot be read, raise
    ValueError before a write."""
    target = hook_file(root, harness)
    if target is None:
        raise ValueError("the nookku plugin has the hooks, so no project file has them")
    if not target.exists():
        return Removed(target, 0)
    try:
        before = target.read_text(encoding="utf-8")
        settings = json.loads(before)
        if not isinstance(settings, dict):
            raise ValueError("it is not a JSON object")
        count = _remove_hooks(settings)
    except (OSError, ValueError) as e:
        raise ValueError(
            f"cannot read {target}: {e}. Correct the file, then run init --remove again"
        ) from None
    if count:
        try:
            replace_text(target, json.dumps(settings, indent=1) + "\n")
        except OSError as e:
            raise ValueError(f"cannot write {target}: {e}") from None
    return Removed(target, count, before)


def replace_text(path: Path, text: str) -> None:
    """Write a new file and replace the old one, so a failed write leaves the old file whole."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def hook_file(root: Path, harness: str) -> Path | None:
    """The file of the project hooks. With the plugin, the plugin has the hooks, so None."""
    if harness == "plugin":
        return None
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


def _test_project(folder: Path) -> str | None:
    """The project root of a test folder, from its manifest.json, or None if the folder is not
    a test folder of nookku. A copied test folder also has its manifest."""
    try:
        data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("versions"), dict):
        return None
    ours = "nookku" in data["versions"] or "verbatim-relay" in data["versions"]
    return str(data.get("root", "")) if ours and isinstance(data.get("test"), str) else None


def state_root_error(root: Path, harness: str) -> str | None:
    """The error of init if root is in a state folder or a test folder, else None (#148). A
    state folder matches by its name, in any case, because the file system of macOS and Windows
    ignores case, or by its marker file, for the target of a symlink. A test folder matches by
    its manifest."""
    names = (STATE_DIR.casefold(), OLD_STATE_DIR.casefold())
    for folder in (root, *root.parents):
        if folder.name.casefold() in names:
            return (
                f"the root {root} is inside the state folder {folder}. Run init in the "
                f"project: nookku init {harness} --root {folder.parent}"
            )
        if (folder / state.MARKER).is_file():
            return (
                f"the root {root} is inside the state folder {folder}. Run init in the "
                "project that holds this state folder"
            )
        project = _test_project(folder)
        if project is not None:
            where = f": nookku init {harness} --root {project}" if project else ""
            return (
                f"the root {root} is inside the test folder {folder}. Run init in the "
                f"project{where}"
            )
    return None


def init(root: Path, harness: str, changes: dict[str, Any]) -> Installed:
    """Write the config, the mode file and the harness hook file. For the plugin, write no hook
    file, because the plugin has the hooks.

    An existing config.json keeps each key, and only the keys in `changes` get a new value. A new
    config.json gets each key with its default, then `changes`. If an existing file cannot be
    read, if a key is unknown, or if root is inside a state folder, raise ValueError before a
    write (#148)."""
    error = state_root_error(root, harness)
    if error is not None:
        raise ValueError(error)
    conf = root / CONFIG_FILE
    new = not conf.exists()
    old = asdict(Config()) if new else read_config(root)
    merged = check({**old, **changes})
    target = hook_file(root, harness)
    settings: dict[str, Any] = {}
    try:
        if target is not None and target.exists():
            settings = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError("it is not a JSON object")
        settings = _merge_hooks(settings, hook_command(root, harness))
    except (OSError, ValueError) as e:
        raise ValueError(
            f"cannot read {target}: {e}. Correct the file, then run init again."
        ) from None
    conf.parent.mkdir(parents=True, exist_ok=True)
    state.mark(conf.parent)
    conf.write_text(json.dumps(merged, indent=1) + "\n", encoding="utf-8")
    if not mode_path(root).exists():
        set_mode(root, False)
    written = [str(conf)]
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(settings, indent=1) + "\n", encoding="utf-8")
        written.append(str(target))
    changed = [k for k in merged if k not in old or old[k] != merged[k]]
    kept = [k for k in merged if k not in changed]
    return Installed(written, new, changed, kept)


# The one-line legend at the top of the transcript (SPEC.md section 5).
LEGEND = (
    "Legend: ok (an agent block): the agent answered and the relay showed its reply. It does "
    "not judge the reply. Not ok (a relay error block): the relay got no reply and shows its "
    "own error text."
)


def render_turn(turn: Turn, n: int) -> str:
    shown = "(no reply shown)" if turn.shown is None else turn.shown
    who = "relay error, not an agent reply" if turn.ok is False else "agent"
    # A scripted turn is never shown as a typed turn (SPEC.md section 7.10).
    sender = "script" if turn.harness == "script" else "tester"
    return f"──── {sender}, turn {n} ────\n{turn.said}\n──── {who} ────\n{shown}\n"


def latest_session(record: Path) -> list[Turn]:
    """The turns of the session of the last turn. Turns without a session id are one session."""
    turns = [r for r in read_relay(record) if isinstance(r, Turn)]
    return [t for t in turns if t.session == turns[-1].session] if turns else []


def transcript(
    record: Path, every_session: bool, out: TextIO, scope: str = "", session: str | None = None
) -> int:
    """Print the exact conversation for the harness model to evaluate.

    The plugin's transcript tool runs this command, so that both forms show the same text.
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
        f"nookku transcript, {scope}: {len(turns)} turns. The text is exact: the "
        "tester typed each tester block, and the agent sent each agent block.\n"
        f"{LEGEND}\n\n"
    )
    for n, turn in enumerate(turns, 1):
        out.write(render_turn(turn, n))
    return 0


class TranscriptError(Exception):
    """The transcript cannot be made. The text says why."""


# The name of a test folder. It has no path separator and no drive, on each system.
TEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
TESTS_HELP = f"A test id is the name of a folder in {STATE_DIR}/tests of the project."


def folder_of_test(root: Path, test: str) -> Path:
    """The folder of a test id, which must stay in the tests folder of the project. The model
    can give the id to the transcript tool, so a path must not reach another folder."""
    tests = (root / STATE_DIR / "tests").resolve()
    folder = (tests / test).resolve()
    if not TEST_ID.fullmatch(test) or folder.parent != tests:
        raise TranscriptError(f"'{test}' is not a test id. {TESTS_HELP}")
    return folder


def parse_test_arg(root: Path, arg: str) -> str:
    """The test id of a TEST argument of the CLI. A tester can give the test id or the path of
    the test folder. Raise TranscriptError with the expected argument for other text."""
    if TEST_ID.fullmatch(arg):
        return arg
    tests = (root / STATE_DIR / "tests").resolve()
    # The shell expands "~", so the argument is a path as it is. A loop of symbolic links
    # raises RuntimeError or OSError, and then the argument is not a test folder.
    try:
        folder = Path(arg).resolve()
    except (OSError, RuntimeError):
        folder = None
    if folder is not None and folder.parent == tests and TEST_ID.fullmatch(folder.name):
        return folder.name
    raise TranscriptError(f"'{arg}' is not a test id or a test folder. {TESTS_HELP}")


def existing_test(root: Path, test: str) -> Path:
    """The folder of a test id. Raise TranscriptError that names the expected argument if the
    id is not valid or the test does not exist."""
    folder = folder_of_test(root, test)
    if not folder.is_dir():
        raise TranscriptError(f"no test '{test}'. {TESTS_HELP}")
    return folder


def _latest(root: Path) -> Path | None:
    """The latest test, with the same check as a test id: a symbolic link in the tests folder
    must not take the transcript to a folder outside the project."""
    last = state.latest_test(root)
    return None if last is None else folder_of_test(root, last.name)


def transcript_text(
    root: Path,
    test: str | None = None,
    trace: bool = False,
    every_session: bool = False,
    session: str | None = None,
    record: Path | None = None,
    compact: bool | None = None,
) -> str:
    """The text of `nookku transcript`. The CLI and the transcript tool of `nookku mcp` use it,
    so that both give the model the same text. Raise TranscriptError if it cannot be made.

    `compact` applies only with trace. None takes the config key `transcript_compact`."""
    import io

    def config() -> Config:
        # The plugin has no config file. Without one, use the defaults.
        has_config = (root / STATE_DIR / "config.json").exists()
        try:
            return Config.load(root) if has_config else Config()
        except (OSError, ValueError, TypeError) as e:
            raise TranscriptError(f"cannot read the config: {e}") from None

    if trace:
        folder = existing_test(root, test) if test else _latest(root)
        if folder is None or not folder.is_dir():
            raise TranscriptError("no test folder.")
        from nookku import evaluation

        if compact is None:
            compact = config().transcript_compact
        return evaluation.transcript(folder, compact)
    conf = config()
    folder = _latest(root) if conf.entry and not record else None
    if test and not record:
        folder = existing_test(root, test)
    path = record or (folder / "relay.jsonl" if folder else conf.record_path(root))
    out = io.StringIO()
    scope = f"test {folder.name}" if folder else ""
    try:
        transcript(path, every_session or folder is not None, out, scope, session)
    except RecordError as e:
        raise TranscriptError(str(e)) from None
    return out.getvalue()


def view(
    record: Path, follow: bool, out: TextIO, poll: float = 0.3, err: TextIO | None = None
) -> int:
    """Print each turn of the relay record. With follow, wait for new turns.

    An invalid record raises a RecordError. With follow, the view shows the error on err and
    continues: it shows the turns again when the record changes and is valid.
    """
    shown = _Shown(out)
    for turns in _turns(record, follow, poll, _ErrorOnce(err or sys.stderr)):
        shown.show(turns)
    return 0


def view_until_entry(
    root: Path,
    record: Path,
    follow: bool,
    out: TextIO,
    poll: float = 0.3,
    err: TextIO | None = None,
) -> int:
    """Print each turn of the record of a project with no entry, as in view. With follow, read
    the config again before each poll (#312). If the config gives a different record, follow
    that record. When the config has an entry, follow each test as in view_tests.

    If the config cannot be read, the view shows the error on err one time, keeps the record
    that it follows and reads the config again at the next poll."""
    err = err or sys.stderr
    errors, config_errors = _ErrorOnce(err), _ConfigErrorOnce(err)
    target: Path | None = record

    def changed() -> bool:
        nonlocal target
        target = _next_record(root, record, config_errors)
        return target != record

    while True:
        shown = _Shown(out)
        for turns in _turns(record, follow, poll, errors, changed):
            shown.show(turns)
        if not follow:
            return 0
        if target is None:
            return view_tests(root, follow, out, poll, err)
        record = target
        errors.clear()
        out.write(f"════ record {record} ════\n")
        out.flush()


def _next_record(root: Path, record: Path, errors: _ConfigErrorOnce) -> Path | None:
    """The record that the view follows next: None if the config has an entry, else the record
    of the config. If the config cannot be read, show the error and keep the record."""
    if not (root / STATE_DIR / "config.json").exists():
        errors.clear()
        return Config().record_path(root)
    try:
        config = Config.load(root)
    except (OSError, ValueError, TypeError) as e:
        errors.show(str(e))
        return record
    errors.clear()
    return None if config.entry else config.record_path(root)


class _ConfigErrorOnce:
    """Show a config error once. Show it again only when the error changes."""

    def __init__(self, err: TextIO) -> None:
        self.err = err
        self.last: str | None = None

    def show(self, reason: str) -> None:
        if reason == self.last:
            return
        self.last = reason
        self.err.write(
            f"nookku: cannot read the config: {reason}. "
            "The view reads the config again when it changes.\n"
        )
        self.err.flush()

    def clear(self) -> None:
        self.last = None


def view_tests(
    root: Path, follow: bool, out: TextIO, poll: float = 0.3, err: TextIO | None = None
) -> int:
    """Print each turn of the latest test. With follow, wait for new turns and new tests.

    An invalid record raises a RecordError. With follow, the view shows the error on err and
    continues, as in view.
    """
    shown_test, shown = None, _Shown(out)
    errors = _ErrorOnce(err or sys.stderr)
    while True:
        folder = state.latest_test(root)
        if folder is not None and folder != shown_test:
            shown_test, shown = folder, _Shown(out)
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
            else:
                shown.show(turns)
        if not follow:
            return 0
        time.sleep(poll)


RECORD_CHANGED = "──── the record changed: the view shows each turn again ────\n"


class _Shown:
    """The turns that the view showed. A count is not enough: if a person removes a line of the
    record, a new turn can have the number of a turn that the view showed (#113). If the record
    does not start with the shown turns, the view says so and shows each turn again."""

    def __init__(self, out: TextIO) -> None:
        self.out = out
        self.turns: list[Turn] = []

    def show(self, turns: list[Turn]) -> None:
        if turns[: len(self.turns)] != self.turns:
            self.turns = []
            self.out.write(RECORD_CHANGED)
        for turn in turns[len(self.turns) :]:
            self.turns.append(turn)
            self.out.write(render_turn(turn, len(self.turns)))
        self.out.flush()


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
            f"nookku: {cause}: {e}. Do not trust this record. "
            "The view shows the next turns when the record changes and is valid.\n"
        )
        self.err.flush()

    def clear(self) -> None:
        self.last = None


def _turns(
    record: Path,
    follow: bool,
    poll: float,
    errors: _ErrorOnce,
    stop: Callable[[], bool] | None = None,
) -> Iterator[list[Turn]]:
    """The turns of the record, one list for each poll. With follow, stop before a poll when
    stop gives True."""
    while True:
        try:
            # With follow, the view waits for a record that does not exist yet.
            yield [r for r in read_relay(record, missing_ok=follow) if isinstance(r, Turn)]
            errors.clear()
        except RecordError as e:
            if not follow:
                raise
            errors.show(e, record)
        if not follow or (stop is not None and stop()):
            return
        time.sleep(poll)

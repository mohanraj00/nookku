"""The hook kit of SPEC.md section 5: classic hooks that Codex and Claude Code share."""

from __future__ import annotations

import json
import re
import shlex
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from verbatim_relay.adapters import AdapterError, History, make
from verbatim_relay.record import RecordError, Turn, Writer, read_relay

STATE_DIR = ".verbatim-relay"
TIMEOUT = 280
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
DENY_REASON = "verbatim-relay: only the tester talks to the agent."


@dataclass
class Config:
    tap_url: str = "http://127.0.0.1:8800/"
    agent_url: str = ""
    adapter: str = "json"
    message_field: str = "text"
    reply_field: str = "reply"
    openai_model: str = ""
    record: str = f"{STATE_DIR}/relay.jsonl"

    @classmethod
    def load(cls, root: Path) -> Config:
        data = json.loads((root / STATE_DIR / "config.json").read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**data)

    def record_path(self, root: Path) -> Path:
        return root / self.record


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
            parts.append(rf"{re.escape(h)}:{port}(?!\d)")
            if u.port is None:
                parts.append(rf"{re.escape(h)}(?![\w.:-])")
    return re.compile("|".join(parts), re.IGNORECASE) if parts else None


def history(record: Path, session: str | None) -> History:
    """The turns of this session that showed the agent's reply (SPEC.md section 5)."""
    if not record.exists():
        return []
    out: History = []
    for line in record.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if (
            row.get("type") == "turn"
            and row.get("ok") is True
            and row.get("session") == session
            and row.get("shown") is not None
        ):
            out.append((row["said"], row["shown"]))
    return out


def relay(config: Config, said: str, past: History) -> tuple[str, bool]:
    """Send one message through the tap. Return (the text to show, whether it is the reply)."""
    adapter = make(config.adapter, config.message_field, config.reply_field, config.openai_model)
    req = urllib.request.Request(
        config.tap_url,
        data=adapter.request(said, past),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return f"verbatim-relay: the agent returned HTTP {e.code}:\n{text}", False
    except (OSError, ValueError) as e:
        return f"verbatim-relay: cannot reach the tap at {config.tap_url}: {e}", False
    try:
        return adapter.reply(body), True
    except AdapterError as e:
        return f"verbatim-relay: cannot read the reply: {e}", False


def _block(reason: str) -> dict[str, Any]:
    return {"decision": "block", "reason": reason}


def handle(event: dict[str, Any], root: Path, harness: str) -> dict[str, Any] | None:
    """Answer one hook event. Return the JSON to print, or None to let the harness go on."""
    name = event.get("hook_event_name")
    if name == "UserPromptSubmit":
        if not is_on(root):
            return None
        try:
            config = Config.load(root)
        except (OSError, ValueError, TypeError) as e:
            return _block(f"verbatim-relay: relay mode is on, but the config is broken: {e}")
        said = event.get("prompt")
        if not isinstance(said, str):
            return _block("verbatim-relay: the hook input has no prompt text. Nothing was sent.")
        session = event.get("session_id") if isinstance(event.get("session_id"), str) else None
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
        if tool in FILE_TOOLS:
            return None
        try:
            config = Config.load(root)
        except (OSError, ValueError, TypeError):
            return None
        pattern = deny_pattern([config.tap_url, config.agent_url])
        text = json.dumps(event.get("tool_input", event), ensure_ascii=False)
        if pattern is None or not pattern.search(text):
            return None
        record = config.record_path(root)
        record.parent.mkdir(parents=True, exist_ok=True)
        Writer(record).append(
            {"type": "blocked_call", "harness": harness, "tool": tool, "detail": text[:300]}
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": DENY_REASON,
            }
        }
    return None


def run_hook(root: Path, harness: str, stdin: TextIO, stdout: TextIO) -> int:
    """The hook command. In relay mode, any failure still blocks the prompt."""
    try:
        event = json.loads(stdin.read())
        answer = handle(event, root, harness)
    except Exception as e:  # fail closed: a crash must not hand the prompt to the model
        if is_on(root):
            answer = _block(
                f"verbatim-relay: the hook failed ({type(e).__name__}: {e}). "
                "Nothing reached the model."
            )
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


def _merge_hooks(settings: dict[str, Any], command: str) -> dict[str, Any]:
    hooks = settings.setdefault("hooks", {})
    wanted = {"UserPromptSubmit": ({}, 300), "PreToolUse": ({"matcher": ".*"}, 30)}
    for event, (matcher, timeout) in wanted.items():
        groups = hooks.setdefault(event, [])
        groups[:] = [
            g
            for g in groups
            if not any("verbatim_relay hook" in h.get("command", "") for h in g.get("hooks", []))
        ]
        groups.append(
            {**matcher, "hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        )
    return settings


def init(root: Path, harness: str, config: Config) -> list[str]:
    """Write the config, the mode file and the harness hook file. Return the paths written."""
    state = root / STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    written = []
    conf = state / "config.json"
    conf.write_text(json.dumps(asdict(config), indent=1) + "\n")
    written.append(str(conf))
    if not mode_path(root).exists():
        set_mode(root, False)
    target = (
        root / ".codex" / "hooks.json"
        if harness == "codex"
        else root / ".claude" / "settings.local.json"
    )
    settings = json.loads(target.read_text()) if target.exists() else {}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_merge_hooks(settings, hook_command(root, harness)), indent=1) + "\n"
    )
    written.append(str(target))
    return written


def render_turn(turn: Turn, n: int) -> str:
    shown = "(no reply shown)" if turn.shown is None else turn.shown
    return f"──── tester, turn {n} ────\n{turn.said}\n──── agent ────\n{shown}\n"


def view(record: Path, follow: bool, out: TextIO, poll: float = 0.3) -> int:
    """Print each turn of the relay record. With follow, wait for new turns."""
    seen = 0
    for turns in _turns(record, follow, poll):
        for turn in turns[seen:]:
            seen += 1
            out.write(render_turn(turn, seen))
            out.flush()
    return 0


def _turns(record: Path, follow: bool, poll: float) -> Iterator[list[Turn]]:
    while True:
        try:
            yield [r for r in read_relay(record) if isinstance(r, Turn)]
        except RecordError:
            if not follow:
                raise
        if not follow:
            return
        time.sleep(poll)

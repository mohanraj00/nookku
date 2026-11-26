"""The simulated user of a test (SPEC.md section 7.10, #520). The harness model plays a user of
the agent in a new session. It gets only the persona, the goal and the conversation so far, and
writes each next message. Nookku calls no model: it runs the harness CLI.

The config key `persona_runner` selects the runner of each message (#667): `claude -p`, `codex
exec`, or a command that the tester declares. Each runner gets the same prompt and environment.

The messages of a simulated user are not deterministic, so a gate run never starts one (ADR
0002), with any runner. Save the test as a script with `nookku script save`, and run the script
again."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from nookku.record import loads, lone_surrogate

# The copy of the persona file in the test folder. The seal covers it.
COPY = "persona.json"
# The result of the simulated user in the test folder. The seal covers it.
RESULT = "simulated_user.json"
# The harness of the simulated user. The relay row of each of its messages has this harness.
HARNESS = "simulated-user"
# The most turns of a test with a simulated user. This is a chosen value.
MAX_TURNS = 50
# The seconds that one message of the simulated user can take. This is a chosen value.
TIMEOUT = 300
# The text that ends the test when the simulated user sees that the goal is met.
DONE = "GOAL MET"
# The environment variables that the session of the simulated user does not get, so that its
# hooks do not take it for a part of the test or of the tester's session.
HIDDEN = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")
# The text of each end of a run.
ENDED = {
    "goal": "The simulated user wrote that the goal is met.",
    "limit": "The run stopped at the turn limit.",
    "no_reply": "The entry sent no reply.",
    "error": "The session of the simulated user failed.",
}
SYSTEM = (
    "You play a user of a chat agent in a test of the agent. You have no tools. Write only the "
    "next message of the user, as the user types it."
)
# The runner of a simulated user if the config has no key persona_runner.
DEFAULT_RUNNER = "claude-code"
# The file of the message of a codex exec session, in its temporary folder.
CODEX_MESSAGE = "message.txt"

# A value of the config key persona_runner: a runner name or a declared command.
Runner = str | list[str]


class PersonaError(ValueError):
    """A persona file that cannot be read or that breaks the rule of SPEC.md section 7.10."""


def parse(data: bytes) -> dict[str, Any]:
    """The persona, the goal and the turn limit of a persona file. Raise PersonaError."""
    try:
        value = loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise PersonaError(f"the persona file is not UTF-8 JSON: {e}") from None
    if not isinstance(value, dict) or set(value) != {"persona", "goal", "turns"}:
        raise PersonaError("the persona file must be an object with persona, goal and turns")
    for key in ("persona", "goal"):
        text = value[key]
        if not isinstance(text, str) or not text.strip():
            raise PersonaError(f"the {key} must be a string that is not empty")
        found = lone_surrogate(text)
        if found:
            raise PersonaError(f"the {key} has {found}")
    turns = value["turns"]
    if type(turns) is not int or not 1 <= turns <= MAX_TURNS:
        raise PersonaError(f"turns must be an integer from 1 to {MAX_TURNS}")
    return value


def read(path: Path) -> tuple[dict[str, Any], bytes]:
    """The persona and the bytes of a persona file. Raise PersonaError."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise PersonaError(f"cannot read the persona file {path}: {e}") from None
    return parse(data), data


def prompt(persona: dict[str, Any], turns: list[tuple[str, str | None]]) -> str:
    """The prompt of the next message: the persona, the goal and each earlier turn."""
    parts = [
        f"Your persona: {persona['persona']}",
        f"Your goal: {persona['goal']}",
    ]
    if turns:
        lines = []
        for said, shown in turns:
            lines += [f"You: {said}", f"Agent: {'(no reply)' if shown is None else shown}"]
        parts.append("The conversation so far:\n" + "\n".join(lines))
    else:
        parts.append("The conversation has no message yet. Write the first message.")
    parts.append(
        f"Write only the text of your next message to the agent. If the goal is met, write only "
        f"{DONE}."
    )
    return "\n\n".join(parts)


def command(runner: Runner = DEFAULT_RUNNER, folder: Path | None = None) -> list[str]:
    """The command of one message. The claude -p session loads no settings, no CLAUDE.md, no
    plugin, no hook and no MCP server, has no tools and keeps no session file. The codex exec
    session loads no config.toml and no rules file, keeps no session file and runs only
    read-only commands in its empty folder. A declared command is the tester's own."""
    if isinstance(runner, list):
        return list(runner)
    if runner == "codex":
        if folder is None:
            raise ValueError("codex exec needs the folder of the message")
        return [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "-C",
            str(folder),
            "-o",
            str(folder / CODEX_MESSAGE),
            "-",
        ]
    return [
        "claude",
        "-p",
        "--setting-sources",
        "",
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt",
        SYSTEM,
    ]


def harness(runner: Runner) -> str:
    """The harness of simulated_user.json: claude-code, codex or command."""
    return "command" if isinstance(runner, list) else runner


def _name(runner: Runner) -> str:
    if isinstance(runner, list):
        return "the declared command"
    return "codex exec" if runner == "codex" else "claude -p"


def environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("NOOKKU_") and k not in HIDDEN}
    # Print mode can send the first prompt in a title request (src/nookku/print_mode.py). Claude
    # Code loads a mod from each folder of CLAUDE_CODE_PLUGIN_DIRS, also with no setting sources,
    # so an empty value keeps the mods of the tester out of the session.
    return env | {"CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1", "CLAUDE_CODE_PLUGIN_DIRS": ""}


def next_message(
    persona: dict[str, Any],
    turns: list[tuple[str, str | None]],
    runner: Runner = DEFAULT_RUNNER,
) -> str | None:
    """The next message of the simulated user, or None if the goal is met. Raise OSError or
    PersonaError if the session fails or gives no valid message."""
    text = prompt(persona, turns)
    if runner == "codex":
        # codex exec has no flag for a system prompt, so the prompt starts with it.
        text = f"{SYSTEM}\n\n{text}"
    with tempfile.TemporaryDirectory(prefix="nookku-simulated-user-") as tmp:
        folder = Path(tmp).resolve()
        try:
            done = subprocess.run(
                command(runner, folder),
                input=text.encode("utf-8"),
                capture_output=True,
                cwd=folder,
                env=environment(),
                timeout=TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise PersonaError(f"the simulated user gave no message in {TIMEOUT} seconds") from None
        if done.returncode != 0:
            raise PersonaError(f"{_name(runner)} exited with {done.returncode}")
        raw = done.stdout
        if runner == "codex":
            try:
                raw = (folder / CODEX_MESSAGE).read_bytes()
            except OSError:
                raise PersonaError(f"codex exec wrote no {CODEX_MESSAGE}") from None
    return _message(raw)


def _message(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as e:
        raise PersonaError(f"the message of the simulated user is not UTF-8: {e}") from None
    if text == DONE:
        return None
    if not text:
        raise PersonaError("the simulated user gave an empty message")
    found = lone_surrogate(text)
    if found:
        raise PersonaError(f"the message of the simulated user has {found}")
    return text


def version(runner: Runner = DEFAULT_RUNNER) -> str | None:
    """The version of the harness of the simulated user, or None. A declared command has
    none."""
    if isinstance(runner, list):
        return None
    cmd = "codex" if runner == "codex" else "claude"
    try:
        done = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            env=environment(),
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = done.stdout.decode("utf-8", "replace").split()
    if done.returncode != 0 or not text:
        return None
    # claude prints "2.1.319 (Claude Code)", and codex prints "codex-cli 0.169.0".
    return text[-1] if runner == "codex" else text[0]

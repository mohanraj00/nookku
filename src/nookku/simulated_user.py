"""The simulated user of a test (SPEC.md section 7.10, #520). The harness model plays a user of
the agent in a new session. It gets only the persona, the goal and the conversation so far, and
writes each next message. Nookku calls no model: it runs the harness CLI.

The messages of a simulated user are not deterministic, so a gate run never starts one (ADR
0002). Save the test as a script with `nookku script save`, and run the script again."""

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


def command() -> list[str]:
    """The claude -p command of one message. The session loads no settings, no CLAUDE.md, no
    plugin, no hook and no MCP server, has no tools and keeps no session file."""
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


def environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("NOOKKU_") and k not in HIDDEN}
    # Print mode can send the first prompt in a title request (src/nookku/print_mode.py).
    return env | {"CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"}


def next_message(persona: dict[str, Any], turns: list[tuple[str, str | None]]) -> str | None:
    """The next message of the simulated user, or None if the goal is met. Raise OSError or
    PersonaError if the session fails or gives no valid message."""
    with tempfile.TemporaryDirectory(prefix="nookku-simulated-user-") as tmp:
        try:
            done = subprocess.run(
                command(),
                input=prompt(persona, turns).encode("utf-8"),
                capture_output=True,
                cwd=tmp,
                env=environment(),
                timeout=TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise PersonaError(f"the simulated user gave no message in {TIMEOUT} seconds") from None
    if done.returncode != 0:
        raise PersonaError(f"claude -p exited with {done.returncode}")
    try:
        text = done.stdout.decode("utf-8").strip()
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


def version() -> str | None:
    """The version of the Claude Code of the simulated user, or None."""
    try:
        done = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            env=environment(),
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = done.stdout.decode("utf-8", "replace").split()
    return text[0] if done.returncode == 0 and text else None

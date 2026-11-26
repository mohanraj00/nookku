"""The run of a test with a simulated user (SPEC.md section 7.10, "Simulated user", #520). The
bridge keeps the name `run_persona`, and the module size rule moved the run here (#667)."""

from __future__ import annotations

import time
from pathlib import Path

from nookku import bridge, simulated_user
from nookku.record import Writer


def run(
    root: Path, persona_path: Path, entry_name: str | None = None, gate: bool = False
) -> tuple[bool, list[str], Path]:
    """Run a test with a simulated user (SPEC.md section 7.10, #520). Return (passed, the report
    lines, the test folder).

    The harness model writes each message in a new session, from the persona, the goal and the
    turns so far. Each message goes to the entry byte for byte, as a relay row with the harness
    simulated-user. The run stops when the simulated user writes that the goal is met, at the
    turn limit, at a turn with no reply, or when the session fails. Before the end, the run
    writes the result to simulated_user.json, so the seal covers it. With gate, a verdict that is
    not `pass` also fails the run (SPEC.md section 7.14)."""
    try:
        persona = simulated_user.read(persona_path)[0]
    except simulated_user.PersonaError as e:
        raise bridge.BridgeError(str(e)) from None
    runner = bridge.load_config(root, entry_name).persona_runner
    cur = bridge.start(root, entry_name=entry_name, persona_path=persona_path)
    folder = Path(cur["dir"])
    relay = folder / "relay.jsonl"
    turns: list[tuple[str, str | None]] = []
    ended, error = "limit", None
    try:
        version = simulated_user.version(runner)
        while len(turns) < persona["turns"]:
            try:
                said = simulated_user.next_message(persona, turns, runner)
            except (OSError, simulated_user.PersonaError) as e:
                ended, error = "error", str(e)
                break
            if said is None:
                ended = "goal"
                break
            shown, ok = bridge.send(cur, said)
            row = {"type": "turn", "harness": simulated_user.HARNESS, "said": said}
            Writer(relay).append({**row, "shown": shown, "ok": ok})
            turns.append((said, shown))
            if not ok:
                ended = "no_reply"
                break
        result = {
            "harness": simulated_user.harness(runner),
            "command": runner if isinstance(runner, list) else None,
            "version": version,
            "turns": len(turns),
            "limit": persona["turns"],
            "ended": ended,
            "error": error,
        }
        bridge._write_json(folder / simulated_user.RESULT, result)
        time.sleep(2 * bridge.POLL)
    finally:
        manifest = bridge.end(root, find_stopped=False) or {}
    lines = [
        f"Test {cur['test']}: {cur['dir']}",
        f"Turns: {len(turns)} of {persona['turns']}. {simulated_user.ENDED[ended]}",
    ]
    first = None
    if ended == "error":
        first = f"The simulated user stopped: {error}"
    elif ended == "no_reply":
        first = f"The entry sent no reply to message {len(turns)} of the simulated user."
    elif not turns:
        first = "The simulated user sent no message."
    return bridge._report(folder, manifest, lines, first, gate)

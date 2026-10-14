"""The print mode rule of the Claude Code relay (SPEC.md section 5, #199).

In print mode (`claude -p`, or an app of the Agent SDK), Claude Code can send the first prompt of
a session to the model API in a request that makes the session title. A blocked prompt is in that
request too, so a hook cannot keep it from the model. The data is in
proofs/spikes/print-mode.json, and the method is scripts/spike_print_mode.py.

Claude Code sets CLAUDE_CODE_ENTRYPOINT to "sdk-cli" in print mode, and the hook gets this
variable. CLAUDE_CODE_DISABLE_TERMINAL_TITLE stops the title request.
"""

from __future__ import annotations

from collections.abc import Mapping

ENTRYPOINT = "sdk-cli"
OFF_SWITCH = "CLAUDE_CODE_DISABLE_TERMINAL_TITLE"
# The values that Claude Code reads as true.
TRUE = ("1", "true", "yes", "on")
REASON = (
    "nookku: nothing was sent. Claude Code runs in print mode, and print mode can send a prompt "
    "to the model API in a title request. Use the interactive CLI, or set "
    f"{OFF_SWITCH}=1 before you start Claude Code."
)


def refused(env: Mapping[str, str]) -> bool:
    """True if the harness runs in print mode and the title request is not off."""
    if env.get("CLAUDE_CODE_ENTRYPOINT") != ENTRYPOINT:
        return False
    return env.get(OFF_SWITCH, "").strip().lower() not in TRUE

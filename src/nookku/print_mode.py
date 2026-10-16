"""The print mode rule of the Claude Code relay (SPEC.md section 5, #199).

In print mode (`claude -p`), Claude Code can send the first prompt of a session to the model API in
a request that makes the session title. A blocked prompt is in that request too, so a hook cannot
keep it from the model. The data is in proofs/spikes/print-mode.json, and the method is
scripts/spike_print_mode.py.

Claude Code gives the hook CLAUDE_CODE_ENTRYPOINT. In the data, the interactive CLI gave "cli" and
print mode gave "sdk-cli". An Agent SDK app or another client can give other values, which the
data does not cover. Thus the rule fails closed: each value that the data does not show as the
interactive CLI gets the refusal, also no value. CLAUDE_CODE_DISABLE_TERMINAL_TITLE stops the
title request, so it turns off the refusal.
"""

from __future__ import annotations

from collections.abc import Mapping

from nookku import __version__

VARIABLE = "CLAUDE_CODE_ENTRYPOINT"
# The values that the data shows as the interactive CLI.
INTERACTIVE = ("cli",)
OFF_SWITCH = "CLAUDE_CODE_DISABLE_TERMINAL_TITLE"
# The values that Claude Code reads as true.
TRUE = ("1", "true", "yes", "on")
# The fix in the docs of the installed version. A tester who installed nookku from PyPI has no
# local docs, so the link names the release tag (#395).
ANCHOR = "claude-code-does-not-run-as-the-interactive-cli"
DOCS = f"https://github.com/mohanraj00/nookku/blob/v{__version__}/docs/troubleshooting.md#{ANCHOR}"
REASON = (
    "nookku: nothing was sent. Claude Code does not run as the interactive CLI, and then it can "
    "send a prompt to the model API in a title request. Use the interactive CLI, or set "
    f"{OFF_SWITCH}=1 in the environment that starts Claude Code. The fix: {DOCS}"
)
# The white space that JavaScript trim() removes from an ASCII value. Python str.strip() also
# removes other characters, for example U+001F and U+0085, and then a value that Claude Code reads
# as false can turn off the refusal.
WHITE_SPACE = " \t\n\r\v\f"


def refused(env: Mapping[str, str]) -> bool:
    """True if the title request is not off and the entrypoint is not the interactive CLI."""
    if env.get(OFF_SWITCH, "").strip(WHITE_SPACE).lower() in TRUE:
        return False
    return env.get(VARIABLE) not in INTERACTIVE


def applies(env: Mapping[str, str], harness: str) -> bool:
    """True if the rule applies. The Claude Code relay always uses it. A plugin hook runs as Codex
    if PLUGIN_ROOT is set, also in Claude Code, so the Codex relay uses it if Claude Code gave
    the entrypoint."""
    return (harness == "claude-code" or VARIABLE in env) and refused(env)

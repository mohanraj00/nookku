"""Parts that more than one proof script uses."""

from __future__ import annotations

import json
from typing import Any

# The Agent SDK of the toy apps. A new release bundles a new Claude Code, and the session reader is
# tested only for the versions in TESTED of trace.py (#35). Change this pin only with the proofs.
AGENT_SDK = "claude-agent-sdk==0.2.164"


def json_lines(text: str) -> list[Any]:
    """The JSON lines of a harness output or a record.

    Split on \\n only. str.splitlines() also splits at U+2028, U+2029 and U+0085, and a JSON string
    can hold these characters unescaped (#31).
    """
    return [json.loads(x) for x in text.split("\n") if x.startswith("{")]

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from proof_common import AGENT_SDK, json_lines

# U+2028, U+2029 and U+0085, written as escapes.
SEPARATORS = "".join(chr(c) for c in (0x2028, 0x2029, 0x85))


def test_a_unicode_line_separator_in_a_string_does_not_cut_the_line() -> None:
    text = f"a toy shop reply {SEPARATORS} with 3 separators"
    out = json.dumps({"type": "agent_message", "text": text}, ensure_ascii=False)
    stdout = f"a log line\n{out}\r\n{{}}\n"
    assert len(stdout.splitlines()) > 3
    assert json_lines(stdout) == [{"type": "agent_message", "text": text}, {}]


def test_the_agent_sdk_is_pinned() -> None:
    assert AGENT_SDK.startswith("claude-agent-sdk==")

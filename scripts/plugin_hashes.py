"""Write plugins/nookku/hook-hashes.json: the SHA-256 of each hook file of the plugin (#628).

The start check compares each install of the plugin with the hash file of that install (SPEC.md
section 7.8). tests/test_plugin.py fails if the file differs from the plugin files. After a
change to a hook file or to the plugin manifest, run this script and commit the file.

usage: uv run python scripts/plugin_hashes.py
"""

from __future__ import annotations

import json
from pathlib import Path

from nookku import claude_gate

PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "nookku"


def text() -> str:
    data = {"v": 1, "files": claude_gate.hook_files(PLUGIN)}
    return json.dumps(data, indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    (PLUGIN / claude_gate.PLUGIN_HASHES).write_text(text(), encoding="utf-8")

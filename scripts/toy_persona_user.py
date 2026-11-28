"""A toy declared command for the simulated user (#667). It calls no model and has no tools.

The proof of the simulated user runs it with `--runner command`, as the value of the config key
`persona_runner`. It follows the contract of a declared command: it reads the prompt on stdin
and writes the next message on stdout. It reads only the prompt, and it writes one JSON line to
the log file of its first argument for each call: its folder, the files in the folder, the
variables that a session of the simulated user must not get, and the prompt.

The messages follow the toy shop agent of examples/toy-shop/: the first message names no
keyword, so the agent asks which item. The second message asks about the refund. When the
prompt holds the refund reply, the command writes GOAL MET.

usage: python3 scripts/toy_persona_user.py LOG
"""

from __future__ import annotations

import json
import os
import sys

FIRST = "Hello. My order came broken. What can you do for me?"
SECOND = "It is the teapot. What refund do I get for a damaged item?"
# The text of the toy shop reply that meets the goal.
MET = "Damaged items: full refund."
HIDDEN = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def main() -> int:
    prompt = sys.stdin.read()
    folder = os.getcwd()
    row = {
        "cwd": folder,
        "files": sorted(os.listdir(folder)),
        "hidden": sorted(k for k in os.environ if k.startswith("NOOKKU_") or k in HIDDEN),
        "prompt": prompt,
    }
    with open(sys.argv[1], "a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")
    if MET in prompt:
        print("GOAL MET")
    elif "The conversation so far:" in prompt:
        print(SECOND)
    else:
        print(FIRST)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The hook command: one process for each hook event of Claude Code or Codex (SPEC.md section 5).

This path does not import the CLI, so that a warm event stays fast (#214).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

USAGE = "usage: nookku hook --harness {claude-code,codex} [--root ROOT]"
HARNESSES = ("claude-code", "codex")


def main(argv: Sequence[str]) -> int:
    """Run one hook event. Exit 2 blocks the event, so wrong arguments fail closed."""
    options: dict[str, str] = {}
    args = list(argv)
    while args:
        name = args.pop(0)
        if name in ("-h", "--help"):
            print(USAGE)
            return 0
        if name not in ("--root", "--harness") or not args or name in options:
            print(f"nookku hook: wrong argument '{name}'\n{USAGE}", file=sys.stderr)
            return 2
        options[name] = args.pop(0)
    harness = options.get("--harness")
    if harness not in HARNESSES:
        print(f"nookku hook: give --harness {' or '.join(HARNESSES)}\n{USAGE}", file=sys.stderr)
        return 2
    from nookku import kit

    root = Path(options["--root"]).resolve() if "--root" in options else None
    return kit.run_hook(root, harness, sys.stdin, sys.stdout)

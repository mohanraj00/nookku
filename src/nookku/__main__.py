"""The `nookku` command. A hook event takes a short path that does not import the CLI (#214)."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["hook"]:
        from nookku.hook import main as hook

        return hook(args[1:])
    from nookku.cli import main as cli

    return cli(args)


if __name__ == "__main__":
    sys.exit(main())

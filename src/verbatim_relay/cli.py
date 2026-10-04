"""Command line entry point. The subcommands (tap, audit, view) come in M1 to M3."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from verbatim_relay import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verbatim-relay", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0

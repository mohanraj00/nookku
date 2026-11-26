"""The config flags of `nookku init` (docs/reference/cli.md): the config keys that are a plain
string flag, and the keys that init takes in another form."""

from __future__ import annotations

import argparse

from nookku.config import KEYS, Config

# Config keys that are not a plain string flag of init.
LIST_KEYS = {
    "entry",
    "entries",
    "models",
    "evaluate",
    "otel",
    "openai_stream",
    "repeated_reply",
    "transcript_compact",
    "page",
    "record_limit",
    "body_limit",
    "spec",
    "egress_ignore",
    "replay_ignore",
    "persona_runner",
}
# The plain string flags of init. A flag that the user does not give is None.
STRING_KEYS = [k for k in KEYS if k not in LIST_KEYS]


def add_string_flags(parser: argparse.ArgumentParser) -> None:
    """Add a flag to init for each plain string key, with its default for a new file."""
    defaults = vars(Config())
    for name in STRING_KEYS:
        parser.add_argument(
            f"--{name.replace('_', '-')}",
            help=f"the config key {name} (new file: {defaults[name]!r})",
        )

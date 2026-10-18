"""A test folder with an empty egress answer, for a test that replaces bridge.start."""

import json
from pathlib import Path

from nookku import discovery

# The start text of a test with an empty answer (SPEC.md section 7.11).
NO_EGRESS = "Egress of the agent:\n- no egress part: the agent calls no service"


def folder(path: Path) -> str:
    """Write a manifest with an empty egress answer into path, and return the path."""
    path.mkdir(parents=True, exist_ok=True)
    manifest = {"egress": {"answer": discovery.make()}}
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return str(path)

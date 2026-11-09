"""CLAUDE.md and GEMINI.md hold imports only. AGENTS.md and CONSTITUTION.md hold the rules."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IMPORTS = b"@CONSTITUTION.md\n@AGENTS.md\n"


@pytest.mark.parametrize("name", ["CLAUDE.md", "GEMINI.md"])
def test_the_harness_entry_file_holds_imports_only(name: str) -> None:
    path = ROOT / name
    if not path.exists():
        pytest.skip("the sdist has no agent instruction files")
    assert path.read_bytes() == IMPORTS

"""Codex reads AGENTS.md and Claude Code reads CLAUDE.md. The two must give the same rules."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_agents_md_is_a_copy_of_claude_md() -> None:
    claude, agents = ROOT / "CLAUDE.md", ROOT / "AGENTS.md"
    if not claude.exists():
        pytest.skip("the sdist has no agent instruction files")
    assert agents.read_bytes() == claude.read_bytes()

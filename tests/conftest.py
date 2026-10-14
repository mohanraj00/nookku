from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def seal_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Each test writes the copies of its seals in a temporary folder, not in the home folder."""
    home = tmp_path_factory.mktemp("nookku-home")
    monkeypatch.setenv("NOOKKU_HOME", str(home))
    monkeypatch.setenv("VERBATIM_RELAY_HOME", str(tmp_path_factory.mktemp("old-home")))
    return home


@pytest.fixture(autouse=True)
def codex_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The Codex hook gate of a test reads an empty Codex home, not the user's hooks."""
    home = tmp_path_factory.mktemp("codex-home")
    monkeypatch.setenv("CODEX_HOME", str(home))
    # No Codex: a test of the gate gives a fake codex command.
    monkeypatch.setenv("NOOKKU_CODEX", "nookku-test-no-codex")
    return home


@pytest.fixture(autouse=True)
def claude_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The Claude Code check of a test reads empty user settings, not the user's plugins."""
    home = tmp_path_factory.mktemp("claude-home")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    return home


@pytest.fixture(autouse=True)
def interactive_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hook of a test runs as in the interactive CLI, also when a print mode session runs
    pytest. The print mode tests set these variables (#199)."""
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_TERMINAL_TITLE", raising=False)

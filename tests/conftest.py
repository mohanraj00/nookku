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


@pytest.fixture(autouse=True)
def no_auto_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test start opens no browser and starts no page server. The tests of the page start
    (#328) in tests/test_page_auto.py turn it on again."""
    from nookku import page_auto

    monkeypatch.setattr(page_auto, "enabled", lambda root: False)


@pytest.fixture(autouse=True)
def no_mods(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test gets no mod of the Claude Code session that runs pytest. The mod tests set the
    variable (#424)."""
    monkeypatch.delenv("CLAUDE_CODE_PLUGIN_DIRS", raising=False)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "real_discovery: the test reads only the egress answers that it registers"
    )


@pytest.fixture(autouse=True)
def egress_answer(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that starts a test gets an answer with no egress part, if it registered no answer
    (SPEC.md section 7.11). The tests of discovery mark real_discovery and read only their own
    answers."""
    if request.node.get_closest_marker("real_discovery"):
        return
    import time

    from nookku import discovery

    real = discovery.pending

    def pending(root: Path, now: float | None = None) -> dict | None:
        found = real(root, now)
        empty = {kind: [] for kind in discovery.LISTS}
        return found or {"v": discovery.VERSION, "registered": time.time(), "answer": empty}

    monkeypatch.setattr(discovery, "pending", pending)

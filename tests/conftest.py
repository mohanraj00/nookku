from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def seal_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Each test writes the copies of its seals in a temporary folder, not in the home folder."""
    home = tmp_path_factory.mktemp("nookku-home")
    monkeypatch.setenv("NOOKKU_HOME", str(home))
    monkeypatch.setenv("VERBATIM_RELAY_HOME", str(tmp_path_factory.mktemp("old-home")))
    return home

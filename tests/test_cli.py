import pytest

from verbatim_relay import __version__
from verbatim_relay.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"verbatim-relay {__version__}"

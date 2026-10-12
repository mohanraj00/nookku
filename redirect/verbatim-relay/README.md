# verbatim-relay is now nookku

This is the last release of `verbatim-relay`. The project has the new name [nookku](https://pypi.org/project/nookku/).

The command `verbatim-relay` prints one line with the new name and the link to the upgrade guide. Then it exits with 1 ([the test](https://github.com/mohanraj00/nookku/blob/main/tests/test_redirect.py)). It does not run `nookku`, because the move of the state folder must be your choice. An old project hook runs `python -m verbatim_relay hook`. It prints the same line and exits with 2, so the hook blocks the event and no prompt goes to the model.

To upgrade, follow [the upgrade guide](https://github.com/mohanraj00/nookku/blob/main/docs/how-to/upgrade.md#040).

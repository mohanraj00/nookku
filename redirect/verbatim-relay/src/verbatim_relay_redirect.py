"""The command verbatim-relay: one line that names nookku and the upgrade guide, then exit 1.

The command does not run nookku. The first nookku command in a project moves the state folder,
so the user must choose to run it.
"""

import sys

UPGRADE = "https://github.com/mohanraj00/nookku/blob/main/docs/how-to/upgrade.md#040"
MESSAGE = f"verbatim-relay is now nookku. To upgrade, follow {UPGRADE}"


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

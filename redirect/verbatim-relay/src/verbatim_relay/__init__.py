"""The module verbatim_relay is now nookku. An import gives the upgrade message as an error.

The project hooks of verbatim-relay 0.3.x run `python -m verbatim_relay hook`. For a hook, only
exit 2 blocks the event, so `-m` writes the message to stderr and exits with 2. Then an old hook
fails closed: no prompt goes to the model while relay mode or a test is still on.
"""

import sys

from verbatim_relay_redirect import MESSAGE

# While Python imports the package of `python -m verbatim_relay`, sys.argv[0] is "-m".
if sys.argv[:1] == ["-m"]:
    print(MESSAGE, file=sys.stderr)
    raise SystemExit(2)
raise ImportError(MESSAGE)

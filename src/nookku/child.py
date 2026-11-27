"""Start a child with the Nookku package of its parent."""

import sys
from pathlib import Path

import nookku

BOOTSTRAP = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from nookku.__main__ import main; sys.exit(main())"
)


def argv(*args: str) -> list[str]:
    # Isolated mode omits the current folder and user site, and keeps the virtual environment's
    # site-packages. Give the child the library folder even if only the parent could import it.
    library = Path(nookku.__file__).parent.parent.resolve()
    return [sys.executable, "-I", "-c", BOOTSTRAP, str(library), *args]

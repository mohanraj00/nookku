"""Stealth gate: fail if a banned term occurs in the repo files, their paths or the commit messages.

The repo keeps only salted SHA-256 hashes of the banned terms, so the terms never enter it.

usage:
  python scripts/stealth.py check      scan the repo, exit 1 on a hit
  python scripts/stealth.py add        read terms from stdin (one per line) and store their hashes
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HASHES = ROOT / "scripts" / "stealth-hashes.txt"
SALT = "verbatim-relay-stealth:"
MAX_WORDS = 3
TOKEN = re.compile(r"[a-z0-9]+")


def digest(phrase: str) -> str:
    return hashlib.sha256((SALT + phrase).encode()).hexdigest()


def normalize(term: str) -> str:
    return " ".join(TOKEN.findall(term.lower()))


def phrases(text: str) -> Iterator[str]:
    words = TOKEN.findall(text.lower())
    for n in range(1, MAX_WORDS + 1):
        for i in range(len(words) - n + 1):
            yield " ".join(words[i : i + n])


def banned() -> set[str]:
    lines = HASHES.read_text().splitlines() if HASHES.exists() else []
    return {ln.split()[0] for ln in lines if ln.strip() and not ln.startswith("#")}


def sources() -> Iterator[tuple[str, str]]:
    """Yield (where, text) for each repo path, each text file and each commit message."""
    git = ["git", "-C", str(ROOT)]
    out = subprocess.run(
        [*git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout
    for name in out.decode().split("\0"):
        path = ROOT / name
        if not name or not path.is_file():
            continue
        yield f"path {name}", name
        if path == HASHES:
            continue
        try:
            yield name, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    log = subprocess.run([*git, "log", "-z", "--format=%H %B"], capture_output=True, text=True)
    for entry in log.stdout.split("\0") if log.returncode == 0 else []:
        if entry.strip():
            yield f"commit {entry[:12]}", entry[41:]


def hits(items: Iterable[tuple[str, str]], hashes: set[str]) -> list[str]:
    found = []
    for where, text in items:
        for lineno, line in enumerate(text.splitlines() or [text], 1):
            if any(digest(p) in hashes for p in phrases(line)):
                found.append(f"{where}:{lineno}")
    return found


def main(argv: list[str]) -> int:
    if argv == ["add"]:
        terms = [t for t in map(normalize, sys.stdin) if t]
        if any(len(t.split()) > MAX_WORDS for t in terms):
            print(f"stealth: a term has more than {MAX_WORDS} words", file=sys.stderr)
            return 2
        new = {digest(t) for t in terms}
        merged = sorted(banned() | new)
        HASHES.write_text(
            "# salted SHA-256 of banned terms; add with scripts/stealth.py add\n"
            + "".join(h + "\n" for h in merged)
        )
        print(f"{len(merged)} hashes stored ({len(new)} given)")
        return 0
    if argv == ["check"]:
        hashes = banned()
        if not hashes:
            print("stealth: no hashes stored, so nothing is checked", file=sys.stderr)
            return 2
        found = hits(sources(), hashes)
        for f in found:
            print(f"stealth: banned term at {f}")
        return 1 if found else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

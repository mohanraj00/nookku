"""Build the static files of the evaluation dashboard (#581).

The build copies site/ and the pinned files of the mugham kit into one folder:

    <out>/index.html, dashboard.js, dashboard.css
    <out>/mugham/src/..., mugham/catalog/..., mugham/LICENSE

mugham.json pins the kit: the repository, the tag, the commit and the paths. The build checks
that the tag points to the commit and that the checkout is at the commit. Then it checks the
SHA-256 of each copied file against checksums.json. A missing file, an extra file or a changed
file stops the build, and the build writes no output folder.

The kit is a build-time choice. The Python package of Nookku keeps no dependency on it:
`nookku dashboard --site <out>` serves the output folder as static files.

usage:
    python build.py --out DIR [--mugham CHECKOUT]
    python build.py --checksums --mugham CHECKOUT   (write checksums.json after a pin change)

Without --mugham, the build clones the tag of the pin into a temporary folder with git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN = HERE / "mugham.json"
CHECKSUMS = HERE / "checksums.json"
SITE = HERE / "site"
KIT = "mugham"


class BuildError(Exception):
    pass


def git(checkout: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(checkout), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise BuildError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def check_pin(checkout: Path, pin: dict[str, object]) -> None:
    """The tag of the pin points to the commit of the pin, and the checkout is at the commit."""
    tag, commit = str(pin["tag"]), str(pin["commit"])
    tagged = git(checkout, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if tagged != commit:
        raise BuildError(f"the tag {tag} points to {tagged}, not to the pinned commit {commit}")
    head = git(checkout, "rev-parse", "HEAD^{commit}")
    if head != commit:
        raise BuildError(f"the checkout is at {head}, not at the pinned commit {commit}")


def kit_files(checkout: Path, paths: list[str]) -> dict[str, str]:
    """The SHA-256 of each file of the pinned paths, by its path in the kit."""
    out: dict[str, str] = {}
    for name in paths:
        top = checkout / name
        if top.is_symlink() or not top.exists():
            raise BuildError(f"the kit has no {name}")
        found = [top] if top.is_file() else sorted(p for p in top.rglob("*") if not p.is_dir())
        for path in found:
            if path.is_symlink() or not path.is_file():
                raise BuildError(f"{path.relative_to(checkout)} is not a plain file")
            rel = path.relative_to(checkout).as_posix()
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def check_files(found: dict[str, str], expected: dict[str, str]) -> None:
    missing = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    changed = sorted(k for k in set(found) & set(expected) if found[k] != expected[k])
    problems = [f"missing {p}" for p in missing] + [f"extra {p}" for p in extra]
    problems += [f"changed {p}" for p in changed]
    if problems:
        listed = ", ".join(problems)
        raise BuildError(f"the kit files are not the files of checksums.json: {listed}")


def clone(pin: dict[str, object], into: Path) -> Path:
    checkout = into / KIT
    done = subprocess.run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            str(pin["tag"]),
            str(pin["repository"]),
            str(checkout),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise BuildError(f"git clone failed: {done.stderr.strip()}")
    return checkout


def build(out: Path, checkout: Path) -> dict[str, str]:
    """Check the kit and write the site to `out`. Return the SHA-256 of each kit file."""
    pin = json.loads(PIN.read_text())
    check_pin(checkout, pin)
    found = kit_files(checkout, list(pin["paths"]))
    sums = json.loads(CHECKSUMS.read_text())
    if (sums.get("tag"), sums.get("commit")) != (pin["tag"], pin["commit"]):
        raise BuildError("checksums.json is not for the tag and the commit of mugham.json")
    check_files(found, sums["files"])
    if out.exists():
        raise BuildError(f"{out} exists. Give a new folder.")
    work = out.with_name(out.name + ".part")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(SITE, work)
    for rel, sha in found.items():
        target = work / KIT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (checkout / rel).read_bytes()
        # The file can change between the check and the copy, so check the copied bytes again.
        if hashlib.sha256(data).hexdigest() != sha:
            raise BuildError(f"{rel} changed during the build")
        target.write_bytes(data)
    work.rename(out)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="the output folder; it must not exist")
    parser.add_argument("--mugham", type=Path, help="a git checkout of the kit at the pin")
    parser.add_argument("--checksums", action="store_true", help="write checksums.json")
    args = parser.parse_args(argv)
    pin = json.loads(PIN.read_text())
    try:
        with tempfile.TemporaryDirectory(prefix="nookku-kit-") as tmp:
            checkout = args.mugham.resolve() if args.mugham else clone(pin, Path(tmp))
            if args.checksums:
                check_pin(checkout, pin)
                files = kit_files(checkout, list(pin["paths"]))
                data = {"tag": pin["tag"], "commit": pin["commit"], "files": files}
                CHECKSUMS.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
                print(f"wrote {len(files)} checksums to {CHECKSUMS.name}")
                return 0
            if args.out is None:
                parser.error("give --out or --checksums")
            files = build(args.out.resolve(), checkout)
    except BuildError as e:
        print(f"build.py: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"out": str(args.out), "kit": pin["tag"], "files": len(files)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

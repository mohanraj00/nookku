"""Packaging rules: no runtime dependencies, a plain version, the same version in the plugin
and in the links of the PyPI page."""

import json
import re
from importlib.metadata import requires
from pathlib import Path

import nookku

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_plain() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", nookku.__version__)


def test_no_runtime_dependencies() -> None:
    assert (requires("nookku") or []) == []


def test_the_plugin_has_the_package_version() -> None:
    manifest = ROOT / "plugins" / "nookku" / ".claude-plugin" / "plugin.json"
    assert json.loads(manifest.read_text())["version"] == nookku.__version__


def test_the_pypi_readme_links_use_the_release_tag() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    tags = re.findall(
        r"replacement = '\]\(https://github\.com/mohanraj00/nookku/blob/([^/]+)/", pyproject
    )
    assert tags == [f"v{nookku.__version__}"]


def test_each_blob_link_in_pyproject_uses_the_release_tag() -> None:
    # The README substitution and the Documentation, Specification and Changelog URLs.
    pyproject = (ROOT / "pyproject.toml").read_text()
    tags = re.findall(r"https://github\.com/mohanraj00/nookku/blob/([^/]+)/", pyproject)
    assert tags == [f"v{nookku.__version__}"] * 4


def test_each_docs_version_line_names_the_package_version() -> None:
    # The README and the install fix tell the tester the version of the docs. A release changes
    # both, so a check of the installed version agrees with the docs.
    for path in (ROOT / "README.md", ROOT / "docs" / "troubleshooting.md"):
        versions = re.findall(r"The docs are for version (\d+\.\d+\.\d+)\.", path.read_text())
        assert versions == [nookku.__version__], path


# The pages that state no release: a copy of the project standard, the review texts, the provenance
# note, a page of another open change (#712), and each moved page, which only keeps old anchors.
NO_RELEASE = {
    "docs/STANDARD.md",
    "docs/REVIEW.md",
    "docs/PROVENANCE.md",
    "docs/limits.md",
    "docs/claude-code.md",
    "docs/codex.md",
    "docs/code-quality.md",
    "docs/codex-display.md",
    "docs/how-to/claude-code.md",
    "docs/how-to/claude-code-hook-kit.md",
    "docs/how-to/run-the-proofs.md",
}


def test_each_docs_page_states_the_release_that_it_describes() -> None:
    # The line under the title names the package version. A release changes each line (#715).
    pages = [*(ROOT / "docs").glob("*.md"), *(ROOT / "docs" / "how-to").glob("*.md")]
    pages += (ROOT / "docs" / "reference").rglob("*.md")
    for page in pages:
        name = page.relative_to(ROOT).as_posix()
        if name in NO_RELEASE:
            continue
        lines = page.read_text(encoding="utf-8").splitlines()
        assert lines[2].startswith(f"Release: nookku {nookku.__version__}."), name

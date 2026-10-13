"""Packaging rules: no runtime dependencies, a plain version, the same version in the plugin
and in the links of the PyPI README."""

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


def test_each_docs_version_line_names_the_package_version() -> None:
    # The README and the install fix tell the tester the version of the docs. A release changes
    # both, so a check of the installed version agrees with the docs.
    for path in (ROOT / "README.md", ROOT / "docs" / "troubleshooting.md"):
        versions = re.findall(r"The docs are for version (\d+\.\d+\.\d+)\.", path.read_text())
        assert versions == [nookku.__version__], path

"""Packaging rules: no runtime dependencies, a plain version, the same version in the plugin."""

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

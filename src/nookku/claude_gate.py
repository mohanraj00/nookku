"""The check that the nookku plugin and the project hooks are not both on in Claude Code (#151).

With both on, each message goes to the agent two times. The Codex hook gate does the same check
for Codex (SPEC.md section 7.8). Claude Code merges the settings files: the local file wins over
the project file, and the project file wins over the user file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nookku import kit

PLUGIN = "nookku@"
# The command that turns off the plugin in each scope.
DISABLE = "claude plugin disable nookku@nookku"
PROBLEM = (
    "both the nookku plugin and the project hooks of nookku init claude-code are on in Claude "
    "Code, so each message would go to the agent two times. Remove one of them: run "
    f"{DISABLE}, or remove the nookku hooks from .claude/settings.local.json."
)


def _user_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def settings_files(root: Path) -> list[Path]:
    """The settings files of Claude Code, from the lowest to the highest precedence."""
    return [
        _user_dir() / "settings.json",
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
    ]


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def plugin_on(root: Path) -> bool:
    """True if a settings file enables a nookku plugin and no file of higher precedence turns
    it off."""
    enabled: dict[str, Any] = {}
    for path in settings_files(root):
        plugins = _read(path).get("enabledPlugins")
        if isinstance(plugins, dict):
            enabled.update(plugins)
    return any(k.startswith(PLUGIN) and v is True for k, v in enabled.items())


def project_hooks_on(root: Path) -> bool:
    """True if a project settings file has a hook of nookku init claude-code."""
    for path in settings_files(root)[1:]:
        hooks = _read(path).get("hooks")
        if not isinstance(hooks, dict):
            continue
        for groups in hooks.values():
            for group in groups if isinstance(groups, list) else []:
                inner = group.get("hooks") if isinstance(group, dict) else None
                if isinstance(inner, list) and any(kit._ours(h) for h in inner):
                    return True
    return False


def problem(root: Path) -> str | None:
    """The refusal of a test if the plugin and the project hooks are both on, else None."""
    return PROBLEM if plugin_on(root) and project_hooks_on(root) else None

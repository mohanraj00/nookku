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
# The command that turns off the plugin in this project only. Without --scope local, it can
# turn off the plugin of the user, and a test in another project then loses its prompt hook.
DISABLE = "claude plugin disable --scope local nookku@nookku"
PROBLEM = (
    "both the nookku plugin and the project hooks of nookku init claude-code are on in Claude "
    "Code, so each message would go to the agent two times. Remove one of them: run "
    f"{DISABLE}, or remove the nookku hooks from .claude/settings.local.json. A running Claude "
    "Code session keeps a plugin that it loaded, so then run /reload-plugins or restart it."
)


def _user_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _main_checkout(root: Path) -> Path | None:
    """The main checkout of a linked git worktree, or None. Claude Code reads the local settings
    file of a linked worktree from the main checkout."""
    import subprocess  # only start and init need it, and a hook event imports little

    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    if common is None or common.name != ".git" or common.parent.resolve() == root.resolve():
        return None
    return common.parent


def settings_files(root: Path) -> list[Path]:
    """The settings files of Claude Code, from the lowest to the highest precedence. In a
    linked git worktree, the local file of the main checkout comes last, and both local files
    count, so the check refuses in each case."""
    files = [
        _user_dir() / "settings.json",
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
    ]
    main = _main_checkout(root)
    if main is not None:
        files.append(main / ".claude" / "settings.local.json")
    return files


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def plugin_on(root: Path) -> bool:
    """True if a settings file enables a nookku plugin and no file of higher precedence turns
    it off."""
    files = settings_files(root)
    # In a linked worktree, each local file can be the one that Claude Code reads.
    orders = [files[:3], files[:2] + files[3:]] if len(files) > 3 else [files]
    for order in orders:
        enabled: dict[str, Any] = {}
        for path in order:
            plugins = _read(path).get("enabledPlugins")
            if isinstance(plugins, dict):
                enabled.update(plugins)
        if any(k.startswith(PLUGIN) and v is True for k, v in enabled.items()):
            return True
    return False


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

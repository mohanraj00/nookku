"""The checks of the nookku hooks in the settings files of Claude Code (SPEC.md section 7.8).

1. The nookku plugin and the project hooks are not both on (#151). With both on, each message
   goes to the agent two times.
2. The project hooks of `nookku init claude-code` are complete and not changed (#554). Without
   the prompt hook, a relayed message goes to the model.
3. No settings file turns off all hooks while a nookku setup is on (#554).
4. Each install of an enabled nookku plugin has the hook files of this version (#554).

The Codex hook gate does the same checks for Codex. Claude Code merges the settings files: the
local file wins over the project file, and the project file wins over the user file. Claude Code
runs the hooks of each file.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import time
from pathlib import Path
from typing import Any

from nookku import __version__, kit
from nookku.record import loads

PLUGIN = "nookku@"
# The hooks file and the hook script of an install of the plugin.
PLUGIN_HOOKS = "hooks/hooks.json"
PLUGIN_SCRIPT = "hooks/nookku-hook.sh"
# The shells that can run the hook script of the plugin, and the path of the script in a hook
# command. A required hook must run one of these shells with this path and its event, and no
# other word.
PLUGIN_SHELLS = ("sh", "bash")
PLUGIN_SCRIPT_ARG = "${CLAUDE_PLUGIN_ROOT}/" + PLUGIN_SCRIPT
# The file of the refusals of a start (SPEC.md section 7.8). It is a log for a person, with no
# seal.
REFUSALS = "refusals.jsonl"
# The command that turns off the plugin in this project only. Without --scope local, it can
# turn off the plugin of the user, and a test in another project then loses its prompt hook.
DISABLE = "claude plugin disable --scope local nookku@nookku"
PROBLEM = (
    "both the nookku plugin and the project hooks of nookku init claude-code are on in Claude "
    "Code, so each message would go to the agent two times. Remove one of them: run "
    f"{DISABLE}, or remove the nookku hooks from {{file}}. A running Claude "
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
        data = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _orders(root: Path) -> list[list[Path]]:
    """The settings files that Claude Code can read, from the lowest to the highest precedence.
    In a linked worktree, each local file can be the one that Claude Code reads, so each order
    counts."""
    files = settings_files(root)
    return [files[:3], files[:2] + files[3:]] if len(files) > 3 else [files]


def enabled_plugins(root: Path) -> list[str]:
    """The ids of the nookku plugins that a settings file enables and no file of higher
    precedence turns off, in any order of the files."""
    out: list[str] = []
    for order in _orders(root):
        enabled: dict[str, Any] = {}
        for path in order:
            plugins = _read(path).get("enabledPlugins")
            if isinstance(plugins, dict):
                enabled.update(plugins)
        out += [k for k, v in enabled.items() if k.startswith(PLUGIN) and v is True]
    return list(dict.fromkeys(out))


def plugin_on(root: Path) -> bool:
    """True if a settings file enables a nookku plugin and no file of higher precedence turns
    it off."""
    return bool(enabled_plugins(root))


def _installs(plugin: str, root: Path) -> list[Path] | None:
    """The install folders of a plugin that Claude Code can load in the project, from
    plugins/installed_plugins.json of the user folder. An install with the scope user counts,
    and an install of another scope counts if its projectPath is the project. None if the file
    cannot be read."""
    data = _read(_user_dir() / "plugins" / "installed_plugins.json")
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entries = plugins.get(plugin)
    out = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("installPath"), str):
            continue
        project = entry.get("projectPath")
        if entry.get("scope") == "user" or (
            isinstance(project, str) and Path(project).resolve() == root.resolve()
        ):
            out.append(Path(entry["installPath"]))
    return out


def _plugin_hook_ok(group: Any, event: str) -> bool:
    """True if a group of the hooks file of the plugin runs the hook script for `event`, with
    the matcher of this version."""
    if not isinstance(group, dict):
        return False
    if group.get("matcher") != kit.HOOK_EVENTS[event][0].get("matcher"):
        return False
    hooks = group.get("hooks")
    for hook in hooks if isinstance(hooks, list) else []:
        if not isinstance(hook, dict) or hook.get("type") != "command":
            continue
        argv = _argv(str(hook.get("command", "")))
        if argv[:1] in ([x] for x in PLUGIN_SHELLS) and argv[1:] == [PLUGIN_SCRIPT_ARG, event]:
            return True
    return False


def _install_problems(folder: Path) -> list[str]:
    """Each required hook that an install of the plugin does not have. The check reads what the
    hooks run, not the bytes of the files, so an install of a newer plugin passes."""
    if not (folder / PLUGIN_SCRIPT).is_file():
        return [f"the plugin hook script {folder / PLUGIN_SCRIPT} is missing."]
    hooks = _read(folder / PLUGIN_HOOKS).get("hooks")
    if not isinstance(hooks, dict):
        return [f"the plugin hooks file {folder / PLUGIN_HOOKS} is missing or has no hooks."]
    out = []
    for event in kit.HOOK_EVENTS:
        groups = hooks.get(event)
        if not any(_plugin_hook_ok(g, event) for g in (groups if isinstance(groups, list) else [])):
            out.append(
                f"the plugin hook {event} is missing in {folder / PLUGIN_HOOKS}, or its matcher "
                "or its command differs from the hook of nookku."
            )
    return out


def plugin_problems(root: Path) -> list[str]:
    """Each reason to refuse a test for an enabled nookku plugin: no install for the project,
    or an install with a required hook missing. Empty if no nookku plugin is on."""
    out: list[str] = []
    for plugin in enabled_plugins(root):
        installs = _installs(plugin, root)
        if not installs:
            out.append(
                f"the plugin {plugin} is on, but plugins/installed_plugins.json of Claude Code "
                "has no install of it for this project."
            )
            continue
        for folder in installs:
            out += _install_problems(folder)
    return out


def plugin_warnings(root: Path) -> list[str]:
    """A warning for each install of an enabled nookku plugin with another version than this
    nookku. A version skew does not refuse a test, because the marketplace installs the plugin
    from main."""
    out: list[str] = []
    for plugin in enabled_plugins(root):
        for folder in _installs(plugin, root) or []:
            version = _read(folder / ".claude-plugin" / "plugin.json").get("version")
            if version != __version__:
                out.append(
                    f"nookku: warning: the plugin in {folder} has version {version}, and nookku "
                    f"has version {__version__}. Install the plugin of this version if a hook "
                    "does not work."
                )
    return out


def project_hooks_file(root: Path) -> Path | None:
    """The first project settings file with a hook of nookku init claude-code, or None."""
    for path in settings_files(root)[1:]:
        hooks = _read(path).get("hooks")
        if not isinstance(hooks, dict):
            continue
        for groups in hooks.values():
            for group in groups if isinstance(groups, list) else []:
                inner = group.get("hooks") if isinstance(group, dict) else None
                if isinstance(inner, list) and any(kit._ours(h) for h in inner):
                    return path
    return None


def project_hooks_on(root: Path) -> bool:
    """True if a project settings file has a hook of nookku init claude-code."""
    return project_hooks_file(root) is not None


def _ours_by_event(order: list[Path]) -> dict[str, list[tuple[Path, Any, dict[str, Any]]]]:
    """Each hook of nookku init claude-code in the files, by its event: the file, the matcher of
    its group and the hook."""
    out: dict[str, list[tuple[Path, Any, dict[str, Any]]]] = {}
    for path in order:
        hooks = _read(path).get("hooks")
        for event, groups in hooks.items() if isinstance(hooks, dict) else []:
            for group in groups if isinstance(groups, list) else []:
                inner = group.get("hooks") if isinstance(group, dict) else None
                for hook in inner if isinstance(inner, list) else []:
                    if kit._ours(hook):
                        out.setdefault(str(event), []).append((path, group.get("matcher"), hook))
    return out


def _argv(command: str) -> list[str]:
    """The words of a hook command, with the path after --root resolved."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return []
    for i, word in enumerate(argv[:-1]):
        if word == "--root":
            argv[i + 1] = str(Path(argv[i + 1]).resolve())
    return argv


def _changed(root: Path, event: str, matcher: Any, hook: dict[str, Any]) -> str | None:
    """Why a project hook differs from the hook of nookku init claude-code, or None."""
    want_matcher, timeout = kit.HOOK_EVENTS[event]
    if matcher != want_matcher.get("matcher") or hook.get("timeout") != timeout:
        return "its matcher or its timeout differs from this version of nookku"
    command = str(hook.get("command", ""))
    # The full command, with the Python of this nookku: another executable can exit 0 and not
    # block the prompt.
    if hook.get("type") != "command" or _argv(command) != _argv(
        kit.hook_command(root, "claude-code")
    ):
        return (
            f"its command is not the command of nookku init claude-code: {command}. If you "
            "installed nookku again, run nookku init claude-code again"
        )
    return None


def hook_problems(root: Path) -> list[str]:
    """Each reason to refuse a test for the project hooks of nookku init claude-code and for a
    file that turns off all hooks. Empty if the check passes. If no file has a nookku hook and
    the plugin is off, Claude Code has no nookku setup, and the check passes."""
    out: list[str] = []
    plugin = plugin_on(root)
    for order in _orders(root):
        found = _ours_by_event(order)
        off = None
        for path in order:
            value = _read(path).get("disableAllHooks")
            if isinstance(value, bool):
                off = path if value else None
        if off is not None and (plugin or found):
            out.append(f"{off} has disableAllHooks: true, so Claude Code runs no nookku hook.")
        if not found:
            continue
        for event in kit.HOOK_EVENTS:
            listed = found.get(event, [])
            if not listed:
                out.append(f"the project hook {event} is missing.")
                continue
            if len(listed) > 1:
                out.append(f"the project hook {event} is there {len(listed)} times.")
            for path, matcher, hook in listed:
                wrong = _changed(root, event, matcher, hook)
                if wrong:
                    out.append(f"the project hook {event} in {path} is modified: {wrong}.")
    return list(dict.fromkeys(out))


def problems(root: Path) -> list[str]:
    """Each reason to refuse a test for the nookku hooks of Claude Code. Empty if the check
    passes."""
    found = project_hooks_file(root)
    if found is not None and plugin_on(root):
        return [PROBLEM.format(file=found)]
    return hook_problems(root) + plugin_problems(root)


def refusal(found: list[str]) -> str:
    """The text that refuses a test, for the reasons of `problems`."""
    if len(found) == 1 and found[0].startswith("both the nookku plugin"):
        return found[0]
    lines = "\n".join(f"- {p}" for p in found)
    return (
        "the Claude Code hooks of nookku are not ready, so nookku refuses the test and does not "
        "change relay mode. Without the prompt hook, a message goes to the model.\n"
        f"{lines}\n"
        "Run nookku init claude-code again, or install the plugin of this version of nookku, or "
        "remove disableAllHooks. Then start the test again."
    )


def problem(root: Path) -> str | None:
    """The refusal of a test for the nookku hooks of Claude Code, or None."""
    found = problems(root)
    return refusal(found) if found else None


def log_refusal(root: Path, command: str, harness: str, found: list[str]) -> None:
    """Add a row for a refused start to the file REFUSALS of the state folder. The row is a log
    for a person: it has no seal, and a failed write does not change the refusal."""
    row = {
        "ts": time.time(),
        "command": command,
        "harness": harness,
        "nookku": __version__,
        "problems": found,
    }
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        # The state folder and the log must not be symlinks, and the log must be a regular file.
        # A model can write project files before a test, so a symlink could send the row to
        # another file of the user.
        folder = os.open(
            root / kit.STATE_DIR, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        )
    except OSError:
        return
    try:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | nofollow | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(REFUSALS, flags, 0o600, dir_fd=folder)
    except OSError:
        os.close(folder)
        return
    try:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            os.write(fd, data)
    except OSError:
        pass
    finally:
        os.close(fd)
        os.close(folder)

"""The Codex hook gate (SPEC.md section 7.8, #217).

Codex skips a hook that a person did not trust, and then a relayed prompt goes to the model
(#177). A hook cannot check its own trust, because Codex does not run it. Thus `start` and
`mode on` run this check outside the hooks, and refuse a test if a nookku hook of Codex is
missing, disabled, untrusted or modified. `end` runs it again, and the manifest keeps both
results.

The check reads the hook state with `codex app-server` and `hooks/list`. It never changes the
trust of a hook: a person does the trust step. The trust hash of Codex covers the hook
definition, but not the script that a plugin hook runs (proofs/codex-gate/gate.json). Thus the
check also compares the SHA-256 of the plugin script with the script of this package.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from nookku import __version__, kit

# The SHA-256 of plugins/nookku/hooks/nookku-hook.sh of this version (tests/test_codex_gate.py).
PLUGIN_SCRIPT_SHA256 = "f50a064260a464c81c864c5bb5bc760f15c9b04770ff81c42ade03dba7511341"
PLUGIN_SCRIPT = "nookku-hook.sh"
# The plugin id of Codex is <plugin>@<marketplace>.
PLUGIN_PREFIX = "nookku@"
# hooks/list names each event in camel case.
EVENTS = {"UserPromptSubmit": "userPromptSubmit", "PreToolUse": "preToolUse"}
TIMEOUT = 60.0


def command() -> str:
    """The codex command: NOOKKU_CODEX, else codex."""
    return os.environ.get("NOOKKU_CODEX") or "codex"


class GateError(Exception):
    """The hook state of Codex cannot be read."""


class CodexUnusable(Exception):
    """codex app-server stopped before it answered, for example with a CODEX_HOME that does not
    exist. Then Codex cannot run in this environment, and no Codex test can run either."""


def read_hooks(root: Path, timeout: float | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """The hooks and the warnings of hooks/list for the project, from one app-server."""
    timeout = TIMEOUT if timeout is None else timeout
    lines = [
        {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "nookku", "version": __version__},
                "capabilities": {"experimentalApi": True},
            },
        },
        {"method": "initialized"},
        {"id": 2, "method": "hooks/list", "params": {"cwds": [str(root)]}},
    ]
    try:
        proc = subprocess.Popen(
            [command(), "app-server", "--stdio", "-c", "features.hooks=true"],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as e:
        raise GateError(f"cannot start codex app-server: {e}") from None
    assert proc.stdin is not None and proc.stdout is not None
    timed_out = threading.Event()

    def stop() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, stop)
    timer.start()
    answer: dict[str, Any] | None = None
    try:
        proc.stdin.write("".join(json.dumps(line) + "\n" for line in lines))
        proc.stdin.flush()
        for raw in proc.stdout:
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if message.get("id") == 2:
                answer = message
                break
    except OSError as e:
        raise GateError(f"codex app-server stopped: {e}") from None
    finally:
        timer.cancel()
        proc.kill()
        proc.wait()
    if answer is None and timed_out.is_set():
        raise GateError(f"codex app-server gave no hooks/list answer in {timeout:g} s")
    if answer is None:
        raise CodexUnusable(f"codex app-server stopped with exit code {proc.returncode}")
    if "error" in answer:
        raise GateError(f"hooks/list failed: {answer['error']}")
    try:
        entry = answer["result"]["data"][0]
        return list(entry["hooks"]), list(entry.get("warnings", []))
    except (KeyError, IndexError, TypeError):
        raise GateError(f"hooks/list gave an answer of a wrong form: {answer}") from None


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _project_events(root: Path) -> set[str]:
    """The events of the nookku hooks in the project hook file of Codex."""
    target = root / ".codex" / "hooks.json"
    try:
        hooks = json.loads(target.read_text(encoding="utf-8")).get("hooks", {})
    except (OSError, ValueError, AttributeError):
        return set()
    found = set()
    for event, groups in hooks.items() if isinstance(hooks, dict) else []:
        for group in groups if isinstance(groups, list) else []:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list) and any(kit._ours(h) for h in inner):
                found.add(event)
    return found


def _origin(hook: dict[str, Any]) -> str | None:
    """plugin or project for a nookku hook, else None."""
    if str(hook.get("pluginId") or "").startswith(PLUGIN_PREFIX):
        return "plugin"
    if hook.get("source") == "project" and kit._ours(hook):
        return "project"
    return None


def _definition_problem(origin: str, event: str, hook: dict[str, Any], root: Path) -> str | None:
    """Why a nookku hook differs from the hook of this version, or None."""
    matcher, timeout = kit.HOOK_EVENTS[event]
    if hook.get("matcher") != matcher.get("matcher") or hook.get("timeoutSec") != timeout:
        return "its matcher or its timeout differs from this version of nookku"
    command = str(hook.get("command", ""))
    if origin == "project":
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        if argv[1:] != ["-m", "nookku", "hook", "--root", str(root), "--harness", "codex"]:
            return f"its command is not the command of nookku init codex: {command}"
        return None
    script = Path(str(hook.get("sourcePath", ""))).parent / PLUGIN_SCRIPT
    if command != f'sh "{script}" {event}':
        return f"its command is not the command of the plugin: {command}"
    if _sha256(script) != PLUGIN_SCRIPT_SHA256:
        return f"its script {script} differs from the script of nookku {__version__}"
    return None


def problems(hooks: list[dict[str, Any]], root: Path) -> list[str]:
    """Each reason to refuse a test, for the hooks of hooks/list. Empty if the gate passes."""
    found: dict[str, dict[str, list[dict[str, Any]]]] = {"plugin": {}, "project": {}}
    for hook in hooks:
        origin = _origin(hook)
        if origin is not None:
            found[origin].setdefault(str(hook.get("eventName")), []).append(hook)
    expected: dict[str, set[str]] = {"plugin": set(), "project": set()}
    if found["plugin"]:
        expected["plugin"] = set(EVENTS)
    if found["project"] or _project_events(root):
        expected["project"] = set(EVENTS)
    out = []
    if expected["plugin"] and expected["project"]:
        out.append(
            "both the nookku plugin and the project hooks of nookku init codex are on, so each "
            "message would go to the agent two times. Remove one of them."
        )
    for origin, events in expected.items():
        name = "the plugin hook" if origin == "plugin" else "the project hook"
        for event in sorted(events):
            listed = found[origin].get(EVENTS[event], [])
            if not listed:
                why = (
                    "is missing. Codex lists the project hooks only in a project that you trust."
                    if origin == "project"
                    else "is missing."
                )
                out.append(f"{name} {event} {why}")
                continue
            if len(listed) > 1:
                out.append(f"{name} {event} is there {len(listed)} times.")
            for hook in listed:
                if hook.get("enabled") is not True:
                    out.append(f"{name} {event} is disabled.")
                trust = hook.get("trustStatus")
                if trust != "trusted":
                    out.append(f"{name} {event} is {trust}, not trusted.")
                wrong = _definition_problem(origin, event, hook, root)
                if wrong:
                    out.append(f"{name} {event} is modified: {wrong}.")
    return out


def _summary(hook: dict[str, Any]) -> dict[str, Any]:
    row = {
        "origin": _origin(hook),
        "event": hook.get("eventName"),
        "enabled": hook.get("enabled"),
        "trust": hook.get("trustStatus"),
        "hash": hook.get("currentHash"),
    }
    if row["origin"] == "plugin":
        row["script_sha256"] = _sha256(Path(str(hook.get("sourcePath", ""))).parent / PLUGIN_SCRIPT)
    return row


def check(root: Path) -> dict[str, Any]:
    """The gate result: the nookku hooks that Codex lists, and each problem. With no codex
    command, no check runs, and the result has no problem: the test cannot run in Codex."""
    if shutil.which(command()) is None:
        return {"codex": False, "hooks": [], "problems": []}
    try:
        hooks, _ = read_hooks(root)
    except CodexUnusable as e:
        return {"codex": False, "hooks": [], "problems": [], "note": str(e)}
    except GateError as e:
        return {"codex": True, "hooks": [], "problems": [f"cannot read the hooks of Codex: {e}"]}
    ours = [_summary(h) for h in hooks if _origin(h) is not None]
    return {"codex": True, "hooks": ours, "problems": problems(hooks, root)}


def refusal(result: dict[str, Any]) -> str:
    """The text that refuses a test, for a result with problems."""
    lines = "\n".join(f"- {p}" for p in result["problems"])
    return (
        "the Codex hooks of nookku are not ready, so relay mode stays off. Codex skips a hook "
        "that is not trusted, and then a message goes to the model.\n"
        f"{lines}\n"
        "Start codex in this project, type /hooks, check each nookku hook and trust it. Then "
        "start the test again."
    )

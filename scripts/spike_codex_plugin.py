"""Measure plugin hooks for #177. Local only; a person must trust every new hook.

Run `python3 scripts/spike_codex_plugin.py prepare`, then `exec untrusted`.
Run `interactive` in a terminal to inspect /hooks and trust the toy plugin.
Run `exec trusted` after that. `upgrade-version` changes only the manifest;
`upgrade-hook` changes the hook timeout. Repeat the checks after each upgrade.
Run `validate-layout` to check the shared manifests. Run `desktop-start` before
the maintainer submits the toy prompts in a new desktop chat. Do not run a CLI
probe in the test folder until `desktop-finish` saves that observation.

The Git marketplace is served over loopback HTTP. The model provider is a local
mock that records only toy prompt markers and emits one harmless shell call.
No auth value, model context, or model answer is written to the proof.
Desktop runs and the trust UI require the maintainer. This script never edits
hook trust or uses a trust bypass. An absent observation stays pending.
The desktop version comes from the installed bundle, and bundled_cli comes from
that bundle's --version command. Neither identifies the running chat process.
Keep that runtime version unknown unless it is measured independently.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import plistlib
import selectors
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".proof" / "codex-plugin-spike"
REPO = WORK / "marketplace"
PROJECT = WORK / "project"
PROOF = ROOT / "proofs" / "spikes" / "codex-plugin.json"
NAME = "toy-hook-spike-177"
MARKET = "toy-hook-market-177"
SELECTOR = f"{NAME}@{MARKET}"
BLOCK = "SPIKE_BLOCK_PROMPT_177"
TOOL = "SPIKE_TOOL_177"
PROMPT = f"Use the shell to run printf {TOOL}, then reply done."
EVENTS = ".spike-177-events.jsonl"
DESKTOP_BASELINE = WORK / "desktop-baseline.json"
DESKTOP = Path("/Applications/ChatGPT.app")
SOURCES = [
    "https://learn.chatgpt.com/docs/hooks",
    "https://developers.openai.com/plugins/build/plugins",
]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_proof() -> dict[str, Any]:
    if not PROOF.exists():
        raise SystemExit("No proof exists. Run prepare first.")
    return json.loads(PROOF.read_text(encoding="utf-8"))


def run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=90)
    if completed.returncode:
        raise SystemExit(f"Command failed: {shlex.join(args)}\n{completed.stderr}")
    return completed


def versions() -> dict[str, Any]:
    plist = DESKTOP / "Contents" / "Info.plist"
    desktop: dict[str, Any] = {"status": "not_found"}
    if plist.exists():
        with plist.open("rb") as stream:
            info = plistlib.load(stream)
        desktop = {
            "status": "installed",
            "measurement": "Installed Info.plist and bundled CLI --version",
            "version": info["CFBundleShortVersionString"],
            "build": info["CFBundleVersion"],
            "bundled_cli": run(
                [str(DESKTOP / "Contents/Resources/codex-cli/bin/codex"), "--version"]
            ).stdout.strip(),
            "independently_observed_runtime_version": None,
        }
    return {"codex_cli": run(["codex", "--version"]).stdout.strip(), "desktop": desktop}


def inspect_hooks() -> dict[str, Any]:
    """Read hook metadata. This never calls a trust or config mutation API."""
    process = subprocess.Popen(
        [
            "codex",
            "app-server",
            "--stdio",
            "-c",
            "features.hooks=true",
            "-c",
            f'plugins."{SELECTOR}".enabled=true',
        ],
        cwd=PROJECT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdin is not None and process.stdout is not None
    buffered = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)

        def request(identifier: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal buffered
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(
                (json.dumps({"id": identifier, "method": method, "params": params}) + "\n").encode()
            )
            process.stdin.flush()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                while b"\n" in buffered:
                    line, buffered = buffered.split(b"\n", 1)
                    response = json.loads(line)
                    if response.get("id") == identifier:
                        if "error" in response:
                            raise RuntimeError(f"{method}: {response['error']}")
                        return response["result"]
                if selector.select(timeout=min(1, max(0, deadline - time.monotonic()))):
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError(f"{method}: app-server closed before its response")
                    buffered += chunk
            raise TimeoutError(f"{method}: no response in 30 seconds")

        try:
            request(
                1,
                "initialize",
                {
                    "clientInfo": {"name": "toy-spike-177", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            process.stdin.write(b'{"method":"initialized"}\n')
            process.stdin.flush()
            data = request(2, "hooks/list", {"cwds": [str(PROJECT)]})
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    entry = data["data"][0]
    result = {
        "codex_version": run(["codex", "--version"]).stdout.strip(),
        "method": "app-server initialize, hooks/list; no trust mutation",
        "hooks": [hook for hook in entry["hooks"] if hook.get("pluginId") == SELECTOR],
        "errors": entry["errors"],
        "warnings": entry["warnings"],
    }
    return json.loads(
        json.dumps(result)
        .replace(str(Path.home()), "<user-home>")
        .replace(str(WORK), "<spike-work>")
    )


def event_rows() -> list[dict[str, Any]]:
    record = PROJECT / EVENTS
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text(encoding="utf-8").split("\n") if line]


def safe_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for original in rows:
        row = original.copy()
        row["root_variables_equal"] = row["plugin_root"] == row["claude_plugin_root"]
        row["plugin_root_set"] = bool(row.pop("plugin_root"))
        row["claude_plugin_root_set"] = bool(row.pop("claude_plugin_root"))
        result.append(row)
    return result


def desktop_start() -> None:
    """Save the baseline; a person operates the desktop app after this step."""
    proof = read_proof()
    write_json(
        DESKTOP_BASELINE,
        {"row_count": len(event_rows()), "versions": versions(), "fixture": proof["fixture"]},
    )
    proof["status"] = "awaiting_human_desktop_check"
    proof["manual_next_step"] = {
        "surface": "desktop_local_chat",
        "project": "<worktree>/.proof/codex-plugin-spike/project",
        "instructions": [
            "Open the test folder as a project in the desktop app. Start a new local Codex chat.",
            "Do not run the CLI in that folder between desktop-start and desktop-finish.",
            f"Submit {BLOCK}. Record whether the app shows the toy prompt block.",
            f"Submit: {PROMPT} If a tool is blocked, do not retry it.",
            "Report whether the app showed each block and confirm the desktop version.",
            "If the app asks for hook trust, a person must review and trust the toy definitions.",
        ],
    }
    write_json(PROOF, proof)
    print(f"Open this folder in the desktop app: {PROJECT}")
    print(f"First prompt: {BLOCK}")
    print(f"Second prompt: {PROMPT} If the tool is blocked, do not retry it.")
    print("Only a person operates the app. No desktop test was performed by this command.")


def desktop_finish(prompt_blocked: str, tool_blocked: str) -> None:
    if not DESKTOP_BASELINE.exists():
        raise SystemExit("No desktop baseline exists. Run desktop-start before the app check.")
    baseline = json.loads(DESKTOP_BASELINE.read_text(encoding="utf-8"))
    rows = event_rows()
    if len(rows) < baseline["row_count"]:
        raise SystemExit("The event log changed. Run desktop-start and repeat the desktop check.")
    proof = read_proof()
    proof.setdefault("desktop_runs", []).append(
        {
            "surface": "desktop_local_chat",
            "operation": "Maintainer operates the desktop app; the script reads toy hook events",
            "versions_before": baseline["versions"],
            "versions_after": versions(),
            "fixture": baseline["fixture"],
            "hook_events": safe_events(rows[baseline["row_count"] :]),
            "human_observation": {"prompt_blocked": prompt_blocked, "tool_blocked": tool_blocked},
            "limits": [
                "Attribution requires no CLI run in the same folder during this observation.",
                "No independent desktop model-request capture; block display is a human report.",
                "Installed bundle versions do not identify the running desktop chat process.",
            ],
        }
    )
    proof["status"] = "desktop_evidence_recorded"
    proof.pop("manual_next_step", None)
    write_json(PROOF, proof)
    print(f"Saved the desktop observation to {PROOF}.")


def hook() -> int:
    """Record allowed fields from the toy event, then block its test markers."""
    # This toy probe expects harness fields. A malformed event can fail open.
    # It is not a relay guard; the external check must run before relay prompts.
    event = json.load(sys.stdin)
    if Path(event["cwd"]).parts[-3:] != (".proof", "codex-plugin-spike", "project"):
        print("{}")
        return 0
    name = event["hook_event_name"]
    row = {
        "event": name,
        "tool_name": event.get("tool_name"),
        "blocked_prompt": BLOCK in event.get("prompt", ""),
        "plugin_root": os.environ.get("PLUGIN_ROOT"),
        "claude_plugin_root": os.environ.get("CLAUDE_PLUGIN_ROOT"),
        "plugin_data_set": bool(os.environ.get("PLUGIN_DATA")),
        "claude_plugin_data_set": bool(os.environ.get("CLAUDE_PLUGIN_DATA")),
    }
    with (Path(event["cwd"]) / EVENTS).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    if name == "UserPromptSubmit" and row["blocked_prompt"]:
        print(json.dumps({"decision": "block", "reason": "Toy spike blocked the prompt."}))
    elif name == "PreToolUse" and TOOL in json.dumps(event.get("tool_input", {})):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": name,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "Toy spike blocked the shell call.",
                    }
                }
            )
        )
    else:
        print("{}")
    return 0


def fixture(version: str, timeout: int) -> None:
    plugin = REPO / "plugins" / NAME
    manifest = {"name": NAME, "version": version, "skills": "./skills/"}
    write_json(plugin / ".codex-plugin/plugin.json", manifest)
    write_json(plugin / ".claude-plugin/plugin.json", manifest)
    # One hooks file and one skills folder, with both compatibility manifests.
    command = f'{shlex.quote(sys.executable)} "${{CLAUDE_PLUGIN_ROOT}}/scripts/probe.py" hook'
    write_json(
        plugin / "hooks/hooks.json",
        {
            "hooks": {
                event: [{"hooks": [{"type": "command", "command": command, "timeout": timeout}]}]
                for event in ("SessionStart", "UserPromptSubmit", "PreToolUse")
            }
        },
    )
    skill = plugin / "skills/toy-spike/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: toy-spike\ndescription: Identify the toy hook spike.\n---\n\n"
        "This skill belongs to the toy hook spike.\n",
        encoding="utf-8",
    )
    script = plugin / "scripts/probe.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    # Keep the executable fixed during manifest and timeout comparisons.
    # Later edits to this script do not update an existing fixture probe.
    # Use a new fixture and repeat human trust and measurements for new code.
    if not script.exists():
        script.write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    write_json(
        REPO / ".agents/plugins/marketplace.json",
        {
            "name": MARKET,
            "plugins": [
                {
                    "name": NAME,
                    "source": {"source": "local", "path": f"./plugins/{NAME}"},
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    "category": "Productivity",
                }
            ],
        },
    )
    if not (REPO / ".git").exists():
        run(["git", "init", "-b", "main"], REPO)
    run(["git", "add", "."], REPO)
    run(["git", "commit", "-m", f"Toy hook fixture {version}, timeout {timeout}"], REPO)
    run(["git", "update-server-info"], REPO)


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


def install(upgrade: bool = False) -> dict[str, Any]:
    handler = functools.partial(QuietFiles, directory=str(REPO))
    port_file = WORK / "marketplace-port.txt"
    port = int(port_file.read_text()) if port_file.exists() else 0
    if upgrade and not port:
        listed = json.loads(
            run(["codex", "plugin", "list", "--marketplace", MARKET, "--json"]).stdout
        )
        installed = next(item for item in listed["installed"] if item["pluginId"] == SELECTOR)
        port = urlsplit(installed["marketplaceSource"]["source"]).port or 0
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    port_file.write_text(str(server.server_port))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/.git"
    try:
        added = (
            run(["codex", "plugin", "marketplace", "upgrade", MARKET, "--json"])
            if upgrade
            else run(["codex", "plugin", "marketplace", "add", url, "--ref", "main", "--json"])
        )
        installed = run(["codex", "plugin", "add", SELECTOR, "--json"])
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    installed_result = json.loads(installed.stdout)
    installed_result["installedPath"] = installed_result["installedPath"].replace(
        str(Path.home()), "<user-home>"
    )
    return {
        "source": "Git over loopback HTTP, ref main",
        "marketplace_command": "upgrade" if upgrade else "add",
        "marketplace_exit": added.returncode,
        "plugin_add_exit": installed.returncode,
        "upgrade": upgrade,
        "git_commit": run(["git", "rev-parse", "HEAD"], REPO).stdout.strip(),
        "hook_definition_sha256": hashlib.sha256(
            (REPO / "plugins" / NAME / "hooks/hooks.json").read_bytes()
        ).hexdigest(),
        "installed": installed_result,
    }


class MockModel(BaseHTTPRequestHandler):
    observations: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8")
        self.observations.append(
            {
                "path": self.path,
                "block_marker": BLOCK in body,
                "tool_marker": TOOL in body,
                "toy_tool_denial": "Toy spike blocked the shell call." in body,
            }
        )
        first = len(self.observations) == 1
        item: dict[str, Any]
        if first:
            item = {
                "type": "function_call",
                "id": "fc_spike177",
                "call_id": "call_spike177",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": f"printf {TOOL}"}),
            }
        else:
            item = {
                "type": "message",
                "id": "msg_spike177",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "done", "annotations": []}],
            }
        events = [
            {"type": "response.created", "response": {"id": "resp_spike177"}},
            {"type": "response.output_item.added", "output_index": 0, "item": item},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_spike177",
                    "status": "completed",
                    "output": [item],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            },
        ]
        payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def measure(interactive: bool, expectation: str, case: str) -> None:
    proof = read_proof()
    hook_metadata = inspect_hooks()
    expected_events = {"sessionStart", "userPromptSubmit", "preToolUse"}
    trusted = (
        len(hook_metadata["hooks"]) == 3
        and {hook["eventName"] for hook in hook_metadata["hooks"]} == expected_events
        and all(
            hook["trustStatus"] == "trusted" and hook["enabled"] for hook in hook_metadata["hooks"]
        )
    )
    if expectation == "trusted" and not trusted:
        proof.setdefault("preflight_refusals", []).append(
            {"hook_metadata": hook_metadata, "model_endpoint_started": False}
        )
        write_json(PROOF, proof)
        raise SystemExit("The toy hooks are not all trusted. A person must inspect /hooks first.")
    if expectation == "untrusted" and trusted:
        raise SystemExit("The toy hooks are already trusted. Use exec trusted to measure them.")
    listed = json.loads(run(["codex", "plugin", "list", "--marketplace", MARKET, "--json"]).stdout)
    installed = next(item for item in listed["installed"] if item["pluginId"] == SELECTOR)
    source = installed["marketplaceSource"]["source"]
    PROJECT.mkdir(parents=True, exist_ok=True)
    record = PROJECT / EVENTS
    before = record.read_text(encoding="utf-8").count("\n") if record.exists() else 0
    MockModel.observations = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockModel)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    overrides = {
        "model": '"toy-spike-model"',
        "model_provider": '"toy_spike"',
        "model_providers.toy_spike.name": '"Toy spike loopback"',
        "model_providers.toy_spike.base_url": f'"http://127.0.0.1:{server.server_port}/v1"',
        "model_providers.toy_spike.wire_api": '"responses"',
        "model_providers.toy_spike.requires_openai_auth": "false",
        f'plugins."{SELECTOR}".enabled': "true",
        "features.hooks": "true",
        "features.code_mode": "false",
        "features.code_mode_only": "false",
        f'marketplaces."{MARKET}".source_type': '"git"',
        f'marketplaces."{MARKET}".source': json.dumps(source),
        f'marketplaces."{MARKET}".ref': '"main"',
    }
    # Hook trust is in user config. Ignoring that file invalidates a trusted run.
    cmd = ["codex"] if interactive else ["codex", "exec", "--json"]
    for key, value in overrides.items():
        cmd.extend(["-c", f"{key}={value}"])
    cmd.extend(["-C", str(PROJECT), "-s", "read-only"])
    if interactive:
        cmd.extend(["--no-alt-screen", "--no-daemon"])
        print(f"Inspect /hooks for {SELECTOR}. A person must review and trust the hooks.")
        print(f"Submit {BLOCK}, then: {PROMPT}. Exit with Ctrl+D.")
    else:
        cmd.extend(["--skip-git-repo-check", "--ephemeral", BLOCK if case == "prompt" else PROMPT])
    try:
        completed = subprocess.run(
            cmd, cwd=PROJECT, text=True, capture_output=not interactive, timeout=600
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    rows = safe_events(event_rows()[before:])
    warnings = []
    stream_types: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    if not interactive:
        warnings = [
            line.replace(str(Path.home()), "<user-home>").replace(str(WORK), "<spike-work>")
            for line in (completed.stderr + "\n" + completed.stdout).split("\n")
            if "hook" in line.lower() and ("trust" in line.lower() or "review" in line.lower())
        ]
        for line in completed.stdout.split("\n"):
            if not line.startswith("{"):
                continue
            entry = json.loads(line)
            stream_types.append(entry.get("type", "unknown"))
            item = entry.get("item", {})
            if item.get("type") in ("error", "warning"):
                message = item.get("message", "")
                diagnostics.append(
                    {
                        "type": item["type"],
                        "message": message.replace(str(Path.home()), "<user-home>").replace(
                            str(WORK), "<spike-work>"
                        ),
                    }
                )
    proof["runs"].append(
        {
            "surface": "interactive_cli" if interactive else "codex_exec",
            "expected_trust": expectation,
            "case": case,
            "hook_metadata_before_run": hook_metadata,
            "fixture": proof["fixture"],
            "plugin_listed_installed": installed["installed"],
            "exit_code": completed.returncode,
            "hook_events": rows,
            "model_requests": MockModel.observations,
            "trust_warnings": warnings,
            "stream_event_types": stream_types,
            "diagnostics": diagnostics,
            "codex_version": run(["codex", "--version"]).stdout.strip(),
        }
    )
    write_json(PROOF, proof)
    print(f"Saved observation to {PROOF}. Trust state was not changed by the script.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "step",
        choices=[
            "prepare",
            "exec",
            "interactive",
            "inspect",
            "validate-layout",
            "desktop-start",
            "desktop-finish",
            "upgrade-version",
            "upgrade-hook",
            "hook",
        ],
    )
    parser.add_argument("expectation", nargs="?", choices=["untrusted", "trusted", "observe"])
    parser.add_argument("--case", choices=["prompt", "tool"], default="prompt")
    parser.add_argument("--prompt-blocked", choices=["yes", "no", "unknown"], default="unknown")
    parser.add_argument("--tool-blocked", choices=["yes", "no", "unknown"], default="unknown")
    args = parser.parse_args()
    if args.step == "hook":
        return hook()
    if args.step == "desktop-start":
        desktop_start()
    elif args.step == "desktop-finish":
        desktop_finish(args.prompt_blocked, args.tool_blocked)
    elif args.step == "inspect":
        metadata = inspect_hooks()
        proof = read_proof()
        proof.setdefault("hook_inspections", []).append(metadata)
        write_json(PROOF, proof)
        print(json.dumps(metadata, indent=2))
    elif args.step == "validate-layout":
        checked = run(["claude", "plugin", "validate", str(REPO / "plugins" / NAME)])
        proof = read_proof()
        proof["shared_layout_validation"] = {
            "claude_code_version": run(["claude", "--version"]).stdout.strip(),
            "exit_code": checked.returncode,
            "scope": "Manifest validation; not a Claude Code hook runtime test",
            "warnings": ["No description provided", "No author information provided"],
        }
        write_json(PROOF, proof)
        print(checked.stdout)
    elif args.step == "prepare":
        if PROOF.exists():
            raise SystemExit("The proof already exists. Continue with exec or interactive.")
        if not REPO.exists():
            fixture("1.0.0", 10)
        installation = install()
        PROJECT.mkdir(parents=True, exist_ok=True)
        write_json(
            PROOF,
            {
                "issue": 177,
                "date_utc": datetime.now(timezone.utc).date().isoformat(),
                "status": "awaiting_human_trust_and_desktop_checks",
                "versions": versions(),
                "method": "scripts/spike_codex_plugin.py",
                "documentation": SOURCES,
                "fixture": {"version": "1.0.0", "hook_timeout": 10},
                "installation": [installation],
                "runs": [],
                "answers": {
                    question: {"status": "pending"}
                    for question in (
                        "events_by_surface",
                        "trust_ui",
                        "trust_after_upgrade",
                        "untrusted_prompt",
                        "session_start_detection",
                        "shared_layout",
                        "plugin_root_variables",
                        "git_marketplace_install",
                    )
                },
            },
        )
        print(f"Installed {SELECTOR}. Next: exec untrusted. No hooks were trusted.")
    elif args.step in ("upgrade-version", "upgrade-hook"):
        proof = read_proof()
        version, timeout = ("1.0.1", 10) if args.step == "upgrade-version" else ("1.0.2", 11)
        fixture(version, timeout)
        proof["installation"].append(install(upgrade=True))
        proof["fixture"] = {"version": version, "hook_timeout": timeout}
        write_json(PROOF, proof)
        print("The fixture changed. Inspect /hooks before you trust a changed definition.")
    else:
        measure(args.step == "interactive", args.expectation or "observe", args.case)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Measure Codex tool-result call_id matches (#250). Local only.

Run codex exec in a toy shop folder with the trusted project-proof home. First give it only
standard OTEL_* variables, then configure the native Codex OTLP log exporter. Ask for separate
shell calls. Join each Codex tool_result log's call_id to the response_item call_id or to the
completed item id in the rollout. Keep only ids, names and source lines. No model text, command
output, instruction file, credential or personal telemetry attribute is stored in the result.

usage: uv run python scripts/spike_codex_call_id.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from proof_common import json_lines  # noqa: E402

from nookku import __version__, otlp  # noqa: E402
from nookku.stdio import start_in_thread  # noqa: E402

PROMPT = (
    "This is a toy shop tool test. Run these shell commands as two separate tool calls, "
    "in this order: `printf 'toy-order-ready\\n'` then `printf 'toy-stock-ready\\n'`. "
    "Do not read any files. Then reply with one word: done."
)


def measure(native: bool) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="nookku-call-id-"))
    home = ROOT / ".proof/codex-hooks/codex-home"
    record = work / "otel.jsonl"
    receiver = otlp.Receiver(("127.0.0.1", 0), record)
    start_in_thread(receiver)
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "read-only", "-C", str(work)]
    overrides = []
    if native:
        exporter = (
            f'otel.exporter={{otlp-http={{endpoint="{receiver.url}/v1/logs",protocol="binary"}}}}'
        )
        overrides = ["-c", exporter, "-c", "otel.log_user_prompt=false"]
    try:
        result = subprocess.run(
            [*cmd, *overrides, PROMPT],
            capture_output=True,
            text=True,
            env={**os.environ, **otlp.environment(receiver.url), "CODEX_HOME": str(home)},
            stdin=subprocess.DEVNULL,
            timeout=300,
        )
        receiver.quiet(limit=5)
    finally:
        receiver.shutdown()
        receiver.server_close()
    events = json_lines(result.stdout)
    thread = next((e["thread_id"] for e in events if e.get("type") == "thread.started"), None)
    paths = list((home / "sessions").rglob(f"*{thread}.jsonl")) if thread else []
    calls = []
    items = []
    for path in paths:
        for line, row in enumerate(json_lines(path.read_text()), 1):
            payload = row.get("payload") or {}
            if row.get("type") == "response_item" and payload.get("type") in (
                "function_call",
                "custom_tool_call",
                "local_shell_call",
            ):
                calls.append(
                    {
                        "line": line,
                        "type": payload["type"],
                        "call_id": payload.get("call_id"),
                        "name": payload.get("name"),
                    }
                )
            item = payload.get("item") or {}
            if (
                row.get("type") == "event_msg"
                and payload.get("type") == "item_completed"
                and item.get("type") in ("CommandExecution", "McpToolCall", "DynamicToolCall")
            ):
                items.append({"line": line, "type": item["type"], "id": item.get("id")})
    logs = []
    for line, row in enumerate(json_lines(record.read_text()) if record.exists() else [], 1):
        if otlp.short(row.get("event_name")) != "tool_result":
            continue
        attrs = row["attributes"]
        logs.append(
            {
                "line": line,
                "event": row["event_name"],
                "attribute_names": sorted(attrs),
                "call_id": attrs.get("call_id"),
                "tool_name": attrs.get("tool_name"),
                "call_lines": [c["line"] for c in calls if c["call_id"] == attrs.get("call_id")],
                "item_lines": [i["line"] for i in items if i["id"] == attrs.get("call_id")],
            }
        )
    return {
        "exporter": "native otel.exporter" if native else "OTEL_* only",
        "native_overrides": [v.replace(receiver.url, "<receiver URL>") for v in overrides],
        "exit_code": result.returncode,
        "turn_completed": any(e.get("type") == "turn.completed" for e in events),
        "session_file_found": len(paths) == 1,
        "session": thread,
        "calls": calls,
        "completed_items": items,
        "tool_result_logs": logs,
        "every_result_matches_one_call": bool(logs)
        and all(
            log["call_id"] and len(log["call_lines"]) + len(log["item_lines"]) == 1 for log in logs
        ),
        # Errors contain no model answer. Keep only the fact of a config failure.
        "config_error": "error loading configuration" in result.stderr.lower(),
    }


def main() -> int:
    runs = [measure(False), measure(True)]
    checks = {
        "both_turns_completed": all(r["exit_code"] == 0 and r["turn_completed"] for r in runs),
        "native_exporter_has_tool_results": bool(runs[1]["tool_result_logs"]),
        "native_results_match_by_call_id": runs[1]["every_result_matches_one_call"],
        "multiple_calls_tested": len(runs[1]["calls"]) >= 2,
        "each_response_call_has_a_result": bool(runs[1]["calls"])
        and all(
            any(log["call_id"] == call["call_id"] for log in runs[1]["tool_result_logs"])
            for call in runs[1]["calls"]
        ),
        "each_completed_item_has_a_result": bool(runs[1]["completed_items"])
        and all(
            any(log["call_id"] == item["id"] for log in runs[1]["tool_result_logs"])
            for item in runs[1]["completed_items"]
        ),
    }
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=30)
    data = {
        "date": date.today().isoformat(),
        "method": "scripts/spike_codex_call_id.py",
        "versions": {"nookku": __version__, "codex": version.stdout.strip()},
        "prompt": PROMPT,
        "runs": runs,
        "checks": checks,
        "pass": all(checks.values()),
    }
    out = ROOT / "proofs/spikes/codex-call-id.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1) + "\n")
    print(json.dumps(data))
    return 0 if data["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

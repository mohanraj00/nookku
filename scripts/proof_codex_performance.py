"""Check SPEC.md 8.7 with a real Codex app-server session. Local only (#456).

Run the toy shop entry with --codex-only. It records thread/tokenUsage/updated notifications
without model text. Compare their last and total usage with the copied rollout token_count
lines, then compare their sums with performance.json. Repeated totals must not add calls.
The result keeps only usage data, line numbers, checks and versions. No model answer is stored.

usage: uv run python scripts/proof_codex_performance.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from proof_common import codex_home  # noqa: E402
from proof_sessions import ENTRY  # noqa: E402

from nookku import bridge, discovery, seal  # noqa: E402

MESSAGES = ["Where is my order 4471?", "Where is my order 9999?"]


def read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().split("\n") if line]


def main() -> int:
    project = Path(tempfile.mkdtemp(prefix="nookku-codex-performance-"))
    (project / ".nookku").mkdir(parents=True, exist_ok=True)
    usage = project / "usage.jsonl"
    usage.unlink(missing_ok=True)
    os.environ["CODEX_HOME"] = str(codex_home(False, project))
    os.environ["NOOKKU_PROOF_CODEX_USAGE"] = str(usage)
    config = {"entry": [*ENTRY, "--codex-only"], "models": ["codex"], "page": False}
    (project / ".nookku/config.json").write_text(json.dumps(config))
    discovery.register(project, discovery.make(model_apis=[]))
    cur = bridge.start(project, wait=120)
    replies = []
    try:
        for message in MESSAGES:
            reply, ok = bridge.send(cur, message)
            replies.append(ok and bool(reply.strip()))
    finally:
        manifest = bridge.end(project)
    assert manifest is not None
    folder = Path(cur["dir"])
    data = json.loads((folder / "performance.json").read_text())
    sessions = [s for s in manifest["model_sessions"] if s["harness"] == "codex"]
    events = []
    for session in sessions:
        for n, row in enumerate(read(folder / session["file"]), 1):
            payload = row.get("payload", {})
            if row.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info")
                if isinstance(info, dict) and isinstance(info.get("last_token_usage"), dict):
                    events.append({"line": n, "timestamp": row["timestamp"], **info})
    notifications = read(usage) if usage.exists() else []
    calls = []
    previous = None
    for event in events:
        total = event.get("total_token_usage")
        if total != previous:
            calls.append(event)
        previous = total
    expected = [
        {
            "input_tokens": n["tokenUsage"]["last"]["inputTokens"],
            "output_tokens": n["tokenUsage"]["last"]["outputTokens"],
        }
        for n in notifications
    ]
    actual = [
        {k: c["last_token_usage"][k] for k in ("input_tokens", "output_tokens")} for c in calls
    ]
    token_keys = {
        "input_tokens": "inputTokens",
        "cached_input_tokens": "cachedInputTokens",
        "output_tokens": "outputTokens",
        "reasoning_output_tokens": "reasoningOutputTokens",
        "total_tokens": "totalTokens",
    }
    totals_agree = len(calls) == len(notifications) and all(
        all(
            event["total_token_usage"][key] == note["tokenUsage"]["total"][camel]
            for key, camel in token_keys.items()
        )
        and all(
            event["last_token_usage"][key] == note["tokenUsage"]["last"][camel]
            for key, camel in token_keys.items()
        )
        for event, note in zip(calls, notifications, strict=True)
    )
    turns = data["turns"]
    turn_ids = list(dict.fromkeys(n["turnId"] for n in notifications))
    per_turn = [
        [n["tokenUsage"]["last"] for n in notifications if n["turnId"] == turn] for turn in turn_ids
    ]
    checks = {
        "each_turn_has_an_answer": all(replies) and len(replies) == len(MESSAGES),
        "one_codex_app_session": len(sessions) == 1,
        "usage_notifications_match_rollout_calls": bool(expected) and expected == actual,
        "last_and_total_usage_match_notifications": bool(calls) and totals_agree,
        "each_turn_matches_its_notifications": len(turns) == len(per_turn)
        and all(
            t["model_calls"] == len(ns)
            and t["input_tokens"] == sum(n["inputTokens"] for n in ns)
            and t["output_tokens"] == sum(n["outputTokens"] for n in ns)
            for t, ns in zip(turns, per_turn, strict=True)
        ),
        "cached_usage_is_present": any(
            n["tokenUsage"]["last"]["cachedInputTokens"] for n in notifications
        ),
        "performance_has_known_usage": data["unknown"] is None,
        "each_turn_has_codex_calls": len(turns) == len(MESSAGES)
        and all(
            t["model_calls"] and t["sources"] and all(s["harness"] == "codex" for s in t["sources"])
            for t in turns
        ),
        "performance_counts_each_call_once": sum(t["model_calls"] or 0 for t in turns)
        == len(calls),
        "input_tokens_include_cached_tokens": sum(t["input_tokens"] or 0 for t in turns)
        == sum(c["input_tokens"] for c in actual),
        "output_tokens_match": sum(t["output_tokens"] or 0 for t in turns)
        == sum(c["output_tokens"] for c in actual),
        "no_call_outside_turns": data["outside_turns"] == 0,
        "seal_intact": seal.verify(folder)["intact"],
    }
    result = {
        "date": date.today().isoformat(),
        "method": "scripts/proof_codex_performance.py",
        "versions": manifest["versions"],
        "messages": MESSAGES,
        "repeat_total_events": len(events) - len(calls),
        "rollout_token_count": events,
        "usage_notifications": notifications,
        "performance": data,
        "checks": checks,
        "pass": all(checks.values()),
    }
    out = ROOT / "proofs/performance/codex-app.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(checks))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

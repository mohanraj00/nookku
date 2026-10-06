"""The trace of SPEC.md section 8: read the app's model sessions, tie each item to a turn, check.

The readers take the copied session files of a test folder. Each reader keeps the messages, the
tool calls and the commands, and counts each other line type. A reader never fails on a line that
it does not know.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .record import VERSION

# The versions that the conformance cases and proofs/trace/ cover.
TESTED = {"claude-code": ("2.1.286",), "codex": ("0.160.0",)}
# Tools that the harness itself gives to the model. They are not tools of the app.
HARNESS_INTERNAL = {"claude-code": {"ToolSearch"}, "codex": set()}
CHECKS = (
    "agent_error",
    "tool_error",
    "command_failed",
    "turn_without_model",
    "item_between_turns",
    "session_inferred",
    "version_untested",
)


def _lines(path: Path) -> Iterator[tuple[int, Any]]:
    """Each JSON line with its line number. Split on \\n only: a text can hold U+2028."""
    for n, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not raw.strip():
            continue
        try:
            yield n, json.loads(raw)
        except ValueError:
            yield n, None


def _time(value: Any) -> float | None:
    """Unix seconds from an ISO 8601 time, for example 2026-10-06T08:17:35.859Z."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _item(harness: str, session: str, file: str, line: int, ts: float | None) -> dict[str, Any]:
    return {
        "v": VERSION,
        "type": "model_item",
        "turn": None,
        "harness": harness,
        "session": session,
        "ts": ts,
        "kind": None,
        "role": None,
        "server": None,
        "name": None,
        "input": None,
        "output": None,
        "error": None,
        "exit_code": None,
        "harness_internal": False,
        "source": {"file": file, "line": line},
    }


def _text(blocks: Any, kinds: tuple[str, ...]) -> str:
    """The text of the content blocks of the given types. Other blocks show as JSON."""
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    parts = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") in kinds and isinstance(b.get("text"), str):
            parts.append(b["text"])
        else:
            parts.append(json.dumps(b, ensure_ascii=False))
    return "\n".join(parts)


def _tool(harness: str, name: str) -> tuple[str | None, str]:
    """The MCP server and the tool name. Claude Code names an MCP tool mcp__<server>__<tool>."""
    if harness == "claude-code" and name.startswith("mcp__"):
        server, _, tool = name[5:].partition("__")
        if server and tool:
            return server, tool
    return None, name


def read_claude(path: Path, session: str, file: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a Claude Code session file. Return the items and the file info."""
    items: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    ignored: Counter[str] = Counter()
    version = None
    for n, row in _lines(path):
        if not isinstance(row, dict):
            ignored["invalid_json"] += 1
            continue
        kind = str(row.get("type"))
        version = version or (row.get("version") if isinstance(row.get("version"), str) else None)
        message = row.get("message")
        if kind not in ("user", "assistant") or not isinstance(message, dict) or row.get("isMeta"):
            if kind not in ("user", "assistant"):
                ignored[kind] += 1
            else:
                ignored[f"{kind}.meta" if row.get("isMeta") else f"{kind}.no_message"] += 1
            continue
        ts = _time(row.get("timestamp"))
        content = message.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for b in blocks:
            btype = b.get("type") if isinstance(b, dict) else None
            if btype == "text" and isinstance(b.get("text"), str):
                it = _item("claude-code", session, file, n, ts)
                it.update(kind="message", role=kind, output=b["text"])
                items.append(it)
            elif btype == "tool_use" and kind == "assistant":
                it = _item("claude-code", session, file, n, ts)
                server, name = _tool("claude-code", str(b.get("name")))
                it.update(kind="tool_call", server=server, name=name, input=b.get("input"))
                it["harness_internal"] = str(b.get("name")) in HARNESS_INTERNAL["claude-code"]
                it["error"] = "no tool_result in the session file"
                calls[str(b.get("id"))] = it
                items.append(it)
            elif btype == "tool_result" and kind == "user":
                call = calls.pop(str(b.get("tool_use_id")), None)
                if call is None:
                    ignored["tool_result.unmatched"] += 1
                    continue
                text = _text(b.get("content"), ("text",))
                call["source"]["result_line"] = n
                call["output"], call["error"] = (None, text) if b.get("is_error") else (text, None)
            else:
                ignored[f"{kind}.{btype}"] += 1
    return items, {"version": version, "ignored": dict(sorted(ignored.items()))}


def _codex_item(it: dict[str, Any], item: dict[str, Any]) -> bool:
    """Fill a trace item from a Codex item. Return False for an item type that the trace skips."""
    kind = item.get("type")
    if kind in ("UserMessage", "AgentMessage"):
        role = "user" if kind == "UserMessage" else "assistant"
        it.update(kind="message", role=role, output=_text(item.get("content"), ("text", "Text")))
    elif kind == "CommandExecution":
        code = item.get("exit_code")
        it.update(kind="command", input=item.get("command"), output=item.get("aggregated_output"))
        it["exit_code"] = code if isinstance(code, int) else None
        if it["exit_code"] is None and item.get("status") != "completed":
            it["error"] = f"status {item.get('status')}"
    elif kind == "DynamicToolCall":
        text = _text(item.get("content_items"), ("inputText",))
        it.update(kind="tool_call", server=item.get("namespace"), name=item.get("tool"))
        it["input"] = item.get("arguments")
        it["output"], it["error"] = (text, None) if item.get("success") else (None, text)
    elif kind == "McpToolCall":
        it.update(kind="tool_call", server=item.get("server"), name=item.get("tool"))
        it["input"] = item.get("arguments")
        result: dict[str, Any] = item["result"] if isinstance(item.get("result"), dict) else {}
        out = _text(result.get("content"), ("text",)) if result else None
        error = item.get("error")
        if isinstance(error, dict):
            it["error"] = str(error.get("message"))
        elif result.get("isError"):
            it["error"] = out
        else:
            it["output"] = out
    else:
        return False
    it["harness_internal"] = it["name"] in HARNESS_INTERNAL["codex"]
    return True


def read_codex(path: Path, session: str, file: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a Codex rollout file. Return the items and the file info."""
    items: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    version = None
    for n, row in _lines(path):
        if not isinstance(row, dict):
            ignored["invalid_json"] += 1
            continue
        payload: dict[str, Any] = row["payload"] if isinstance(row.get("payload"), dict) else {}
        ptype = payload.get("type")
        if row.get("type") == "session_meta" and isinstance(payload.get("cli_version"), str):
            version = payload["cli_version"]
        item = payload.get("item")
        if (
            row.get("type") != "event_msg"
            or ptype != "item_completed"
            or not isinstance(item, dict)
        ):
            ignored[f"{row.get('type')}.{ptype}" if ptype else str(row.get("type"))] += 1
            continue
        at = item.get("completed_at_ms", payload.get("completed_at_ms"))
        ts = at / 1000 if isinstance(at, (int, float)) else _time(row.get("timestamp"))
        it = _item("codex", session, file, n, ts)
        if _codex_item(it, item):
            items.append(it)
        else:
            ignored[f"item_completed.{item.get('type')}"] += 1
    return items, {"version": version, "ignored": dict(sorted(ignored.items()))}


READERS = {"claude-code": read_claude, "codex": read_codex}


def _exchanges(tap: Path) -> list[dict[str, Any]]:
    if not tap.exists():
        return []
    return [r for _, r in _lines(tap) if isinstance(r, dict) and r.get("type") == "exchange"]


def windows(exchanges: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """The time window of each turn. A 0.1 row has no `started`: its window starts at the end of
    the turn before it."""
    out: list[tuple[float, float]] = []
    for r in exchanges:
        end = float(r.get("ts", 0.0))
        started = r.get("started")
        if isinstance(started, (int, float)):
            start = float(started)
        else:
            start = out[-1][1] if out else float("-inf")
        out.append((start, end))
    return out


def assign(items: list[dict[str, Any]], spans: list[tuple[float, float]]) -> None:
    """Set the turn of each item: the 1-based number of the exchange whose window holds it."""
    for it in items:
        ts = it["ts"]
        it["turn"] = next(
            (i for i, (a, b) in enumerate(spans, 1) if ts is not None and a <= ts <= b), None
        )


def _finding(check: str, turn: int | None, detail: str, **where: Any) -> dict[str, Any]:
    return {"check": check, "turn": turn, "detail": detail, **where}


def check(
    exchanges: list[dict[str, Any]],
    spans: list[tuple[float, float]],
    items: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The findings of SPEC.md section 8.4. They do not change the audit's exit code."""
    out: list[dict[str, Any]] = []
    for i, r in enumerate(exchanges, 1):
        if r.get("status") != 200:
            what = "a timeout or a crash" if r.get("status") is None else f"status {r['status']}"
            out.append(_finding("agent_error", i, f"the agent gave {what}"))
    for it in items:
        where = {"harness": it["harness"], "session": it["session"], "source": it["source"]}
        if it["kind"] == "tool_call" and it["error"] is not None:
            detail = f"{it['name']}: {it['error']}"
            out.append(_finding("tool_error", it["turn"], detail, **where))
        if it["kind"] == "command" and (it["exit_code"] not in (0, None) or it["error"]):
            what = f"exit code {it['exit_code']}" if it["exit_code"] is not None else it["error"]
            out.append(_finding("command_failed", it["turn"], what, **where))
        first = spans[0][0] if spans else None
        if it["turn"] is None and first is not None and it["ts"] is not None and it["ts"] >= first:
            out.append(_finding("item_between_turns", None, f"a {it['kind']} item", **where))
    if any(s.get("items") for s in sessions):
        used = {it["turn"] for it in items}
        for i in range(1, len(exchanges) + 1):
            if i not in used:
                out.append(_finding("turn_without_model", i, "no model item in this turn"))
    for s in sessions:
        where = {"harness": s["harness"], "session": s["session"]}
        if s.get("inferred"):
            out.append(_finding("session_inferred", None, "found by directory and time", **where))
        tested = TESTED.get(s["harness"], ())
        if s.get("version") is not None and s["version"] not in tested:
            detail = f"version {s.get('version')}, tested: {', '.join(tested)}"
            out.append(_finding("version_untested", None, detail, **where))
    order = {c: n for n, c in enumerate(CHECKS)}
    big = len(exchanges) + 1
    out.sort(key=lambda f: (order[f["check"]], f["turn"] if f["turn"] is not None else big))
    return out


def build(folder: Path) -> dict[str, Any]:
    """Build trace.jsonl and findings.json in a test folder from its copied session files."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    exchanges = _exchanges(folder / "tap.jsonl")
    spans = windows(exchanges)
    items: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    for s in manifest.get("model_sessions", []):
        info: dict[str, Any] = {
            "harness": s["harness"],
            "session": s["session"],
            "file": s.get("file"),
            "inferred": bool(s.get("inferred")),
            "version": None,
            "items": 0,
            "ignored": {},
        }
        reader = READERS.get(s["harness"])
        if reader is not None and s.get("file") and (folder / s["file"]).exists():
            found, more = reader(folder / s["file"], s["session"], s["file"])
            info.update(more, items=len(found))
            info["version"] = info["version"] or "unknown"
            items += found
        sessions.append(info)
    items.sort(key=lambda it: it["ts"] if it["ts"] is not None else float("inf"))
    assign(items, spans)
    findings = check(exchanges, spans, items, sessions)
    lines = [json.dumps(it, ensure_ascii=False) + "\n" for it in items]
    (folder / "trace.jsonl").write_text("".join(lines), encoding="utf-8")
    counts = Counter(f["check"] for f in findings)
    report = {
        "v": VERSION,
        "test": manifest.get("test"),
        "turns": len(exchanges),
        "items": len(items),
        "sessions": sessions,
        "counts": {c: counts[c] for c in CHECKS},
        "findings": findings,
    }
    text = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    (folder / "findings.json").write_text(text, encoding="utf-8")
    return report


def summary(report: dict[str, Any]) -> str:
    found = ", ".join(f"{n} {c}" for c, n in report["counts"].items() if n) or "no findings"
    return f"Trace: {report['items']} model items in {report['turns']} turns, {found}."

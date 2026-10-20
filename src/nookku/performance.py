"""The time, the model calls and the tokens of each turn of a test (SPEC.md section 8.7).

`build` writes performance.json in a test folder after the trace. The time of a turn comes from
tap.jsonl. The model calls come from the session files of the app and from the trace items of
model_api.jsonl. A value that the records do not hold is `null`, never 0.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from . import model_api
from .record import json_text
from .trace import _exchanges, _lines, _time, _turn, windows

FILE = "performance.json"
VERSION = "0.1"
# A message that Claude Code writes itself, for example after an API error. It is not a call.
SYNTHETIC = "<synthetic>"
# The largest count that a record can give: the largest integer that a JSON number holds exactly.
MOST = 2**53 - 1


def _int(value: Any) -> int | None:
    """A count from a record, or None if the value is not an integer from 0 to MOST."""
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MOST
    return value if ok else None


def _clean(text: str) -> str:
    """`text` with each character that is not printable as an escape, for example a new line as
    `\\u000a`. Thus a record string cannot add a line to the transcript."""
    return "".join(
        c if c.isprintable() else f"\\u{ord(c):04x}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08x}"
        for c in text
    )


def _call(ts: float | None, tokens: tuple[int | None, int | None]) -> dict[str, Any]:
    return {"ts": ts, "input_tokens": tokens[0], "output_tokens": tokens[1]}


def anthropic_tokens(usage: Any) -> tuple[int | None, int | None]:
    """The input and output tokens of an Anthropic `usage`. The input is all input tokens: the
    tokens of `input_tokens`, of `cache_creation_input_tokens` and of `cache_read_input_tokens`."""
    if not isinstance(usage, dict):
        return None, None
    parts = [usage.get(k, 0) for k in ("cache_creation_input_tokens", "cache_read_input_tokens")]
    known = _int(usage.get("input_tokens")) is not None and all(_int(p) is not None for p in parts)
    total = _int(usage["input_tokens"] + sum(parts)) if known else None
    return total, _int(usage.get("output_tokens"))


def openai_tokens(usage: Any) -> tuple[int | None, int | None]:
    """The input and output tokens of an OpenAI `usage`: `prompt_tokens` and `completion_tokens`
    (Chat Completions), else `input_tokens` and `output_tokens`. Both include the cached tokens."""
    if not isinstance(usage, dict):
        return None, None
    given = _int(usage.get("prompt_tokens")), _int(usage.get("completion_tokens"))
    if given == (None, None):
        given = _int(usage.get("input_tokens")), _int(usage.get("output_tokens"))
    return given


def read_claude_calls(path: Path) -> list[dict[str, Any]]:
    """The model calls of a Claude Code session file. Claude Code writes one `assistant` line for
    each content block of a message, each with the same `message.id` and `usage`. Thus one id is
    one call. Its time is the time of its first line. Its usage is the usage of its last line."""
    calls: dict[str, dict[str, Any]] = {}
    for n, row in _lines(path, Counter()):
        if not isinstance(row, dict) or row.get("type") != "assistant" or row.get("isMeta"):
            continue
        message = row.get("message")
        if not isinstance(message, dict) or message.get("model") == SYNTHETIC:
            continue
        key = next(
            (str(v) for v in (message.get("id"), row.get("requestId")) if isinstance(v, str) and v),
            f"line {n}",
        )
        tokens = anthropic_tokens(message.get("usage"))
        if key in calls:
            calls[key].update(input_tokens=tokens[0], output_tokens=tokens[1])
        else:
            calls[key] = _call(_time(row.get("timestamp")), tokens)
    return list(calls.values())


def read_codex_calls(path: Path) -> list[dict[str, Any]]:
    """The model calls of a Codex rollout file: one call for each `token_count` event with
    `info.last_token_usage`, the usage of the last call. An event with the same
    `total_token_usage` as the event before it is a repeat, not a call. `input_tokens` includes
    the cached tokens."""
    calls = []
    total: Any = None
    for _, row in _lines(path, Counter()):
        if not isinstance(row, dict) or row.get("type") != "event_msg":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        last = info.get("last_token_usage") if isinstance(info, dict) else None
        now = info.get("total_token_usage") if isinstance(info, dict) else None
        if not isinstance(last, dict) or (now is not None and now == total):
            continue
        total = now
        tokens = _int(last.get("input_tokens")), _int(last.get("output_tokens"))
        calls.append(_call(_time(row.get("timestamp")), tokens))
    return calls


READERS = {"claude-code": read_claude_calls, "codex": read_codex_calls}


def _direct_calls(items: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """The direct model calls of the app: one `model_api` assistant item for each call. A cut
    result can hold the usage of the start of the response only, so its usage is not known."""
    out = []
    for it in items:
        if it.get("harness") != "model_api" or it.get("role") != "assistant":
            continue
        info = it["input"] if isinstance(it.get("input"), dict) else {}
        read = anthropic_tokens if it.get("session") == "anthropic" else openai_tokens
        tokens = (None, None) if "cut" in info else read(info.get("usage"))
        out.append((str(it.get("session")), {**_call(it.get("ts"), tokens), "turn": it["turn"]}))
    return out


def _answered(items: list[dict[str, Any]], harness: str, session: str) -> bool:
    """True if the trace has an item of the model of a session: a reply, a tool call or a
    command. Then the model made at least 1 call."""
    return any(
        it.get("harness") == harness
        and it.get("session") == session
        and (it.get("role") == "assistant" or it.get("kind") in ("tool_call", "command"))
        for it in items
    )


def _sum(calls: list[dict[str, Any]], key: str) -> int | None:
    values = [c[key] for c in calls]
    return None if any(v is None for v in values) else _int(sum(values))


def _totals(calls: list[dict[str, Any]]) -> dict[str, Any]:
    missing = sum(1 for c in calls if c["input_tokens"] is None or c["output_tokens"] is None)
    return {
        "model_calls": len(calls),
        "input_tokens": _sum(calls, "input_tokens"),
        "output_tokens": _sum(calls, "output_tokens"),
        "no_usage": missing,
    }


def _unknown(folder: Path, manifest: dict[str, Any]) -> str | None:
    """Why the records cannot give each model call of the app, or None if they can."""
    sessions = manifest.get("model_sessions") or []
    for s in sessions:
        file = s.get("file")
        if s.get("harness") not in READERS or not file or not (folder / file).is_file():
            name = _clean(f"{s.get('session')} ({s.get('harness')})")
            return f"the model session {name} has no session file"
    egress = manifest.get("egress")
    answer = egress.get("answer") if isinstance(egress, dict) else None
    if not isinstance(answer, dict) or not isinstance(answer.get("model_apis"), list):
        # The model API proxies start only from the egress answer (SPEC.md section 7.11).
        return "the test has no egress answer, so no proxy recorded the direct model calls"
    found = {s.get("harness") for s in sessions}
    calls_path = folder / model_api.FILE
    if not sessions and not calls_path.exists():
        return f"the test has no model session and no {model_api.FILE}"
    if calls_path.exists() and not (folder / "trace.jsonl").exists():
        return f"the test folder has {model_api.FILE} and no trace.jsonl"
    if calls_path.exists():
        harness_calls: Counter[str] = Counter()
        for _, row in _lines(calls_path, Counter()):
            if isinstance(row, dict) and row.get("type") == "call" and row.get("harness"):
                harness_calls[str(row["harness"])] += 1
        for harness, n in sorted(harness_calls.items()):
            if harness not in found:
                calls = "1 call" if n == 1 else f"{n} calls"
                return f"{model_api.FILE} has {calls} of {harness}, and no session file of it"
    return None


def summarize(folder: Path) -> dict[str, Any]:
    """The summary of each turn of a test folder, from tap.jsonl, the manifest, the session files
    and trace.jsonl. An invalid tap.jsonl raises a RecordError, as in the trace."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    exchanges = _exchanges(folder / "tap.jsonl")
    spans = windows(exchanges)
    trace = folder / "trace.jsonl"
    rows = _lines(trace, Counter()) if trace.exists() else iter(())
    items = [r for _, r in rows if isinstance(r, dict)]
    unknown = _unknown(folder, manifest)
    calls: list[tuple[str, str, dict[str, Any]]] = []
    if unknown is None:
        for s in manifest.get("model_sessions") or []:
            found = READERS[s["harness"]](folder / s["file"])
            if not found and _answered(items, s["harness"], s["session"]):
                name = _clean(str(s["session"]))
                unknown = f"the session file of {name} has model items and no model call"
                calls = []
                break
            for c in found:
                calls.append((s["harness"], s["session"], {**c, "turn": _turn(c["ts"], spans)}))
        else:
            calls += [("model_api", api, c) for api, c in _direct_calls(items)]
    outside = None if unknown is not None else sum(1 for _, _, c in calls if c["turn"] is None)
    turns = []
    for n, ex in enumerate(exchanges, 1):
        started = ex.get("started")
        seconds = None
        if isinstance(started, (int, float)) and isinstance(ex.get("ts"), (int, float)):
            seconds = round(ex["ts"] - started, 3)
        row: dict[str, Any] = {"turn": n, "seconds": seconds}
        if unknown is not None:
            row.update(model_calls=None, input_tokens=None, output_tokens=None, no_usage=None)
            row["sources"] = None
        else:
            mine = [(h, s, c) for h, s, c in calls if c["turn"] == n]
            row.update(_totals([c for _, _, c in mine]))
            keys = sorted({(h, s) for h, s, _ in mine})
            row["sources"] = [
                {"harness": h, "session": s, **_totals([c for x, y, c in mine if (x, y) == (h, s)])}
                for h, s in keys
            ]
        turns.append(row)
    return {
        "v": VERSION,
        "test": manifest.get("test"),
        "unknown": unknown,
        "outside_turns": outside,
        "turns": turns,
    }


def build(folder: Path) -> dict[str, Any]:
    """Write performance.json in a test folder. Return its data."""
    data = summarize(folder)
    (folder / FILE).write_text(json_text(data, indent=1) + "\n", encoding="utf-8")
    return data


def _number(value: Any) -> bool:
    return _int(value) is not None


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.isprintable()


def _known(row: Any) -> bool:
    """True if a turn or a source has its counts, and each token total is a count or null."""
    return (
        isinstance(row, dict)
        and _number(row.get("model_calls"))
        and _number(row.get("no_usage"))
        and all(row.get(k) is None or _number(row[k]) for k in ("input_tokens", "output_tokens"))
    )


def _valid(row: Any, n: int, unknown: Any) -> bool:
    """True if `row` is a valid turn `n` of performance.json."""
    if not isinstance(row, dict) or row.get("turn") != n:
        return False
    seconds = row.get("seconds")
    if seconds is not None and (not isinstance(seconds, (int, float)) or seconds < 0):
        return False
    if unknown is not None:
        counts = ("model_calls", "input_tokens", "output_tokens", "no_usage", "sources")
        return _text(unknown) and all(row.get(k) is None for k in counts)
    sources = row.get("sources")
    return (
        _known(row)
        and isinstance(sources, list)
        and all(_known(x) and _text(x.get("harness")) and _text(x.get("session")) for x in sources)
    )


def read(folder: Path, count: int) -> tuple[dict[str, Any] | None, str | None]:
    """The data of performance.json for a test of `count` turns, or None and the problem."""
    try:
        data = json.loads((folder / FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"the test folder has no {FILE}"
    except (OSError, ValueError) as e:
        return None, f"{FILE} cannot be read ({e})"
    turns = data.get("turns") if isinstance(data, dict) else None
    if not isinstance(turns, list) or len(turns) != count:
        return None, f"{FILE} does not have {count} turns"
    outside = data.get("outside_turns")
    if not (outside is None if data.get("unknown") is not None else _number(outside)):
        return None, f"outside_turns of {FILE} is not valid"
    for n, row in enumerate(turns, 1):
        if not _valid(row, n, data.get("unknown")):
            return None, f"turn {n} of {FILE} is not valid"
    return data, None


def _value(value: Any, unit: str) -> str:
    return f"{unit} not known" if value is None else f"{value} {unit}"


def line(data: dict[str, Any], n: int) -> str:
    """The lines of turn `n` in the transcript, for example `4.212 seconds, 3 model calls, 1520
    input tokens, 210 output tokens`, then one line for each source, then the output tokens of
    the model sessions together. Each record string is escaped with _clean."""
    turn, unknown = data["turns"][n - 1], data["unknown"]
    parts = [_value(turn["seconds"], "seconds")]
    if unknown is not None:
        return f"{parts[0]}. The model calls and the tokens are not known: {_clean(unknown)}."
    parts.append(f"{turn['model_calls']} model calls")
    parts.append(_value(turn["input_tokens"], "input tokens"))
    parts.append(_value(turn["output_tokens"], "output tokens"))
    text = ", ".join(parts)
    if turn["no_usage"]:
        text += f" ({turn['no_usage']} of {turn['model_calls']} model calls have no usage)"
    for s in turn["sources"]:
        text += (
            f"\n  - {_clean(s['harness'])} {_clean(s['session'])}: {s['model_calls']} model "
            f"calls, {_value(s['input_tokens'], 'input tokens')}, "
            f"{_value(s['output_tokens'], 'output tokens')}"
        )
    sessions = [s for s in turn["sources"] if s["harness"] in READERS]
    total = _sum(sessions, "output_tokens")
    return text + f"\n  - model sessions together: {_value(total, 'output tokens')}"

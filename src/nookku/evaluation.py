"""The evaluation of SPEC.md section 9: the transcript with the trace, and the prompt.

At the end of a test, the relay gives the harness model the evaluation prompt. The model reads the
transcript with the trace, the findings and the audit, checks the app, and writes report.md.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Any

from . import bridge, seal
from .record import RecordError, read_rows

REPORT = "report.md"
# A longer text shows its start, and the trace line holds all of it.
CUT = 2000
# In compact mode, a shorter text always shows: its reference is almost as long as the text.
COMPACT_MIN = 200


def enabled(root: Path) -> bool:
    """The `evaluate` key of the configuration. It is true if it is not there."""
    try:
        conf = json.loads((root / bridge.STATE_DIR / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return conf.get("evaluate", True) is not False


def pending(root: Path) -> Path | None:
    """The latest test, if it ended, has no report and the configuration lets it be evaluated."""
    if not enabled(root) or bridge.current(root) is not None:
        return None
    folder = bridge.latest_test(root)
    if folder is None or (folder / REPORT).exists():
        return None
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return folder if manifest.get("ended") is not None else None


def _items(path: Path) -> list[dict[str, Any]]:
    """The items of trace.jsonl, or none if the file does not exist. Split on \\n only: a text can
    hold U+2028. A line that is not a JSON object raises a RecordError that names the line."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except UnicodeDecodeError:
        raise RecordError("record_invalid", path, "not UTF-8") from None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out = []
    for n, raw in enumerate(lines, 1):
        try:
            item = json.loads(raw)
        except ValueError:
            raise RecordError("record_invalid", path, f"line {n}: not JSON") from None
        if not isinstance(item, dict):
            raise RecordError("record_invalid", path, f"line {n}: not a JSON object")
        out.append(item)
    return out


def _cut(text: str, line: int) -> str:
    if len(text) <= CUT:
        return text
    return f"{text[:CUT]}\n(cut at {CUT} characters: the full text is in trace.jsonl:{line})"


def _value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def decision(answer: dict[str, Any]) -> str:
    """One answer of a call to the Decisions API on one line, for example
    `department: billing (0.95), confidence 0.93`. For a choice, the number in brackets is the
    probability of the chosen value."""
    name = answer.get("name") if answer.get("name") is not None else "(no name)"
    kind, value = answer.get("type"), answer.get("value")
    if kind == "refusal":
        return f"{name}: refusal (the model did not answer this question)"
    if kind == "predicate":
        out = f"{name}: probability {_value(value)}"
    elif kind == "score":
        out = f"{name}: score {_value(value)}"
    else:
        out = f"{name}: {_value(value)}"
        for p in answer.get("probabilities") or []:
            same = isinstance(p, dict) and p.get("value") == value
            if same and type(p.get("value")) is type(value):
                out += f" ({_value(p.get('probability'))})"
                break
    if answer.get("confidence") is not None:
        out += f", confidence {_value(answer['confidence'])}"
    return out


def _asked(asked: Any) -> str:
    """The questions and the images of a request to the Decisions API, one on each line."""
    if not isinstance(asked, dict):
        return ""
    out = ""
    for q in asked.get("questions") or []:
        options = q.get("options")
        shown = f": {', '.join(_value(o) for o in options)}" if options else ""
        out += f"question {q.get('name') or '(no name)'} ({q.get('type')}){shown}\n"
    for i in asked.get("images") or []:
        size = f"{i['size']} bytes" if i.get("size") is not None else "not base64"
        out += f"image: {i.get('media_type')}, {size}, sha256 {i.get('sha256')}\n"
    return out


def render_item(it: dict[str, Any], line: int) -> str:
    """One trace item, with its line in trace.jsonl as its evidence."""
    head = f"[trace.jsonl:{line}] {it['harness']} {it['kind']}"
    if it["kind"] == "message":
        out = f"{head}, {it['role']}:\n{_cut(it['output'] or '', line)}\n"
        if it["harness"] == "model_api" and it["role"] == "user":
            out += _asked(it["input"])
        if it["harness"] == "model_api" and it["role"] == "assistant":
            status = it["exit_code"] if it["exit_code"] is not None else "no answer"
            out = f"{head}, assistant: {it['session']} {it['input']['path']}, status {status}:\n"
            answers = it["input"].get("answers")
            if answers:
                out += "".join(f"{decision(a)}\n" for a in answers if isinstance(a, dict))
            else:
                out += f"{_cut(it['output'] or '', line)}\n"
        if it.get("error") is not None:
            out += f"error:\n{_cut(it['error'], line)}\n"
        return out
    if it["kind"] == "http":
        status = it["exit_code"] if it["exit_code"] is not None else "no answer"
        out = f"{head}: backend {it['session']}: {it['name']}, status {status}\n"
        out += f"request: {_cut(_value(it['input']), line)}\n"
        if it["error"] is not None:
            return out + f"error:\n{_cut(it['error'], line)}\n"
        return out + f"response:\n{_cut(it['output'] or '', line)}\n"
    if it["kind"] in ("span", "log"):
        who = it["service"] or "a service"
        out = f"{head}: {who} {it['kind']} {it['name'] or '(no name)'}\n"
        out += f"attributes: {_cut(_value(it['input']), line)}\n"
        if it["output"] is not None:
            out += f"body:\n{_cut(it['output'], line)}\n"
        if it["error"] is not None:
            out += f"error:\n{_cut(it['error'], line)}\n"
        return out
    if it["kind"] == "command":
        out = f"{head}: {_value(it['input'])}, exit code {it['exit_code']}\n"
        if it["error"]:
            out += f"error: {it['error']}\n"
        return out + f"output:\n{_cut(it['output'] or '', line)}\n"
    name = f"{it['server']}.{it['name']}" if it["server"] else str(it["name"])
    internal = " (a harness tool)" if it["harness_internal"] else ""
    out = f"{head}: {name}{internal}\ninput: {_value(it['input'])}\n"
    if it["error"] is not None:
        return out + f"error:\n{_cut(it['error'], line)}\n"
    return out + f"result:\n{_cut(it['output'] or '', line)}\n"


def _finding(f: dict[str, Any], lines: dict[tuple[str, int], int]) -> str:
    where = ""
    source = f.get("source")
    if isinstance(source, dict):
        n = lines.get((source["file"], source["line"]))
        where = f" [trace.jsonl:{n}]" if n else f" [{source['file']}:{source['line']}]"
    elif f.get("harness"):
        where = f" ({f['harness']} session {f['session']})"
    return f"- {f['check']}: {f['detail']}{where}\n"


def _loose(findings: list[dict[str, Any]], lines: dict[tuple[str, int], int]) -> str:
    """The lines of the findings with no turn. The version_untested findings of one harness and
    one version show as one line with the count of sessions. findings.json keeps each one."""
    rows: list[str | tuple[str, str]] = []
    sessions: Counter[tuple[str, str]] = Counter()
    for f in findings:
        if f["check"] != "version_untested":
            rows.append(_finding(f, lines))
            continue
        key = (str(f.get("harness")), str(f["detail"]))
        if key not in sessions:
            rows.append(key)
        sessions[key] += 1
    out = []
    for row in rows:
        if isinstance(row, tuple):
            n = sessions[row]
            row = f"- version_untested: {row[1]} ({row[0]}, {n} session{'s' if n > 1 else ''})\n"
        out.append(row)
    return "".join(out)


def _reference(text: str, line: int) -> str:
    digest = hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()
    return (
        f"(compact: the same text as [trace.jsonl:{line}], sha256 {digest}, {len(text)} characters)"
    )


def _otel(it: dict[str, Any]) -> bool:
    return it["kind"] in ("span", "log") and isinstance(it["input"], dict)


def _long(value: Any) -> bool:
    return isinstance(value, str) and len(value) >= COMPACT_MIN


def _compact(order: list[tuple[int, dict[str, Any]]]) -> dict[int, dict[str, Any]]:
    """The shown form of each item in compact mode (#152), by its line in trace.jsonl. `order` is
    the order of the transcript.

    - An attribute of an OTel span or log that has the same text as a session item of the same
      turn shows a reference to that item.
    - A user message or an OTel attribute with a text that an earlier item showed in full shows
      a reference to that item, with the sha256 and the length of the text.

    A text shorter than COMPACT_MIN characters always shows. No other field changes."""
    session: dict[int, dict[str, int]] = {}
    for k, it in order:
        if it["turn"] is not None and str(it["source"]["file"]).startswith("sessions/"):
            for text in (it["output"], it["error"]):
                if _long(text):
                    session.setdefault(it["turn"], {}).setdefault(text, k)
    same_turn = {k: session.get(it["turn"], {}) for k, it in order}
    first: dict[str, int] = {}
    for k, it in order:
        if it["kind"] == "message" and it["role"] == "user" and _long(it["output"]):
            first.setdefault(it["output"], k)
        if _otel(it):
            for value in it["input"].values():
                if _long(value) and value not in same_turn[k]:
                    first.setdefault(value, k)
    shown: dict[int, dict[str, Any]] = {}
    for k, it in order:
        out = it
        user = it["kind"] == "message" and it["role"] == "user" and _long(it["output"])
        if user and first[it["output"]] != k:
            out = {**it, "output": _reference(it["output"], first[it["output"]])}
        if _otel(it):
            attributes = {}
            for key, value in it["input"].items():
                if _long(value) and value in same_turn[k]:
                    value = _reference(value, first.get(value, same_turn[k][value]))
                elif _long(value) and first[value] != k:
                    value = _reference(value, first[value])
                attributes[key] = value
            out = {**it, "input": attributes}
        shown[k] = out
    return shown


def transcript(folder: Path, compact: bool = False) -> str:
    """The exact conversation of a test as the agent received and sent it, with the trace.

    If tap.jsonl or trace.jsonl is invalid, the first line says so, and the transcript shows no
    turn: a changed text must not look exact. With compact, a repeated text of a model item shows
    one time, and then a reference to it (_compact).
    """
    try:
        tap = read_rows("tap", folder / "tap.jsonl", missing_ok=True)
        items = _items(folder / "trace.jsonl")
    except RecordError as e:
        return (
            f"Record: INVALID. {e}. Do not trust these records. This transcript shows no turn.\n"
            f"{seal.summary(seal.verify(folder))}\n"
        )
    exchanges = [r for _, r in tap if r["type"] == "exchange"]
    try:
        findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))["findings"]
    except (OSError, ValueError, KeyError):
        findings = []
    lines = {(it["source"]["file"], it["source"]["line"]): n for n, it in enumerate(items, 1)}
    out = [
        seal.summary(seal.verify(folder)) + "\n",
        f"nookku transcript with trace, test {folder.name}: {len(exchanges)} turns, "
        f"{len(items)} model items. The tester and agent blocks are exact: they come from "
        "tap.jsonl. A model item comes from the app's own model sessions, or from the "
        "OpenTelemetry spans and logs of the app (otel.jsonl), or from the calls of the app to "
        "its backends (backend.jsonl), or from its direct calls to a model API "
        "(model_api.jsonl). [trace.jsonl:N] is "
        f"line N of {folder / 'trace.jsonl'}.\n",
    ]
    if compact:
        out.append(
            f"Compact: a text of {COMPACT_MIN} or more characters in a user message or in an "
            "OpenTelemetry attribute shows one time. After that, it shows as (compact: the same "
            "text as [trace.jsonl:N], sha256 H, L characters). An OpenTelemetry attribute with "
            "the text of a session item of the same turn also shows in this form.\n"
        )
    loose = [f for f in findings if f["turn"] is None]
    if loose:
        out.append("\nFindings with no turn:\n" + _loose(loose, lines))
    first = [n for n, it in enumerate(items, 1) if it["turn"] is None]
    turns = range(1, len(exchanges) + 1)
    order = [(k, it) for n in turns for k, it in enumerate(items, 1) if it["turn"] == n]
    order += [(k, items[k - 1]) for k in first]
    shown = _compact(order) if compact else dict(order)
    for n, ex in enumerate(exchanges, 1):
        out.append(f"\n════ turn {n} ════\n──── tester → agent ────\n{ex.get('input', '')}\n")
        mine = [k for k, it in enumerate(items, 1) if it["turn"] == n]
        if mine:
            out.append("──── model items ────\n" + "".join(render_item(shown[k], k) for k in mine))
        found = [f for f in findings if f["turn"] == n]
        if found:
            out.append("──── findings ────\n" + "".join(_finding(f, lines) for f in found))
        reply = ex.get("reply")
        if reply is None:
            reply = f"(no reply: status {ex.get('status')}, {ex.get('error', 'no error text')})"
        out.append(f"──── agent → tester ────\n{reply}\n")
    if first:
        rows = "".join(render_item(shown[k], k) for k in first)
        out.append(f"\n════ model items outside each turn ════\n{rows}")
    return "".join(out)


def prompt(folder: Path) -> str:
    """The evaluation prompt for a test folder (src/nookku/evaluate.md)."""
    text = resources.files("nookku").joinpath("evaluate.md").read_text(encoding="utf-8")
    text = text.replace("{test}", folder.name).replace("{folder}", str(folder))
    return scripted_note(folder) + text


def scripted_note(folder: Path) -> str:
    """The note at the top of the evaluation prompt of a scripted test, or "" (SPEC.md 9.2)."""
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    found = manifest.get("script") if isinstance(manifest, dict) else None
    if not isinstance(found, dict):
        return ""
    name = manifest.get("entry_name") or "the default entry"
    entry = json.dumps(manifest.get("entry"), ensure_ascii=False)
    return (
        f"This test is scripted. Each message came byte for byte from the script file "
        f"{found.get('source')} (copy: {found.get('file')}, SHA-256 {found.get('sha256')}), not "
        f"from a tester. The entry is {name}: {entry}. If this entry replays a recording, the "
        "replies do not come from a model: then judge the app and the transport, not the "
        "model.\n\n"
    )

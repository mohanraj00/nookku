"""The evaluation of SPEC.md section 9: the transcript with the trace, and the prompt.

At the end of a test, the relay gives the harness model the evaluation prompt. The model reads the
transcript with the trace, the findings and the audit, checks the app, and writes report.md.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from . import bridge, seal

REPORT = "report.md"
# A longer text shows its start, and the trace line holds all of it.
CUT = 2000


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


def _rows(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for x in text.split("\n"):
        if x:
            try:
                out.append(json.loads(x))
            except ValueError:
                continue
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


def transcript(folder: Path) -> str:
    """The exact conversation of a test as the agent received and sent it, with the trace."""
    exchanges = [r for r in _rows(folder / "tap.jsonl") if r.get("type") == "exchange"]
    items = _rows(folder / "trace.jsonl")
    try:
        findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))["findings"]
    except (OSError, ValueError, KeyError):
        findings = []
    lines = {(it["source"]["file"], it["source"]["line"]): n for n, it in enumerate(items, 1)}
    out = [
        seal.summary(seal.verify(folder)) + "\n",
        f"verbatim-relay transcript with trace, test {folder.name}: {len(exchanges)} turns, "
        f"{len(items)} model items. The tester and agent blocks are exact: they come from "
        "tap.jsonl. A model item comes from the app's own model sessions, or from the "
        "OpenTelemetry spans and logs of the app (otel.jsonl), or from the calls of the app to "
        "its backends (backend.jsonl), or from its direct calls to a model API "
        "(model_api.jsonl). [trace.jsonl:N] is "
        f"line N of {folder / 'trace.jsonl'}.\n",
    ]
    loose = [f for f in findings if f["turn"] is None]
    if loose:
        out.append("\nFindings with no turn:\n" + "".join(_finding(f, lines) for f in loose))
    first = [n for n, it in enumerate(items, 1) if it["turn"] is None]
    for n, ex in enumerate(exchanges, 1):
        out.append(f"\n════ turn {n} ════\n──── tester → agent ────\n{ex.get('input', '')}\n")
        mine = [(k, it) for k, it in enumerate(items, 1) if it["turn"] == n]
        if mine:
            out.append("──── model items ────\n" + "".join(render_item(it, k) for k, it in mine))
        found = [f for f in findings if f["turn"] == n]
        if found:
            out.append("──── findings ────\n" + "".join(_finding(f, lines) for f in found))
        reply = ex.get("reply")
        if reply is None:
            reply = f"(no reply: status {ex.get('status')}, {ex.get('error', 'no error text')})"
        out.append(f"──── agent → tester ────\n{reply}\n")
    if first:
        rows = "".join(render_item(items[k - 1], k) for k in first)
        out.append(f"\n════ model items outside each turn ════\n{rows}")
    return "".join(out)


def prompt(folder: Path) -> str:
    """The evaluation prompt for a test folder (src/verbatim_relay/evaluate.md)."""
    text = resources.files("verbatim_relay").joinpath("evaluate.md").read_text(encoding="utf-8")
    return text.replace("{test}", folder.name).replace("{folder}", str(folder))

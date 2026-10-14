"""Replay a saved script, and show the replies that changed (#351, SPEC.md section 7.10, "Replay").

`nookku replay` runs a script with the code of `nookku run --script`. Then it compares the new
test with the source test of the script, turn by turn. The diff uses the tap `reply` of each turn,
not the relay `shown`, because the tap records what the agent really sent (SPEC.md section 2.1).

The chat page server serves the same diff at `api/diff/<test id>/<test id>`, for `diff.html`. It
reads only the files of the 2 test folders, and it changes no file.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from nookku import dashboard
from nookku.audit import _anchors
from nookku.record import Exchange, RecordError, read_tap, turns

# The path of the page request after the token: api/diff/<test id>/<test id>.
ROUTE = "api/diff"
# A word or a run of white space. The words of a reply joined again give the reply, byte for byte.
WORD = re.compile(r"\s+|\S+")
# In the terminal, a run of equal words longer than this shows only its first and last words.
CONTEXT = 6
# The most words and runs of white space on one side of the part between the equal start and the
# equal end of 2 replies that the matcher compares. The time of the matcher grows fast with the
# count, so a larger part gets one delete and one insert. Thus a long reply cannot stop the replay
# or the page server.
MAX_TOKENS = 2000


class ReplayError(ValueError):
    """The replay cannot find the test to compare with."""


def replies(folder: Path) -> list[tuple[str, str | None]]:
    """The said text and the tap reply of each turn of a test. A turn with no tap exchange, or an
    exchange with a null reply (an agent error), has the reply None. The turns pair with the
    exchanges as in step 1 of the audit (SPEC.md section 3.2). Raise RecordError if a record is
    not valid."""
    found = turns(folder / "relay.jsonl", missing_ok=True)
    tap = [r for r in read_tap(folder / "tap.jsonl", missing_ok=True) if isinstance(r, Exchange)]
    pairs = dict(_anchors(found, tap))
    return [(t.said, tap[pairs[i]].reply if i in pairs else None) for i, t in enumerate(found)]


def words(old: str, new: str) -> list[list[str]]:
    """The word diff of 2 texts: a list of [op, text], with op "equal", "delete" or "insert". The
    equal and delete parts give the old text, and the equal and insert parts give the new text."""
    a, b = WORD.findall(old), WORD.findall(new)
    parts: list[list[str]] = []

    def add(op: str, tokens: list[str]) -> None:
        if not tokens:
            return
        if parts and parts[-1][0] == op:
            parts[-1][1] += "".join(tokens)
        else:
            parts.append([op, "".join(tokens)])

    # The equal start and the equal end need no matcher.
    start = 0
    while start < min(len(a), len(b)) and a[start] == b[start]:
        start += 1
    end = 0
    while end < min(len(a), len(b)) - start and a[-1 - end] == b[-1 - end]:
        end += 1
    mid_a, mid_b = a[start : len(a) - end], b[start : len(b) - end]
    add("equal", a[:start])
    if max(len(mid_a), len(mid_b)) > MAX_TOKENS:
        add("delete", mid_a)
        add("insert", mid_b)
    else:
        matcher = difflib.SequenceMatcher(None, mid_a, mid_b, autojunk=False)
        for op, i, j, k, m in matcher.get_opcodes():
            if op == "equal":
                add("equal", mid_a[i:j])
            else:
                add("delete", mid_a[i:j])
                add("insert", mid_b[k:m])
    add("equal", a[len(a) - end :])
    return parts


def diff(root: Path, old: Path, new: Path) -> dict[str, Any]:
    """The diff of 2 tests, turn by turn: turn n of the old test with turn n of the new test."""
    running = dashboard.running_id(root)
    result: dict[str, Any] = {
        "old": dashboard.row(old, running),
        "new": dashboard.row(new, running),
        "turns": [],
        "changed": None,
        "error": None,
    }
    try:
        sides = replies(old), replies(new)
    except RecordError as e:
        result["error"] = f"nookku: {e}"
        return result
    rows = []
    for n in range(max(len(sides[0]), len(sides[1]))):
        said_a, reply_a = sides[0][n] if n < len(sides[0]) else (None, None)
        said_b, reply_b = sides[1][n] if n < len(sides[1]) else (None, None)
        rows.append(
            {
                "n": n + 1,
                "said_old": said_a,
                "said_new": said_b,
                "reply_old": reply_a,
                "reply_new": reply_b,
                # A turn that only one test has is a changed turn.
                "changed": said_a is None or said_b is None or reply_a != reply_b,
                "said_changed": said_a != said_b,
                "words": words(reply_a or "", reply_b or ""),
            }
        )
    result["turns"] = rows
    result["changed"] = sum(r["changed"] for r in rows)
    return result


def answer(root: Path, rest: str) -> tuple[int, dict[str, Any]]:
    """The answer to `api/diff/<test id>/<test id>`: the status and the data. Each id must be the
    name of a test folder (`dashboard.find`), so a path from the request never leaves the test
    folders."""
    parts = rest[len(ROUTE) + 1 :].split("/") if rest.startswith(ROUTE + "/") else []
    if len(parts) != 2:
        return 404, {"error": "nookku page: not found"}
    folders = [dashboard.find(root, unquote(p)) for p in parts]
    if folders[0] is None or folders[1] is None:
        return 404, {"error": "nookku: no test has this id."}
    return 200, diff(root, folders[0], folders[1])


def base(root: Path, script_path: Path, test: str | None) -> Path | None:
    """The test to compare with: the test `test`, else the test whose id is the name of the
    script file, as `nookku script save` names it (SPEC.md section 7.10), else None. Raise
    ReplayError if `test` names no test."""
    if test is not None:
        folder = dashboard.find(root, test)
        if folder is None:
            raise ReplayError(f"no test has the id {test!r}. Give a folder name of .nookku/tests/.")
        return folder
    return dashboard.find(root, script_path.stem)


def _marked(parts: list[list[str]]) -> str:
    """The word diff as one line of text: [-old words-] and {+new words+}. A long run of equal
    words shows only its ends."""
    out = []
    for op, text in parts:
        if op == "delete":
            out.append(f"[-{text}-]")
        elif op == "insert":
            out.append(f"{{+{text}+}}")
        else:
            tokens = WORD.findall(text)
            if len(tokens) > 4 * CONTEXT:
                text = "".join(tokens[: 2 * CONTEXT]) + " ... " + "".join(tokens[-2 * CONTEXT :])
            out.append(text)
    # repr shows a line feed and each other control character as an escape, on one line.
    return repr("".join(out))[1:-1]


def report(root: Path, old: Path | None, new: Path) -> tuple[list[str], dict[str, Any]]:
    """The lines and the JSON part of the replay, after the run of the script."""
    if old is None:
        text = (
            "Replay: no test to compare with. The script name is not a test id. "
            "Give one with --base TEST."
        )
        return [text], {"diff": None}
    if old == new:
        return ["Replay: the new test is the test to compare with."], {"diff": None}
    result = diff(root, old, new)
    if result["error"]:
        return [f"Replay: no diff. {result['error']}"], {"diff": result}
    lines = [
        f"Replay of test {old.name}: {result['changed']} of {len(result['turns'])} turns changed."
    ]
    for row in result["turns"]:
        if not row["changed"]:
            continue
        if row["said_old"] is None:
            lines.append(f"Turn {row['n']}: only in the new test.")
        elif row["said_new"] is None:
            lines.append(f"Turn {row['n']}: only in test {old.name}.")
        else:
            if row["said_changed"]:
                lines.append(f"Turn {row['n']}: the message is not the same.")
            # The word diff shows no reply as empty text, so name the test with no reply here.
            for test, reply in ((old.name, row["reply_old"]), (new.name, row["reply_new"])):
                if reply is None:
                    lines.append(f"Turn {row['n']}: test {test} has no reply in the tap record.")
        lines.append(f"Turn {row['n']} reply: {_marked(row['words'])}")
    lines.append(
        f"Diff page: run nookku page, open the dashboard, and select tests {old.name} "
        f"and {new.name}."
    )
    return lines, {"diff": result}

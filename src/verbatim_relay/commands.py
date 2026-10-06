"""The shell command check of the deny rules in SPEC.md section 5.

A shell command passes the check if each of its commands is a read program and each output
redirect writes /dev/null or report.md. All other input fails, also input that the check cannot
parse, so the deny fails closed. The plugin has the same check in plugins/claude-code/hooks/core.ts.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from typing import Any

SHELL_TOOLS = {"Bash", "shell", "local_shell", "exec_command"}
SHELLS = {"bash", "sh", "zsh"}
OPS = set("();<>|&")
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# A sed command that writes a file (w, W) or runs a command (e).
SED_WRITE = re.compile(r"(^|[0-9$/;}\s])[wWe](\s|$)")
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprint0"}
FIND_ACTIONS |= {"-fprintf"}
VIEWS = {"transcript", "trace", "audit", "check", "status", "view"}
# The file types of an entry argument that names a program file (SPEC.md section 5).
CODE = {".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".rb"}


def _short(args: list[str], letter: str) -> bool:
    """True if a short option group, for example -nE, holds the letter."""
    return any(a.startswith("-") and not a.startswith("--") and letter in a[1:] for a in args)


def _sed(args: list[str]) -> bool:
    quiet = _short(args, "n") or "--quiet" in args or "--silent" in args
    edit = _short(args, "i") or any(a.startswith("--in-place") for a in args)
    return quiet and not edit and not any(SED_WRITE.search(a) for a in args)


def _sort(args: list[str]) -> bool:
    return not _short(args, "o") and not any(a.startswith("--output") for a in args)


READS: dict[str, Callable[[list[str]], bool]] = {
    **dict.fromkeys(
        ["cat", "head", "tail", "grep", "egrep", "fgrep", "jq", "wc", "ls", "nl", "cut"],
        lambda args: True,
    ),
    **dict.fromkeys(
        ["diff", "cmp", "stat", "sha256sum", "shasum", "echo", "printf", "pwd", "cd"],
        lambda args: True,
    ),
    "rg": lambda args: not any(a.startswith("--pre") for a in args),
    "sed": _sed,
    "sort": _sort,
    "find": lambda args: not FIND_ACTIONS & set(args),
    "verbatim-relay": lambda args: bool(args) and args[0] in VIEWS,
}


def _strip_heredocs(text: str) -> str:
    """The command without the bodies of its here-documents."""
    out: list[str] = []
    ends: list[tuple[str, bool]] = []
    for line in text.split("\n"):
        if ends:
            end, dash = ends[0]
            if (line.lstrip("\t") if dash else line) == end:
                ends.pop(0)
            continue
        out.append(line)
        ends += [(m.group(3), m.group(1) == "-") for m in HEREDOC.finditer(line)]
    return "\n".join(out)


def tokens(text: str) -> list[tuple[str, bool]] | None:
    """The words and operators of a command, as (text, is_operator), or None if it cannot parse."""
    out: list[tuple[str, bool]] = []
    word: str | None = None
    i, n = 0, len(text)

    def flush() -> None:
        nonlocal word
        if word is not None:
            out.append((word, False))
            word = None

    while i < n:
        c = text[i]
        if c == "\n":
            flush()
            out.append((";", True))
        elif c in " \t":
            flush()
        elif c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                return None
            word = (word or "") + text[i + 1 : j]
            i = j
        elif c == '"':
            j, part = i + 1, ""
            while j < n and text[j] != '"':
                if text[j] == "`" or text.startswith("$(", j):
                    return None
                if text[j] == "\\" and j + 1 < n:
                    j += 1
                part += text[j]
                j += 1
            if j >= n:
                return None
            word = (word or "") + part
            i = j
        elif c == "\\":
            if i + 1 >= n:
                return None
            if text[i + 1] != "\n":
                word = (word or "") + text[i + 1]
            i += 1
        elif c == "`":
            return None
        elif c in OPS:
            flush()
            j = i
            while j < n and text[j] in OPS:
                j += 1
            out.append((text[i:j], True))
            i = j - 1
        else:
            word = (word or "") + c
        i += 1
    flush()
    return out


def _writes_only_report(target: str) -> bool:
    return target == "/dev/null" or target.rsplit("/", 1)[-1] == "report.md"


def reads_only(command: str) -> bool:
    """True if each command only reads, and each output redirect writes /dev/null or report.md."""
    toks = tokens(_strip_heredocs(command))
    if toks is None:
        return False
    segments: list[list[str]] = [[]]
    i = 0
    while i < len(toks):
        text, op = toks[i]
        if not op:
            segments[-1].append(text)
        elif "(" in text or ")" in text:
            return False
        elif set(text) <= set(";&|"):
            segments.append([])
        else:
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if nxt is None or nxt[1]:
                return False
            dup = text.endswith("&") and (nxt[0].isdigit() or nxt[0] == "-")
            if ">" in text and not dup and not _writes_only_report(nxt[0]):
                return False
            i += 1
        i += 1
    for words in segments:
        if not words:
            continue
        check = READS.get(words[0].rsplit("/", 1)[-1])
        if check is None or not check(words[1:]):
            return False
    return True


def command_of(tool: str, tool_input: Any) -> str | None:
    """The command of a shell tool call, or None if the tool is not a shell."""
    if tool not in SHELL_TOOLS or not isinstance(tool_input, dict):
        return None
    cmd = tool_input.get("command", tool_input.get("cmd"))
    if isinstance(cmd, str):
        return cmd
    if isinstance(cmd, list) and all(isinstance(x, str) for x in cmd):
        argv: list[str] = cmd
        if len(argv) >= 3 and argv[0].rsplit("/", 1)[-1] in SHELLS and argv[1] in ("-c", "-lc"):
            return argv[2]
        return shlex.join(argv)
    return None


def tool_reads_only(tool: str, tool_input: Any) -> bool:
    """True if the tool call is a shell command that only reads (or writes report.md)."""
    cmd = command_of(tool, tool_input)
    return cmd is not None and reads_only(cmd)


def entry_names(entry: list[str]) -> list[str]:
    """The names that mark a run of the entry: its program files, and the module after -m."""
    names = []
    for k, arg in enumerate(entry):
        base = arg.rsplit("/", 1)[-1]
        if "." in base and base[base.rindex(".") :] in CODE:
            names.append(base)
        elif k > 0 and entry[k - 1] == "-m":
            names.append(arg)
    return names


def names_entry(text: str, names: list[str]) -> bool:
    """True if the text names a program file or the module of the entry."""
    return any(re.search(rf"(?<![\w.-]){re.escape(x)}(?![\w-])", text) for x in names)

"""The shell command check of the deny rules in SPEC.md section 5.

A shell command passes the check if each of its commands is a read program and each output
redirect writes /dev/null or report.md. All other input fails, also input that the check cannot
parse, so the deny fails closed. The plugin runs this check through `nookku hook`.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
import shlex
from collections.abc import Callable
from typing import Any

SHELL_TOOLS = {"Bash", "shell", "local_shell", "exec_command"}
SHELLS = {"bash", "sh", "zsh"}
OPS = set("();<>|&")
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# A sed script reads only if, without its /regex/ addresses, it has only these characters: line
# addresses and the commands p, P, =, q, Q, d and n. So s, w, W, e and r fail.
SED_ADDRESS = re.compile(r"/(?:\\.|[^/\\])*/I?")
SED_READS = re.compile(r"[0-9$,;!\s/pP=qQdn{}+~]*")
# sed short options with no value, and with a value.
SED_FLAGS, SED_VALUES = set("nErsuz"), set("el")
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprint0"}
FIND_ACTIONS |= {"-fprintf"}
# trace writes trace.jsonl and findings.json, and check starts a test, so they are not here.
VIEWS = {"transcript", "audit", "status", "view"}
# A part with only variable assignments passes, for example T=.nookku/tests/x. These
# variables change how the shell finds or runs a program, so an assignment to them fails.
ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")
SHELL_VARIABLES = {"PATH", "IFS", "CDPATH", "ENV", "BASH_ENV", "SHELLOPTS", "BASHOPTS", "PS4"}
SHELL_VARIABLES |= {"PROMPT_COMMAND"}
# The file types of an entry argument that names a program file (SPEC.md section 5).
CODE = {".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".rb"}
STATE = ".nookku"
# Programs that only store or show the body of a here-document. For each other program, for
# example `python -` or `sh`, the body is code (SPEC.md section 5).
DATA_PROGRAMS = {"cat", "tee", "gh", "jq", "wc", "grep", "head", "tail", "sort"}
GIT_DATA = {"commit", "tag", "notes"}
PATCH_FILE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.MULTILINE)
# A word of a text that can name a path in a state folder.
STATE_WORD = re.compile(r"[^\s\"'`;|&<>(),{}]+")


def _short(args: list[str], letter: str) -> bool:
    """True if a short option group, for example -nE, holds the letter."""
    return any(a.startswith("-") and not a.startswith("--") and letter in a[1:] for a in args)


def _sed(args: list[str]) -> bool:
    """True for sed -n with scripts that only print. An unknown option fails."""
    quiet, scripts, rest = False, [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--quiet", "--silent"):
            quiet = True
        elif a.startswith("--expression="):
            scripts.append(a.split("=", 1)[1])
        elif a == "--expression":
            if i + 1 >= len(args):
                return False
            scripts.append(args[i + 1])
            i += 1
        elif a.startswith("--"):
            if a not in (
                "--regexp-extended",
                "--null-data",
                "--separate",
                "--unbuffered",
                "--posix",
            ):
                return False
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:], 1):
                if ch == "n":
                    quiet = True
                elif ch in SED_VALUES:
                    value = a[k + 1 :]
                    if not value:
                        if i + 1 >= len(args):
                            return False
                        value = args[i + 1]
                        i += 1
                    if ch == "e":
                        scripts.append(value)
                    break
                elif ch not in SED_FLAGS:
                    return False
        else:
            rest.append(a)
        i += 1
    if not scripts:
        if not rest:
            return False
        scripts.append(rest[0])
    return quiet and all(SED_READS.fullmatch(SED_ADDRESS.sub("", x)) for x in scripts)


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
    "nookku": lambda args: bool(args) and args[0] in VIEWS,
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


def _assignment(word: str) -> bool:
    """True for a variable assignment that does not change how the shell finds or runs programs."""
    m = ASSIGNMENT.match(word)
    return (
        m is not None
        and m.group(1) not in SHELL_VARIABLES
        and not m.group(1).startswith(("LD_", "DYLD_"))
    )


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
        if all(_assignment(w) for w in words):
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


def names_entry(text: str, names: list[str], command: str | None = None) -> bool:
    """True if the text, or a word of the shell command, names a program file or the module of
    the entry. A word is compared after the shell removes its quotes and escapes, and a word with
    a glob character is compared as a glob."""
    if any(re.search(rf"(?<![\w.-]){re.escape(x)}(?![\w-])", text) for x in names):
        return True
    for word, op in tokens(_strip_heredocs(command)) or [] if command is not None else []:
        if op:
            continue
        base = word.rsplit("/", 1)[-1]
        for x in names:
            if x in (word, base):
                return True
            glob = any(c in word for c in "*?[")
            if glob and (fnmatch.fnmatchcase(x, base) or fnmatch.fnmatchcase(x, word)):
                return True
    return False


def _split(words: list[str]) -> tuple[str, list[str]]:
    """The program of a part of a command and its arguments. The program is the first word that
    is not a variable assignment."""
    k = 0
    while k < len(words) and ASSIGNMENT.match(words[k]):
        k += 1
    return (words[k].rsplit("/", 1)[-1], words[k + 1 :]) if k < len(words) else ("", [])


def _data_heredoc(line: str, at: int) -> bool:
    """True if the here-document that starts at `at` in the line is data, not code: its program
    only stores or shows it, like `cat > file` or `gh issue create --body-file -`."""
    toks = tokens(re.split(r"[;&|]", line[:at])[-1]) or []
    program, args = _split([w for w, op in toks if not op])
    if program in DATA_PROGRAMS:
        return True
    return program == "git" and args[:1] != [] and args[0] in GIT_DATA


def strip_data_heredocs(text: str) -> str:
    """The command without the bodies of the here-documents that are data (SPEC.md section 5).
    The body of a here-document for each other program, for example `python -`, is code, so it
    stays."""
    out: list[str] = []
    ends: list[tuple[str, bool, bool]] = []
    for line in text.split("\n"):
        if ends:
            end, dash, data = ends[0]
            if (line.lstrip("\t") if dash else line) == end:
                ends.pop(0)
            elif not data:
                out.append(line)
            continue
        out.append(line)
        for m in HEREDOC.finditer(line):
            ends.append((m.group(3), m.group(1) == "-", _data_heredoc(line, m.start())))
    return "\n".join(out)


def write_targets(command: str) -> tuple[list[str], list[str]] | None:
    """The words that a command can write, and the folders that it changes to with `cd`. Return
    None if the check cannot parse the command.

    A part that passes the read check writes nothing, so its words are not targets. Each word of
    each other part is a target, because the check does not know where a program writes. Each
    output redirect target is a target."""
    toks = tokens(strip_data_heredocs(command))
    if toks is None:
        return None
    targets: list[str] = []
    folders: list[str] = []
    segments: list[list[str]] = [[]]
    i = 0
    while i < len(toks):
        text, op = toks[i]
        if not op:
            segments[-1].append(text)
        elif "(" in text or ")" in text:
            return None
        elif set(text) <= set(";&|"):
            segments.append([])
        else:
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if nxt is None or nxt[1]:
                return None
            dup = text.endswith("&") and (nxt[0].isdigit() or nxt[0] == "-")
            if ">" in text and not dup:
                targets.append(nxt[0])
            elif text == "<<<":
                segments[-1].append(nxt[0])
            i += 1
        i += 1
    # A variable can carry a path to a later program, for example P=<path> python -c '...'. So if
    # a part writes, each assignment of the command is a target too.
    assignments: list[str] = []
    writes = False
    for words in segments:
        k = 0
        while k < len(words) and ASSIGNMENT.match(words[k]):
            k += 1
        assignments += words[:k]
        if k == len(words):
            continue
        program, args = _split(words)
        if program == "cd":
            folders += args[-1:]
            continue
        check = READS.get(program)
        if check is None or not check(args):
            targets += args
            writes = True
    return (targets + assignments if writes else targets), folders


def state_rest(word: str) -> list[str] | None:
    """The parts of a path after the state folder `.nookku`, or None if the word names no path in
    a state folder. The match ignores case. A glob part that starts with a dot matches the state
    folder as the shell would. The part after `=` of a word like `of=PATH` is a path too."""
    for piece in [word, *word.split("=")[1:]]:
        if not piece:
            continue
        parts = posixpath.normpath(piece.replace("\\", "/")).split("/")
        for k, part in enumerate(parts):
            low = part.lower()
            glob = part.startswith(".") and any(c in part for c in "*?[")
            if low == STATE or (glob and fnmatch.fnmatchcase(STATE, low)):
                return parts[k + 1 :]
    return None


def patch_targets(tool: str, tool_input: Any) -> list[str]:
    """The file names in the headers of each patch of an apply_patch call. The content of another
    file tool can look like a patch, but it is not one."""
    if tool != "apply_patch":
        return []
    out: list[str] = []
    for value in _strings(tool_input):
        out += [m.group(1).strip() for m in PATCH_FILE.finditer(value)]
    return out


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def path_words(text: str) -> list[str]:
    """The words of a text, split at spaces, quotes, brackets, commas and shell operators."""
    return STATE_WORD.findall(text)


def state_words(tool_input: Any) -> list[str]:
    """Each word of each text of a tool input that names a path in a state folder."""
    words = [m.group(0) for s in _strings(tool_input) for m in STATE_WORD.finditer(s)]
    return [w for w in words if state_rest(w) is not None]

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
from typing import Any, NamedTuple

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
# The nookku commands that drive a test. Only a person runs them (#173). `mode` drives a test only
# with one of MODE_DRIVES, and `run` only if the policy key scripts is not model.
DRIVES = {"start", "end", "hook", "run"}
MODE_DRIVES = {"on", "off", "start", "end"}
# `init --remove` removes the project hooks, so the next message would reach the model (#163).
# argparse also takes a unique prefix of the flag, from --rem.
REMOVE = "--remove"
# Programs that run their arguments as a command.
LAUNCHERS = {"env", "exec", "nohup", "time", "command", "sudo", "uvx"}
PYTHON = re.compile(r"python[0-9.]*")
# Text that imports the package, and text that runs a drive command. The rule reads the text only
# if the check cannot parse the command.
IMPORTS = re.compile(
    r"\b(?:import|from)\s+nookku\b|\b(?:import_module|__import__)\s*\(\s*['\"]nookku\b"
)
DRIVE_TEXT = re.compile(
    r"\bnookku\s+(?:-\S+\s+)*(start|end|hook|run|mode\s+(?:on|off|start|end)"
    r"|init\b[^;&|\n]*?\s--rem(?:o|ov|ove)?\b)"
)
# The same text with no word boundary before nookku, for text that an option holds, for example
# env -S'nookku start'.
LAUNCH_TEXT = re.compile(DRIVE_TEXT.pattern.removeprefix(r"\b"))
# The env option that splits its value into a command, alone or in a group as in -vS.
SPLIT = re.compile(r"-[a-zA-Z]*S|--split-string")
# The python long option that takes the next word as its value.
PYTHON_LONG_VALUES = {"--check-hash-based-pycs"}
IMPORT = "import nookku"
SHELL_CODE = re.compile(r"-[a-zA-Z]*c[a-zA-Z]*")
# A word of a text that can name a path in a state folder.
STATE_WORD = re.compile(r"[^\s\"'`;|&<>(),{}]+")
# The entry gets the test folder in NOOKKU_TEST_DIR, and a child process of the app, for example
# its model harness, can inherit it (#145). A word that names the variable names the test folder.
TEST_DIR_NAME = re.compile(r"[$%]?\{?NOOKKU_TEST_DIR\}?%?", re.IGNORECASE)


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
    **dict.fromkeys(["which", "type"], lambda args: True),
    # `command` with no -v or -V runs its argument as a program.
    "command": lambda args: bool(args) and args[0] in ("-v", "-V"),
    "rg": lambda args: not any(a.startswith("--pre") for a in args),
    "sed": _sed,
    "sort": _sort,
    "find": lambda args: not FIND_ACTIONS & set(args),
    "nookku": lambda args: bool(args) and args[0] in VIEWS,
}


def failure(program: str, args: list[str], extra: frozenset[str] = frozenset()) -> str | None:
    """Why a part of a command does not pass the read check, or None if it passes. `extra` holds
    more read programs, from the policy key guard_reads. A program of READS keeps its own check."""
    check = READS.get(program)
    if check is None and program in extra:
        return None
    if check is None:
        return f'"{program}" is not a read command.'
    return None if check(args) else f'"{program}" with these arguments can write.'


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


def reads_only(command: str, extra: frozenset[str] = frozenset()) -> bool:
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
        if failure(words[0].rsplit("/", 1)[-1], words[1:], extra) is not None:
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


def tool_reads_only(tool: str, tool_input: Any, extra: frozenset[str] = frozenset()) -> bool:
    """True if the tool call is a shell command that only reads (or writes report.md)."""
    cmd = command_of(tool, tool_input)
    return cmd is not None and reads_only(cmd, extra)


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


def _parts(toks: list[tuple[str, bool]]) -> list[list[str]] | None:
    """The words of each part of a command, without redirects. None if a part has a bracket."""
    parts: list[list[str]] = [[]]
    i = 0
    while i < len(toks):
        text, op = toks[i]
        if not op:
            parts[-1].append(text)
        elif "(" in text or ")" in text:
            return None
        elif set(text) <= set(";&|"):
            parts.append([])
        else:
            i += 1
        i += 1
    return parts


def _subcommand(args: list[str]) -> str | None:
    """The drive command of the arguments of nookku, for example "nookku start", or None."""
    words = [a for a in args if not a.startswith("-")]
    if words and words[0] in DRIVES:
        return f"nookku {words[0]}"
    state = next((w for w in words[1:] if w in MODE_DRIVES), None)
    if words[:1] == ["mode"] and state is not None:
        return f"nookku mode {state}"
    if words[:1] == ["init"] and any(len(a) >= 5 and REMOVE.startswith(a) for a in args):
        return "nookku init --remove"
    return None


def _program(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _runs(word: str) -> bool:
    """True for a program that the drive rule reads: nookku, python or a shell."""
    program = _program(word)
    return program in ("nookku", "nookku.exe", *SHELLS) or PYTHON.fullmatch(program) is not None


def _python(args: list[str]) -> tuple[str, list[str]]:
    """What python runs: ("-m", [module, *args]), ("-c", []), ("script", args) or
    ("stdin", args). The module can follow -m, be attached as in -mnookku, or follow a group of
    flags as in -Im. A value of -W, -X or --check-hash-based-pycs is not the script."""
    k = 0
    while k < len(args) and args[k].startswith("-") and args[k] != "-":
        word = args[k]
        k += 1
        if word == "--":
            break
        if word.startswith("--"):
            k += word in PYTHON_LONG_VALUES
            continue
        for n, letter in enumerate(word[1:], 2):
            if letter == "m":
                return "-m", [word[n:], *args[k:]] if word[n:] else args[k:]
            if letter == "c":
                return "-c", []
            if letter in "WX":
                # The value is the rest of the word or the next word.
                k += 0 if word[n:] else 1
                break
    if k >= len(args) or args[k] == "-":
        return "stdin", args[k + 1 :]
    return "script", args[k:]


def _shell_stdin(args: list[str]) -> bool:
    """True if a shell runs code from its standard input: no -c, and -s or no script."""
    k, stdin = 0, False
    while k < len(args) and args[k][:1] in ("-", "+") and args[k] != "--":
        word = args[k]
        k += 1
        if word in ("-o", "+o", "-O", "+O"):
            k += 1
        elif SHELL_CODE.fullmatch(word):
            return False
        elif word[0] == "-" and "s" in word[1:] and not word.startswith("--"):
            stdin = True
    return stdin or k + (k < len(args) and args[k] == "--") >= len(args)


def _reads_stdin(words: list[str]) -> bool:
    """True if a shell or python runs code from its standard input, for example echo ... | sh."""
    i = next((k for k, w in enumerate(words) if not ASSIGNMENT.match(w)), len(words))
    if i < len(words) and _program(words[i]) in LAUNCHERS | {"uv", "pipx"}:
        i = next((j for j in range(i + 1, len(words)) if _runs(words[j])), len(words))
    if i >= len(words):
        return False
    program, args = _program(words[i]), words[i + 1 :]
    if program in SHELLS:
        return _shell_stdin(args)
    return PYTHON.fullmatch(program) is not None and _python(args)[0] == "stdin"


def _drive_part(words: list[str], allowed: frozenset[str]) -> str | None:
    i = 0
    while i < len(words) and ASSIGNMENT.match(words[i]):
        i += 1
    if i < len(words) and (
        _program(words[i]) in LAUNCHERS
        or (_program(words[i]) in ("uv", "pipx") and words[i + 1 : i + 2] == ["run"])
    ):
        # A launcher option can take a value, for example uv run --python python3. The rule reads
        # each later word that runs a program, and gives the first drive that it finds. The env
        # option -S holds a command, for example env -S 'nookku start', so the rule reads the
        # text from that option.
        starts = (j for j in range(i + 1, len(words)) if _runs(words[j]))
        found = next((f for j in starts if (f := _drive_part(words[j:], allowed))), None)
        split = next((j for j in range(i + 1, len(words)) if SPLIT.match(words[j])), None)
        if found is None and _program(words[i]) == "env" and split is not None:
            found = _drive_text(" ".join(words[split:]), allowed, LAUNCH_TEXT)
        return found
    if i >= len(words):
        return None
    program = _program(words[i])
    found = None
    if program in ("nookku", "nookku.exe"):
        found = _subcommand(words[i + 1 :])
    elif PYTHON.fullmatch(program) and (run := _python(words[i + 1 :]))[0] == "-m":
        module, *rest = run[1] or [""]
        if module == "nookku":
            found = _subcommand(rest)
        elif module.startswith("nookku."):
            found = IMPORT
    elif program in SHELLS:
        # The code of sh -c, bash -lc and the like. The code can follow --, so the rule reads
        # each word after the flag.
        flags = [k for k in range(i + 1, len(words)) if SHELL_CODE.fullmatch(words[k])]
        later = words[flags[0] + 1 :] if flags else []
        found = next((f for w in later if (f := drive(w, allowed))), None)
    return found if found not in allowed else None


def _drive_text(text: str, allowed: frozenset[str], pattern: re.Pattern[str]) -> str | None:
    for m in pattern.finditer(text):
        what = "nookku " + " ".join(m.group(1).split())
        what = "nookku init --remove" if what.startswith("nookku init") else what
        if what not in allowed:
            return what
    return None


def drive(command: str, allowed: frozenset[str] = frozenset()) -> str | None:
    """The nookku command that a shell command runs to drive a test, for example "nookku start",
    or IMPORT if the command imports the package. None if it does neither (SPEC.md section 5).

    The rule finds the program after assignments, launchers such as env and uv run, python -m
    and sh -c. If the check cannot parse the command, the rule reads its text. A command that
    only reads, for example grep "import nookku", does not import the package. The rule reads
    each part of the command and skips a drive in allowed, so an allowed part cannot hide a
    later part that is not allowed."""
    stripped = strip_data_heredocs(command)
    toks = tokens(stripped)
    parts = _parts(toks) if toks is not None else None
    if parts is None:
        found = _drive_text(stripped, allowed, DRIVE_TEXT)
    else:
        found = next((f for words in parts if (f := _drive_part(words, allowed))), None)
        # A shell or python that reads its standard input runs the text of the command before
        # it, for example echo 'nookku start' | sh.
        if found is None and any(_reads_stdin(words) for words in parts):
            found = _drive_text(stripped, allowed, LAUNCH_TEXT)
    if found is not None:
        return found
    if IMPORTS.search(stripped) and not reads_only(command):
        return IMPORT
    return None


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


class Writes(NamedTuple):
    # Each word that the command can write, with the cause: a sentence for the deny reason.
    targets: list[tuple[str, str]]
    # The folders that the command changes to with `cd`.
    folders: list[str]
    # The first cause of the command, or "" if the command passes the read check.
    cause: str


def write_targets(command: str, extra: frozenset[str] = frozenset()) -> Writes | None:
    """The words that a command can write, and the folders that it changes to with `cd`. Return
    None if the check cannot parse the command.

    A part that passes the read check writes nothing, so its words are not targets. Each word of
    each other part is a target, because the check does not know where a program writes. Each
    output redirect target is a target."""
    toks = tokens(strip_data_heredocs(command))
    if toks is None:
        return None
    targets: list[tuple[str, str]] = []
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
                targets.append((nxt[0], f'The redirect "{text}" writes it.'))
            elif text == "<<<":
                segments[-1].append(nxt[0])
            i += 1
        i += 1
    # A variable can carry a path to a later program, for example P=<path> python -c '...'. So if
    # a part writes, each assignment of the command is a target too.
    assignments: list[str] = []
    writes = ""
    # The read check refuses an assignment before a program, and an assignment that changes how
    # the shell runs programs. These write nothing, but the deny reason names them.
    refused = ""
    for words in segments:
        k = 0
        while k < len(words) and ASSIGNMENT.match(words[k]):
            k += 1
        assignments += words[:k]
        if k == len(words):
            bad = next((w for w in words if not _assignment(w)), None)
            if bad is not None and not refused:
                refused = f'The read check does not accept the assignment "{bad}".'
            continue
        if k and not refused:
            refused = f'The read check does not accept the assignment "{words[0]}".'
        program, args = _split(words)
        if program == "cd":
            folders += args[-1:]
            continue
        cause = failure(program, args, extra)
        if cause is not None:
            targets += [(a, cause) for a in args]
            writes = writes or cause
    if writes:
        targets += [(a, writes) for a in assignments]
    return Writes(targets, folders, writes or next((c for _, c in targets), refused))


def state_rest(word: str) -> list[str] | None:
    """The parts of a path after the state folder `.nookku`, or None if the word names no path in
    a state folder. The match ignores case. A glob part that starts with a dot matches the state
    folder as the shell would. The part after `=` of a word like `of=PATH` is a path too. The
    variable NOOKKU_TEST_DIR names a test folder."""
    word = TEST_DIR_NAME.sub(f"{STATE}/tests/NOOKKU_TEST_DIR", word)
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

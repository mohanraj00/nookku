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
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

SHELL_TOOLS = {"Bash", "shell", "local_shell", "exec_command"}
SHELLS = {"bash", "sh", "zsh"}
OPS = set("();<>|&")
# The start of a here-document: the dash, the quote and the end word. An end word with another
# form, for example E"O"F, does not match, so its body stays in the text of the command.
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2(?![^\s;&|<>()])")
# A command substitution. The shell runs it in the body of a here-document whose end word has
# no quote.
SUBSTITUTION = re.compile(r"\$\(|`")
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
# with one of MODE_DRIVES, and `run` only if the policy key scripts is not model. `chat` prints the
# URL of the chat page with its token, and with the token a model could send as the tester (#327).
# `page` is the old name of `chat`, and it works the same for one release (#394).
# `script` writes a saved script, which the guard protects from a model write (#350). `replay`
# runs a scripted test, with each policy (#351). `gate` runs a set of scripted tests, with each
# policy. Only `gate verify` as the first word after `gate` passes, because it only reads (#574).
# `adjudicate` writes the decision of a person about an answer key mismatch, and it can change
# a verdict from fail to pass (#548). `evaluation` writes the issue rows of an evaluation with
# the author type of the command, and it can change a verdict (#576).
DRIVES = {
    "start",
    "end",
    "hook",
    "run",
    "chat",
    "page",
    "script",
    "replay",
    "gate",
    "adjudicate",
    "evaluation",
}
MODE_DRIVES = {"on", "off", "start", "end"}
# `init --remove` removes the project hooks, so the next message would reach the model (#163).
# argparse also takes a unique prefix of the flag, from --rem.
REMOVE = "--remove"
# The shell can change a word with one of these characters before nookku gets it: a variable, a
# command substitution, a glob or a brace list. Thus the rule cannot know the subcommand, for
# example in C=adjudicate; nookku "$C" (#548).
EXPANDS = re.compile(r"[$`*?\[{]")
# The same word in the text of a command that the check cannot parse. The text keeps its quotes
# and its backslashes, so a word with one of them is also not a known subcommand.
WORD = r"""[^\s;&|]*[$`*?\[{'"\\][^\s;&|]*"""
# Programs that run their arguments as a command.
LAUNCHERS = {"env", "exec", "nohup", "time", "command", "sudo", "uvx"}
PYTHON = re.compile(r"python[0-9.]*")
# Text that imports the package, and text that runs a drive command. The rule reads the text only
# if the check cannot parse the command.
IMPORTS = re.compile(
    r"\b(?:import|from)\s+nookku\b|\b(?:import_module|__import__)\s*\(\s*['\"]nookku\b"
)
DRIVE_TEXT = re.compile(
    r"\bnookku\s+(?:-\S+\s+)*(start|end|hook|run|chat|page|script|replay|adjudicate|evaluation"
    r"|gate\b(?!\s+verify\b)"
    r"|mode\s+(?:on|off|start|end)"
    r"|init\b[^;&|\n]*?\s--rem(?:o|ov|ove)?\b"
    rf"|(?P<word>{WORD})|mode\s+(?P<state>{WORD})|init\b[^;&|\n]*?\s(?P<flag>{WORD}))"
)
# The same text with no word boundary before nookku, for text that an option holds, for example
# env -S'nookku start'.
LAUNCH_TEXT = re.compile(DRIVE_TEXT.pattern.removeprefix(r"\b"))
# The env option that splits its value into a command, alone or in a group as in -vS.
SPLIT = re.compile(r"-[a-zA-Z]*S|--split-string")
# The python long option that takes the next word as its value.
PYTHON_LONG_VALUES = {"--check-hash-based-pycs"}
IMPORT = "import nookku"
# The result of the drive rule for a nookku command with a word that the shell expands.
EXPANDED = "nookku with a word that the shell expands"
SHELL_CODE = re.compile(r"-[a-zA-Z]*c[a-zA-Z]*")
# A word of a text that can name a path in a state folder.
STATE_WORD = re.compile(r"[^\s\"'`;|&<>(),{}]+")
# A word of a command with its braces and commas, for the brace expansion of the shell.
RAW_WORD = re.compile(r"[^\s\"'`;|&<>()]+")
# A quote, a backslash, and a backslash with the line feed that it removes.
UNQUOTE = re.compile(r"""\\\n|["'\\]""")
# The innermost group in brackets of a glob, with its extglob prefix.
GROUP = re.compile(r"[@+?*!]?\([^()]*\)")
# The most levels of groups in brackets that the rule reads. This is a chosen value.
GROUP_DEPTH = 8
# A bracket expression of a glob, for example [a-z], [!a] or [[:alpha:]].
BRACKET = re.compile(r"\[[!^]?\]?(?:\[[:.=][^\]]*\]|[^\]])*\]")
# The innermost brace group of a word, for example {json,txt}.
BRACES = re.compile(r"\{([^{}]*,[^{}]*)\}")
# The most words that the brace expansion of one word gives. This is a chosen value.
BRACE_LIMIT = 64
# The options of rg, grep and find whose value is the glob of a search.
GLOB_OPTIONS = {"-g", "--glob", "--iglob", "--include", "-name", "-iname"}
# The options of find whose value is a glob of the whole path.
PATH_OPTIONS = {"-path", "-ipath", "-wholename", "-iwholename"}
# The characters that come before a path in a word: `if=PATH`, `HEAD:PATH` and `@PATH`.
PATH_STARTS = re.compile(r"[=:@]")
# A path that names each file: the candidate for a word that the rule cannot expand.
EACH_PATH = "/**"
# The entry gets the test folder in NOOKKU_TEST_DIR, and a child process of the app, for example
# its model harness, can inherit it (#145). A word that names the variable names the test folder.
TEST_DIR_NAME = re.compile(r"[$%]?\{?NOOKKU_TEST_DIR\}?%?", re.IGNORECASE)
# NOOKKU_TESTS_DIR names the folder of all tests (SPEC.md section 7). A word that names the
# variable names the tests folder.
TESTS_DIR_NAME = re.compile(r"[$%]?\{?NOOKKU_TESTS_DIR\}?%?", re.IGNORECASE)


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


def _without_heredocs(text: str, code: bool) -> str:
    """The command without the bodies of its here-documents. With `code`, the body of a
    here-document that is code stays. The shell runs each command substitution in a body whose
    end word has no quote, so a body with one always stays."""
    out: list[str] = []
    body: list[str] = []
    # The end word, the dash, True if the body is code that stays, True if the shell expands it.
    ends: list[tuple[str, bool, bool, bool]] = []

    def close() -> None:
        _, _, stays, expands = ends.pop(0)
        if stays or (expands and any(SUBSTITUTION.search(line) for line in body)):
            out.extend(body)
        body.clear()

    for line in text.split("\n"):
        if ends:
            if (line.lstrip("\t") if ends[0][1] else line) == ends[0][0]:
                close()
            else:
                body.append(line)
            continue
        out.append(line)
        for m in HEREDOC.finditer(line):
            stays = code and not _data_heredoc(line, m.start())
            ends.append((m.group(3), m.group(1) == "-", stays, not m.group(2)))
    if ends:
        close()
    return "\n".join(out)


def _strip_heredocs(text: str) -> str:
    """The command without the bodies of its here-documents. A body with a command substitution
    that the shell runs stays."""
    return _without_heredocs(text, False)


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
    only stores or shows it, like `cat > file` or `gh issue create --body-file -`.

    The output of such a program can go to a program that runs it, for example `cat <<EOF | sh`.
    So the here-document is data only if the check can parse the line, and the line has no pipe,
    no bracket and no backslash at its end, which continues the line."""
    whole = tokens(line)
    if whole is None or line.rstrip(" \t").endswith("\\"):
        return False
    if any(op and set(text) & set("|()") for text, op in whole):
        return False
    # The words of the command with the here-document: the words after the last `;` or `&`.
    words: list[str] = []
    for text, op in tokens(line[:at]) or []:
        if not op:
            words.append(text)
        elif set(text) <= set(";&"):
            words = []
    program, args = _split(words)
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
    if words[:2] == ["gate", "verify"]:
        return None
    if words and words[0] in DRIVES:
        return f"nookku {words[0]}"
    if words and EXPANDS.search(words[0]):
        return EXPANDED
    state = next((w for w in words[1:] if w in MODE_DRIVES), None)
    if words[:1] == ["mode"] and state is not None:
        return f"nookku mode {state}"
    if words[:1] == ["init"] and any(len(a) >= 5 and REMOVE.startswith(a) for a in args):
        return "nookku init --remove"
    # The state of `mode` or a flag of `init` can come from a word that the shell expands.
    if words[:1] == ["mode"] and any(EXPANDS.search(w) for w in words[1:]):
        return EXPANDED
    if words[:1] == ["init"] and any(EXPANDS.search(a) for a in args):
        return EXPANDED
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
        if m.group("word") or m.group("state") or m.group("flag"):
            what = EXPANDED
        if what not in allowed:
            return what
    return None


def drive(command: str, allowed: frozenset[str] = frozenset()) -> str | None:
    """The nookku command that a shell command runs to drive a test, for example "nookku start",
    EXPANDED if the shell expands a word that can be the subcommand, or IMPORT if the command
    imports the package. None if it does none of these (SPEC.md section 5).

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
    stays. A body of data with a command substitution that the shell runs stays too, for example
    `$(cat keys/stock.json)` below `cat <<EOF`."""
    return _without_heredocs(text, True)


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


# The programs and options that run a command in another folder (#507).
CHANGE_DIRS = {"cd", "pushd"}
DIR_OPTIONS = {"-C", "--directory"}


def changed_folders(command: str) -> tuple[list[str], bool]:
    """The folders that a command can change to, in their order: the word after `cd` or `pushd`,
    and the value of `-C` or `--directory`. The check reads the words of the whole text, so it
    also finds a `cd` in the code of `bash -c` or in brackets. The bool is True if the command
    changes to a folder that the check cannot know: `cd -`, or a word with `$`, `%` or `~user`.
    The words have no shell operators, so after a `cd` with no folder, the next word counts as
    its folder. The caller adds the home folder for this case."""
    words = path_words(command)
    out: list[str] = []
    unknown = False
    for k, word in enumerate(words):
        j = k + 1
        if _program(word) in CHANGE_DIRS:
            # Skip the options of cd, for example -P.
            while j < len(words) and words[j].startswith("-") and words[j] != "-":
                j += 1
            folder = words[j] if j < len(words) else ""
        elif word in DIR_OPTIONS:
            folder = words[j] if j < len(words) else ""
        elif word.startswith("--directory="):
            folder = word.split("=", 1)[1]
        else:
            continue
        if folder == "-" or any(c in folder for c in "$%") or re.match(r"~[^/]", folder):
            unknown = True
        elif folder:
            out.append(folder)
    return out, unknown


def state_rest(word: str, tests: Sequence[str] = (), cwd: str | None = None) -> list[str] | None:
    """The parts of a path after the state folder `.nookku`, or None if the word names no path in
    a state folder. The match ignores case. A glob part that starts with a dot matches the state
    folder as the shell would. The part after `=` of a word like `of=PATH` is a path too. The
    variable NOOKKU_TEST_DIR names a test folder, and NOOKKU_TESTS_DIR names the tests folder.

    `tests` holds the absolute paths of tests folders outside a state folder (SPEC.md section 7).
    A path in one of them gives `tests` and the parts after the folder, as a path in
    `.nookku/tests` does. `cwd` is the folder of a relative word."""
    word = TEST_DIR_NAME.sub(f"{STATE}/tests/NOOKKU_TEST_DIR", word)
    word = TESTS_DIR_NAME.sub(f"{STATE}/tests", word)
    for piece in [word, *word.split("=")[1:]]:
        if not piece:
            continue
        parts = posixpath.normpath(piece.replace("\\", "/")).split("/")
        for k, part in enumerate(parts):
            low = part.lower()
            glob = part.startswith(".") and any(c in part for c in "*?[")
            if low == STATE or (glob and fnmatch.fnmatchcase(STATE, low)):
                return parts[k + 1 :]
        rest = _tests_rest(piece, tests, cwd)
        if rest is not None:
            return rest
    return None


def _tests_rest(piece: str, tests: Sequence[str], cwd: str | None) -> list[str] | None:
    """`tests` and the parts after a tests folder of `tests`, or None. A relative piece starts
    at `cwd`, and `~` is the home folder. The match ignores case, and a glob part matches as the
    shell would."""
    parts = _path_parts(piece, cwd) if tests else None
    if parts is None:
        return None
    for folder in tests:
        top = posixpath.normpath(folder.replace("\\", "/")).split("/")
        if len(parts) < len(top):
            continue
        pairs = zip(parts[: len(top)], top, strict=True)
        if all(_same_part(given, real) for given, real in pairs):
            return ["tests", *parts[len(top) :]]
    return None


def _path_parts(piece: str, cwd: str | None) -> list[str] | None:
    """The parts of the absolute path of a piece, or None. A relative piece starts at `cwd`, and
    `~` is the home folder."""
    path = piece.replace("\\", "/")
    if path.startswith("~"):
        path = posixpath.expanduser(path)
    if not path.startswith("/"):
        if cwd is None:
            return None
        path = posixpath.join(cwd.replace("\\", "/"), path)
    return posixpath.normpath(path).split("/")


def glob_rests(parts: Sequence[str], top: Sequence[str]) -> list[list[str]]:
    """The parts of a path after the path `top`, for each way that its first parts are `top`.
    A part `**` matches 0 or more parts. If a `**` matches the last part of `top`, it can also
    match parts after `top`, so it is the first part of the result."""
    at = {0}
    for real in top:
        # A `**` can match no part.
        for i in sorted(at):
            while i < len(parts) and parts[i] == "**":
                i += 1
                at.add(i)
        step: set[int] = set()
        for i in at:
            if i < len(parts) and parts[i] == "**":
                step.add(i)
            elif i < len(parts) and _same_part(parts[i], real):
                step.add(i + 1)
        at = step
    return [list(parts[i:]) for i in sorted(at)]


def exact(rest: Sequence[str]) -> bool:
    """True if the result of glob_rests names the path itself, and no path after it."""
    return all(part == "**" for part in rest)


def key_word(
    word: str,
    keys: Sequence[str],
    cwd: str | None,
    tails: Sequence[str] = (),
    deep: Callable[[str, list[str]], bool] | None = None,
) -> bool:
    """True if a word names an answer key of the policy key answer_keys (SPEC.md section 5).

    `keys` holds the absolute path of each key: a file, or a folder with each file in it. A word
    names a key if its path is the path of a key or a path in it. A relative word starts at
    `cwd`, `~` is the home folder, the match ignores case, and a glob part matches as the shell
    would. A part `**` matches 0 or more folders. If a `**` matches the last part of a key and
    more parts come after it, the word names a path in the key only if `deep` says so for the key
    and these parts. The part after `=`, `:` or `@` of a word like `if=PATH`, `HEAD:PATH` or
    `@PATH` is a path too. `tails` holds the path of each key in the project. The shell can
    expand a word with `$` to any path, so such a word names a key if consecutive parts of its
    path are the parts of a tail."""
    for piece in [word, *PATH_STARTS.split(word)[1:]]:
        if not piece:
            continue
        given = _path_parts(piece, cwd)
        for key in keys if given is not None else ():
            top = posixpath.normpath(key.replace("\\", "/")).split("/")
            for rest in glob_rests(given or [], top):
                if exact(rest) or rest[0] != "**":
                    return True
                if deep is not None and deep(key, rest):
                    return True
        if "$" not in piece:
            continue
        parts = posixpath.normpath(piece.replace("\\", "/")).split("/")
        for tail in tails:
            top = tail.split("/")
            for k in range(len(parts) - len(top) + 1):
                pairs = zip(parts[k : k + len(top)], top, strict=True)
                if all(_same_part(given, real) for given, real in pairs):
                    return True
    return False


def _same_part(given: str, real: str) -> bool:
    given, real = given.casefold(), real.casefold()
    if given == real or not any(c in given for c in "*?["):
        return given == real
    return fnmatch.fnmatchcase(real, BRACKET.sub(_bracket, given))


def _bracket(m: re.Match[str]) -> str:
    """A bracket expression of a shell glob in the form that fnmatch knows. fnmatch does not know
    a class such as `[[:alpha:]]`, so `?` replaces an expression with one. `[^a]` is `[!a]`."""
    text = m.group(0)
    if any(mark in text for mark in ("[:", "[.", "[=")):
        return "?"
    return "[!" + text[2:] if text.startswith("[^") else text


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


def braces(word: str) -> list[str] | None:
    """Each word that the brace expansion of a word gives: `st.{json,txt}` gives `st.json` and
    `st.txt`. None if the word gives more than BRACE_LIMIT words."""
    out = [word]
    k = 0
    while k < len(out):
        m = BRACES.search(out[k])
        if m is None:
            k += 1
            continue
        if len(out) >= BRACE_LIMIT:
            return None
        w = out[k]
        out[k : k + 1] = [w[: m.start()] + part + w[m.end() :] for part in m.group(1).split(",")]
    return list(dict.fromkeys(out))


def search_globs(glob: str) -> list[str] | None:
    """The paths that the glob of a search names, relative to the path of the search. A search
    tool reads a glob as a line of .gitignore: `{a,b}` gives each alternative, a `/` at the
    start means the path of the search, and a glob with no other `/` before its last part
    matches in each folder. None if the glob gives more than BRACE_LIMIT words."""
    forms = braces(glob)
    if forms is None:
        return None
    out: list[str] = []
    for form in forms:
        rel = form.lstrip("/")
        if "/" not in rel.rstrip("/") and not form.startswith("/") and rel not in ("", ".", ".."):
            rel = "**/" + rel
        if rel:
            out.append(rel)
    return out


def key_candidates(command: str) -> list[tuple[str, str]]:
    """The words of a shell command that can name an answer key (SPEC.md section 5), each with
    the word of the command that gives it. The words are: each word of path_words, each word of
    the shell without its quotes and backslashes, each word that a brace expansion gives, and
    each path that the glob of a search option names (search_globs), from each word of the
    command. A word that the rule cannot expand gives EACH_PATH, so the rule fails closed.

    The rule also reads the body of each here-document, because a command can run the body or
    store it as a script: `cat <<'EOF' | sh`."""
    text = command
    out = [(w, w) for w in path_words(text)]
    toks = tokens(text)
    if toks is None:
        # The check cannot parse the command. The shell removes each quote and each backslash
        # of a word, so the rule reads the text without them.
        whole = RAW_WORD.findall(UNQUOTE.sub("", text))
    else:
        whole = [w for w, op in toks if not op]
    # A group in brackets is a part of a glob in zsh and with extglob: (stock) or @(stock|list).
    # The rule reads each group as `*`.
    wild = text
    for _ in range(GROUP_DEPTH):
        wild, count = GROUP.subn("*", wild)
        if not count:
            break
    out += [(w, w) for w in RAW_WORD.findall(UNQUOTE.sub("", wild)) if "*" in w]
    for k, word in enumerate(whole):
        forms = braces(word)
        out += [(EACH_PATH, word)] if forms is None else [(form, word) for form in forms]
        option, _, value = word.partition("=")
        if word in PATH_OPTIONS and k + 1 < len(whole):
            # A `*` of find -path also matches `/`, so the glob can name a path at each depth.
            path = whole[k + 1]
            out += [
                (posixpath.join(start, "**", path, tail), path)
                for start in ("", *whole)
                for tail in ("", "**")
                if not start.startswith("-")
            ]
            continue
        if word in GLOB_OPTIONS:
            glob = whole[k + 1] if k + 1 < len(whole) else ""
        elif option in GLOB_OPTIONS:
            glob = value
        elif word.startswith("-g"):
            glob = word[2:]
        else:
            continue
        globs = search_globs(glob) if glob else []
        if globs is None:
            out.append((EACH_PATH, glob))
            continue
        # The command does not show which word is the path of the search. So the glob starts at
        # the folder of the command and at each word that is not an option.
        starts = ["", *(w for w in whole if not w.startswith("-") and w != glob)]
        out += [(posixpath.join(start, g), glob) for start in starts for g in globs]
    return list(dict.fromkeys(out))


def input_candidates(tool_input: Any) -> list[tuple[str, str]]:
    """The words of each text of a tool input that can name an answer key (key_candidates). The
    text of a tool that is not a shell can be a command, for example the input of a persistent
    shell, so the rule reads each text as a command."""
    return [pair for s in _strings(tool_input) for pair in key_candidates(s)]


def input_words(tool_input: Any) -> list[str]:
    """Each word of each text of a tool input (path_words)."""
    return [m.group(0) for s in _strings(tool_input) for m in STATE_WORD.finditer(s)]


def state_words(tool_input: Any, tests: Sequence[str] = (), cwd: str | None = None) -> list[str]:
    """Each word of each text of a tool input that names a path in a state folder or in a tests
    folder of `tests` (state_rest)."""
    words = [m.group(0) for s in _strings(tool_input) for m in STATE_WORD.finditer(s)]
    return [w for w in words if state_rest(w, tests, cwd) is not None]

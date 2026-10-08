"""The docs agree with the repo: links resolve, counts match the data, and the reference pages
match the CLI parser, config.Config and the plugin options."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

import pytest
from test_timeouts import ANSWER

from verbatim_relay import audit, bridge, cli, config, kit, stdio, trace

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

pytestmark = pytest.mark.skipif(
    not (DOCS / "index.md").exists(), reason="the sdist has no docs folder"
)

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,}).*?^ {0,3}\1[`~]*[ \t]*$", re.MULTILINE | re.DOTALL)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
# An inline link or image: [text](target "title"). The text can hold one level of brackets.
LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.MULTILINE)
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"", re.IGNORECASE)
SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__"}


def markdown_files() -> list[Path]:
    """The Markdown files of the repo: tracked, or new and not ignored. Hidden folders, except
    .github, are not part of the docs, for example the worktrees of an agent in .claude/."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "*.md"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        found = [ROOT / n for n in out.decode().split("\0") if n]
    except (OSError, subprocess.CalledProcessError):
        found = list(ROOT.rglob("*.md"))  # no git, for example in an unpacked sdist
    kept = []
    for path in found:
        parts = path.relative_to(ROOT).parts[:-1]
        hidden = any(p in SKIP_DIRS or (p.startswith(".") and p != ".github") for p in parts)
        if path.is_file() and not hidden:
            kept.append(path)
    return sorted(kept)


def prose(text: str) -> str:
    """The text without code blocks, code spans and comments. Links in code are not links."""
    text = FENCE.sub("", text)
    text = COMMENT.sub("", text)
    return CODE_SPAN.sub("", text)


def links(text: str) -> list[str]:
    body = prose(text)
    return [m.group(1) for m in LINK.finditer(body)] + DEFINITION.findall(body)


def slug(heading: str) -> str:
    """The anchor that GitHub gives a heading."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # a link keeps its text
    text = re.sub(r"<[^>]+>", "", text).replace("`", "")
    text = re.sub(r"(\*\*|__|\*)", "", text)
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    seen: Counter[str] = Counter()
    out = set(HTML_ANCHOR.findall(text))
    for m in HEADING.finditer(text):
        base = slug(m.group(2))
        out.add(base if seen[base] == 0 else f"{base}-{seen[base]}")
        seen[base] += 1
    return out


def resolve(source: Path, target: str) -> tuple[Path, str]:
    path, _, fragment = target.partition("#")
    if not path:
        return source, fragment
    base = ROOT if path.startswith("/") else source.parent
    return (base / path.lstrip("/")).resolve(), fragment


def broken_links(source: Path) -> list[str]:
    problems = []
    for target in links(source.read_text(encoding="utf-8")):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            continue  # http, https, mailto: an outside link
        path, fragment = resolve(source, target)
        if not path.exists():
            problems.append(f"{target}: no such file")
        elif fragment and path.suffix == ".md" and fragment not in anchors(path):
            problems.append(f"{target}: no heading with the anchor #{fragment}")
    return problems


FILES = markdown_files()


@pytest.mark.parametrize("source", FILES, ids=[str(f.relative_to(ROOT)) for f in FILES])
def test_each_relative_link_and_anchor_resolves(source: Path) -> None:
    assert broken_links(source) == []


def test_the_link_check_finds_a_broken_link_and_a_broken_anchor(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "# A title\n\n[good](#a-title) [bad](#no-title) [gone](missing.md)\n"
        "`[code](missing.md)`\n\n```\n[block](missing.md)\n```\n",
        encoding="utf-8",
    )
    assert broken_links(page) == [
        "#no-title: no heading with the anchor #no-title",
        "missing.md: no such file",
    ]


@pytest.mark.parametrize(
    "heading, anchor",
    [
        ("6. Agent contract, version 1", "6-agent-contract-version-1"),
        ("7.5 OTLP receiver", "75-otlp-receiver"),
        ("`.verbatim-relay/config.json`", "verbatim-relayconfigjson"),
        (
            "P5: the model judges the record, not its memory",
            "p5-the-model-judges-the-record-not-its-memory",
        ),
        ("Isolate the app's model session", "isolate-the-apps-model-session"),
    ],
)
def test_slug_is_the_anchor_of_github(heading: str, anchor: str) -> None:
    assert slug(heading) == anchor


# Counts --------------------------------------------------------------------------------------

CASE_FOLDERS = {
    "audit": "cases",
    "contract": "contract",
    "trace": "trace",
    "seal": "seal",
    "receiver": "otlp",
}


def _cases(folder: str) -> int:
    return sum(p.is_dir() for p in (ROOT / "conformance" / folder).iterdir())


def test_the_readme_counts_each_folder_of_conformance_cases() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    found = {kind: int(n) for n, kind in re.findall(r"(\d+) (\w+) cases", text)}
    assert found == {kind: _cases(folder) for kind, folder in CASE_FOLDERS.items()}


@pytest.mark.parametrize(
    "page, phrase, count",
    [
        ("README.md", r"(\d+) break classes", len(audit.CHECKS)),
        ("docs/architecture.md", r"(\d+) break classes", len(audit.CHECKS)),
        # The prose and the diagram of the trace.
        ("docs/architecture.md", r"(\d+) checks\b", len(trace.CHECKS)),
    ],
)
def test_each_count_of_the_code_is_correct(page: str, phrase: str, count: int) -> None:
    found = re.findall(phrase, (ROOT / page).read_text(encoding="utf-8"))
    assert found and all(int(n) == count for n in found)


# The architecture page -------------------------------------------------------------------------

ARCHITECTURE = DOCS / "architecture.md"
MERMAID = re.compile(r"^```mermaid\n(.*?)^```", re.MULTILINE | re.DOTALL)
# A file name in a diagram: a record, a configuration file or the report.
RECORD_FILE = re.compile(r"[\w-]+\.(?:jsonl|json|md|log)\b")


def test_each_record_file_in_a_diagram_is_on_the_records_page() -> None:
    diagrams = MERMAID.findall(ARCHITECTURE.read_text(encoding="utf-8"))
    names = {name for diagram in diagrams for name in RECORD_FILE.findall(diagram)}
    records = (DOCS / "reference" / "records.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"`([^`]+)`", records))
    assert len(diagrams) >= 4 and names
    assert sorted(names - listed) == []


# Each constant of the timeout table: its value, the file that defines it, and the name on the
# line that the table links to. Order 2 is the agent timeout and the ANSWER limit of the test.
TIMEOUTS = {
    "stdio.TIMEOUT": (stdio.TIMEOUT, "src/verbatim_relay/stdio.py", "TIMEOUT"),
    "stdio.TIMEOUT + ANSWER": (stdio.TIMEOUT + ANSWER, "tests/test_timeouts.py", "ANSWER"),
    "bridge.TIMEOUT": (bridge.TIMEOUT, "src/verbatim_relay/bridge.py", "TIMEOUT"),
    "kit.TIMEOUT": (kit.TIMEOUT, "src/verbatim_relay/kit.py", "TIMEOUT"),
    "kit.HOOK_DEADLINE": (kit.HOOK_DEADLINE, "src/verbatim_relay/kit.py", "HOOK_DEADLINE"),
}


def test_the_timeout_table_matches_the_constants() -> None:
    section = _sections(ARCHITECTURE, "##")["Timeouts"]
    row = re.compile(r"^\| \d+ \| [^|]+ \| \[(\d+)\]\(([^)#]+)#L(\d+)\) \| `([^`]+)` \|$")
    rows = [m.groups() for m in map(row.match, section.splitlines()) if m]
    assert sorted(r[3] for r in rows) == sorted(TIMEOUTS)
    for seconds, target, line, constant in rows:
        value, file, name = TIMEOUTS[constant]
        path = (ARCHITECTURE.parent / target).resolve()
        assert (int(seconds), path.relative_to(ROOT).as_posix()) == (value, file), constant
        source = path.read_text(encoding="utf-8").splitlines()[int(line) - 1]
        assert source.startswith(f"{name} = "), f"{target}#L{line}: {source}"


# The map of the docs ---------------------------------------------------------------------------


def test_each_docs_page_is_on_the_map() -> None:
    index = DOCS / "index.md"
    linked = {resolve(index, t)[0] for t in links(index.read_text(encoding="utf-8"))}
    pages = {p.resolve() for p in DOCS.rglob("*.md")} - {index.resolve()}
    assert sorted(str(p.relative_to(ROOT)) for p in pages - linked) == []


# Reference pages -----------------------------------------------------------------------------


def _sections(path: Path, level: str) -> dict[str, str]:
    """The body of each heading of one level, by the heading text without backticks. A body ends
    at the next heading of the same level or a higher one."""
    text = path.read_text(encoding="utf-8")
    pattern = rf"^{level} (.+?)[ \t]*\n(.*?)(?=^#{{1,{len(level)}}} |\Z)"
    return {
        m.group(1).replace("`", ""): m.group(2)
        for m in re.finditer(pattern, text, re.MULTILINE | re.DOTALL)
    }


def _parser() -> argparse.ArgumentParser:
    """The parser that cli.main builds, without a parse."""

    class Built(Exception):
        pass

    def stop(self: argparse.ArgumentParser, *args: Any, **kwargs: Any) -> None:
        raise Built(self)

    original = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = stop
    try:
        cli.main([])
    except Built as built:
        return built.args[0]
    finally:
        argparse.ArgumentParser.parse_args = original
    raise AssertionError("cli.main did not build a parser")


def _commands() -> dict[str, argparse.ArgumentParser]:
    sub = next(a for a in _parser()._actions if isinstance(a, argparse._SubParsersAction))
    return dict(sub.choices)


def _documented(action: argparse.Action) -> str | None:
    """The name of an argument on the CLI page, or None if the parser hides it."""
    if action.help == argparse.SUPPRESS or isinstance(action, argparse._HelpAction):
        return None
    if action.option_strings:
        return max(action.option_strings, key=len)
    return (action.metavar if isinstance(action.metavar, str) else action.dest).upper()


def test_the_cli_page_has_each_command_and_each_flag() -> None:
    page = _sections(DOCS / "reference" / "cli.md", "###")
    commands = _commands()
    assert sorted(page) == sorted(f"verbatim-relay {name}" for name in commands)
    for name, parser in commands.items():
        section = page[f"verbatim-relay {name}"]
        rows = set(re.findall(r"^\| `(--[a-z][a-z-]*|[A-Z]+)\b", section, re.MULTILINE))
        wanted = {d for d in map(_documented, parser._actions) if d}
        assert rows == wanted, name


def _row_defaults(section: str) -> dict[str, str]:
    """The key and the default of each row of the tables in a section."""
    rows = re.findall(r"^\| `([a-z_]+)` \| [^|]+ \| ([^|]+) \|", section, re.MULTILINE)
    return {key: default.strip() for key, default in rows}


def _cell(default: Any) -> str:
    if default == "":
        return "empty"
    return f"`{default}`" if isinstance(default, str) else f"`{json.dumps(default)}`"


def test_the_config_page_has_each_key_of_config_json_with_its_default() -> None:
    page = _sections(DOCS / "reference" / "config.md", "##")
    documented = _row_defaults(page[".verbatim-relay/config.json"])
    wanted = {}
    for f in fields(config.Config):
        default = f.default if f.default is not MISSING else f.default_factory()
        wanted[f.name] = _cell(default)
    assert documented == wanted


def test_the_config_page_has_each_plugin_option_with_its_default() -> None:
    manifest = ROOT / "plugins" / "claude-code" / ".claude-plugin" / "plugin.json"
    options = json.loads(manifest.read_text(encoding="utf-8"))["userConfig"]
    documented = _row_defaults(_sections(DOCS / "reference" / "config.md", "##")["Plugin options"])
    assert documented == {key: _cell(o.get("default", "")) for key, o in options.items()}

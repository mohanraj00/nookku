"""The docs agree with the repo: links resolve, counts match the data, and the reference pages
match the CLI parser and config.Config."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

import pytest
from test_timeouts import ANSWER

from nookku import __version__, audit, bridge, cli, config, kit, print_mode, stdio, trace

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
        ("`.nookku/config.json`", "nookkuconfigjson"),
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
    "notes": "notes",
    "discovery": "discovery",
}


def _cases(folder: str) -> int:
    # A case is a folder, or a JSON file for the discovery cases.
    return sum(p.is_dir() or p.suffix == ".json" for p in (ROOT / "conformance" / folder).iterdir())


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
        ("docs/how-to/read-the-results.md", r"(\d+) break classes", len(audit.CHECKS)),
        ("docs/how-to/read-the-results.md", r"(\d+) trace checks", len(trace.CHECKS)),
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
    "stdio.TIMEOUT": (stdio.TIMEOUT, "src/nookku/stdio.py", "TIMEOUT"),
    "stdio.TIMEOUT + ANSWER": (stdio.TIMEOUT + ANSWER, "tests/test_timeouts.py", "ANSWER"),
    "state.TIMEOUT": (bridge.TIMEOUT, "src/nookku/state.py", "TIMEOUT"),
    "kit.TIMEOUT": (kit.TIMEOUT, "src/nookku/kit.py", "TIMEOUT"),
    "kit.HOOK_DEADLINE": (kit.HOOK_DEADLINE, "src/nookku/kit.py", "HOOK_DEADLINE"),
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


CHECK_PAGES = [
    "docs/getting-started.md",
    "docs/how-to/connect-your-agent.md",
    "docs/reference/cli.md",
    "src/nookku/setup.md",
]


@pytest.mark.parametrize("page", CHECK_PAGES)
def test_each_page_that_runs_check_gives_the_default_check_message(page: str) -> None:
    text = (ROOT / page).read_text(encoding="utf-8")
    assert f"`{bridge.CHECK_MESSAGE}`" in text


TEST_ID = re.compile(r"\b\d{8}-\d{6}-[0-9a-f]{4}\b")


def test_the_tutorial_output_comes_from_one_run() -> None:
    # The tutorial makes 2 tests: the test of check and the test in Claude Code. The ls step
    # lists the 2 test folders of the run. Each test id on the page is one of these 2 (#168).
    text = (DOCS / "getting-started.md").read_text(encoding="utf-8")
    listing = re.search(r"^```bash\nls \.nookku/tests/\n```\n\n```text\n(.+?)\n```$", text, re.M)
    assert listing, "the tutorial has no ls step with its output"
    folders = TEST_ID.findall(listing.group(1))
    assert len(folders) == 2
    assert sorted(set(TEST_ID.findall(text))) == sorted(folders)
    # The data of the run has the same 2 test ids (scripts/proof_tutorial.py).
    data = (ROOT / "proofs" / "tutorial" / "output.txt").read_text(encoding="utf-8")
    assert sorted(set(TEST_ID.findall(data))) == sorted(folders)
    # The versions of the run come from the same run.
    run = json.loads((ROOT / "proofs" / "tutorial" / "run.json").read_text(encoding="utf-8"))
    assert sorted(run["tests"]) == sorted(folders)


# The map of the docs ---------------------------------------------------------------------------


def _on_the_map() -> set[Path]:
    index = DOCS / "index.md"
    return {resolve(index, t)[0] for t in links(index.read_text(encoding="utf-8"))}


def test_each_docs_page_is_on_the_map() -> None:
    # A moved page only keeps old links, so the map does not list it (#260).
    skipped = {(DOCS / "index.md").resolve()} | {(ROOT / page).resolve() for page in KEPT_ANCHORS}
    pages = {p.resolve() for p in DOCS.rglob("*.md")} - skipped
    assert sorted(str(p.relative_to(ROOT)) for p in pages - _on_the_map()) == []


def test_no_moved_page_is_on_the_map() -> None:
    moved = {(ROOT / page).resolve() for page in KEPT_ANCHORS}
    assert sorted(str(p.relative_to(ROOT)) for p in moved & _on_the_map()) == []


# A page that moved or split keeps the anchor of each old section, so old links still work.
KEPT_ANCHORS = {
    "docs/claude-code.md": {
        "connect-a-test-to-your-app",
        "backends",
        "direct-model-calls",
        "opentelemetry",
        "isolate-the-apps-model-session",
        "plugin",
        "evaluation",
        "hook-kit",
        "an-agent-that-runs-as-an-http-server",
        "audit",
    },
    "docs/codex.md": {"install", "use", "audit"},
    "docs/how-to/claude-code.md": {"plugin", "hook-kit", "evaluation", "audit", "more"},
    "docs/how-to/claude-code-hook-kit.md": {
        "install",
        "run-a-test",
        "what-the-model-can-do",
        "evaluation",
        "audit",
        "more",
    },
    # The contributor pages moved to docs/contributing/ (#306).
    "docs/code-quality.md": {
        "rules",
        "1-fail-closed",
        "2-exact-bytes",
        "3-one-rule-one-copy",
        "4-records",
        "5-no-secrets",
        "6-timeouts",
        "7-errors",
        "8-tests",
        "9-dependencies-types-and-lint",
        "10-docs-and-claims",
    },
    "docs/codex-display.md": {"what-i-found", "run-the-method", "recommendation-for-the-adr"},
    "docs/adr/0001-one-core-one-plugin.md": {
        "context",
        "can-a-command-hook-show-the-reply-claude-code-176",
        "can-a-command-hook-show-the-reply-codex-193",
        "codex-plugin-hooks-and-the-trust-step-177",
        "can-a-plugin-mcp-server-give-the-model-the-transcript-178-194",
        "what-a-codex-plugin-can-show-205",
        "time-that-a-python-hook-process-adds-179",
        "decision",
        "options-that-i-did-not-take",
        "consequences",
        "change-the-tagline",
        "change-the-description",
    },
    "docs/how-to/run-the-proofs.md": {
        "before-you-start",
        "trust-the-codex-hooks-once",
        "the-commands",
        "after-a-run",
    },
}


@pytest.mark.parametrize("page", sorted(KEPT_ANCHORS))
def test_a_moved_page_keeps_each_old_anchor(page: str) -> None:
    assert sorted(KEPT_ANCHORS[page] - anchors(ROOT / page)) == []


def test_the_docs_table_of_the_readme_lists_each_how_to_guide() -> None:
    # A moved page only keeps old links, so the table does not list it.
    readme = ROOT / "README.md"
    linked = {resolve(readme, t)[0] for t in links(_sections(readme, "##")["Docs"])}
    moved = {(ROOT / page).resolve() for page in KEPT_ANCHORS}
    guides = {p.resolve() for p in (DOCS / "how-to").glob("*.md")} - moved
    assert sorted(str(p.relative_to(ROOT)) for p in guides - linked) == []


# Mermaid ---------------------------------------------------------------------------------------

MERMAID = re.compile(r"^```mermaid[ \t]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
# The diagram types that GitHub renders and that the docs use.
MERMAID_TYPES = ("flowchart ", "sequenceDiagram", "stateDiagram-v2")
# Syntax that GitHub does not render, or that breaks a diagram: the node shapes of @{ },
# click actions, styles, and the word end as a node id.
MERMAID_BANNED = re.compile(
    r"@\{|^\s*(click|style|classDef|class|linkStyle)\b|"
    r"(-->|---|-\.->|==>|\|)\s*end\b|^\s*end\b(?!\s*$)|\bend\s*(\[|\(|\{|-->|---|-\.->|==>)",
    re.MULTILINE,
)


def test_each_mermaid_diagram_has_a_type_and_syntax_that_github_renders() -> None:
    blocks = [
        (path, block)
        for path in DOCS.rglob("*.md")
        for block in MERMAID.findall(path.read_text(encoding="utf-8"))
    ]
    assert blocks
    for path, block in blocks:
        assert block.lstrip().startswith(MERMAID_TYPES), path
        assert MERMAID_BANNED.findall(block) == [], path


@pytest.mark.parametrize(
    "line",
    [
        "a --> end",
        "end[Done]",
        "end --> a",
        "a --> b@{ shape: rect }",
        "click a call f()",
        "style a fill:#f00",
    ],
)
def test_the_mermaid_check_finds_banned_syntax(line: str) -> None:
    assert MERMAID_BANNED.search(line)


@pytest.mark.parametrize(
    "page",
    [
        "README.md",
        "docs/how-to/test-your-app.md",
    ],
)
def test_each_page_that_starts_the_setup_gives_the_form_that_runs_the_command(page: str) -> None:
    # A prompt of only "nookku setup" did not make the model run the command (#125).
    assert "!nookku setup" in (ROOT / page).read_text(encoding="utf-8")


SETUP = ROOT / "src" / "nookku" / "setup.md"
# The setup text ships in the package, so its link uses the release tag, as `[project.urls]` does
# (#305, #358). A release changes the tag.
NODE_WARNING = (
    f"https://github.com/mohanraj00/nookku/blob/v{__version__}/docs/how-to/connect-your-agent.md"
)


def test_the_setup_skill_checks_the_reply_and_app_log_after_a_pass() -> None:
    # A check of a real app printed PASS with an error text as the reply, and the model
    # stopped (#161). The setup skill gives 3 steps after a PASS.
    check = _sections(SETUP, "##")["4. Check"]
    after = check.split("After a PASS, do these 3 steps:", 1)
    assert len(after) == 2, "the check section has no steps after a PASS"
    steps = re.findall(r"^\d+\. (.+)$", after[1], re.MULTILINE)
    assert len(steps) == 3
    reply, log, node = steps
    assert "`Reply:`" in reply and "error text" in reply and "not done" in reply
    # An app can decline the default check message in normal use. Then the step changes the
    # config key, not the entry.
    assert "`check_message`" in reply
    assert "`app.log`" in log and "errors" in log and "tracebacks" in log
    # A warning that the app also writes in normal use does not stop the setup.
    assert "normal use" in log
    assert "`node:readline`" in node and "In Node 25" in node
    assert "U+2028" in node and "U+2029" in node
    link = re.search(rf"\]\({re.escape(NODE_WARNING)}#([\w-]+)\)", node)
    assert link, "the Node step has no link to the warning"
    page = DOCS / "how-to" / "connect-your-agent.md"
    assert link.group(1) in anchors(page)
    assert "U+2028" in _sections(page, "###")["In Node"]


# The first screen of the README ------------------------------------------------------------------

DESCRIPTION = "an evaluation harness for vertical AI agents"


def test_the_readme_gives_the_description_one_time_at_the_top() -> None:
    # The description gives the goal, and byte for byte is the guarantee under it (#313).
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count(f"**Nookku: {DESCRIPTION}**") == 1
    assert readme.index(DESCRIPTION) < readme.index("## ")


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        ".claude-plugin/marketplace.json",
        "plugins/nookku/.claude-plugin/plugin.json",
        "plugins/nookku/.codex-plugin/plugin.json",
        "docs/index.md",
        "CLAUDE.md",
        "AGENTS.md",
    ],
)
def test_each_description_of_the_project_is_the_readme_description(path: str) -> None:
    assert DESCRIPTION.lower() in (ROOT / path).read_text(encoding="utf-8").lower()


QUOTED = re.compile(r"\"[^\"\n]*\"")


def test_harness_has_one_meaning_in_the_docs() -> None:
    # "Harness" means a coding harness, Claude Code or Codex. Nookku is not a harness (#166).
    # Quoted text keeps its words, for example the first tagline in the ADR.
    pages = [ROOT / "README.md", *(p for p in markdown_files() if DOCS in p.parents)]
    found = [
        str(p.relative_to(ROOT))
        for p in pages
        if re.search(r"test[ -]harness", QUOTED.sub("", prose(p.read_text("utf-8"))), re.I)
    ]
    assert found == []


def test_the_try_of_the_readme_gives_the_output_that_it_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The try runs the entry and the script of the README, with no harness and no model (#256).
    section = _sections(ROOT / "README.md", "##")["Try it with no model"]
    commands, shown = (m.group(2) for m in re.finditer(r"```(\w+)\n(.*?)```", section, re.DOTALL))
    entry = re.search(r'--entry "python3 ([^"]+)"', commands)
    script = re.search(r"nookku run --script (\S+) --no-evaluate", commands)
    assert entry and script
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(ROOT / entry.group(1))]}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf), encoding="utf-8")
    args = ["run", "--script", str(ROOT / script.group(1)), "--root", str(root), "--no-evaluate"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Test ") and out[1:] == shown.splitlines()


def test_the_sample_report_of_the_readme_is_an_excerpt_of_its_data() -> None:
    # Each line of the excerpt is a line of the real report, in its order (#257).
    # A "..." line marks a cut.
    # The excerpt has its own headings, so the section ends at the heading after the code block.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    found = re.search(r"^## A sample report\n(.*?```.*?```.*?)(?=^## )", readme, re.M | re.S)
    assert found
    section = found.group(1)
    excerpt = re.search(r"```markdown\n(.*?)```", section, re.DOTALL)
    data = re.search(r"\[[^]]+\]\((proofs/report/[^)]+\.json)\)", section)
    assert excerpt and data
    proof = json.loads((ROOT / data.group(1)).read_text(encoding="utf-8"))
    lines = proof["report"].split("\n")
    at = 0
    for line in excerpt.group(1).splitlines():
        if line == "...":
            continue
        assert line in lines[at:], line
        at = lines.index(line, at) + 1
    rows = sum(1 for line in lines if line.startswith("| ") and line.count("|") > 4) - 1
    notes = sum(1 for line in lines if line.startswith("- "))
    assert f"The full report has {rows} rows and {notes} notes." in section


CAPTURE = re.compile(
    r'<img src="https://raw\.githubusercontent\.com/mohanraj00/nookku/main/([^"]+\.png)" '
    r'alt="([^"]+)"'
)


def test_the_capture_of_the_chat_page_has_its_record_and_shows_on_pypi(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # PyPI shows only an absolute image URL. The record of the run is next to the image (#307).
    section = _sections(ROOT / "README.md", "##")["Try it with no model"]
    found = CAPTURE.search(section)
    assert found, "the try has no capture with an absolute URL and alt text"
    image = ROOT / found.group(1)
    data = image.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) < 300_000
    assert len(found.group(2).split()) >= 10
    folder = image.parent
    assert f"({folder.relative_to(ROOT)}/test/)" in section
    assert f"({folder.relative_to(ROOT)}/capture.json)" in section
    method = json.loads((folder / "capture.json").read_text(encoding="utf-8"))
    test = folder / method["record"]
    relay = [json.loads(line) for line in (test / "relay.jsonl").read_text("utf-8").splitlines()]
    script = (test / "script.jsonl").read_text(encoding="utf-8").splitlines()
    assert [turn["said"] for turn in relay] == [json.loads(line)["said"] for line in script]
    tap, rel = str(test / "tap.jsonl"), str(test / "relay.jsonl")
    assert cli.main(["audit", "--tap", tap, "--relay", rel]) == 0
    capsys.readouterr()
    # The page URL, its token and the local paths of the run stay out of the repo.
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl"}:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"https?://|127\.0\.0\.1|/p/|/Users/|/home/|/tmp/", text), path


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
    """Each command by its first name. An alias, such as page for chat, has no section."""
    sub = next(a for a in _parser()._actions if isinstance(a, argparse._SubParsersAction))
    commands: dict[str, argparse.ArgumentParser] = {}
    for name, parser in sub.choices.items():
        if parser not in commands.values():
            commands[name] = parser
    return commands


def _documented(action: argparse.Action) -> list[str]:
    """The names of an argument on the CLI page, or none if the parser hides it. A flag with a
    --no- form, such as --openai-stream, has 2 names, and the page must give both (#120)."""
    if action.help == argparse.SUPPRESS or isinstance(action, argparse._HelpAction):
        return []
    if action.option_strings:
        return list(action.option_strings)
    return [(action.metavar if isinstance(action.metavar, str) else action.dest).upper()]


def test_the_cli_page_has_each_command_and_each_flag() -> None:
    page = _sections(DOCS / "reference" / "cli.md", "###")
    commands = _commands()
    assert sorted(page) == sorted(f"nookku {name}" for name in commands)
    for name, parser in commands.items():
        section = page[f"nookku {name}"]
        # Each flag in the first cell of a row, for example `--no-evaluate`, `--evaluate`.
        cells = re.findall(r"^\| ((?:`[^`]+`(?:, )?)+) \|", section, re.MULTILINE)
        rows = {m for cell in cells for m in re.findall(r"`(--[a-z][a-z-]*|[A-Z]+)\b", cell)}
        wanted = {d for action in parser._actions for d in _documented(action)}
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
    documented = _row_defaults(page[".nookku/config.json"])
    wanted = {}
    for f in fields(config.Config):
        default = f.default if f.default is not MISSING else f.default_factory()
        wanted[f.name] = _cell(default)
    assert documented == wanted


GLOSSARY_TERMS = {
    "Agent contract",
    "Audit",
    "Bridge",
    "Entry",
    "Evaluation",
    "Findings",
    "Harness",
    "Relay",
    "Relay mode",
    "Scripted test",
    "Seal",
    "Tap",
    "Test folder",
    "Trace",
}


def test_each_glossary_term_links_to_a_section_of_the_spec() -> None:
    glossary = DOCS / "reference" / "glossary.md"
    terms = _sections(glossary, "##")
    assert sorted(GLOSSARY_TERMS - set(terms)) == []
    spec = (ROOT / "SPEC.md").resolve()
    for term, body in terms.items():
        targets = [resolve(glossary, t) for t in links(body)]
        assert any(path == spec and fragment for path, fragment in targets), term


GLOSSARY = (DOCS / "reference" / "glossary.md").resolve()
# The docs use these terms as plain words on almost each page, for example "test your app", "the
# agent of the toy shop" and "the plugins of Codex". A link on each first use can point to the
# wrong meaning, so the test does not check them.
PLAIN_WORDS = {"Agent", "Plugin", "Test"}
# A count before a term in a phrase that a test reads, for example "10 trace checks". The test
# of each count reads these phrases, so they are not a use of the term.
COUNTED = re.compile(r"\b\d+ (?:break classes|trace checks)\b")
# Phrases on a page that use a term with its plain meaning before its glossary meaning. A link
# there points to the wrong meaning, so the test does not count them as a use.
PLAIN_USES = {
    # "break" as a verb: the display layer stops.
    "docs/contributing/adr/0001-one-core-one-plugin.md": ("If they break",),
    # "breaks" as a verb: the script does not obey a rule.
    "docs/reference/cli.md": ("the script breaks a rule",),
}
# "Evaluation harness" names the kind of tool that Nookku is (#313). Its 2 words do not have
# their glossary meanings there, on each page.
PLAIN_EVERYWHERE = re.compile(r"evaluation harness", re.IGNORECASE)
# The link of a glossary term with no fragment: a link to the top of the glossary.
NO_FRAGMENT = "(top of the glossary)"
# An inline link, with its text in group 1 and its target in group 2.
TEXT_LINK = re.compile(
    r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)"
)
HTML_TAG = re.compile(r"<[^>]+>")


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    """The text with each match changed to spaces. Each other character keeps its place."""
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _forms(name: str) -> list[str]:
    """The singular and the plural of a term, for example "entry" and "entries". A heading in the
    plural, for example "Findings", also gives its singular "finding". A singular that ends in
    "ss", for example "Harness", keeps its plural "harnesses"."""
    lower = name.lower()
    if re.search(r"[^aeiou]y$", lower):
        return [lower, lower[:-1] + "ies"]
    forms = [lower, lower + "s", lower + "es"]
    if re.search(r"[^s]s$", lower):
        forms.append(lower[:-1])
    return forms


def _term_pattern(forms: list[str]) -> re.Pattern[str]:
    """A use of a term. The longest form wins, so "relay mode" is not a use of "relay". A file
    name or a path, as in "audit.json", is not a use."""
    alternatives = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile(rf"(?<![\w./#-])({alternatives})(?![\w/-]|\.\w)", re.IGNORECASE)


def first_uses(text: str, page: Path) -> list[tuple[str, int, int, str | None]]:
    """The first use of each glossary term in the prose of a page: the term, the start and the
    end of the use in the text, and the anchor of its glossary link, or None with no link. Code,
    comments, HTML tags, headings and the text of other links are not prose."""
    by_form = {form: name for name in _sections(GLOSSARY, "##") for form in _forms(name)}
    pattern = _term_pattern(list(by_form))
    masked = text
    for part in (FENCE, COMMENT, CODE_SPAN, HTML_TAG, HEADING, COUNTED, PLAIN_EVERYWHERE):
        masked = _blank(masked, part)
    if page.resolve().is_relative_to(ROOT):
        for phrase in PLAIN_USES.get(page.resolve().relative_to(ROOT).as_posix(), ()):
            masked = _blank(masked, re.compile(re.escape(phrase)))
    # Each part of the text: its start, its end and the anchor of its glossary link. Plain text
    # has the anchor None, and the text of another link has the anchor "".
    parts: list[tuple[int, int, str | None]] = []
    end = 0
    for m in TEXT_LINK.finditer(masked):
        parts.append((end, m.start(), None))
        path, fragment = resolve(page, m.group(2))
        anchor = (fragment or NO_FRAGMENT) if path == GLOSSARY else ""
        parts.append((m.start(1), m.end(1), anchor))
        end = m.end()
    parts.append((end, len(masked), None))
    seen: dict[str, tuple[str, int, int, str | None]] = {}
    for start, stop, anchor in parts:
        if anchor == "":
            continue
        for m in pattern.finditer(masked, start, stop):
            name = by_form.get(m.group(1).lower())
            if name is not None and name not in seen:
                seen[name] = (name, m.start(), m.end(), anchor)
    return sorted(seen.values(), key=lambda use: use[1])


def unlinked_first_uses(text: str, page: Path) -> list[str]:
    """Each glossary term whose first use on the page is not a link to its glossary section."""
    return [
        f"{name}: {text[start:end]!r}"
        for name, start, end, anchor in first_uses(text, page)
        if name not in PLAIN_WORDS and anchor != slug(name)
    ]


DOCS_PAGES = sorted(p for p in DOCS.rglob("*.md") if p.resolve() != GLOSSARY)


@pytest.mark.parametrize("page", DOCS_PAGES, ids=[str(p.relative_to(ROOT)) for p in DOCS_PAGES])
def test_each_docs_page_links_the_first_use_of_each_glossary_term(page: Path) -> None:
    assert unlinked_first_uses(page.read_text(encoding="utf-8"), page) == []


@pytest.mark.parametrize(
    "text, wanted",
    [
        # The first use has no link, and a later use has one.
        ("The audit runs. The [audit](../reference/glossary.md#audit) ends.", ["Audit: 'audit'"]),
        # The link goes to the section of another term.
        ("The [tap](../reference/glossary.md#trace) runs.", ["Tap: 'tap'"]),
        # Each first use has its link. "Relay mode" is not a use of "relay".
        (
            "[Relay mode](../reference/glossary.md#relay-mode) and "
            "[relays](../reference/glossary.md#relay).",
            [],
        ),
        # The plural of a term that ends in "y".
        ("Two entries. The [entry](../reference/glossary.md#entry) runs.", ["Entry: 'entries'"]),
        # The singular of a term whose heading is in the plural.
        ("One finding.", ["Findings: 'finding'"]),
        # The plural of a singular term that ends in "s".
        ("Two harnesses.", ["Harness: 'harnesses'"]),
        # A glossary link with no fragment goes to the top of the glossary.
        ("The [seal](../reference/glossary.md) runs.", ["Seal: 'seal'"]),
        # A count is not a use only in a phrase that a test reads.
        ("10 trace checks and 4 break classes.", []),
        ("2 seals and 3 taps.", ["Seal: 'seals'", "Tap: 'taps'"]),
        # A file name, a code span, a heading, another link and a plain word.
        ("# Audit\n\naudit.json, `seal`, [entry.py](e.py), test the agent.", []),
    ],
)
def test_the_glossary_check_finds_a_first_use_with_no_link(text: str, wanted: list[str]) -> None:
    assert unlinked_first_uses(text, DOCS / "how-to" / "example.md") == wanted


def _first_cells(section: str) -> list[str]:
    """The name in the first cell of each table row of a section, in the order of the rows."""
    return re.findall(r"^\| `([a-z_]+)` \|", section, re.MULTILINE)


def test_the_results_guide_names_each_break_class_and_each_trace_check() -> None:
    page = _sections(DOCS / "how-to" / "read-the-results.md", "###")
    assert _first_cells(page["Break classes"]) == list(audit.CHECKS)
    assert _first_cells(page["Trace checks"]) == list(trace.CHECKS)


# How-to pages that name parts of the code ------------------------------------------------------


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_the_remove_page_names_each_hook_that_init_writes(harness: str, tmp_path: Path) -> None:
    """The remove page tells the tester which hook entries to remove. If init writes another
    event, matcher or timeout, the page must change too."""
    kit.init(tmp_path, harness, {})
    hook_file = kit.hook_file(tmp_path, harness)
    page = (DOCS / "how-to" / "remove.md").read_text(encoding="utf-8")
    assert f"`{hook_file.relative_to(tmp_path)}`" in page
    for event, groups in json.loads(hook_file.read_text(encoding="utf-8"))["hooks"].items():
        (group,) = groups
        (hook,) = group["hooks"]
        assert "nookku hook" in hook["command"]
        assert f"`hooks.{event}`" in page
        assert f'"timeout": {hook["timeout"]}' in page
        if "matcher" in group:
            assert f'"matcher": "{group["matcher"]}"' in page
    assert "`nookku hook`" in page


def test_the_upgrade_page_has_a_section_for_each_release_with_an_upgrade_step() -> None:
    changelog = _sections(ROOT / "CHANGELOG.md", "##")
    special = sorted(v for v, body in changelog.items() if "**Upgrade.**" in body)
    page = _sections(DOCS / "how-to" / "upgrade.md", "###")
    assert special
    assert [v for v in special if v not in page] == []


def test_ci_pins_the_claude_code_version_of_the_plugin_proofs_and_the_faq_names_it() -> None:
    """CLAUDE.md says that CI pins the tested version. The tested version is the one in the
    results of the plugin proofs."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pins = re.findall(r"@anthropic-ai/claude-code@(\S+)", ci)
    results = (ROOT / "proofs" / "plugin-claude-code" / "results.json").read_text(encoding="utf-8")
    tested = set(re.findall(r"\"version\": \"(\S+) \(Claude Code\)\"", results))
    assert len(tested) == 1, tested
    assert pins == sorted(tested)
    faq = (DOCS / "faq.md").read_text(encoding="utf-8")
    assert f"CI pins Claude Code {pins[0]} " in faq


def test_the_print_mode_refusal_links_a_heading_of_the_troubleshooting_page() -> None:
    """The link names the release tag, so the heading must be in the docs of this version."""
    assert print_mode.ANCHOR in anchors(DOCS / "troubleshooting.md")
    assert print_mode.DOCS.startswith(f"https://github.com/mohanraj00/nookku/blob/v{__version__}/")

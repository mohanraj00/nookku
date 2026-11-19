"""The deny of writes to the state folder (SPEC.md section 5, #149): it checks paths, not text."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from nookku import commands, kit

STATE = "." + "nookku"
CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "guard").glob("*.json"))
SED = '"sed" with these arguments can write.'


def _fill(value: Any, root: Path, tests: Path) -> Any:
    if isinstance(value, str):
        value = value.replace("{root}", str(root)).replace("{tests}", str(tests))
        return value.replace("{volume}", str(tests.parent))
    if isinstance(value, dict):
        return {k: _fill(v, root, tests) for k, v in value.items()}
    return value


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_conformance(case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = json.loads(case.read_text())
    root = (tmp_path / "shop").resolve() if "tests_dir" in data else tmp_path.resolve()
    # A tests folder outside the project, as on a mounted volume (#457).
    tests = tmp_path.resolve() / "volume" / "tests"
    folder = (tests if "tests_dir" in data else root / STATE / "tests") / "t1"
    folder.mkdir(parents=True)
    (root / STATE).mkdir(parents=True, exist_ok=True)
    if data.get("tests_dir") == "variable":
        monkeypatch.setenv("NOOKKU_TESTS_DIR", str(tests))
    if data.get("tests_dir") == "remembered":
        # A test that --tests-dir started, and that ended: only the state file names the folder.
        kit.state.remember_tests_dir(root, tests)
    if "tests_dirs_text" in data:
        text = _fill(data["tests_dirs_text"], root, tests)
        (root / STATE / kit.state.TESTS_DIRS).write_text(text)
    if "policy_text" in data:
        (root / STATE / "policy.json").write_text(data["policy_text"])
    for link, target in data["links"].items():
        (root / link).parent.mkdir(parents=True, exist_ok=True)
        (root / link).symlink_to(root / target)
    if data["test"]:
        cur = {"dir": str(folder), "tap_url": "http://127.0.0.1:9/"}
        monkeypatch.setattr(kit.state, "current", lambda root: cur)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.chdir(root)
    out = io.StringIO()
    event = io.StringIO(json.dumps(_fill(data["event"], root, tests)))
    assert kit.run_hook(None, "claude-code", event, out) == 0
    answer = json.loads(out.getvalue()) if out.getvalue() else None
    assert answer == _fill(data["answer"], root, tests)


@pytest.mark.parametrize(
    ("command", "targets", "folders", "cause"),
    [
        ("sed -i '' s/a/b/ shop.json", ["-i", "", "s/a/b/", "shop.json"], [], SED),
        ("cat shop.json > out.txt", ["out.txt"], [], 'The redirect ">" writes it.'),
        ("grep -n refund shop.py 2>/dev/null", ["/dev/null"], [], 'The redirect ">" writes it.'),
        ("cd shop && make", [], ["shop"], '"make" is not a read command.'),
        ("python3 <<< 'print(1)'", ["print(1)"], [], '"python3" is not a read command.'),
        ("cat a.txt; echo ${x} $y", [], [], ""),
        (
            "PATH=/tmp cat a.txt",
            [],
            [],
            'The read check does not accept the assignment "PATH=/tmp".',
        ),
        ("IFS=x; cat a.txt", [], [], 'The read check does not accept the assignment "IFS=x".'),
    ],
)
def test_write_targets(command: str, targets: list[str], folders: list[str], cause: str) -> None:
    found = commands.write_targets(command)
    assert found is not None
    assert [w for w, _ in found.targets] == targets
    assert (found.folders, found.cause) == (folders, cause)


def test_guard_reads_adds_programs_but_keeps_each_built_in_check() -> None:
    assert not commands.reads_only("bat shop.json")
    assert commands.reads_only("bat shop.json", frozenset({"bat"}))
    assert not commands.reads_only("sed -i '' s/a/b/ shop.json", frozenset({"sed"}))


def test_a_command_that_the_check_cannot_parse_has_no_targets() -> None:
    assert commands.write_targets("echo $(date) > out.txt") is None


def test_a_heredoc_body_of_code_stays() -> None:
    data = "cat > notes.md <<'EOF'\nsecret\nEOF\necho done"
    assert commands.strip_data_heredocs(data) == "cat > notes.md <<'EOF'\necho done"
    code = "python3 - <<'EOF'\nprint(1)\nEOF"
    assert commands.strip_data_heredocs(code) == "python3 - <<'EOF'\nprint(1)"
    commit = "git commit -F - <<'EOF'\nFix it\nEOF"
    assert commands.strip_data_heredocs(commit) == "git commit -F - <<'EOF'"


@pytest.mark.parametrize(
    ("word", "rest"),
    [
        (f"{STATE}/tests/t1/tap.jsonl", ["tests", "t1", "tap.jsonl"]),
        (f"/home/me/shop/{STATE.upper()}/mode", ["mode"]),
        (f"of={STATE}/relay.jsonl", ["relay.jsonl"]),
        (f"{STATE}/tests/../config.json", ["config.json"]),
        (".noo*/mode", ["mode"]),
        ("*/mode", None),
        ("shop/config.json", None),
    ],
)
def test_state_rest(word: str, rest: list[str] | None) -> None:
    assert commands.state_rest(word) == rest


@pytest.mark.parametrize(
    ("command", "what"),
    [
        ("nookku start", "nookku start"),
        ("X=1 nookku end", "nookku end"),
        ("nookku mode --root . on", "nookku mode on"),
        ("time python3 -m nookku start", "nookku start"),
        ("uv run --with shop nookku end", "nookku end"),
        ("sudo -u shop nookku hook", "nookku hook"),
        ("env A=1 bash -lc 'nookku end'", "nookku end"),
        ("pipx run nookku run --script s.jsonl", "nookku run"),
        ("nookku chat", "nookku chat"),
        ("uv run nookku chat --port 8080", "nookku chat"),
        ("nookku chat --open", "nookku chat"),
        # The old name of nookku chat works for one release, so the relay denies it too (#394).
        ("nookku page", "nookku page"),
        ("uv run nookku page --port 8080", "nookku page"),
        ("nookku page --open", "nookku page"),
        ("bash -c 'nookku page'", "nookku page"),
        ("echo 'nookku chat' | sh", "nookku chat"),
        ("env -S'nookku page --open'", "nookku page"),
        ("nookku chat 'no end", "nookku chat"),
        ("nookku page 'no end", "nookku page"),
        ("echo $(nookku start)", "nookku start"),
        ("uv run --python python3 nookku start", "nookku start"),
        ("env -u HOME python3 -m nookku end", "nookku end"),
        ("uv run --python python3 shop/agent.py", None),
        ("env -S 'nookku start'", "nookku start"),
        ("env -S'nookku end'", "nookku end"),
        ("bash -c -- 'nookku start'", "nookku start"),
        ("python -mnookku start", "nookku start"),
        ("python -Im nookku end", "nookku end"),
        ("python3 -X dev -m nookku start", "nookku start"),
        ("python3 -W ignore -mnookku.kit", commands.IMPORT),
        ("echo 'nookku start' | env bash", "nookku start"),
        ("bash -c 'echo nookku start'", None),
        ("python3 shop/agent.py -m nookku start", None),
        ("cat shop/run.sh | bash", None),
        ("python --check-hash-based-pycs always -m nookku start", "nookku start"),
        ("printf 'nookku start' | bash -s refund", "nookku start"),
        ("echo 'nookku start' | bash -o pipefail", "nookku start"),
        ("echo 'nookku start' | bash shop/run.sh", None),
        ("env NOTE='nookku start' echo ok", None),
        ("env -vS'nookku end'", "nookku end"),
        ("python -m nookku.kit", commands.IMPORT),
        ("python3 -c 'from nookku import kit'", commands.IMPORT),
        ("python3 -c \"__import__('nookku')\"", commands.IMPORT),
        # Only a person writes an adjudication (#548).
        ("nookku adjudicate t1 --turn 2 --outcome key_wrong --reason x", "nookku adjudicate"),
        ("uv run nookku adjudicate --root . t1 --turn 2", "nookku adjudicate"),
        ("bash -c 'nookku adjudicate t1'", "nookku adjudicate"),
        ("nookku adjudicate 'no end", "nookku adjudicate"),
        ("env -S'nookku adjudicate t1'", "nookku adjudicate"),
        ("echo nookku adjudicate", None),
        # The shell expands a word that can be the subcommand (#548).
        ('C=adjudicate; nookku "$C" t1 --turn 2', commands.EXPANDED),
        ("nookku ${C} t1", commands.EXPANDED),
        ("nookku $(echo adjudicate) t1", commands.EXPANDED),
        ("nookku `echo adjudicate` t1", commands.EXPANDED),
        ('nookku "$(echo adjudicate)" t1', commands.EXPANDED),
        ("nookku $'adjudicate' t1", commands.EXPANDED),
        ("nookku adjudicat* t1", commands.EXPANDED),
        ("nookku {adjudicate,t1}", commands.EXPANDED),
        ("nookku $EMPTY adjudicate t1", commands.EXPANDED),
        ('nookku "adjudicate" "$(echo t1)"', commands.EXPANDED),
        ('python3 -m nookku "$C" t1', commands.EXPANDED),
        ("uv run nookku $C t1", commands.EXPANDED),
        ("env -S'nookku $C t1'", commands.EXPANDED),
        ('bash -c "nookku $C t1"', commands.EXPANDED),
        ("echo 'nookku $C' | sh", commands.EXPANDED),
        ("nookku mode $STATE", commands.EXPANDED),
        ('nookku mode "$(echo on)"', commands.EXPANDED),
        ("nookku init $FLAG", commands.EXPANDED),
        ('nookku gate "$WORD"', "nookku gate"),
        # A word after a plain subcommand that only reads can come from the shell.
        ('nookku audit "$T"', None),
        ('nookku audit "$(cat test.txt)"', None),
        ('nookku check --root "$R"', None),
        ('nookku gate verify "$T"', None),
        ('nookku trace "$T" --verdict; echo "$(date)"', None),
        ('for f in *.py; do grep -c nookku "$f"; done', None),
        ('echo "$(date)"; grep -rn nookku src/', None),
        ("nookku mode", None),
        ("nookku mode status", None),
        ("nookku check", None),
        ("uvx nookku audit", None),
        ("echo nookku start", None),
        ('grep -rn "import nookku" shop', None),
        ("bash shop/run.sh", None),
    ],
)
def test_drive(command: str, what: str | None) -> None:
    assert commands.drive(command) == what


@pytest.mark.parametrize(
    ("command", "what"),
    [
        ("nookku run --script s.jsonl", None),
        ("nookku run --script s.jsonl; nookku start", "nookku start"),
        ("nookku run --script s.jsonl && python3 -c 'import nookku'", commands.IMPORT),
        ("bash -c 'nookku run --script s.jsonl; nookku end'", "nookku end"),
        ("echo $(nookku run --script s.jsonl) $(nookku start)", "nookku start"),
    ],
)
def test_an_allowed_drive_does_not_hide_a_later_drive(command: str, what: str | None) -> None:
    assert commands.drive(command, frozenset({"nookku run"})) == what


def test_the_drive_deny_applies_with_no_state_folder(tmp_path: Path) -> None:
    # A model can write the config with init and start a test in one command.
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "nookku init plugin && nookku start"},
    }
    out = io.StringIO()
    assert kit.run_hook(tmp_path, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    reason = json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason == kit.DRIVE_REASON.format(what="nookku start")
    assert not (tmp_path / STATE).exists()


def test_a_nookku_command_with_an_expanded_subcommand_is_denied(tmp_path: Path) -> None:
    # The relay cannot know the subcommand of nookku "$C", so it denies the command (#548).
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": 'C=adjudicate; nookku "$C" t1 --turn 2 --outcome key_wrong'},
    }
    out = io.StringIO()
    assert kit.run_hook(tmp_path, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    reason = json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason == kit.EXPANDED_REASON


@pytest.mark.parametrize(
    ("command", "stripped"),
    [
        # The shell runs a command substitution in a body whose end word has no quote.
        ("cat <<EOF\n$(cat keys/stock.json)\nEOF", "cat <<EOF\n$(cat keys/stock.json)"),
        ("cat <<-EOF\n\t`cat keys/stock.json`\n\tEOF", "cat <<-EOF\n\t`cat keys/stock.json`"),
        ("cat <<EOF\n$(cat \\\nkeys/stock.json)\nEOF", "cat <<EOF\n$(cat \\\nkeys/stock.json)"),
        ("cat <<EOF\nno end $(date)", "cat <<EOF\nno end $(date)"),
        # A quote on the end word, or no command substitution: the body is data.
        ("cat <<'EOF'\n$(cat keys/stock.json)\nEOF", "cat <<'EOF'"),
        ('cat <<"EOF"\n`date`\nEOF', 'cat <<"EOF"'),
        ("cat <<EOF\n$HOME/keys/stock.json\nEOF", "cat <<EOF"),
        # An end word in a form that the rule does not know: each line stays.
        ('cat <<E"O"F\ndata\nEOF\nnookku start', 'cat <<E"O"F\ndata\nEOF\nnookku start'),
        ("cat <<\\EOF\ndata\nEOF", "cat <<\\EOF\ndata\nEOF"),
    ],
)
def test_a_heredoc_body_that_the_shell_runs_stays(command: str, stripped: str) -> None:
    assert commands.strip_data_heredocs(command) == stripped


def test_a_command_substitution_in_a_heredoc_does_not_pass_the_checks() -> None:
    assert not commands.reads_only("cat <<EOF\n$(date)\nEOF")
    assert commands.reads_only("cat <<'EOF'\n$(date)\nEOF")
    assert commands.reads_only("cat <<EOF\n$HOME\nEOF")
    assert commands.drive("cat > notes.md <<EOF\n$(nookku start)\nEOF") == "nookku start"
    assert commands.drive("cat > notes.md <<'EOF'\n$(nookku start)\nEOF") is None
    assert commands.drive('cat <<E"O"F\ndata\nEOF\nnookku start') == "nookku start"


def test_braces() -> None:
    assert commands.braces("keys/st.{json,txt}") == ["keys/st.json", "keys/st.txt"]
    assert commands.braces("{a,b{c,d}}") == ["a", "bc", "bd"]
    assert commands.braces("a{b}c") == ["a{b}c"]
    assert commands.braces("{a,b}" * 6) is not None
    assert commands.braces("{a,b}" * 7) is None


def test_search_globs() -> None:
    assert commands.search_globs("*.{json,md}") == ["**/*.json", "**/*.md"]
    assert commands.search_globs("stock.json") == ["**/stock.json"]
    assert commands.search_globs("keys/*.json") == ["keys/*.json"]
    assert commands.search_globs("/stock.json") == ["stock.json"]
    assert commands.search_globs("**/stock.json") == ["**/stock.json"]
    assert commands.search_globs(".") == ["."]
    assert commands.search_globs("{a,b}" * 7) is None


@pytest.mark.parametrize(
    ("parts", "rests"),
    [
        ("/shop/keys/stock.json", [[]]),
        ("/shop/keys/stock.json/more", [["more"]]),
        ("/shop/**/stock.json", [["**", "stock.json"], []]),
        ("/**/stock.json", [["**", "stock.json"], []]),
        ("/shop/keys/**/stock.json", [["**", "stock.json"], []]),
        ("/shop/**", [["**"]]),
        ("/shop/**/*.md", [["**", "*.md"]]),
        ("/shop/**/**/STOCK.json", [["**", "**", "STOCK.json"], ["**", "STOCK.json"], []]),
        ("/shop/*/stock.json", [[]]),
        ("/shop/stock.json", []),
        ("/shop/**/list.json", [["**", "list.json"]]),
        ("/shop/keys", []),
    ],
)
def test_glob_rests(parts: str, rests: list[list[str]]) -> None:
    top = ["", "shop", "keys", "stock.json"]
    assert commands.glob_rests(parts.split("/"), top) == rests


def _key_project(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    (root / "keys" / "private").mkdir(parents=True)
    (root / "keys" / "private" / "stock.json").write_text("{}")
    (root / "keys" / "private" / "notes.md").write_text("notes")
    (root / "docs").mkdir()
    return root


def _key_named(root: Path, tool: str, tool_input: dict, keys: list[str]) -> str | None:
    event = {"hook_event_name": "PreToolUse", "cwd": str(root)}
    return kit.key_named(event, root, tool, tool_input, keys)


FILE_KEY, FOLDER_KEY = ["keys/private/stock.json"], ["keys/private"]


@pytest.mark.parametrize(
    ("command", "keys", "named"),
    [
        ("cat <<EOF\n$(cat keys/private/stock.json)\nEOF", FILE_KEY, "keys/private/stock.json"),
        # The key rule also reads the body of a here-document that is data.
        ("cat <<'EOF'\n$(cat keys/private/stock.json)\nEOF", FILE_KEY, "keys/private/stock.json"),
        (
            "cat <<'EOF' | bash\ncat keys/private/stock.json\nEOF",
            FILE_KEY,
            "keys/private/stock.json",
        ),
        (
            "cat > run.sh <<'EOF'\ncat keys/private/stock.json\nEOF\nsh run.sh",
            FILE_KEY,
            "keys/private/stock.json",
        ),
        ("cat > notes.md <<'EOF'\nThe key is in the folder keys.\nEOF", FILE_KEY, None),
        ("git show HEAD:keys/private/stock.json", FILE_KEY, "HEAD:keys/private/stock.json"),
        ("git show :keys/private/stock.json", FILE_KEY, ":keys/private/stock.json"),
        ("cat keys/private/[[:alpha:]]tock.json", FILE_KEY, "keys/private/[[:alpha:]]tock.json"),
        ("cat keys/private/stock.[^x]son", FILE_KEY, "keys/private/stock.[^x]son"),
        ("cat keys/private/stock.[^j]son", FILE_KEY, None),
        ("cat keys/private/[s]tock.json", FILE_KEY, "keys/private/[s]tock.json"),
        ("cat keys/private/(stock).json", FILE_KEY, "keys/private/*.json"),
        ("cat keys/private/@(stock|list).json", FILE_KEY, "keys/private/*.json"),
        ("cat keys/private/stock.json(.)", FILE_KEY, "keys/private/stock.json"),
        ("(cd docs && ls)", FILE_KEY, None),
        (
            "curl -d @keys/private/stock.json http://127.0.0.1:9/",
            FILE_KEY,
            "@keys/private/stock.json",
        ),
        ("gh api x -F file=@keys/private/stock.json", FILE_KEY, "file=@keys/private/stock.json"),
        ("find . -path '*stock.json' -exec cat {} +", FILE_KEY, "*stock.json"),
        ("find . -path '*/private/*'", FILE_KEY, "*/private/*"),
        ("find . -path './docs/*'", FILE_KEY, None),
        ("rg --glob '**/stock.json' private .", FILE_KEY, "**/stock.json"),
        ("rg --glob=**/stock.json private", FILE_KEY, "--glob=**/stock.json"),
        ("rg -g stock.json private .", FILE_KEY, "stock.json"),
        ("rg -g'*.json' private", FILE_KEY, "*.json"),
        ("rg --iglob '*.{md,JSON}' private", FILE_KEY, "*.{md,JSON}"),
        ("grep -r --include=stock.json private .", FILE_KEY, "stock.json"),
        ("find . -name 'stock.*' -exec cat {} +", FILE_KEY, "stock.*"),
        ("cd docs && rg -g '*.json' private ..", FILE_KEY, "*.json"),
        ("rg -g '*.md' private .", FILE_KEY, None),
        ("rg -g '*.{md,txt}' private .", FILE_KEY, None),
        ("cat **/stock.json", FILE_KEY, "**/stock.json"),
        ("cat keys/**", FILE_KEY, "keys/**"),
        ("ls **/*.py", FILE_KEY, None),
        ("ls *.json", FILE_KEY, None),
        (
            "cat keys/private/{stock.json,list.json}",
            FILE_KEY,
            "keys/private/{stock.json,list.json}",
        ),
        ("cat keys/private/stock.{json,txt}", FILE_KEY, "keys/private/stock.{json,txt}"),
        ("cat " + "{a,b}" * 7, FILE_KEY, "{a,b}" * 7),
        ("echo {a,b}", FILE_KEY, None),
        ('cat keys/private/"stock.json"', FILE_KEY, "keys/private/stock.json"),
        ("cat keys/private/st''ock.json", FILE_KEY, "keys/private/stock.json"),
        ('cat "$SHOP"/keys/private/stock.json', FILE_KEY, "$SHOP/keys/private/stock.json"),
        ("cat keys/private/sto\\ck.json", FILE_KEY, "keys/private/stock.json"),
        ("cat keys/pri\\\nvate/stock.json", FILE_KEY, "keys/private/stock.json"),
        # The check cannot parse a command substitution in double quotes.
        ("cat keys/private/'stock'.json; echo \"$(date)\"", FILE_KEY, "keys/private/stock.json"),
        ('cat keys/private/sto\\ck.json; echo "$(date)"', FILE_KEY, "keys/private/stock.json"),
        ('cat keys/pri\\\nvate/stock.json; echo "$(date)"', FILE_KEY, "keys/private/stock.json"),
        ("ls **/*.md", FOLDER_KEY, "**/*.md"),
        ("ls **/*.py", FOLDER_KEY, None),
        ("rg -g '*.md' private", FOLDER_KEY, "*.md"),
        ("rg -g '*.py' private", FOLDER_KEY, None),
    ],
)
def test_the_key_rule_reads_a_shell_command_as_the_shell_and_a_search_would(
    tmp_path: Path, command: str, keys: list[str], named: str | None
) -> None:
    # #577: a here-document that the shell runs, a glob of a search, braces and quotes.
    root = _key_project(tmp_path)
    assert _key_named(root, "Bash", {"command": command}, keys) == named


@pytest.mark.parametrize(
    ("tool_input", "keys", "named"),
    [
        ({"pattern": "answer", "glob": "**/stock.json"}, FILE_KEY, "**/stock.json"),
        ({"pattern": "answer", "glob": "stock.json"}, FILE_KEY, "stock.json"),
        ({"pattern": "answer", "glob": "*.{json,md}"}, FILE_KEY, "*.{json,md}"),
        ({"pattern": "answer", "glob": "*.json", "path": "keys"}, FILE_KEY, "*.json"),
        (
            {"pattern": "answer", "glob": "/private/*.json", "path": "keys"},
            FILE_KEY,
            "/private/*.json",
        ),
        ({"pattern": "answer", "glob": "{a,b}" * 7}, FILE_KEY, "{a,b}" * 7),
        ({"pattern": "**/*.json"}, FILE_KEY, "**/*.json"),
        ({"pattern": "**"}, FILE_KEY, "**"),
        ({"pattern": "keys/**"}, FILE_KEY, "keys/**"),
        # The glob of a search starts only at the path of the search.
        ({"pattern": "answer", "glob": "*.json", "path": "docs"}, FILE_KEY, None),
        ({"pattern": "answer", "glob": "*.md"}, FILE_KEY, None),
        ({"pattern": "answer", "glob": "docs/**"}, FILE_KEY, None),
        ({"pattern": "docs/**/*.json"}, FILE_KEY, None),
        ({"pattern": "answer"}, FILE_KEY, None),
        ({"pattern": "."}, FILE_KEY, None),
        # A glob with `**` names a key folder only if a path in the folder matches it.
        ({"pattern": "**/*.md"}, FOLDER_KEY, "**/*.md"),
        ({"pattern": "*.md"}, FOLDER_KEY, "*.md"),
        ({"pattern": "**/private"}, FOLDER_KEY, "**/private"),
        ({"pattern": "**/*.py"}, FOLDER_KEY, None),
        ({"pattern": "answer"}, FOLDER_KEY, None),
    ],
)
def test_the_key_rule_reads_the_glob_of_a_search_as_the_search_tool_would(
    tmp_path: Path, tool_input: dict, keys: list[str], named: str | None
) -> None:
    root = _key_project(tmp_path)
    assert _key_named(root, "Grep", tool_input, keys) == named


@pytest.mark.parametrize(
    ("chars", "named"),
    [
        ('cat keys/private/st"ock".json\n', "keys/private/stock.json"),
        ("cat keys/private/sto\\ck.json\n", "keys/private/stock.json"),
        ("cat keys/private/*.json\n", "keys/private/*.json"),
        ("cat private/{stock,list}.json\n", "private/{stock,list}.json"),
        ("cd keys/private\n", None),
        ("rg -g 'stock.*' answer\n", "stock.*"),
        ("ls docs\n", None),
    ],
)
def test_the_key_rule_reads_the_input_of_a_persistent_shell_as_a_command(
    tmp_path: Path, chars: str, named: str | None
) -> None:
    # The input does not show its folder, so each folder above a key counts.
    root = _key_project(tmp_path)
    tool_input = {"session_id": 1, "chars": chars}
    assert _key_named(root, "write_stdin", tool_input, FILE_KEY) == named


@pytest.mark.parametrize(
    ("command", "stripped"),
    [
        # The output of the data program goes to a program that can run it.
        ("cat <<'EOF' | bash\nnookku start\nEOF", "cat <<'EOF' | bash\nnookku start"),
        ("(cat <<'EOF'\nnookku start\nEOF\n) | sh", "(cat <<'EOF'\nnookku start\n) | sh"),
        ("tee >(sh) <<'EOF'\nnookku start\nEOF", "tee >(sh) <<'EOF'\nnookku start"),
        ("cat <<'EOF' \\\n| sh\nnookku start\nEOF", "cat <<'EOF' \\\n| sh\nnookku start"),
        # A pipe in quotes is text.
        (
            "gh issue create -t 'a | b' -F - <<'EOF'\ntext\nEOF",
            "gh issue create -t 'a | b' -F - <<'EOF'",
        ),
        (
            "git add a.py && git commit -F - <<'EOF'\ntext\nEOF",
            "git add a.py && git commit -F - <<'EOF'",
        ),
    ],
)
def test_a_heredoc_body_that_goes_to_another_program_stays(command: str, stripped: str) -> None:
    assert commands.strip_data_heredocs(command) == stripped


def test_a_drive_command_in_a_heredoc_that_a_shell_gets_is_denied() -> None:
    assert commands.drive("cat <<'EOF' | bash\nnookku start\nEOF") == "nookku start"
    assert commands.drive("cat > notes.md <<'EOF'\nnookku start\nEOF") is None


def test_the_key_rule_fails_closed_for_a_large_key_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _key_project(tmp_path)
    assert _key_named(root, "Glob", {"pattern": "**/*.py"}, FOLDER_KEY) is None
    monkeypatch.setattr(kit, "KEY_WALK_LIMIT", 1)
    assert _key_named(root, "Glob", {"pattern": "**/*.py"}, FOLDER_KEY) == "**/*.py"


@pytest.mark.parametrize(
    ("command", "named"),
    [
        ("cat alias/stock.json", "alias/stock.json"),
        ("cat alias/*.json", "alias/*.json"),
        ("cat alias/st[a-z]ck.json", "alias/st[a-z]ck.json"),
        ("cat alias/*.md", None),
        ("cat docs/*.json", None),
    ],
)
def test_the_key_rule_resolves_the_symlinks_before_a_glob(
    tmp_path: Path, command: str, named: str | None
) -> None:
    root = _key_project(tmp_path)
    (root / "alias").symlink_to(root / "keys" / "private")
    assert _key_named(root, "Bash", {"command": command}, FILE_KEY) == named
    tool_input = {"pattern": "answer", "glob": "*.json", "path": "alias"}
    assert _key_named(root, "Grep", tool_input, FILE_KEY) == "*.json"

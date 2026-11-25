"""The issue rows of an evaluation: evaluation.json, its author type and the seal (#576)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from nookku import bridge, commands, issues, seal, verdict
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
SCRIPT = ["What is your refund policy?", "Do you ship to Pune?"]

REPORT = """# Test t1: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| unsupported_reply | 2 | trace.jsonl:7 | The reply gives a ship date that no tool result has. |
| `tone` | - | APP_SPEC.md line 4 | The reply uses slang \\| and a joke. |

## Notes

```markdown
| Class | Turn | Evidence | Issue |
|---|---|---|---|
| business_rule | 1 | x | A table in a fence is not the issue table. |
```
"""
EMPTY = (
    "# Test t1: evaluation\n\n| Class | Turn | Evidence | Issue |\n|---|---|---|---|\n\n## Notes\n"
)


def test_the_import_reads_the_first_issue_table_as_model_rows() -> None:
    rows = issues.model_rows(REPORT.encode())
    assert rows == [
        {
            "class": "unsupported_reply",
            "turn": 2,
            "evidence": "trace.jsonl:7",
            "text": "The reply gives a ship date that no tool result has.",
            "author": "model",
            "name": None,
        },
        {
            "class": "tone",
            "turn": None,
            "evidence": "APP_SPEC.md line 4",
            "text": "The reply uses slang | and a joke.",
            "author": "model",
            "name": None,
        },
    ]
    assert issues.model_rows(EMPTY.encode()) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("# Report\n\nNo issue.\n", "has no issue table"),
        (EMPTY.replace("|---|---|---|---|\n", "|---|---|---|---|\n| tone | 1 | x |\n"), "line 5"),
        (
            EMPTY.replace("|---|---|---|---|\n", "|---|---|---|---|\n| rude | 1 | x | y |\n"),
            "class",
        ),
        (EMPTY.replace("|---|---|---|---|\n", "|---|---|---|---|\n| tone | 0 | x | y |\n"), "Turn"),
        (EMPTY.replace("|---|---|---|---|\n", "|---|---|---|---|\n| tone | 1 | x |  |\n"), "text"),
        (b"\xff".decode("latin-1"), "has no issue table"),
    ],
)
def test_an_issue_table_with_a_problem_gives_no_row(text: str, problem: str) -> None:
    with pytest.raises(ValueError, match=problem):
        issues.model_rows(text.encode())


def test_the_author_type_comes_from_the_command_and_not_from_the_text() -> None:
    # A row of report.md that names a person is still a model row.
    text = EMPTY.replace(
        "| Class | Turn | Evidence | Issue |\n|---|---|---|---|\n",
        "| Class | Turn | Evidence | Issue | Author |\n|---|---|---|---|---|\n"
        "| tone | 1 | x | y | human |\n",
    )
    assert [r["author"] for r in issues.model_rows(text.encode())] == ["model"]
    assert issues.row("tone", 1, "x", "y", "Asha")["author"] == "human"
    assert issues.row("tone", 1, "x", "y", None)["author"] == "model"
    # The person part of report.md is not part of the model rows.
    people = [issues.row("boundary", 3, "turn 3", "It sold a gift card.", "Asha")]
    shown = issues.with_person_part(EMPTY.encode(), people)
    assert issues.PERSON_HEADING in shown.decode()
    assert issues.model_rows(shown) == []
    # A second write replaces the part, and with no person row the model bytes stay.
    assert issues.with_person_part(shown, people) == shown
    assert issues.with_person_part(REPORT.encode(), []) == REPORT.encode()


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        ({"class": "tone", "turn": 1, "evidence": "x", "text": "y", "author": "model"}, "keys"),
        (
            {
                "class": "tone",
                "turn": 1,
                "evidence": "x",
                "text": "y",
                "author": "model",
                "name": "A",
            },
            "a model row has a name",
        ),
        (
            {
                "class": "tone",
                "turn": 1,
                "evidence": "x",
                "text": "y",
                "author": "human",
                "name": None,
            },
            "no name text",
        ),
        (
            {
                "class": "tone",
                "turn": True,
                "evidence": "x",
                "text": "y",
                "author": "model",
                "name": None,
            },
            "turn",
        ),
        (
            {
                "class": "tone",
                "turn": 1,
                "evidence": "x",
                "text": "y\n",
                "author": "model",
                "name": None,
            },
            "control character",
        ),
        (
            {
                "class": "tone",
                "turn": 1,
                "evidence": "x",
                "text": "y",
                "author": "person",
                "name": "A",
            },
            "author",
        ),
    ],
)
def test_the_rule_of_an_issue_row(row: dict, problem: str) -> None:
    assert problem in (issues.row_problem(row) or "")


def _shop(tmp_path: Path, limits: str) -> Path:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    spec = "# Toy shop\n\n## Verdict\n\n| Finding | Most |\n|---|---|\n| `agent_error` | 0 |\n"
    (root / "APP_SPEC.md").write_text(spec + limits)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": [], "spec": ["APP_SPEC.md"]}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    (root / "script.jsonl").write_text("".join(json.dumps({"said": s}) + "\n" for s in SCRIPT))
    return root


def _test(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, Path]:
    script = str(root / "script.jsonl")
    code = main(["run", "--script", script, "--root", str(root), "--verdict", "--json"])
    capsys.readouterr()
    folder = bridge.latest_test(root)
    assert folder is not None
    return code, folder


def _evaluation(root: Path, folder: Path, *words: str) -> int:
    return main(["evaluation", words[0], folder.name, "--root", str(root), *words[1:]])


def test_a_model_row_fails_a_verdict_only_with_a_limit_of_its_class(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path, "")
    assert _test(root, capsys)[0] == 0
    folder = bridge.latest_test(root)
    assert folder is not None
    (folder / issues.REPORT).write_text(REPORT)
    assert _evaluation(root, folder, "import") == 0
    assert "2 model rows and 0 human rows" in capsys.readouterr().out
    record = json.loads((folder / issues.FILE).read_text())
    assert [r["class"] for r in record["issues"]] == ["unsupported_reply", "tone"]
    assert record["report"] == seal.sha256_of((folder / issues.REPORT).read_bytes())
    # With no Verdict row for an issue class, the verdict does not read the rows.
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "pass"
    assert "issues" not in found


def test_an_issue_limit_counts_model_and_human_rows_and_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path, "| `boundary` | 0 |\n| `tone` | 1 |\n")
    code, folder = _test(root, capsys)
    # With a limit of an issue class and no evaluation.json, the verdict fails closed.
    assert code == 1
    stored = json.loads((folder / verdict.FILE).read_text())
    assert verdict.MISSING_EVALUATION in stored["problems"]
    assert [r["count"] for r in stored["issues"]] == [None, None]
    (folder / issues.REPORT).write_text(REPORT)
    assert _evaluation(root, folder, "import") == 0
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "pass"
    assert found["issues"] == [
        {"class": "tone", "model": 1, "human": 0, "count": 1, "most": 1, "verdict": "pass"},
        {"class": "boundary", "model": 0, "human": 0, "count": 0, "most": 0, "verdict": "pass"},
    ]
    words = ("--class", "boundary", "--turn", "2", "--evidence", "turn 2", "--text", "It sold.")
    assert _evaluation(root, folder, "add", *words, "--author", "Asha") == 0
    out = capsys.readouterr().out
    assert "2 model rows and 1 human rows" in out
    assert "boundary: 1 issue rows, the limit is 0" in out
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "fail"
    assert found["issues"][1] == {
        "class": "boundary",
        "model": 0,
        "human": 1,
        "count": 1,
        "most": 0,
        "verdict": "fail",
    }
    shown = (folder / issues.REPORT).read_text()
    assert "| boundary | 2 | turn 2 | It sold. | Asha |" in shown
    record = json.loads((folder / issues.FILE).read_text())
    assert record["issues"][-1]["author"] == "human" and record["issues"][-1]["name"] == "Asha"
    # A new import keeps the human row and reads the model rows again.
    assert _evaluation(root, folder, "import") == 0
    rows = json.loads((folder / issues.FILE).read_text())["issues"]
    assert [r["author"] for r in rows] == ["model", "model", "human"]


def test_a_changed_evaluation_file_breaks_the_seal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path, "| `tone` | 0 |\n")
    _, folder = _test(root, capsys)
    (folder / issues.REPORT).write_text(EMPTY)
    assert _evaluation(root, folder, "import") == 0
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "pass"
    path = folder / issues.FILE
    record = json.loads(path.read_text())
    record["issues"].append(issues.row("tone", 1, "x", "y", None))
    path.write_text(json.dumps(record))
    assert not seal.verify(folder)["intact"]
    assert verdict.checked(folder)[0] is None
    # No person command writes a row on a broken seal.
    assert (
        _evaluation(root, folder, "add", "--class", "tone", "--evidence", "x", "--text", "y") == 2
    )
    assert "no issue row was written" in capsys.readouterr().err


def test_add_needs_an_import_of_the_report_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path, "")
    _, folder = _test(root, capsys)
    words = ("--class", "tone", "--evidence", "x", "--text", "y", "--author", "Asha")
    # A test with no report.md takes a human row, and report.md stays missing.
    assert _evaluation(root, folder, "add", *words) == 0
    assert not (folder / issues.REPORT).exists()
    (folder / issues.REPORT).write_text(EMPTY)
    assert _evaluation(root, folder, "add", *words) == 2
    assert "nookku evaluation import" in capsys.readouterr().err
    assert _evaluation(root, folder, "import") == 0
    (folder / issues.REPORT).write_text(REPORT)
    assert _evaluation(root, folder, "add", *words) == 2
    # The import with a problem writes nothing.
    (folder / issues.REPORT).write_text("# Report\n")
    before = (folder / issues.FILE).read_bytes()
    assert _evaluation(root, folder, "import") == 2
    assert (folder / issues.FILE).read_bytes() == before


def test_the_import_trusts_a_report_that_changed_after_the_evaluation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # SPEC.md section 9.4, "The trust of report.md" (#645).
    root = _shop(tmp_path, "| `tone` | 0 |\n")
    _, folder = _test(root, capsys)
    report = folder / issues.REPORT
    # The evaluation writes a report with a `tone` row. Then a writer of the test folder
    # replaces it with an empty issue table, before the first import.
    report.write_text(REPORT)
    report.write_text(EMPTY)
    assert _evaluation(root, folder, "import") == 0
    # No record has the bytes of the evaluation, so the import seals the rows of the new file.
    assert "0 model rows" in capsys.readouterr().out
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "pass"
    assert seal.verify(folder)["intact"]
    # After the import, `report` binds the file. A changed file gets no human row.
    report.write_text(REPORT)
    before = (folder / issues.FILE).read_bytes()
    words = ("--class", "tone", "--evidence", "x", "--text", "y")
    assert _evaluation(root, folder, "add", *words) == 2
    assert (folder / issues.FILE).read_bytes() == before and seal.verify(folder)["intact"]
    # Only a new import reads the rows of the changed file.
    assert _evaluation(root, folder, "import") == 0
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "fail"


@pytest.fixture
def sealed_test(tmp_path: Path) -> tuple[Path, Path]:
    folder = tmp_path / ".nookku" / "tests" / "20261031-090000-ab12"
    folder.mkdir(parents=True)
    (folder / verdict.MANIFEST).write_text(json.dumps({"test": folder.name}))
    (folder / verdict.FINDINGS).write_text(json.dumps({"counts": {}}))
    verdict.build(folder)
    assert seal.write(folder) is None
    return tmp_path, folder


def test_add_that_would_make_the_report_too_large_writes_nothing(
    sealed_test: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root, folder = sealed_test
    issue_text = "The reply says « dépêche-toi | vite »."
    row = issues.row("tone", None, "turn 2", issue_text, "Asha")
    body = EMPTY.encode()
    new_size = issues.MAX_REPORT + 1
    padding = new_size - len(issues.with_person_part(body, [row]))
    (folder / issues.REPORT).write_bytes(body + b"x" * (padding - 1) + b"\n")
    assert _evaluation(root, folder, "import") == 0
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    words = ("--class", "tone", "--evidence", "turn 2", "--text", issue_text, "--author", "Asha")
    assert _evaluation(root, folder, "add", *words) == 2
    error = capsys.readouterr().err
    assert "no issue row was written" in error
    assert f"The new report.md would have {new_size} bytes" in error
    assert f"The limit is {issues.MAX_REPORT} bytes" in error
    assert {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before


def test_add_and_import_can_read_a_report_near_the_limit(sealed_test: tuple[Path, Path]) -> None:
    root, folder = sealed_test
    row = issues.row("tone", None, "turn 2", "The reply uses slang.", "Asha")
    body = EMPTY.encode()
    padding = issues.MAX_REPORT - len(issues.with_person_part(body, [row, row]))
    report = folder / issues.REPORT
    report.write_bytes(body + b"x" * (padding - 1) + b"\n")
    assert _evaluation(root, folder, "import") == 0

    words = ("--class", "tone", "--evidence", "turn 2", "--text", row["text"], "--author", "Asha")
    assert _evaluation(root, folder, "add", *words) == 0
    assert _evaluation(root, folder, "add", *words) == 0
    assert report.stat().st_size == issues.MAX_REPORT
    assert _evaluation(root, folder, "import") == 0
    assert json.loads((folder / issues.FILE).read_text())["issues"] == [row, row]


def test_a_report_that_is_a_symlink_is_not_read(tmp_path: Path) -> None:
    folder = tmp_path / "t1"
    folder.mkdir()
    (tmp_path / "other.md").write_text(EMPTY)
    (folder / issues.REPORT).symlink_to(tmp_path / "other.md")
    with pytest.raises(ValueError, match=r"report\.md"):
        issues.read_report(folder)


def test_the_end_of_a_test_removes_the_rows_of_the_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path, "")
    planter = tmp_path / "plant.py"
    planter.write_text(
        "import json, os, pathlib, runpy, sys\n"
        f"answer = runpy.run_path({str(TOY_SHOP)!r})['answer']\n"
        "for raw in sys.stdin.buffer:\n"
        "    request = json.loads(raw)\n"
        "    folder = pathlib.Path(os.environ['NOOKKU_TEST_DIR'])\n"
        "    (folder / 'evaluation.json').write_text('{}')\n"
        "    out = {'v': 1, 'id': request['id'], 'reply': answer(request['message'])}\n"
        "    sys.stdout.write(json.dumps(out) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    conf = json.loads((root / ".nookku" / "config.json").read_text())
    conf["entry"] = [sys.executable, str(planter)]
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    code, folder = _test(root, capsys)
    # A reply that the tap refuses makes the tap wait for its timeout, and the test fails.
    assert code == 0
    assert not (folder / issues.FILE).exists()
    assert "only nookku evaluation writes it" in (folder / "bridge.log").read_text()
    assert seal.verify(folder)["intact"]


def test_the_relay_denies_the_command_to_the_model() -> None:
    assert commands.drive("nookku evaluation import t1") == "nookku evaluation"
    assert commands.drive("uv run nookku evaluation add t1 --class tone") == ("nookku evaluation")
    assert commands.drive("nookku end --evaluation") == "nookku end"

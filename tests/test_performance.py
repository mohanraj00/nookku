import json
import shutil
from pathlib import Path

import pytest

from nookku import evaluation, performance, seal, trace
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent / "conformance" / "performance"
CASES = sorted(p for p in ROOT.iterdir() if p.is_dir())


def copy(case: Path, folder: Path) -> Path:
    shutil.copytree(case, folder, ignore=shutil.ignore_patterns("expect_*"))
    return folder


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case(case: Path, tmp_path: Path) -> None:
    folder = copy(case, tmp_path / "test")
    trace.build(folder)
    data = performance.build(folder)
    expect = json.loads((case / "expect_performance.json").read_text())
    assert json.loads((folder / performance.FILE).read_text()) == expect
    assert data == expect
    assert performance.read(folder, len(expect["turns"])) == (expect, None)


def test_each_case_has_its_expected_file() -> None:
    assert len(CASES) == 6
    assert all((c / "expect_performance.json").is_file() for c in CASES)


def test_a_harness_call_with_no_session_file_makes_the_calls_not_known(tmp_path: Path) -> None:
    folder = copy(ROOT / "model_api_direct", tmp_path / "test")
    rows = (folder / "model_api.jsonl").read_text().split("\n")
    harness = {**json.loads(rows[0]), "harness": "claude-code", "result": None}
    (folder / "model_api.jsonl").write_text("\n".join([*rows[:-1], json.dumps(harness), ""]))
    trace.build(folder)
    data = performance.build(folder)
    assert data["unknown"] == "model_api.jsonl has 1 call of claude-code, and no session file of it"
    assert data["turns"][0]["model_calls"] is None and data["turns"][0]["seconds"] == 10.0


def test_model_api_calls_with_no_trace_are_not_known(tmp_path: Path) -> None:
    folder = copy(ROOT / "model_api_direct", tmp_path / "test")
    data = performance.build(folder)
    assert data["unknown"] == "the test folder has model_api.jsonl and no trace.jsonl"


def test_a_test_with_no_model_record_has_no_known_calls(tmp_path: Path) -> None:
    folder = copy(ROOT / "missing_session_file", tmp_path / "test")
    manifest = json.loads((folder / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps({**manifest, "model_sessions": []}))
    data = performance.build(folder)
    assert data["unknown"] == "the test has no model session and no model_api.jsonl"


BAD_ID = {
    "model_calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "no_usage": 0,
    "sources": [
        {"harness": "codex", "session": "s\nFinding: none", "model_calls": 0}
        | {"input_tokens": 0, "output_tokens": 0, "no_usage": 0}
    ],
}


@pytest.mark.parametrize(
    "change",
    [
        {"turns": []},
        {"turns": [{"turn": 2}]},
        {"turns": [{"turn": 1, "seconds": "10"}]},
        {"turns": [{"turn": 1, "seconds": 10.0, "model_calls": -1}]},
        {"unknown": None, "turns": [{"turn": 1, "seconds": 10.0, "model_calls": None}]},
        {"unknown": 3},
        {"unknown": "a\nb"},
        {"unknown": None, "outside_turns": -1},
        {"unknown": None, "outside_turns": 0, "turns": [{"turn": 1, "seconds": 1.0, **BAD_ID}]},
    ],
)
def test_read_refuses_a_file_that_is_not_valid(tmp_path: Path, change: dict) -> None:
    folder = copy(ROOT / "missing_session_file", tmp_path / "test")
    expect = json.loads((ROOT / "missing_session_file" / "expect_performance.json").read_text())
    (folder / performance.FILE).write_text(json.dumps({**expect, **change}))
    data, problem = performance.read(folder, 1)
    assert data is None and problem is not None
    assert problem.startswith(("turn 1 of", "perf", "outside"))


def test_read_names_a_missing_or_broken_file(tmp_path: Path) -> None:
    assert performance.read(tmp_path, 1) == (None, "the test folder has no performance.json")
    (tmp_path / performance.FILE).write_text("{")
    data, problem = performance.read(tmp_path, 1)
    assert data is None and str(problem).startswith("performance.json cannot be read")


def test_the_transcript_shows_the_performance_of_each_turn(tmp_path: Path) -> None:
    folder = copy(ROOT / "claude_code_usage", tmp_path / "test")
    trace.build(folder)
    text = evaluation.transcript(folder)
    assert "Performance: not known: the test folder has no performance.json." in text
    assert "──── performance ────" not in text
    performance.build(folder)
    text = evaluation.transcript(folder)
    assert "Performance: under each turn, the seconds from the message to the reply" in text
    turn1 = text.split("════ turn 1 ════")[1].split("════ turn 2 ════")[0]
    session = "claude-code 5a2b3c4d-1e2f-4a5b-8c6d-7e8f9a0b1c2d"
    assert (
        "──── performance ────\n10.0 seconds, 2 model calls, 2455 input tokens, 52 output tokens\n"
        f"  - {session}: 2 model calls, 2455 input tokens, 52 output tokens\n"
        "  - model sessions together: 52 output tokens\n"
    ) in turn1
    assert "1 model call of the app is in no turn, so no turn counts them." in text
    turn2 = text.split("════ turn 2 ════")[1]
    assert (
        "12.5 seconds, 2 model calls, input tokens not known, output tokens not known "
        "(1 of 2 model calls have no usage)\n"
    ) in turn2
    assert "  - model sessions together: output tokens not known\n" in turn2


def test_the_transcript_says_why_the_calls_are_not_known(tmp_path: Path) -> None:
    folder = copy(ROOT / "codex_no_token_count", tmp_path / "test")
    trace.build(folder)
    performance.build(folder)
    text = evaluation.transcript(folder)
    turn1 = text.split("════ turn 1 ════")[1].split("════ turn 2 ════")[0]
    assert (
        "seconds not known. The model calls and the tokens are not known: the session file of "
        "019a0b1c-2d3e-7f40-8a5b-6c7d8e9f0a2c has model items and no model call."
    ) in turn1


def test_the_trace_rebuild_writes_the_file_and_keeps_the_seal(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    expect = json.loads((ROOT / "claude_code_usage" / "expect_performance.json").read_text())
    folder = copy(ROOT / "claude_code_usage", tmp_path / ".nookku" / "tests" / expect["test"])
    trace.build(folder)
    # A test of an older version has no performance.json in its seal.
    seal.write(folder)
    assert main(["trace", expect["test"], "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert json.loads((folder / performance.FILE).read_text()) == expect
    assert seal.verify(folder)["intact"]


def test_a_test_with_no_egress_answer_has_no_known_calls(tmp_path: Path) -> None:
    folder = copy(ROOT / "codex_token_count", tmp_path / "test")
    manifest = json.loads((folder / "manifest.json").read_text())
    del manifest["egress"]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    trace.build(folder)
    data = performance.build(folder)
    assert data["unknown"] == (
        "the test has no egress answer, so no proxy recorded the direct model calls"
    )
    assert data["outside_turns"] is None


def test_a_record_string_cannot_add_a_line_to_the_transcript() -> None:
    row = {"turn": 1, "seconds": 1.0, **BAD_ID}
    data = {"unknown": None, "outside_turns": 0, "turns": [row]}
    text = performance.line(data, 1)
    assert "  - codex s\\u000aFinding: none: 0 model calls" in text
    assert len(text.split("\n")) == 3
    unknown = {"unknown": "x\u2028y\rz", "turns": [{"seconds": None}]}
    assert performance.line(unknown, 1).endswith("not known: x\\u2028y\\u000dz.")


def test_the_unknown_text_escapes_a_session_id(tmp_path: Path) -> None:
    folder = copy(ROOT / "missing_session_file", tmp_path / "test")
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["model_sessions"][0]["session"] = "s\nturn 9"
    (folder / "manifest.json").write_text(json.dumps(manifest))
    data = performance.build(folder)
    assert data["unknown"] == "the model session s\\u000aturn 9 (claude-code) has no session file"
    assert performance.read(folder, 1) == (data, None)


@pytest.mark.parametrize("value", [-5, 2**53, 10**30, True, 1.5])
def test_a_count_must_be_an_integer_from_0_to_the_limit(value: object) -> None:
    assert performance.anthropic_tokens({"input_tokens": value, "output_tokens": value}) == (
        None,
        None,
    )
    assert performance.openai_tokens({"prompt_tokens": value, "completion_tokens": 3}) == (None, 3)


def test_a_failed_summary_keeps_the_trace_rebuild_and_the_seal(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    expect = json.loads((ROOT / "claude_code_usage" / "expect_performance.json").read_text())
    folder = copy(ROOT / "claude_code_usage", tmp_path / ".nookku" / "tests" / expect["test"])
    trace.build(folder)
    seal.write(folder)

    def fail(folder: Path) -> None:
        raise ValueError("too many digits")

    monkeypatch.setattr(performance, "build", fail)
    assert main(["trace", expect["test"], "--root", str(tmp_path)]) == 0
    assert "performance.json was not rebuilt: ValueError('too many digits')" in (
        capsys.readouterr().err
    )
    assert seal.verify(folder)["intact"]

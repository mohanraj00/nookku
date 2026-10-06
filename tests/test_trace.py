import json
import shutil
from pathlib import Path

import pytest

from verbatim_relay import trace

CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "trace").iterdir())


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case(case: Path, tmp_path: Path) -> None:
    folder = tmp_path / "test"
    shutil.copytree(case, folder, ignore=shutil.ignore_patterns("expect_*"))
    report = trace.build(folder)
    assert rows(folder / "trace.jsonl") == rows(case / "expect_trace.jsonl")
    expect = json.loads((case / "expect_findings.json").read_text())
    assert json.loads((folder / "findings.json").read_text()) == expect
    assert report == expect


def test_a_missing_session_file_is_not_an_error(tmp_path: Path) -> None:
    session = {"harness": "codex", "session": "s", "inferred": True, "file": "sessions/codex/x"}
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t", "model_sessions": [session]}))
    report = trace.build(tmp_path)
    assert report["items"] == 0
    assert report["turns"] == 0
    assert report["sessions"][0]["version"] is None
    assert [f["check"] for f in report["findings"]] == ["session_inferred"]


def test_summary() -> None:
    report = {"items": 3, "turns": 2, "counts": dict.fromkeys(trace.CHECKS, 0)}
    assert trace.summary(report) == "Trace: 3 model items in 2 turns, no findings."
    report["counts"]["tool_error"] = 2
    assert trace.summary(report) == "Trace: 3 model items in 2 turns, 2 tool_error."


def test_a_file_without_a_version_is_unknown(tmp_path: Path) -> None:
    session = {"harness": "codex", "session": "s", "inferred": False, "file": "rollout.jsonl"}
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t", "model_sessions": [session]}))
    (tmp_path / "rollout.jsonl").write_text('{"type": "world_state"}\n')
    report = trace.build(tmp_path)
    assert report["sessions"][0]["version"] == "unknown"
    assert report["findings"][0]["detail"] == "version unknown, tested: 0.160.0"

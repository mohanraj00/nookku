"""`nookku faults`: each check of the trace on its seeded faults (ADR 0002, #546)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nookku import faults, trace
from nookku.cli import main

CASES = Path(__file__).resolve().parent.parent / "conformance" / "trace"


def _copy(tmp_path: Path, *names: str) -> Path:
    for name in names:
        shutil.copytree(CASES / name, tmp_path / name)
    return tmp_path


def test_each_seeded_fault_of_the_repo_is_found() -> None:
    result = faults.run(CASES)
    assert result["ok"] and result["missed"] == 0 and result["unseeded"] == []
    assert result["checks"] == len(trace.CHECKS)
    assert {f["check"] for f in result["faults"]} == set(trace.CHECKS)
    assert all(f["found"] and f["error"] is None for f in result["faults"])


def test_a_missed_fault_fails_with_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cases = _copy(tmp_path, "mcp_task_unfinished")
    (cases / "mcp_task_unfinished" / faults.FILE).write_text(
        json.dumps({"faults": [{"check": "mcp_task_unfinished", "turn": 2}]})
    )
    assert main(["faults", "--cases", str(cases), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["missed"] == 1 and not result["faults"][0]["found"]


def test_a_check_with_no_seeded_fault_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = _copy(tmp_path, "mcp_task_unfinished")
    assert main(["faults", "--cases", str(cases)]) == 1
    out = capsys.readouterr().out
    assert "found  mcp_task_unfinished (turn 1) in mcp_task_unfinished" in out
    assert "NO FAULT agent_error: no trace case has a seeded fault of this check" in out
    assert f"1 of 1 seeded faults found in 1 trace cases. 1 of {len(trace.CHECKS)} checks" in out


def test_a_case_that_the_trace_cannot_read_misses_its_faults(tmp_path: Path) -> None:
    cases = _copy(tmp_path, "mcp_task_unfinished")
    (cases / "mcp_task_unfinished" / "manifest.json").write_text("[")
    result = faults.run(cases)
    assert not result["faults"][0]["found"]
    assert result["faults"][0]["error"].startswith("mcp_task_unfinished/manifest.json")


@pytest.mark.parametrize(
    "data",
    [
        "[",
        "[]",
        '{"faults": []}',
        '{"faults": [{"check": "no_such_check", "turn": 1}]}',
        '{"faults": [{"check": "agent_error"}]}',
        '{"faults": [{"check": "agent_error", "turn": true}]}',
    ],
)
def test_a_faults_file_that_is_not_valid_stops_with_2(
    tmp_path: Path, data: str, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = _copy(tmp_path, "mcp_task_unfinished")
    (cases / "mcp_task_unfinished" / faults.FILE).write_text(data)
    assert main(["faults", "--cases", str(cases)]) == 2
    assert faults.FILE in capsys.readouterr().err


def test_a_folder_with_no_case_stops_with_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["faults", "--cases", str(tmp_path)]) == 2
    assert main(["faults", "--cases", str(tmp_path / "none")]) == 2
    assert "has no trace case" in capsys.readouterr().err

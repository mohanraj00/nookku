import json
import shutil
from pathlib import Path

import pytest

from nookku import seal
from nookku.cli import main

CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "seal").iterdir())
TEST = "20261006-120000-se01"


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_conformance(case: Path) -> None:
    expect = json.loads((case / "expect_verify.json").read_text())
    assert seal.verify(case / "test" / TEST, case / "home") == expect


def folder(tmp_path: Path) -> Path:
    """A copy of the intact case, as a test folder of a project."""
    f = tmp_path / ".nookku" / "tests" / TEST
    shutil.copytree(CASES[0].parent / "intact" / "test" / TEST, f)
    (f / "seal.json").unlink()
    return f


def test_write_seals_the_folder_and_writes_the_copy(tmp_path: Path, seal_home: Path) -> None:
    f = folder(tmp_path)
    assert seal.write(f) is None
    result = seal.verify(f)
    assert result["intact"] and result["copy"] == "same"
    assert "report.md" not in json.loads((f / "seal.json").read_text())["files"]
    assert (seal_home / "seals" / f"{TEST}.json").exists()


def test_verify_finds_the_copy_of_a_test_that_verbatim_relay_sealed(
    tmp_path: Path, seal_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old-home"
    monkeypatch.setenv("NOOKKU_HOME", str(old))
    f = folder(tmp_path)
    assert seal.write(f) is None
    monkeypatch.setenv("NOOKKU_HOME", str(seal_home))
    monkeypatch.setenv("VERBATIM_RELAY_HOME", str(old))
    assert seal.verify(f)["copy"] == "same"
    assert seal.verify(f)["intact"]
    assert not (seal_home / "seals" / f"{TEST}.json").exists()


def test_a_new_seal_goes_to_the_new_home(tmp_path: Path, seal_home: Path) -> None:
    assert seal.copy_path(TEST) == seal_home / "seals" / f"{TEST}.json"


def test_a_seal_with_no_copy_says_so(tmp_path: Path) -> None:
    f = folder(tmp_path)
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("")
    assert seal.write(f, blocked) is not None
    assert json.loads((f / "seal.json").read_text())["copy"] is False
    assert seal.verify(f, blocked)["copy"] == "none"
    assert seal.summary(seal.verify(f, blocked)).startswith("Seal: intact (no copy")


def test_update_puts_the_new_hashes_in_both_seals(tmp_path: Path) -> None:
    f = folder(tmp_path)
    seal.write(f)
    (f / "trace.jsonl").write_text('{"rebuilt": true}\n')
    assert seal.verify(f)["changed"] == ["trace.jsonl"]
    seal.update(f, ["trace.jsonl", "findings.json"])
    assert seal.verify(f)["intact"]


def test_the_summary_names_each_broken_part() -> None:
    result = {
        "sealed": False,
        "intact": False,
        "changed": ["trace.jsonl"],
        "missing": [],
        "added": ["x"],
        "copy": "different",
    }
    assert seal.summary(result) == (
        "Seal: BROKEN. seal.json is missing; changed: trace.jsonl; new: x; "
        "the copy of the seal is different. Do not trust these records."
    )


def test_cli_verify_and_the_trace_rebuild(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    f = folder(tmp_path)
    seal.write(f)
    assert main(["verify", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("Seal: intact.")
    (f / "tap.jsonl").write_text('{"changed": true}\n')
    assert main(["verify", TEST, "--root", str(tmp_path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["changed"] == ["tap.jsonl"]
    # A changed source stops the rebuild of the trace, so the trace does not hide the change.
    assert main(["trace", TEST, "--root", str(tmp_path)]) == 2
    assert "the trace was not rebuilt" in capsys.readouterr().err

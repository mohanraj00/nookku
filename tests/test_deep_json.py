"""JSON that nests too deep in a file of a test folder (#471).

json.loads raises RecursionError for such a text, not ValueError. Each reader of a test folder
must give the error of a file that is not JSON, not a traceback.
"""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from nookku import evaluation, seal, trace
from nookku.cli import main
from nookku.record import RecordError, loads, read_manifest

CASE = Path(__file__).resolve().parent.parent / "conformance" / "trace" / "claude_code_toy_shop"
TEST = "20261022-100000-ab12"
DEEP = '{"a": ' + "[" * 100_000 + "]" * 100_000 + "}"
FILES = [
    "manifest.json",
    "tap.jsonl",
    "relay.jsonl",
    "notes.jsonl",
    "trace.jsonl",
    "findings.json",
    "performance.json",
    "audit.json",
    "seal.json",
    "sessions/claude-code/4f1c2a7e-0d3b-4c55-9a61-2b8e5d7c9f10.jsonl",
]


def _folder(tmp_path: Path, name: str, sealed: bool = True) -> tuple[Path, Path]:
    """A project with one test of the toy shop, and one file with JSON that nests too deep: the
    only object of a .json file, or the last line of a .jsonl file. A sealed test has its seal
    from before the change."""
    root = tmp_path / "shop"
    folder = root / ".nookku" / "tests" / TEST
    shutil.copytree(CASE, folder)
    (root / ".nookku" / "config.json").write_text(json.dumps({"entry": ["true"], "models": []}))
    trace.build(folder)
    if sealed:
        seal.write(folder, tmp_path / "home")
    path = folder / name
    if name.endswith(".json"):
        path.write_text(DEEP)
    else:
        old = path.read_text() if path.exists() else ""
        path.write_text(old + DEEP + "\n")
    return root, folder


def _readers(root: Path, folder: Path) -> list[tuple[str, Callable[[], object]]]:
    at = ["--root", str(root)]
    return [
        ("trace", lambda: main(["trace", *at, TEST])),
        ("transcript", lambda: main(["transcript", *at, "--test", TEST])),
        ("transcript --trace", lambda: main(["transcript", *at, "--trace", "--test", TEST])),
        ("verify", lambda: main(["verify", *at, TEST])),
        ("export", lambda: main(["export", *at, TEST, "--out", str(root / "t.html")])),
        ("script save", lambda: main(["script", "save", *at, TEST])),
        ("prompt", lambda: evaluation.prompt(folder)),
    ]


@pytest.mark.parametrize("name", FILES)
def test_each_reader_gives_an_error_not_a_traceback(
    tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    root, folder = _folder(tmp_path, name)
    for label, read in _readers(root, folder):
        try:
            read()
        except SystemExit:
            pass
        except RecursionError:  # pragma: no cover - the failure that this test finds
            pytest.fail(f"{label} raised RecursionError for {name}")
    capsys.readouterr()


def test_the_trace_names_a_manifest_that_nests_too_deep(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, folder = _folder(tmp_path, "manifest.json", sealed=False)
    with pytest.raises(RecordError, match=r"manifest.json: not JSON \(the JSON nests too deep\)"):
        read_manifest(folder)
    assert main(["trace", "--root", str(root), TEST]) == 2
    assert "not JSON (the JSON nests too deep)" in capsys.readouterr().err


def test_a_tap_line_that_nests_too_deep_is_not_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = _folder(tmp_path, "tap.jsonl", sealed=False)
    assert main(["transcript", "--root", str(root), "--trace", "--test", TEST]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Record: INVALID.") and "not JSON (the JSON nests too deep)" in out


def test_loads_raises_a_value_error_for_json_that_nests_too_deep() -> None:
    with pytest.raises(json.JSONDecodeError, match="the JSON nests too deep"):
        loads(DEEP)
    with pytest.raises(json.JSONDecodeError):
        loads(DEEP.encode())
    assert loads('{"a": [[1]]}') == {"a": [[1]]}

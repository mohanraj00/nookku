"""JSON that nests too deep in a file of a test folder (#471).

json.loads raises RecursionError for such a text, not ValueError. Each reader of a test folder
must give the error of a file that is not JSON, not a traceback.
"""

import io
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nookku import (
    bridge,
    claude_gate,
    codex_gate,
    config,
    dashboard,
    discovery,
    evaluation,
    kit,
    page,
    page_auto,
    policy,
    seal,
    state,
    trace,
)
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


def test_deep_project_config_is_invalid_for_the_relay_and_guard(tmp_path: Path) -> None:
    path = tmp_path / config.FILE
    path.parent.mkdir()
    path.write_text(DEEP)
    with pytest.raises(config.ConfigError, match=r"config\.json.*the JSON nests too deep"):
        config.read_config(tmp_path)
    assert kit._guard_config(tmp_path) == kit.Config()


def test_deep_legacy_config_stops_the_move(tmp_path: Path) -> None:
    path = tmp_path / config.OLD_STATE_DIR / config.NAME
    path.parent.mkdir()
    path.write_text(DEEP)
    assert "the JSON nests too deep" in (config.move_old_state(tmp_path) or "")
    assert path.is_file()


def test_deep_current_json_means_no_active_test(tmp_path: Path) -> None:
    path = state.state(tmp_path) / "current.json"
    path.parent.mkdir()
    path.write_text(DEEP)
    assert state.current(tmp_path) is None
    assert dashboard.running_id(tmp_path) is None
    assert not page._active(tmp_path)
    assert not page_auto._runs(tmp_path, TEST)
    assert path.read_text() == DEEP


def test_deep_page_json_is_invalid(tmp_path: Path) -> None:
    path = state.state(tmp_path) / state.PAGE_FILE
    path.parent.mkdir()
    path.write_text(DEEP)
    assert state.page_info(tmp_path) is None


def test_deep_tests_dirs_json_is_refused(tmp_path: Path) -> None:
    path = state.state(tmp_path) / state.TESTS_DIRS
    path.parent.mkdir()
    path.write_text(DEEP)
    with pytest.raises(state.TestsDirError, match="the JSON nests too deep"):
        state.known_tests_dirs(tmp_path)


def test_deep_policy_json_is_refused(tmp_path: Path) -> None:
    path = policy.path(tmp_path)
    path.parent.mkdir()
    path.write_text(DEEP)
    with pytest.raises(policy.PolicyError, match="the JSON nests too deep"):
        policy.read(tmp_path)


@pytest.mark.real_discovery
def test_deep_egress_json_is_invalid(tmp_path: Path) -> None:
    path = discovery.path(tmp_path)
    path.parent.mkdir()
    path.write_text(DEEP)
    assert discovery.pending(tmp_path) is None


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_deep_hook_settings_are_refused_before_edit(tmp_path: Path, harness: str) -> None:
    target = kit.hook_file(tmp_path, harness)
    assert target is not None
    target.parent.mkdir()
    target.write_text(DEEP)
    with pytest.raises(ValueError, match="the JSON nests too deep"):
        kit.init(tmp_path, harness, {})
    with pytest.raises(ValueError, match="the JSON nests too deep"):
        kit.remove(tmp_path, harness)
    assert target.read_text() == DEEP
    assert not (tmp_path / config.FILE).exists()
    if harness == "codex":
        assert codex_gate._project_events(tmp_path) == set()
    else:
        assert claude_gate._read(target) == {}


def test_deep_hook_input_still_blocks_in_relay_mode(tmp_path: Path) -> None:
    kit.init(tmp_path, "codex", {})
    kit.set_mode(tmp_path, True)
    output = io.StringIO()
    assert kit.run_hook(tmp_path, "codex", io.StringIO(DEEP), output) == 0
    result = json.loads(output.getvalue())
    assert result["decision"] == "block"
    assert "the JSON nests too deep" in result["reason"]


def test_a_deep_ending_file_does_not_stop_the_bridge_from_finishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    path = tmp_path / config.FILE
    path.parent.mkdir()
    app = CASE.parents[2] / "examples" / "toy-shop" / "agent.py"
    path.write_text(json.dumps({"entry": [sys.executable, str(app)], "otel": False, "page": False}))
    cur = bridge.start(tmp_path)
    ending = state.state(tmp_path) / bridge.ENDING
    try:
        ending.write_text(DEEP)
    finally:
        result = bridge.end(tmp_path)
    assert result is not None and result.get("ended") is not None
    assert not ending.exists()
    assert (Path(cur["dir"]) / seal.SEAL).is_file()

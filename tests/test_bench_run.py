import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

RUN = Path(__file__).resolve().parents[1] / "bench" / "run.py"


def mark_done(out: Path, session_id: str) -> None:
    session = out / session_id
    session.mkdir(parents=True)
    (session / "meta.json").write_text('{"done": true}\n')


@pytest.fixture
def benchmark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path]:
    monkeypatch.syspath_prepend(str(RUN.parent))
    spec = importlib.util.spec_from_file_location("bench_run", RUN)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "BENCH", tmp_path)
    monkeypatch.setattr(sys, "argv", [str(RUN), "prompt", "codex"])
    version_command = Mock(return_value=SimpleNamespace(stdout="codex 2.0\n"))
    monkeypatch.setattr(runner, "subprocess", SimpleNamespace(run=version_command))
    monkeypatch.setattr(runner, "BenchAgent", Mock(side_effect=AssertionError("Unexpected agent")))
    (tmp_path / "sessions.json").write_text(json.dumps({"sessions": [{"id": "a"}, {"id": "b"}]}))
    out = tmp_path / "runs" / "codex-prompt"
    mark_done(out, "a")
    return runner, out


@pytest.mark.parametrize("previous", [b'{\n  "version": "codex 1.0"\n}\n', None])
def test_all_sessions_done_preserves_harness_version(
    benchmark: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str], previous: bytes | None
) -> None:
    runner, out = benchmark
    mark_done(out, "b")
    version = out / "harness.json"
    if previous is not None:
        version.write_bytes(previous)

    status = runner.main()

    assert (version.read_bytes() if version.exists() else None) == previous
    assert status != 0
    assert capsys.readouterr().err == (
        f"Each session in {out} is already done, so this run measured no turn. "
        "Use a new run folder for a new version.\n"
    )
    runner.subprocess.run.assert_not_called()


def test_pending_session_runs_and_writes_harness_version(
    benchmark: tuple[ModuleType, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, out = benchmark
    version = out / "harness.json"
    version.write_text('{"version": "codex 1.0"}\n')
    run_session = Mock(return_value="b done")
    monkeypatch.setattr(runner, "run_session", run_session)

    assert runner.main() == 0

    run_session.assert_called_once_with("prompt", "codex", {"id": "b"}, out)
    assert version.read_text() == '{"version": "codex 2.0"}\n'

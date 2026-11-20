import signal
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import proof_codex_gate as proof
from proof_codex_gate import home_pids, home_start, signal_same, stop_home

from nookku import state
from nookku.cli import main

HOME = Path("/work/.proof/codex-gate/codex-home")
DAEMON = f"{HOME}/packages/app-server-daemon/bin/codex app-server --listen unix:// --managed-daemon"


def test_the_proof_sets_up_a_toy_shop_in_a_path_with_a_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = tmp_path / "Toy Shop"
    entry = shop / "agent.py"
    monkeypatch.setattr(proof, "PROJECT", shop)
    monkeypatch.setattr(proof, "TOY_SHOP", entry)

    def run(cmd: list[str], cwd: Path) -> None:
        assert main([*cmd[1:], "--root", str(cwd)]) == 0

    monkeypatch.setattr(proof, "run", run)
    proof.project()
    config = proof.loads((shop / ".nookku" / "config.json").read_text())
    assert config["entry"] == [sys.executable, str(entry)]
    assert config["page"] is False


def test_only_a_process_with_a_path_in_the_home_matches() -> None:
    ps = "\n".join(
        [
            f"  101 {DAEMON}",
            "  102 /usr/local/bin/codex app-server --listen unix:// --managed-daemon",
            f"  103 {HOME}2/packages/app-server-daemon/bin/codex app-server",
            "  104 /other/.proof/codex-gate/codex-home/bin/codex app-server",
            f"  105 codex exec --config=home={HOME}/config.toml",
            f"  106 codex -C {HOME}",
            "  not-a-pid line",
        ]
    )
    assert home_pids(ps, HOME) == [101, 105, 106]


def test_a_home_path_with_a_space_matches() -> None:
    home = Path("/work/toy shop/.proof/codex-gate/codex-home")
    ps = "\n".join(
        [
            f"  201 {home}/packages/app-server-daemon/bin/codex app-server --managed-daemon",
            "  202 /work/toy shop/.proof/codex-gate/codex-home2/bin/codex app-server",
            "  203 /work/toy /other/.proof/codex-gate/codex-home/bin/codex",
        ]
    )
    assert home_pids(ps, home) == [201]


def sleeper(path: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(path)])


def test_stop_home_stops_the_processes_of_the_home_and_waits_for_them(tmp_path: Path) -> None:
    home = tmp_path / "codex-home"
    inside = sleeper(home / "bin" / "codex")
    outside = sleeper(tmp_path / "codex-home-other" / "bin" / "codex")
    try:
        stop_home(home, timeout=5)
        assert inside.wait(timeout=5) is not None
        assert outside.poll() is None
    finally:
        inside.kill()
        outside.kill()
        inside.wait()
        outside.wait()


def test_a_pid_with_a_different_start_time_gets_no_signal(tmp_path: Path) -> None:
    proc = sleeper(tmp_path / "codex-home" / "bin" / "codex")
    try:
        start = state.process_start(proc.pid)
        assert start is not None
        signal_same(proc.pid, start + " of an older process", signal.SIGTERM)
        assert proc.poll() is None
        signal_same(proc.pid, start, signal.SIGTERM)
        assert proc.wait(timeout=5) == -signal.SIGTERM
    finally:
        proc.kill()
        proc.wait()


def test_home_start_binds_the_start_time_only_to_a_process_of_the_home(tmp_path: Path) -> None:
    home = tmp_path / "codex-home"
    inside = sleeper(home / "bin" / "codex")
    outside = sleeper(tmp_path / "codex-home-other" / "bin" / "codex")
    try:
        assert home_start(inside.pid, home) == state.process_start(inside.pid)
        assert home_start(outside.pid, home) is None
        inside.kill()
        inside.wait()
        assert home_start(inside.pid, home) is None
    finally:
        inside.kill()
        outside.kill()
        inside.wait()
        outside.wait()


def _gate(**hashes: str) -> dict[str, list[dict[str, str]]]:
    return {"hooks": [{"event": event, "hash": value} for event, value in hashes.items()]}


def test_the_hook_part_is_the_part_before_the_slash() -> None:
    # The 2 parts of the trust hash of codex-cli 0.169.0 (proofs/codex-gate/gate.json), and the
    # 1 part of an older Codex.
    gate = _gate(preToolUse="sha256:aa/sha256:bb", userPromptSubmit="sha256:cc")
    assert proof.hook_parts(gate) == {"preToolUse": "sha256:aa", "userPromptSubmit": "sha256:cc"}


def test_a_script_change_that_changes_only_the_second_part_keeps_the_hook_part() -> None:
    before = _gate(preToolUse="sha256:aa/sha256:bb", userPromptSubmit="sha256:cc/sha256:bb")
    after = _gate(preToolUse="sha256:aa/sha256:dd", userPromptSubmit="sha256:cc/sha256:dd")
    assert proof.hashes(after) != proof.hashes(before)
    assert proof.hook_parts(after) == proof.hook_parts(before)

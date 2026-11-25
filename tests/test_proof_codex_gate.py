import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def _gate(*, problems: tuple[str, ...] = (), **hashes: str | None) -> dict[str, Any]:
    return {
        "hooks": [{"event": event, "hash": value} for event, value in hashes.items()],
        "problems": list(problems),
    }


def test_the_hook_part_is_the_part_before_the_slash() -> None:
    # The 2 parts of the trust hash of codex-cli 0.169.0 (proofs/codex-gate/gate.json), and the
    # 1 part of an older Codex.
    gate = _gate(preToolUse="sha256:aa/sha256:bb", userPromptSubmit="sha256:cc")
    assert proof.hook_parts(gate) == {"preToolUse": "sha256:aa", "userPromptSubmit": "sha256:cc"}


@pytest.fixture
def installed_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    state_dir = project / proof.STATE_DIR
    state_dir.mkdir(parents=True)
    (state_dir / "mode").write_text("off\n")
    monkeypatch.setattr(proof, "PROJECT", project)
    installed = tmp_path / proof.__version__
    hooks = installed / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "nookku-hook.sh").write_text("#!/bin/sh\n")
    (hooks / "hooks.json").write_text('{"hooks":{"PreToolUse":[{"hooks":[{"timeout":1}]}]}}')
    return installed


@pytest.fixture
def untrusted_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "is untrusted, not trusted", "")

    monkeypatch.setattr(proof, "run", run)


@pytest.mark.parametrize("value", [None, "md5:cc"])
@pytest.mark.parametrize("snapshot", [0, 1, 2])
def test_part_a_fails_if_a_trust_hash_does_not_start_with_sha256(
    installed_plugin: Path,
    untrusted_start: None,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    snapshot: int,
) -> None:
    results = [
        _gate(preToolUse="sha256:aa", userPromptSubmit="sha256:cc"),
        _gate(preToolUse="sha256:aa", userPromptSubmit="sha256:cc", problems=("its script",)),
        _gate(preToolUse="sha256:bb", userPromptSubmit="sha256:cc"),
    ]
    results[snapshot]["hooks"][1]["hash"] = value
    monkeypatch.setattr(proof, "gate", iter(results).__next__)

    checks = proof.part_a(installed_plugin)["checks"]

    assert checks["each trust hash starts with sha256:"] is False


@pytest.mark.parametrize(
    ("before_suffix", "pre_tool_suffix", "prompt_suffix", "expected"),
    [
        ("/sha256:bb", "/sha256:dd", "/sha256:dd", True),
        ("/sha256:bb", "/sha256:bb", "/sha256:dd", False),
        ("/sha256:bb", "", "/sha256:dd", False),
        ("", "", "", None),
    ],
)
def test_part_a_checks_each_two_part_hash_after_a_script_change(
    installed_plugin: Path,
    untrusted_start: None,
    monkeypatch: pytest.MonkeyPatch,
    before_suffix: str,
    pre_tool_suffix: str,
    prompt_suffix: str,
    expected: bool | None,
) -> None:
    before = _gate(
        preToolUse=f"sha256:aa{before_suffix}", userPromptSubmit=f"sha256:cc{before_suffix}"
    )
    after_script = _gate(
        preToolUse=f"sha256:aa{pre_tool_suffix}",
        userPromptSubmit=f"sha256:cc{prompt_suffix}",
        problems=("its script",),
    )
    after_timeout = _gate(
        preToolUse=f"sha256:ee{before_suffix}", userPromptSubmit=f"sha256:cc{before_suffix}"
    )
    monkeypatch.setattr(proof, "gate", iter([before, after_script, after_timeout]).__next__)

    checks = proof.part_a(installed_plugin)["checks"]

    assert checks.get("a script change changes each two-part trust hash") is expected
    assert checks["each trust hash starts with sha256:"] is True
    assert checks["a script change keeps the hook part of the trust hash"] is True
    assert all(checks.values()) is (expected is not False)


@pytest.mark.parametrize("has_hooks", [True, False])
def test_part_b_records_each_check_as_a_boolean(
    installed_plugin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_hooks: bool
) -> None:
    gate = _gate(preToolUse="sha256:aa", userPromptSubmit="sha256:cc") if has_hooks else _gate()
    monkeypatch.setattr(proof, "gate", lambda: gate)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"codex_gate": {"start": gate, "end": gate}})
    )

    def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"dir": str(tmp_path)}), "")

    monkeypatch.setattr(proof, "run", run)

    result = proof.part_b(installed_plugin)

    assert result["gate"]["hooks"] == gate["hooks"]
    assert all(isinstance(value, bool) for value in result["checks"].values())
    assert result["checks"]["the gate passes with trusted hooks"] is has_hooks

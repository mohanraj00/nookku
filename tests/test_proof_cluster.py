import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def proof(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("proof_cluster")


def test_login_waits_for_its_secret_key(proof, monkeypatch):
    replies = iter(["codex", "codex claude-code"])
    seen = []

    def secret(args, **kwargs):
        seen.append(args[-1])
        return subprocess.CompletedProcess(args, 0, stdout=next(replies))

    def shell(command):
        assert len(seen) == 2
        assert 'test -n "$CLAUDE_CODE_OAUTH_TOKEN"' in command
        return "yes"

    monkeypatch.setattr(proof.subprocess, "run", secret)
    monkeypatch.setattr(proof.time, "sleep", lambda _: None)
    cluster = SimpleNamespace(name="proof", kubectl="kubectl")
    proof.wait_for_login(cluster, SimpleNamespace(sh=shell), 30, "koodam")
    assert seen == ["go-template={{range $k, $v := .data}}{{$k}} {{end}}"] * 2


def test_manifests_pin_the_preset_by_digest(proof):
    values, objects = proof.manifests(("172.18.0.2", "6443"), "2.1.319")
    assert f"image: {proof.NOOKKU_IMAGE}" in values
    assert "@sha256:" in proof.NOOKKU_IMAGE and "@sha256:" in proof.WORKSPACE_BASE
    assert proof.CHART_DIGEST.startswith("sha256:")
    assert "mode: bundled" in values and f"modelName: {proof.MODEL}" in values
    assert "plugins: [nookku]" in objects
    assert f"image: {proof.WORKSPACE_IMAGE}" in objects
    assert f"FROM {proof.WORKSPACE_BASE}" in proof.WORKSPACE_DOCKERFILE


def test_tag_plugin_skips_the_test_file(proof):
    files = proof.tag_plugin(proof.PRESET_NOOKKU)
    assert "hooks/register.test.ts" not in files
    assert {"hooks/hooks.json", "hooks/register.tsx", ".mcp.json"} <= set(files)


def test_login_prompt_removes_the_gateway_env(proof):
    scripts = []

    def sh(script, *, data=None, timeout=300):
        scripts.append(script)
        return ""

    ws = proof.Workspace(SimpleNamespace())
    ws.sh = sh
    ws.claude("nookku status")
    ws.claude("nookku end", login=True)
    assert "unset" not in scripts[0]
    assert "unset ${!ANTHROPIC_@} CLAUDE_CODE_SUBAGENT_MODEL && claude -p" in scripts[1]
    assert all(f"--plugin-dir={proof.PLUGIN_DIR}" in s for s in scripts)


def good_w1(proof):
    return {
        "phase": "Running",
        "conditions": {"TracedEgress": "True", "Harnesses": "True"},
        "init_exit_codes": {name: 0 for name in proof.PRESET_INIT},
        "preset": {
            "nookku_path": proof.PRESET_LAUNCHER,
            "nookku_version": proof.PRESET_NOOKKU,
            "tests_dir": proof.TESTS,
            "tests_dir_mode": "700",
            "python3_flags": ["1", "1"],
            "tests_dir_on_home": proof.HOME,
            "files_read_only": True,
            "plugin_same_as_tag": True,
        },
        "plugin_paths": [proof.PLUGIN_DIR],
        "mcp_servers": ["plugin:nookku:nookku"],
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda w: w["conditions"].update(Harnesses="False"),
        lambda w: w["init_exit_codes"].update({"koodam-nookku-python": 1}),
        lambda w: w["preset"].update(nookku_version="0.6.1"),
        lambda w: w["preset"].update(tests_dir=""),
        lambda w: w["preset"].update(python3_flags=["0", "1"]),
        lambda w: w["preset"].update(files_read_only=False),
        lambda w: w["preset"].update(plugin_same_as_tag=False),
        lambda w: w.update(plugin_paths=[]),
        lambda w: w.update(mcp_servers=["plugin:nookku:nookku", "other"]),
    ],
)
def test_w1_fails_on_each_preset_break(proof, change):
    w1 = good_w1(proof)
    assert proof.w1_pass(w1)
    change(w1)
    assert not proof.w1_pass(w1)


def test_main_refuses_another_koodam_cli(proof, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["proof_cluster.py", "plugin-claude-code"])
    monkeypatch.setattr(proof, "tool", lambda name: name)
    monkeypatch.setattr(proof, "run", lambda args: b"koodam 0.3.0")
    monkeypatch.setattr(proof, "Cluster", lambda _: pytest.fail("the proof made a cluster"))
    with pytest.raises(SystemExit, match=r"koodam CLI 0\.5\.0"):
        proof.main()


def test_retry_waits_for_a_late_answer(proof, monkeypatch):
    waits = []
    monkeypatch.setattr(proof.time, "sleep", waits.append)
    answers = iter([SystemExit("connection refused"), False, "ok"])

    def check():
        value = next(answers)
        if isinstance(value, BaseException):
            raise value
        return value

    assert proof.retry("API", check) == "ok"
    assert waits == [proof.EVERY] * 2
    assert (proof.TRIES, proof.EVERY) == (60, 5.0)


def test_retry_stops_after_its_tries(proof, monkeypatch):
    monkeypatch.setattr(proof.time, "sleep", lambda _: None)

    def check():
        raise SystemExit("connection refused")

    with pytest.raises(SystemExit, match=r"no API after 3 tries.*connection refused"):
        proof.retry("API", check, tries=3)


def test_profile_step_gives_the_launcher_and_the_lib(proof):
    writes = {}

    def sh(script, *, data=None, timeout=300):
        writes[script] = data
        return ""

    ws = proof.Workspace(SimpleNamespace())
    ws.sh = sh
    proof.setup_project(ws)
    profile = writes[f"cat >> {proof.HOME}/.profile"].decode().split("\n")
    assert f"export PATH={proof.PRESET_BIN}:$PATH" in profile
    assert f"export PYTHONPATH={proof.PRESET_LIB} PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1" in profile
    assert "(3, 11)" in proof.WORKSPACE_DOCKERFILE
    assert proof.ENTRY == ["python3", "service_entry.py"]
    assert proof.PATH_ISSUE.endswith("/koodam/issues/476")
    assert proof.LIB_ISSUE.startswith("https://github.com/mohanraj00/koodam/issues/")

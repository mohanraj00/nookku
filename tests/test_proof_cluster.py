import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def proof(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("proof_cluster")


def test_codex_login_waits_for_its_secret_key(proof, monkeypatch):
    replies = iter(["claude-code", "claude-code codex"])
    seen = []

    def secret(args, **kwargs):
        seen.append(args[-1])
        return subprocess.CompletedProcess(args, 0, stdout=next(replies))

    def shell(command):
        assert len(seen) == 2
        assert 'test -s "$HOME/.codex/auth.json"' in command
        return "yes"

    monkeypatch.setattr(proof.subprocess, "run", secret)
    monkeypatch.setattr(proof.time, "sleep", lambda _: None)
    cluster = SimpleNamespace(name="proof", kubectl="kubectl")
    proof.wait_for_login(cluster, SimpleNamespace(sh=shell), 30, "koodam", "codex")
    assert seen == ["go-template={{range $k, $v := .data}}{{$k}} {{end}}"] * 2


@pytest.mark.parametrize("enabled", [True, False])
def test_codex_setup_checks_the_enabled_plugin(proof, enabled):
    def shell(command):
        if "python -c" in command:
            return json.dumps(
                {
                    "hooks": [
                        {"trust": "trusted", "origin": "plugin", "event": event}
                        for event in ("preToolUse", "userPromptSubmit")
                    ],
                    "problems": [],
                }
            )
        if "plugin list" in command:
            return json.dumps({"installed": [{"pluginId": proof.PLUGIN_ID, "enabled": enabled}]})
        assert "mcp list" in command
        return json.dumps([{"name": "nookku", "enabled": True}])

    ws = SimpleNamespace(sh=shell)
    if enabled:
        assert proof.codex_setup(ws, "/wheel") == ([proof.PLUGIN_ID], ["nookku"])
    else:
        with pytest.raises(SystemExit, match="enabled nookku plugin"):
            proof.codex_setup(ws, "/wheel")


def test_failed_resume_reports_retained_cluster_and_removes_temp_dir(proof, monkeypatch, capsys):
    class Cluster:
        name = "proof"

        def exists(self):
            return True

        def delete(self):
            pytest.fail("the proof deleted the resumed cluster")

    dirs = []

    def fail(cluster, koodam, work, login_wait, harness, *, resume):
        assert resume
        assert work.is_dir()
        dirs.append(work)
        raise SystemExit("the proof stopped")

    monkeypatch.setattr(sys, "argv", ["proof_cluster.py", "plugin-codex", "--resume"])
    monkeypatch.setattr(proof, "Cluster", lambda _: Cluster())
    monkeypatch.setattr(proof, "tool", lambda name: name)
    monkeypatch.setattr(proof, "run", lambda args: b"koodam 0.3.0")
    monkeypatch.setattr(proof, "free_space", lambda cluster: None)
    monkeypatch.setattr(proof, "prove", fail)
    with pytest.raises(SystemExit, match="the proof stopped"):
        proof.main()
    assert "kind delete cluster --name proof" in capsys.readouterr().err
    assert len(dirs) == 1
    assert not dirs[0].exists()

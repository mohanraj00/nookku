import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def proof(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("proof_cluster_tap")


def test_free_space_stops_when_the_base_image_is_missing(proof, monkeypatch):
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            [], 1, stderr=b"Error: No such image: python:3.12-slim"
        )
    )
    monkeypatch.setattr(proof.subprocess, "run", runner)

    with pytest.raises(SystemExit) as stopped:
        proof.free_space(SimpleNamespace(docker="docker"))

    runner.assert_called_once()
    assert runner.call_args.args[0] == ["docker", "image", "inspect", "python:3.12-slim"]
    assert str(stopped.value) == (
        "Docker has no image python:3.12-slim. Run the following command.\n"
        "  docker pull python:3.12-slim"
    )


def test_free_space_gives_other_docker_errors_as_they_are(proof, monkeypatch):
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            [], 1, stderr=b"Cannot connect to the Docker daemon"
        )
    )
    monkeypatch.setattr(proof.subprocess, "run", runner)

    with pytest.raises(SystemExit) as stopped:
        proof.free_space(SimpleNamespace(docker="docker"))

    assert "Cannot connect to the Docker daemon" in str(stopped.value)
    assert "docker pull" not in str(stopped.value)


def test_free_space_uses_the_local_base_image(proof, monkeypatch):
    runner = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout=b"[]\n"),
            subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    b"Filesystem 1M-blocks Used Available Use% Mounted on\n"
                    b"overlay 4096 2048 2048 50% /\n"
                ),
            ),
        ]
    )
    monkeypatch.setattr(proof.subprocess, "run", runner)

    assert proof.free_space(SimpleNamespace(docker="docker")) == 2048
    assert [call.args[0] for call in runner.call_args_list] == [
        ["docker", "image", "inspect", "python:3.12-slim"],
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--entrypoint",
            "df",
            "python:3.12-slim",
            "-m",
            "/var/lib",
        ],
    ]

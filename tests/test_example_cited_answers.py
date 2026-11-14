"""The example of a CI gate on a verdict (docs/how-to/gate-a-ci-job.md): a toy shop agent that
retrieves a section of a local store and cites its locator. The test needs no model and no
login, so it runs in CI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nookku import bridge
from nookku.cli import main

# The egress answer of the agent: it calls no service.
NO_EGRESS = {"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "toy-shop-docs"


def _project(tmp_path: Path) -> Path:
    """A copy of the example, with the config and the egress answer of the how-to steps."""
    root = tmp_path / "shop"
    shutil.copytree(EXAMPLE, root)
    argv = ["init", "plugin", "--root", str(root), "--entry", "python3 agent.py"]
    assert main([*argv, "--spec", "APP_SPEC.md"]) == 0
    (root / "egress.json").write_text(json.dumps(NO_EGRESS))
    assert main(["register", "--root", str(root), "--file", str(root / "egress.json")]) == 0
    return root


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """The exit code and the report lines of `nookku run --script --verdict`, as one text."""
    capsys.readouterr()
    script = str(root / "script.jsonl")
    argv = ["run", "--script", script, "--root", str(root), "--verdict", "--no-evaluate"]
    code = main([*argv, "--json"])
    return code, "\n".join(json.loads(capsys.readouterr().out)["report"])


@pytest.mark.real_discovery
def test_the_example_passes_its_verdict_with_no_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path)
    code, report = _run(root, capsys)
    assert code == 0, report
    assert "Verdict: pass (3 limits)." in report
    folder = bridge.latest_test(root)
    assert folder is not None
    rows = [json.loads(line) for line in (folder / "tap.jsonl").open()]
    replies = [r["reply"] for r in rows if r["type"] == "exchange"]
    assert json.loads(replies[1]) == {
        "answer": "We ship to Chennai and Pune.",
        "source": "store/shipping.md#cities",
    }


@pytest.mark.real_discovery
def test_a_wrong_locator_fails_the_ci_job(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path)
    # The seeded fault: the agent cites the wrong section for a question of the key.
    agent = root / "agent.py"
    agent.write_text(agent.read_text().replace('("ship to", "deliver to")', '("never",)'))
    code, report = _run(root, capsys)
    assert code == 1, report
    assert "answer_key_mismatch: 1, the limit is 0." in report

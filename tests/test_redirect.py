"""The last verbatim-relay release: one line to stderr, exit 1, an import error, and a separate
release workflow. The tests run the code from the repo, with no build and no network."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "redirect" / "verbatim-relay"
SRC = PACKAGE / "src"
WORKFLOW = ROOT / ".github" / "workflows" / "release-verbatim-relay.yml"
GUIDE = "https://github.com/mohanraj00/nookku/blob/main/docs/how-to/upgrade.md#040"
MESSAGE = f"verbatim-relay is now nookku. To upgrade, follow {GUIDE}"

pytestmark = pytest.mark.skipif(
    not PACKAGE.is_dir(), reason="the sdist of nookku has no redirect folder"
)


def run(code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=30
    )


def test_the_command_prints_one_line_to_stderr_and_exits_1() -> None:
    done = run("import sys, verbatim_relay_redirect as r; sys.exit(r.main())")
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr == MESSAGE + "\n"


def test_the_command_does_not_import_nookku() -> None:
    done = run(
        "import sys, verbatim_relay_redirect as r; r.main(); "
        "print(sorted(m for m in sys.modules if m.split('.')[0] == 'nookku'))"
    )
    assert done.stdout == "[]\n"


def test_the_import_raises_import_error_with_the_message() -> None:
    done = run(
        "try:\n"
        "    import verbatim_relay\n"
        "except ImportError as e:\n"
        "    print(e)\n"
        "else:\n"
        "    print('no error')\n"
    )
    assert done.stdout == MESSAGE + "\n"


@pytest.mark.parametrize("args", [["hook"], ["hook", "--harness", "codex"], []])
def test_an_old_hook_command_exits_2_so_the_hook_fails_closed(args: list[str]) -> None:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    done = subprocess.run(
        [sys.executable, "-m", "verbatim_relay", *args],
        input='{"prompt": "Is the teapot in stock?"}',
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr == MESSAGE + "\n"


def test_the_link_goes_to_the_0_4_0_section_of_the_upgrade_guide() -> None:
    guide = (ROOT / "docs" / "how-to" / "upgrade.md").read_text(encoding="utf-8")
    assert re.search(r"^### 0\.4\.0$", guide, re.MULTILINE)


def test_the_project_names_the_old_package_and_depends_on_nookku() -> None:
    text = (PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^name = "verbatim-relay"$', text, re.MULTILINE)
    assert re.search(r'^version = "0\.4\.0"$', text, re.MULTILINE)
    assert re.search(r'^dependencies = \["nookku>=0\.4\.0"\]$', text, re.MULTILINE)
    assert re.search(r'^verbatim-relay = "verbatim_relay_redirect:main"$', text, re.MULTILINE)
    assert re.search(r'^license = "Apache-2\.0"$', text, re.MULTILINE)
    assert (PACKAGE / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()


def test_the_workflow_runs_only_on_its_own_tag_and_checks_the_version() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'tags: ["verbatim-relay-v*"]' in text
    assert "refs/tags/verbatim-relay-v*) ;;" in text
    assert "verbatim_relay-${GITHUB_REF_NAME#verbatim-relay-v}-py3-none-any.whl" in text
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in release  # "verbatim-relay-v..." does not start with "v"


def test_only_the_publish_job_gets_an_id_token() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("id-token: write") == 1
    publish = text[text.index("\n  publish:") :]
    assert "id-token: write" in publish
    assert "environment: pypi" in publish
    assert "permissions: {}\n\njobs:" in text


def test_the_workflow_pins_the_same_actions_as_release_yml() -> None:
    uses = re.compile(r"uses: (\S+)@(\S+) # (\S+)")
    pinned = dict(
        (name, (sha, tag))
        for name, sha, tag in uses.findall(
            (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        )
    )
    found = uses.findall(WORKFLOW.read_text(encoding="utf-8"))
    assert found
    for name, sha, tag in found:
        assert pinned[name] == (sha, tag), name

"""Child commands use the parent's library from inside the project folder."""

import shutil
import subprocess
import sys
import textwrap
import venv
from collections.abc import Callable
from pathlib import Path

import pytest

import nookku

TOY_SHOP = Path(__file__).resolve().parents[1] / "examples" / "toy-shop" / "agent.py"


@pytest.fixture(params=["install", "launcher"])
def run_in_project(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], None]:
    root = tmp_path / "toy shop's project"
    shadow = root / "nookku"
    shadow.mkdir(parents=True)
    marker = root / "shadow-imported"
    (shadow / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(root))
    monkeypatch.setenv("SSH_CONNECTION", "127.0.0.1 1 127.0.0.1 2")
    python = [sys.executable, "-I"]
    setup = ""
    if request.param == "launcher":
        # The child cannot find Nookku in this environment without the library argument.
        env = tmp_path / "empty venv"
        venv.create(env, symlinks=True)
        library = tmp_path / "launcher library"
        shutil.copytree(Path(nookku.__file__).parent, library / "nookku")
        python = [str(env / "bin" / "python"), "-I", "-S"]
        setup = f"import sys\nsys.path.insert(0, {str(library)!r})\n"

    def run(code: str) -> None:
        proc = subprocess.run(
            [*python, "-c", setup + textwrap.dedent(code)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert not marker.exists()
        assert proc.returncode == 0, proc.stdout + proc.stderr

    return run


def test_the_mcp_wrapper_hook_and_chat_start_in_the_project(run_in_project) -> None:
    run_in_project(
        """
        import json
        import os
        import shlex
        import subprocess
        from pathlib import Path

        from nookku import kit, mcp_proxy, page, page_auto

        root = Path.cwd()
        part = {"name": "stock", "transport": "stdio", "env": "STOCK", "command": ["/bin/cat"]}
        command = mcp_proxy.stdio_environment([part], root)["STOCK"]
        data = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\\n'
        mcp = subprocess.run(shlex.split(command), input=data, capture_output=True, check=True)
        assert mcp.stdout == data
        assert len((root / mcp_proxy.FILE).read_text().splitlines()) == 2

        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": "nookku start"}}
        hook = subprocess.run(
            kit.hook_command(root, "claude-code"), shell=True, input=json.dumps(event),
            capture_output=True, text=True, check=True,
        )
        out = json.loads(hook.stdout)["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"

        # The page process reports this refusal before it needs a socket.
        for name in page.HARNESS_SHELL:
            os.environ.pop(name, None)
        os.environ["CODEX_THREAD_ID"] = "test"
        assert page_auto._start(root, "toy-test", print_url=True) == page_auto.FAILED.format(
            reason="CODEX_THREAD_ID is set, so the URL is not shown"
        )
        """
    )


def test_a_test_starts_relays_a_turn_and_ends(run_in_project) -> None:
    run_in_project(
        f"""
        import json
        import subprocess
        import sys
        import time
        from pathlib import Path

        from nookku import bridge, discovery, kit, page_auto

        root = Path.cwd()
        (root / ".nookku").mkdir()
        (root / ".nookku" / "config.json").write_text(
            json.dumps({{"entry": [sys.executable, {str(TOY_SHOP)!r}], "otel": False}})
        )
        egress = {{"registered": time.time(), "answer": discovery.make()}}
        cur = bridge.start(root, egress=egress)
        try:
            assert page_auto._start(root, cur["test"], print_url=False) == page_auto.NO_BROWSER
            kit.set_mode(root, True)
            event = {{"hook_event_name": "UserPromptSubmit", "prompt": "Do you ship to Chennai?"}}
            hook = subprocess.run(
                kit.hook_command(root, "codex"), shell=True, input=json.dumps(event),
                capture_output=True, text=True, check=True,
            )
            out = json.loads(hook.stdout)
            assert out["decision"] == "block" and out["reason"].startswith("We ship to Chennai")
        finally:
            manifest = bridge.end(root)
        assert manifest is not None and manifest["ended"] >= manifest["started"]
        out = json.loads((Path(cur["dir"]) / "audit.json").read_text())
        assert out["turns"] == out["exchanges"] == 1 and out["breaks"] == []
        """
    )

"""The print mode rule of the Claude Code relay (SPEC.md section 5, #199)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from toy_agent import ToyAgent, shop_reply

from nookku import cli, kit, print_mode, state
from nookku.adapters import make
from nookku.record import read_tap
from nookku.tap import Tap, start_in_thread

QUESTION = "Is the toy mug in stock?"
HOOK = Path(__file__).resolve().parent.parent / "plugins" / "nookku" / "hooks" / "nookku-hook.sh"


@pytest.fixture
def project(tmp_path: Path):
    agent = ToyAgent()
    tap = Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("json"))
    start_in_thread(tap)
    root = tmp_path / "project"
    url = f"http://127.0.0.1:{tap.server_address[1]}/"
    kit.init(root, "claude-code", dict(tap_url=url, agent_url=agent.url))
    yield root, tmp_path / "tap.jsonl"
    tap.shutdown()
    agent.shutdown()


def prompt(text: str) -> dict[str, str]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": text, "session_id": "s1"}


def relay_rows(root: Path) -> list[str]:
    path = root / ".nookku" / "relay.jsonl"
    return path.read_text().splitlines() if path.exists() else []


TITLE_OFF = "CLAUDE_CODE_DISABLE_TERMINAL_TITLE"


@pytest.mark.parametrize(
    ("env", "refused"),
    [
        ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-py"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-ts"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "toy-shop-client"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "CLI"}, True),
        ({}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: "1"}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-py", TITLE_OFF: " ON"}, False),
        ({TITLE_OFF: "true"}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: "0"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: ""}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: "\t1\r\n"}, False),
        # Python strip() removes these characters, and JavaScript trim() does not.
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: "1\x1f"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: "1\x85"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: "\x85on"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", TITLE_OFF: "1\u00a0"}, True),
    ],
)
def test_only_the_interactive_cli_or_the_title_request_off_is_not_refused(
    env: dict[str, str], refused: bool
) -> None:
    assert print_mode.refused(env) is refused


@pytest.mark.parametrize(
    ("env", "harness", "applies"),
    [
        ({}, "claude-code", True),
        ({}, "codex", False),
        ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, "codex", False),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, "codex", True),
    ],
)
def test_the_codex_relay_uses_the_rule_only_with_an_entrypoint(
    env: dict[str, str], harness: str, applies: bool
) -> None:
    assert print_mode.applies(env, harness) is applies


def test_in_print_mode_relay_mode_blocks_and_sends_nothing(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, tap_rec = project
    kit.set_mode(root, True)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    answer = kit.handle(prompt(QUESTION), root, "claude-code")
    assert answer == {"decision": "block", "reason": print_mode.REASON}
    assert relay_rows(root) == []
    assert not tap_rec.exists() or read_tap(tap_rec) == []


def test_in_print_mode_nookku_start_starts_no_test(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    answer = kit.handle(prompt("nookku start"), root, "claude-code")
    assert answer == {"decision": "block", "reason": print_mode.REASON}
    assert not kit.is_on(root)
    assert state.current(root) is None


def test_in_print_mode_status_and_end_still_run(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    kit.set_mode(root, True)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert kit.handle(prompt("nookku status"), root, "claude-code")["reason"] == kit.status(root)
    kit.handle(prompt("nookku end"), root, "claude-code")
    assert not kit.is_on(root)


def test_with_the_title_request_off_print_mode_relays(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, tap_rec = project
    kit.set_mode(root, True)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_TERMINAL_TITLE", "1")
    answer = kit.handle(prompt(QUESTION), root, "claude-code")
    assert answer == {"decision": "block", "reason": shop_reply(QUESTION)}
    assert read_tap(tap_rec)[0].input == QUESTION


@pytest.mark.parametrize("entrypoint", ["sdk-cli", "sdk-py", "sdk-ts", "toy-shop-client"])
def test_each_entrypoint_but_the_interactive_cli_is_refused(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    root, tap_rec = project
    kit.set_mode(root, True)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", entrypoint)
    answer = kit.handle(prompt(QUESTION), root, "claude-code")
    assert answer == {"decision": "block", "reason": print_mode.REASON}
    assert relay_rows(root) == []
    assert not tap_rec.exists() or read_tap(tap_rec) == []


def test_with_no_entrypoint_the_claude_code_relay_refuses(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    kit.set_mode(root, True)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT")
    assert kit.handle(prompt(QUESTION), root, "claude-code")["reason"] == print_mode.REASON
    assert relay_rows(root) == []


def test_the_codex_relay_with_no_entrypoint_relays(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, tap_rec = project
    kit.set_mode(root, True)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT")
    answer = kit.handle(prompt(QUESTION), root, "codex")
    assert answer == {"decision": "block", "reason": shop_reply(QUESTION)}
    assert read_tap(tap_rec)[0].input == QUESTION


def test_the_codex_relay_refuses_a_claude_code_print_mode_entrypoint(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    kit.set_mode(root, True)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert kit.handle(prompt(QUESTION), root, "codex")["reason"] == print_mode.REASON
    assert relay_rows(root) == []


def test_the_hook_command_refuses_print_mode(project: tuple[Path, Path]) -> None:
    root, tap_rec = project
    kit.set_mode(root, True)
    env = {**os.environ, "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}
    env.pop("CLAUDE_CODE_DISABLE_TERMINAL_TITLE", None)
    done = subprocess.run(
        [sys.executable, "-m", "nookku", "hook", "--harness", "claude-code", "--root", str(root)],
        input=json.dumps(prompt(QUESTION)),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert json.loads(done.stdout) == {"decision": "block", "reason": print_mode.REASON}
    assert relay_rows(root) == []
    assert not tap_rec.exists() or read_tap(tap_rec) == []


@pytest.mark.parametrize("plugin_root", [None, "/toy/plugin"])
def test_the_plugin_hook_refuses_print_mode(
    project: tuple[Path, Path], plugin_root: str | None
) -> None:
    """The plugin hook runs nookku from PATH. With PLUGIN_ROOT set, it runs as Codex, and the
    rule still applies."""
    root, tap_rec = project
    kit.set_mode(root, True)
    env = {k: v for k, v in os.environ.items() if k not in ("PLUGIN_ROOT", TITLE_OFF)}
    env.update(
        CLAUDE_CODE_ENTRYPOINT="sdk-cli",
        CLAUDE_PROJECT_DIR=str(root),
        PATH=f"{Path(sys.executable).parent}{os.pathsep}{env['PATH']}",
    )
    if plugin_root:
        env["PLUGIN_ROOT"] = plugin_root
    done = subprocess.run(
        ["sh", str(HOOK), "UserPromptSubmit"],
        input=json.dumps({**prompt(QUESTION), "cwd": str(root)}),
        capture_output=True,
        text=True,
        cwd=root,
        env=env,
        check=True,
    )
    assert json.loads(done.stdout) == {"decision": "block", "reason": print_mode.REASON}
    assert relay_rows(root) == []
    assert not tap_rec.exists() or read_tap(tap_rec) == []


def test_nookku_mode_start_refuses_print_mode(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The /nookku command of the plugin runs nookku mode start."""
    root, _ = project
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert cli.main(["mode", "start", "--root", str(root)]) == 1
    assert capsys.readouterr().out.strip() == print_mode.REASON
    assert not kit.is_on(root)


def test_nookku_mode_start_in_a_shell_has_no_print_mode_check(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT")
    assert cli.main(["mode", "start", "--root", str(root)]) == 0
    assert kit.is_on(root)

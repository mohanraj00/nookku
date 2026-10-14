"""The print mode rule of the Claude Code relay (SPEC.md section 5, #199)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from toy_agent import ToyAgent, shop_reply

from nookku import kit, print_mode, state
from nookku.adapters import make
from nookku.record import read_tap
from nookku.tap import Tap, start_in_thread

QUESTION = "Is the toy mug in stock?"


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


@pytest.mark.parametrize(
    ("env", "refused"),
    [
        ({}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": " ON"}, False),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "0"}, True),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": ""}, True),
    ],
)
def test_only_print_mode_with_the_title_request_on_is_refused(
    env: dict[str, str], refused: bool
) -> None:
    assert print_mode.refused(env) is refused


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


def test_the_codex_relay_ignores_the_claude_code_variables(
    project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, tap_rec = project
    kit.set_mode(root, True)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    answer = kit.handle(prompt(QUESTION), root, "codex")
    assert answer == {"decision": "block", "reason": shop_reply(QUESTION)}
    assert read_tap(tap_rec)[0].input == QUESTION


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

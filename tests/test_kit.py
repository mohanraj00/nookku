import io
import json
import subprocess
import sys

import pytest
from toy_agent import ToyAgent, shop_reply

from verbatim_relay import kit
from verbatim_relay.adapters import make
from verbatim_relay.audit import audit
from verbatim_relay.record import BlockedCall, Turn, read_relay, read_tap
from verbatim_relay.tap import Tap, start_in_thread

TRICKY = "Hi, I want to return order #4471.  \n\nÜnïcödé € ₹\t| a | b |\n"


@pytest.fixture
def setup(tmp_path):
    agent = ToyAgent()
    tap = Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("json"))
    start_in_thread(tap)
    root = tmp_path / "project"
    url = f"http://127.0.0.1:{tap.server_address[1]}/"
    kit.init(root, "codex", kit.Config(tap_url=url, agent_url=agent.url))
    yield root, tmp_path / "tap.jsonl", agent
    tap.shutdown()
    agent.shutdown()


def prompt(text, session="s1"):
    return {"hook_event_name": "UserPromptSubmit", "prompt": text, "session_id": session}


def record(root):
    return root / ".verbatim-relay" / "relay.jsonl"


def test_init_writes_hooks_once_and_keeps_other_hooks(tmp_path):
    target = tmp_path / ".claude" / "settings.local.json"
    target.parent.mkdir()
    other = {"type": "command", "command": "echo hi"}
    target.write_text(json.dumps({"model": "x", "hooks": {"PreToolUse": [{"hooks": [other]}]}}))
    kit.init(tmp_path, "claude-code", kit.Config())
    kit.init(tmp_path, "claude-code", kit.Config())
    settings = json.loads(target.read_text())
    assert settings["model"] == "x"
    assert len(settings["hooks"]["UserPromptSubmit"]) == 1
    assert settings["hooks"]["PreToolUse"][0]["hooks"] == [other]
    assert len(settings["hooks"]["PreToolUse"]) == 2
    assert (
        "--harness claude-code" in settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    )
    assert not kit.is_on(tmp_path)


def test_relay_mode_off_does_nothing(setup):
    root, _, agent = setup
    assert kit.handle(prompt("hi"), root, "codex") is None
    assert agent.received == []


def test_relay_mode_on_relays_exact_bytes_and_blocks_the_prompt(setup):
    root, tap_rec, _ = setup
    kit.set_mode(root, True)
    answer = kit.handle(prompt(TRICKY), root, "codex")
    assert answer["decision"] == "block"
    [turn] = read_relay(record(root))
    assert turn == Turn(1, TRICKY, shop_reply(TRICKY))
    row = json.loads(record(root).read_text())
    assert (row["ok"], row["session"], row["harness"]) == (True, "s1", "codex")
    assert read_tap(tap_rec)[0].input == TRICKY
    assert audit(tap_rec, record(root)).exit == 0


def test_an_unreachable_tap_still_blocks_and_is_recorded(tmp_path):
    kit.init(tmp_path, "codex", kit.Config(tap_url="http://127.0.0.1:9/"))
    kit.set_mode(tmp_path, True)
    assert kit.handle(prompt("hi"), tmp_path, "codex")["decision"] == "block"
    row = json.loads(record(tmp_path).read_text())
    assert row["ok"] is False and row["shown"].startswith("verbatim-relay: cannot reach the tap")


def test_a_broken_config_blocks_in_relay_mode(tmp_path):
    kit.set_mode(tmp_path, True)
    (tmp_path / ".verbatim-relay" / "config.json").write_text('{"tap": 1}')
    assert "config is broken" in kit.handle(prompt("hi"), tmp_path, "codex")["reason"]


@pytest.mark.parametrize("on", [True, False])
def test_a_crash_blocks_only_in_relay_mode(tmp_path, on):
    kit.set_mode(tmp_path, on)
    out = io.StringIO()
    assert kit.run_hook(tmp_path, "codex", io.StringIO("not json"), out) == 0
    assert ('"decision": "block"' in out.getvalue()) is on


@pytest.mark.parametrize(
    "tool, tool_input, denied",
    [
        ("Bash", {"command": "curl -s http://localhost:{port}/ -d x"}, True),
        ("shell", {"command": ["curl", "http://127.0.0.1:{port}"]}, True),
        ("mcp__fetch__get", {"url": "http://[::1]:{port}/"}, True),
        ("Write", {"file_path": "a.py", "content": "http://127.0.0.1:{port}/"}, False),
        ("Bash", {"command": "curl http://127.0.0.1:{port}9/"}, False),
        ("Bash", {"command": "ls"}, False),
    ],
)
def test_pre_tool_use(setup, tool, tool_input, denied):
    root, _, _ = setup
    port = kit.Config.load(root).tap_url.rsplit(":", 1)[1].strip("/")
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": json.loads(json.dumps(tool_input).replace("{port}", port)),
    }
    answer = kit.handle(event, root, "codex")
    assert (answer is not None) is denied
    rows = read_relay(record(root)) if record(root).exists() else []
    assert rows == [BlockedCall(1, tool, rows[0].detail)] if denied else rows == []
    if denied:
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_blocked_call_with_a_lone_surrogate_is_still_denied(setup):
    root, _, _ = setup
    port = kit.Config.load(root).tap_url.rsplit(":", 1)[1].strip("/")
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": f"curl http://127.0.0.1:{port}/", "note": "mug \ud83d"},
    }
    answer = kit.handle(event, root, "codex")
    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    rows = read_relay(record(root))
    assert rows == [BlockedCall(1, "Bash", rows[0].detail)]
    assert "\\ud83d" in rows[0].detail


def test_the_agent_url_is_denied_too(setup):
    root, _, agent = setup
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": f"curl {agent.url}/"},
    }
    assert kit.handle(event, root, "codex") is not None


def test_openai_history_is_per_session(tmp_path):
    agent = ToyAgent()
    tap = Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("openai"))
    start_in_thread(tap)
    url = f"http://127.0.0.1:{tap.server_address[1]}/v1/chat/completions"
    root = tmp_path / "p"
    kit.init(root, "codex", kit.Config(tap_url=url, adapter="openai", openai_model="toy"))
    kit.set_mode(root, True)
    for text, session in (("first", "a"), ("second", "a"), ("other", "b")):
        kit.handle(prompt(text, session), root, "codex")
    tap.shutdown()
    agent.shutdown()
    bodies = [json.loads(r["body"]) for r in agent.received]
    assert [m["content"] for m in bodies[1]["messages"]] == ["first", shop_reply("first"), "second"]
    assert [m["content"] for m in bodies[2]["messages"]] == ["other"]
    assert bodies[0]["model"] == "toy"
    assert audit(tmp_path / "tap.jsonl", record(root)).exit == 0


def test_view_prints_each_turn_exactly(setup):
    root, _, _ = setup
    kit.set_mode(root, True)
    kit.handle(prompt(TRICKY), root, "codex")
    out = io.StringIO()
    kit.view(record(root), follow=False, out=out)
    assert out.getvalue() == (
        f"──── tester, turn 1 ────\n{TRICKY}\n──── agent ────\n{shop_reply(TRICKY)}\n"
    )


def test_the_installed_hook_command_runs(setup):
    root, _, _ = setup
    kit.set_mode(root, True)
    command = json.loads((root / ".codex" / "hooks.json").read_text())
    line = command["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    p = subprocess.run(
        line,
        shell=True,
        input=json.dumps(prompt(TRICKY)),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert json.loads(p.stdout)["decision"] == "block"
    assert read_relay(record(root))[0].said == TRICKY
    assert sys.executable in line


def test_transcript_prints_the_latest_session(setup):
    root, _, _ = setup
    kit.set_mode(root, True)
    for text, session in (("old one", "a"), (TRICKY, "b"), ("second", "b")):
        kit.handle(prompt(text, session), root, "codex")
    out = io.StringIO()
    kit.transcript(record(root), every_session=False, out=out)
    text = out.getvalue()
    assert "2 turns" in text and "old one" not in text
    assert f"──── tester, turn 1 ────\n{TRICKY}\n" in text
    out = io.StringIO()
    kit.transcript(record(root), every_session=True, out=out)
    assert "3 turns" in out.getvalue()


def test_the_model_may_run_the_transcript_command(setup):
    root, _, _ = setup
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "verbatim-relay transcript"},
    }
    assert kit.handle(event, root, "codex") is None

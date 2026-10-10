import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from toy_agent import ToyAgent, shop_reply

from nookku import bridge, cli, kit
from nookku.adapters import make
from nookku.audit import audit
from nookku.record import (
    BlockedCall,
    RecordError,
    Turn,
    read_relay,
    read_rows,
    read_tap,
)
from nookku.tap import Tap, start_in_thread

ROOT = Path(__file__).resolve().parent.parent


def test_the_deny_pattern_matches_each_case_of_the_table() -> None:
    tables = json.loads((ROOT / "tests" / "tables.json").read_text("utf-8"))
    rows = tables["deny_cases"]
    assert rows
    pattern = kit.deny_pattern(tables["deny_urls"])
    assert pattern is not None
    for command, denied in rows:
        assert (command, bool(pattern.search(command))) == (command, denied)


# The prompt that ends a test and starts the evaluation, and the end with no evaluation
# (SPEC.md section 9.1).
EVALUATION_END = "To end the test and start the evaluation, type the prompt nookku end"


def test_the_start_text_names_the_prompt_that_starts_the_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bridge, "start", lambda root, session=None: {"test": "t-1"})
    text = kit.start_test(tmp_path)
    assert text.startswith("nookku: test t-1 started. Relay mode is on")
    assert f"{EVALUATION_END}. " in text
    assert text.endswith("To end the test with no evaluation, run nookku end in a shell.")
    assert kit.is_on(tmp_path)


def test_the_blocked_call_detail_keeps_300_code_points(tmp_path: Path) -> None:
    rows = json.loads((ROOT / "tests" / "tables.json").read_text("utf-8"))["detail_cases"]
    assert rows
    path = tmp_path / "relay.jsonl"
    for pad, tail, cut in rows:
        detail = kit.blocked_detail("x" * pad + tail)
        assert [pad, tail, detail] == [pad, tail, "x" * pad + cut]
        row = {"v": "0.2", "type": "blocked_call", "ts": 1.0, "harness": "claude-code"}
        row.update(tool="Bash", detail=detail)
        path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        assert read_rows("relay", path) == [(1, row)]


TRICKY = "Hi, I want to return order #4471.  \n\nÜnïcödé € ₹\t| a | b |\n"


@pytest.fixture
def setup(tmp_path):
    agent = ToyAgent()
    tap = Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("json"))
    start_in_thread(tap)
    root = tmp_path / "project"
    url = f"http://127.0.0.1:{tap.server_address[1]}/"
    kit.init(root, "codex", dict(tap_url=url, agent_url=agent.url))
    yield root, tmp_path / "tap.jsonl", agent
    tap.shutdown()
    agent.shutdown()


def prompt(text, session="s1"):
    return {"hook_event_name": "UserPromptSubmit", "prompt": text, "session_id": session}


def record(root):
    return root / ".nookku" / "relay.jsonl"


def test_init_writes_hooks_once_and_keeps_other_hooks(tmp_path):
    target = tmp_path / ".claude" / "settings.local.json"
    target.parent.mkdir()
    other = {"type": "command", "command": "echo hi"}
    target.write_text(json.dumps({"model": "x", "hooks": {"PreToolUse": [{"hooks": [other]}]}}))
    kit.init(tmp_path, "claude-code", {})
    kit.init(tmp_path, "claude-code", {})
    settings = json.loads(target.read_text())
    assert settings["model"] == "x"
    assert len(settings["hooks"]["UserPromptSubmit"]) == 1
    assert settings["hooks"]["PreToolUse"][0]["hooks"] == [other]
    assert len(settings["hooks"]["PreToolUse"]) == 2
    assert (
        "--harness claude-code" in settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    )
    assert not kit.is_on(tmp_path)


def test_init_keeps_another_hook_in_the_group_of_the_kit(tmp_path):
    target = tmp_path / ".codex" / "hooks.json"
    target.parent.mkdir()
    ours = {"type": "command", "command": "python -m nookku hook --harness codex"}
    other = {"type": "command", "command": "echo hi"}
    stop = [{"hooks": [other]}]
    hooks = {"UserPromptSubmit": [{"hooks": [ours, other]}], "Stop": stop}
    target.write_text(json.dumps({"hooks": hooks}))
    kit.init(tmp_path, "codex", {})
    settings = json.loads(target.read_text())
    groups = settings["hooks"]["UserPromptSubmit"]
    assert groups[0] == {"hooks": [other]}
    assert [h["command"] for h in groups[1]["hooks"]] == [kit.hook_command(tmp_path, "codex")]
    assert settings["hooks"]["Stop"] == stop


def test_init_replaces_the_hooks_of_verbatim_relay(tmp_path):
    target = tmp_path / ".codex" / "hooks.json"
    target.parent.mkdir()
    old = {"type": "command", "command": "python -m verbatim_relay hook --harness codex"}
    target.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [old]}]}}))
    kit.init(tmp_path, "codex", {})
    groups = json.loads(target.read_text())["hooks"]["UserPromptSubmit"]
    assert [h["command"] for g in groups for h in g["hooks"]] == [
        kit.hook_command(tmp_path, "codex")
    ]


def test_relay_mode_off_does_nothing(setup):
    root, _, agent = setup
    assert kit.handle(prompt("hi"), root, "codex") is None
    assert agent.received == []


def test_relay_mode_on_relays_exact_bytes_and_blocks_the_prompt(setup):
    root, tap_rec, _ = setup
    kit.set_mode(root, True)
    answer = kit.handle(prompt(TRICKY), root, "codex")
    assert answer["decision"] == "block"
    # The block reason shows the reply byte for byte (ADR 0001: reply display).
    assert answer["reason"] == shop_reply(TRICKY)
    [turn] = read_relay(record(root))
    assert turn == Turn(1, TRICKY, shop_reply(TRICKY), True, "s1")
    row = json.loads(record(root).read_text())
    assert (row["ok"], row["session"], row["harness"]) == (True, "s1", "codex")
    assert read_tap(tap_rec)[0].input == TRICKY
    assert audit(tap_rec, record(root)).exit == 0


def test_an_unreachable_tap_still_blocks_and_is_recorded(tmp_path):
    kit.init(tmp_path, "codex", dict(tap_url="http://127.0.0.1:9/"))
    kit.set_mode(tmp_path, True)
    assert kit.handle(prompt("hi"), tmp_path, "codex")["decision"] == "block"
    row = json.loads(record(tmp_path).read_text())
    assert row["ok"] is False and row["shown"].startswith("nookku: cannot reach the tap")


def test_a_broken_config_blocks_in_relay_mode(tmp_path):
    kit.set_mode(tmp_path, True)
    (tmp_path / ".nookku" / "config.json").write_text('{"tap": 1}')
    assert "config is broken" in kit.handle(prompt("hi"), tmp_path, "codex")["reason"]


def test_a_prompt_with_a_lone_surrogate_is_refused_and_not_recorded(setup):
    root, tap_rec, agent = setup
    kit.set_mode(root, True)
    # The harness sends the prompt as JSON, which can escape a lone surrogate.
    event = '{"hook_event_name": "UserPromptSubmit", "prompt": "a \\ud83d\\ude00 mug \\ud83d"}'
    out = io.StringIO()
    assert kit.run_hook(root, "codex", io.StringIO(event), out) == 0
    answer = json.loads(out.getvalue())
    assert answer == {
        "decision": "block",
        "reason": "nookku: nothing was sent. "
        "The message has a lone surrogate U+D83D at character 8.",
    }
    assert agent.received == []
    assert not record(root).exists()
    assert not tap_rec.exists()


@pytest.mark.parametrize("on", [True, False])
def test_a_crash_blocks_only_in_relay_mode(tmp_path, on):
    kit.set_mode(tmp_path, on)
    out = io.StringIO()
    assert kit.run_hook(tmp_path, "codex", io.StringIO("not json"), out) == 0
    assert ('"decision": "block"' in out.getvalue()) is on


def test_a_bad_line_in_the_relay_record_is_an_error_and_blocks(setup):
    root, _, agent = setup
    kit.set_mode(root, True)
    kit.handle(prompt("first"), root, "codex")
    line = record(root).read_text(encoding="utf-8")
    # One byte of the said text changes, and its hash stays.
    record(root).write_text(line.replace("first", "firsT", 1), encoding="utf-8")
    with pytest.raises(RecordError, match=r"relay\.jsonl: line 1: field said_sha256"):
        kit.history(record(root), "s1")
    record(root).write_text(line + "{not json\n", encoding="utf-8")
    with pytest.raises(RecordError, match=r"relay\.jsonl: line 2: not JSON"):
        kit.history(record(root), "s1")
    out = io.StringIO()
    kit.run_hook(root, "codex", io.StringIO(json.dumps(prompt("second"))), out)
    answer = json.loads(out.getvalue())
    assert answer["decision"] == "block"
    assert "relay.jsonl: line 2: not JSON" in answer["reason"]
    assert len(agent.received) == 1
    assert kit.history(root / "no-such.jsonl", "s1") == []


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


def pre(tool_input, tool="Bash"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


def running_test(root):
    """A running test with the entry in its manifest. The pid of this process is alive."""
    folder = root / ".nookku" / "tests" / "20261007-090000-ab12"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"entry": ["python", "shop/entry.py"]}))
    cur = {"test": folder.name, "pid": os.getpid(), "dir": str(folder), "tap_url": ""}
    cur["pid_start"] = bridge.process_start(os.getpid())
    (root / ".nookku" / "current.json").write_text(json.dumps(cur))
    return folder


@pytest.mark.parametrize("config", ["not json", '{"tap": 1}', "[[]]"])
def test_a_broken_config_still_denies_test_files_and_the_entry(tmp_path, config):
    folder = running_test(tmp_path)
    (tmp_path / ".nookku" / "config.json").write_text(config)
    for command in ("cat .nookku/tests/x/tap.jsonl", "cd shop && python entry.py"):
        answer = kit.handle(pre({"command": command}), tmp_path, "codex")
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = kit.handle(pre({"command": "python entry.py"}), tmp_path, "codex")
    assert reason["hookSpecificOutput"]["permissionDecisionReason"] == kit.ENTRY_REASON
    assert kit.handle(pre({"command": "ls"}), tmp_path, "codex") is None
    assert [r.tool for r in read_relay(folder / "relay.jsonl")] == ["Bash"] * 3


def test_a_failed_deny_path_denies_with_relay_mode_off(tmp_path, monkeypatch):
    def fail(*_):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(kit.state, "current", fail)
    event = json.dumps(pre({"command": "ls"}))
    out = io.StringIO()
    # With no state folder, no deny applies, so the call goes on.
    assert kit.run_hook(tmp_path, "codex", io.StringIO(event), out) == 0
    assert out.getvalue() == ""
    kit.set_mode(tmp_path, False)
    assert kit.run_hook(tmp_path, "codex", io.StringIO(event), out) == 0
    answer = json.loads(out.getvalue())["hookSpecificOutput"]
    assert answer["permissionDecision"] == "deny"
    assert "RuntimeError: disk gone" in answer["permissionDecisionReason"]


def test_openai_history_is_per_session(tmp_path):
    agent = ToyAgent()
    tap = Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("openai"))
    start_in_thread(tap)
    url = f"http://127.0.0.1:{tap.server_address[1]}/v1/chat/completions"
    root = tmp_path / "p"
    kit.init(root, "codex", dict(tap_url=url, adapter="openai", openai_model="toy"))
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


@pytest.mark.parametrize("openai_stream", [True, False])
def test_openai_stream_asks_an_agent_that_streams_only_on_request(tmp_path, openai_stream):
    agent = ToyAgent(stream="on_request")
    tap = Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("openai"))
    start_in_thread(tap)
    url = f"http://127.0.0.1:{tap.server_address[1]}/v1/chat/completions"
    root = tmp_path / "p"
    config = dict(tap_url=url, adapter="openai", openai_stream=openai_stream)
    kit.init(root, "codex", config)
    kit.set_mode(root, True)
    for text in (TRICKY, "second"):
        assert kit.handle(prompt(text), root, "codex")["decision"] == "block"
    tap.shutdown()
    agent.shutdown()
    bodies = [json.loads(r["body"]) for r in agent.received]
    assert [b["stream"] for b in bodies] == [openai_stream, openai_stream]
    rows = [json.loads(x) for x in (tmp_path / "tap.jsonl").read_text().split("\n") if x]
    assert ["stream" in r for r in rows] == [openai_stream, openai_stream]
    shown = [(t.ok, t.shown) for t in read_relay(record(root)) if isinstance(t, Turn)]
    assert shown == [(True, shop_reply(TRICKY)), (True, shop_reply("second"))]
    assert audit(tmp_path / "tap.jsonl", record(root)).exit == 0


def test_openai_stream_must_be_a_boolean(tmp_path):
    kit.init(tmp_path, "codex", dict(adapter="openai"))
    path = tmp_path / ".nookku" / "config.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "openai_stream": "true"}))
    with pytest.raises(ValueError, match="'openai_stream' must be true or false"):
        kit.Config.load(tmp_path)


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/cut/chat/completions"])
def test_a_streamed_reply_is_shown_only_when_complete(tmp_path, path):
    agent = ToyAgent(stream=True)
    tap = Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("openai"))
    start_in_thread(tap)
    root = tmp_path / "p"
    url = f"http://127.0.0.1:{tap.server_address[1]}{path}"
    kit.init(root, "codex", dict(tap_url=url, adapter="openai"))
    kit.set_mode(root, True)
    assert kit.handle(prompt(TRICKY), root, "codex")["decision"] == "block"
    tap.shutdown()
    agent.shutdown()
    row = json.loads(record(root).read_text())
    report = audit(tmp_path / "tap.jsonl", record(root))
    if "cut" in path:
        assert row["ok"] is False
        assert row["shown"] == (
            "nookku: cannot read the reply: the stream ended before data: [DONE]"
        )
        assert [n.kind for n in report.notes] == ["agent_error"] and report.exit == 0
    else:
        assert (row["ok"], row["shown"]) == (True, shop_reply(TRICKY))
        assert report.exit == 0 and report.notes == []


def test_view_prints_each_turn_exactly(setup):
    root, _, _ = setup
    kit.set_mode(root, True)
    kit.handle(prompt(TRICKY), root, "codex")
    out = io.StringIO()
    kit.view(record(root), follow=False, out=out)
    assert out.getvalue() == (
        f"──── tester, turn 1 ────\n{TRICKY}\n──── agent ────\n{shop_reply(TRICKY)}\n"
    )


class _StopView(Exception):
    pass


def _follow(monkeypatch, steps):
    """Run each step in place of a poll sleep of the view. After the last step, stop the view."""
    todo = list(steps)

    def sleep(_: float) -> None:
        if not todo:
            raise _StopView
        todo.pop(0)()

    monkeypatch.setattr(kit.time, "sleep", sleep)


@pytest.mark.parametrize("tests", [False, True], ids=["view", "view_tests"])
def test_the_view_shows_a_bad_line_once_and_then_follows_again(setup, monkeypatch, tests):
    root, _, _ = setup
    kit.set_mode(root, True)
    kit.handle(prompt("Refund policy?"), root, "codex")
    kit.handle(prompt("Where is order #4471?"), root, "codex")
    first, second = record(root).read_text().splitlines(keepends=True)
    if tests:
        path = root / ".nookku" / "tests" / "20261007-080000-aaaa" / "relay.jsonl"
        path.parent.mkdir(parents=True)
    else:
        path = record(root)
    path.write_text(first)
    shown_at_error = []

    def bad_line() -> None:
        with path.open("a") as f:
            f.write("not json\n")

    _follow(
        monkeypatch,
        [
            bad_line,
            lambda: shown_at_error.append(out.getvalue()),  # the record does not change
            lambda: path.write_text(first + second),
        ],
    )
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(_StopView):
        if tests:
            kit.view_tests(root, True, out, poll=0, err=err)
        else:
            kit.view(path, True, out, poll=0, err=err)
    assert err.getvalue() == (
        f"nookku: the record is invalid: {path}: line 2: not JSON (Expecting value). "
        "Do not trust this record. The view shows the next turns when the record changes "
        "and is valid.\n"
    )
    assert "turn 1" in shown_at_error[0] and "turn 2" not in shown_at_error[0]
    assert "──── tester, turn 2 ────\nWhere is order #4471?\n" in out.getvalue()


def test_the_view_without_follow_stops_at_a_bad_line(setup, capsys):
    root, _, _ = setup
    record(root).write_text("not json\n")
    with pytest.raises(RecordError, match="line 1"):
        kit.view(record(root), follow=False, out=io.StringIO())
    assert cli.main(["view", "--root", str(root), "--no-follow"]) == 2
    assert (
        capsys.readouterr().err == f"nookku: {record(root)}: line 1: not JSON (Expecting value)\n"
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
    assert json.loads(p.stdout) == {"decision": "block", "reason": shop_reply(TRICKY)}
    assert read_relay(record(root))[0].said == TRICKY
    assert sys.executable in line


@pytest.mark.parametrize("source", ["env", "cwd"])
def test_a_hook_with_no_root_finds_the_project(setup, monkeypatch, source):
    root, _, _ = setup
    kit.set_mode(root, True)
    event = prompt(TRICKY)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    if source == "env":
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    else:
        event["cwd"] = str(root)
    out = io.StringIO()
    assert kit.run_hook(None, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    assert json.loads(out.getvalue())["reason"] == shop_reply(TRICKY)
    assert json.loads(record(root).read_text())["harness"] == "claude-code"


def test_a_codex_hook_ignores_the_project_variable_of_claude_code(setup, monkeypatch, tmp_path):
    root, _, _ = setup
    kit.set_mode(root, True)
    other = tmp_path / "claude-project"
    other.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))
    event = {**prompt(TRICKY), "cwd": str(root)}
    out = io.StringIO()
    assert kit.run_hook(None, "codex", io.StringIO(json.dumps(event)), out) == 0
    assert json.loads(out.getvalue())["reason"] == shop_reply(TRICKY)


@pytest.mark.parametrize(
    "args",
    [[], ["--harness"], ["--harness", "other"], ["--harness", "codex", "--x", "1"]],
)
def test_wrong_hook_arguments_exit_2(args, capsys):
    from nookku.__main__ import main

    assert main(["hook", *args]) == 2
    assert "usage: nookku hook" in capsys.readouterr().err


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
        "tool_input": {"command": "nookku transcript"},
    }
    assert kit.handle(event, root, "codex") is None


@pytest.mark.parametrize(
    "event",
    [
        {"hook_event_name": "UserPromptSubmit", "prompt": "nookku status"},
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
    ],
)
def test_with_no_state_folder_the_hook_gives_no_answer(tmp_path: Path, event: dict) -> None:
    # The plugin runs the hook in each project.
    out = io.StringIO()
    assert kit.run_hook(tmp_path, "claude-code", io.StringIO(json.dumps(event)), out) == 0
    assert out.getvalue() == ""
    assert not (tmp_path / kit.STATE_DIR).exists()

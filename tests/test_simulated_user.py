"""A test with a simulated user: nookku run --persona (SPEC.md section 7.10, #520)."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

import pytest
from test_bridge import ECHO_APP, project
from test_bridge import homes as homes

from nookku import bridge, evaluation, kit, script, script_save, seal, simulated_user
from nookku.cli import main
from nookku.config import ConfigError, check
from nookku.record import Turn

PERSONA = {
    "persona": "A customer whose teapot came broken.",
    "goal": "Get a return label for the teapot.",
    "turns": 8,
}
# A claude -p of the test. It logs each call, and gives message n of the plan, where n is the
# count of earlier turns in the prompt. The plan item "exit 3" exits with 3.
FAKE = """import json, os, sys
if sys.argv[1:] == ["--version"]:
    print("2.1.319 (Claude Code)")
    sys.exit(0)
prompt = sys.stdin.read()
plan = json.loads(open(os.environ["FAKE_PLAN"]).read())
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt,
        "nookku": sorted(k for k in os.environ if k.startswith("NOOKKU_")),
        "mods": os.environ.get("CLAUDE_CODE_PLUGIN_DIRS")}) + "\\n")
said = plan[min(prompt.count("\\nYou: "), len(plan) - 1)]
if said == "exit 3":
    sys.exit(3)
print(said)
"""


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    script = bin_dir / "claude.py"
    script.write_text(FAKE)
    claude.write_text(f'#!/bin/sh\nexec {shlex.join([sys.executable, str(script)])} "$@"\n')
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_PLAN", str(tmp_path / "plan.json"))
    return tmp_path


def _setup(
    tmp_path: Path, plan: list[str], persona: dict = PERSONA, runner: object = None
) -> tuple[Path, Path]:
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    app = tmp_path / "app.py"
    app.write_text(ECHO_APP)
    root = project(tmp_path, [sys.executable, str(app)])
    if runner is not None:
        conf = root / ".nookku" / "config.json"
        conf.write_text(json.dumps({**json.loads(conf.read_text()), "persona_runner": runner}))
    path = tmp_path / "persona.json"
    path.write_text(json.dumps(persona))
    return root, path


def relay_turns(folder: Path) -> list[dict]:
    # str.splitlines also splits at U+2028, which a message can hold.
    rows = [json.loads(x) for x in (folder / "relay.jsonl").read_text().split("\n") if x]
    return [r for r in rows if r["type"] == "turn"]


def _calls(tmp_path: Path) -> list[dict]:
    return [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]


def test_the_simulated_user_writes_each_message_up_to_the_goal(
    fake: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOOKKU_TEST_ID", "the tester's test")
    # A mod folder of the tester. The session of the simulated user must not load it.
    monkeypatch.setenv("CLAUDE_CODE_PLUGIN_DIRS", str(fake / "mods"))
    plan = ["My teapot came broken.\u2028What now?  ", "Can I get a label?", "GOAL MET"]
    root, path = _setup(fake, plan)
    passed, lines, folder = bridge.run_persona(root, path)
    assert passed, lines
    assert lines[1] == "Turns: 2 of 8. The simulated user wrote that the goal is met."
    assert lines[-1] == "PASS"
    # Each message is the output with no white space at the start and at the end.
    said = ["My teapot came broken.\u2028What now?", "Can I get a label?"]
    turns = relay_turns(folder)
    assert [(t["harness"], t["said"]) for t in turns] == [("simulated-user", s) for s in said]
    assert [t["shown"] for t in turns] == [f"Toy shop: {s}" for s in said]
    assert (folder / simulated_user.COPY).read_bytes() == path.read_bytes()
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["script"] is None
    assert manifest["persona"] == {
        "source": str(path.resolve()),
        "file": simulated_user.COPY,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    result = json.loads((folder / simulated_user.RESULT).read_text())
    assert result == {
        "harness": "claude-code",
        "command": None,
        "version": "2.1.319",
        "turns": 2,
        "limit": 8,
        "ended": "goal",
        "error": None,
    }
    assert seal.verify(folder)["intact"]
    assert simulated_user.RESULT in json.loads((folder / "seal.json").read_text())["files"]
    assert not kit.is_on(root)
    assert evaluation.prompt(folder).startswith("In this test, a simulated user wrote")
    assert "──── simulated user, turn 2 ────" in kit.render_turn(
        Turn(1, turns[1]["said"], turns[1]["shown"], harness="simulated-user"), 2
    )
    calls = _calls(fake)
    assert len(calls) == 3
    for call in calls:
        # A new session with no settings, no tools and no session file, in its own folder.
        assert call["argv"][:5] == ["-p", "--setting-sources", "", "--tools", ""]
        assert "--no-session-persistence" in call["argv"]
        assert Path(call["cwd"]).name.startswith("nookku-simulated-user-")
        assert call["nookku"] == []
        assert call["mods"] == ""
        assert PERSONA["persona"] in call["prompt"] and PERSONA["goal"] in call["prompt"]
    assert "no message yet" in calls[0]["prompt"]
    assert f"You: {said[0]}\nAgent: Toy shop: {said[0]}" in calls[1]["prompt"]
    # A script save gives the messages, so a gate run can send them again (ADR 0002).
    saved, count = script_save.save(root, folder.name)
    assert (script.read(saved)[0], count) == (said, 2)


def test_the_run_stops_at_the_turn_limit(fake: Path, homes: tuple) -> None:
    root, path = _setup(fake, ["One more question."], {**PERSONA, "turns": 2})
    passed, lines, folder = bridge.run_persona(root, path)
    assert passed, lines
    assert lines[1] == "Turns: 2 of 2. The run stopped at the turn limit."
    assert len(relay_turns(folder)) == 2
    assert json.loads((folder / simulated_user.RESULT).read_text())["ended"] == "limit"


def test_a_failed_session_fails_the_run(fake: Path, homes: tuple) -> None:
    root, path = _setup(fake, ["Hello.", "exit 3"])
    passed, lines, folder = bridge.run_persona(root, path)
    assert not passed
    assert lines[1] == "Turns: 1 of 8. The session of the simulated user failed."
    assert "FAIL: The simulated user stopped: claude -p exited with 3" in lines
    result = json.loads((folder / simulated_user.RESULT).read_text())
    assert (result["ended"], result["error"]) == ("error", "claude -p exited with 3")
    assert seal.verify(folder)["intact"]


def test_a_goal_at_the_start_sends_no_message_and_fails(fake: Path, homes: tuple) -> None:
    root, path = _setup(fake, ["GOAL MET"])
    passed, lines, _ = bridge.run_persona(root, path)
    assert not passed
    assert "FAIL: The simulated user sent no message." in lines


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"\xff", "not UTF-8 JSON"),
        (b"[]", "an object with persona, goal and turns"),
        (json.dumps({**PERSONA, "more": 1}).encode(), "an object with persona, goal and turns"),
        (json.dumps({**PERSONA, "goal": " "}).encode(), "the goal must be a string"),
        (json.dumps({**PERSONA, "persona": 1}).encode(), "the persona must be a string"),
        (json.dumps({**PERSONA, "turns": 0}).encode(), "turns must be an integer from 1 to 50"),
        (json.dumps({**PERSONA, "turns": 51}).encode(), "turns must be an integer from 1 to 50"),
        (json.dumps({**PERSONA, "turns": True}).encode(), "turns must be an integer"),
        (b'{"persona": "\\ud800", "goal": "g", "turns": 1}', "the persona has"),
    ],
)
def test_a_persona_file_that_is_not_valid_starts_no_test(
    fake: Path, homes: tuple, data: bytes, error: str
) -> None:
    root, path = _setup(fake, ["Hello."])
    path.write_bytes(data)
    with pytest.raises(bridge.BridgeError, match=error):
        bridge.run_persona(root, path)
    assert not (root / ".nookku" / "tests").exists()
    assert not (fake / "calls.jsonl").exists()


def test_run_takes_a_script_or_a_persona_file(
    fake: Path, homes: tuple, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _setup(fake, ["Hello.", "GOAL MET"])
    with pytest.raises(SystemExit):
        main(["run", "--root", str(root), "--script", str(path), "--persona", str(path)])
    assert "not allowed with argument" in capsys.readouterr().err
    assert main(["run", "--root", str(root), "--persona", str(path), "--no-evaluate"]) == 0
    assert (
        "Turns: 1 of 8. The simulated user wrote that the goal is met." in capsys.readouterr().out
    )


# A Verdict table with a Finding that is not a check. The problem fails the verdict.
BAD_VERDICT = "# Toy shop\n\n## Verdict\n\n| Finding | Most |\n|---|---|\n| `no_such_check` | 0 |\n"


def _bad_verdict(root: Path) -> None:
    (root / "APP_SPEC.md").write_text(BAD_VERDICT)
    conf = json.loads((root / ".nookku" / "config.json").read_text())
    (root / ".nookku" / "config.json").write_text(json.dumps({**conf, "spec": ["APP_SPEC.md"]}))


def test_a_gate_persona_run_fails_on_a_verdict_that_is_not_pass(fake: Path, homes: tuple) -> None:
    root, path = _setup(fake, ["Hello.", "GOAL MET"])
    _bad_verdict(root)
    passed, lines, _ = bridge.run_persona(root, path)
    assert passed, lines
    passed, lines, folder = bridge.run_persona(root, path, gate=True)
    assert not passed
    assert "Audit: exit 0" in lines
    assert any(x.startswith("FAIL: The verdict is fail.") for x in lines), lines
    assert json.loads((folder / "verdict.json").read_text())["verdict"] == "fail"


def test_run_persona_obeys_verdict(
    fake: Path, homes: tuple, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _setup(fake, ["Hello.", "GOAL MET"])
    _bad_verdict(root)
    argv = ["run", "--root", str(root), "--persona", str(path), "--no-evaluate"]
    assert main(argv) == 0
    capsys.readouterr()
    assert main([*argv, "--verdict"]) == 1
    assert "FAIL: The verdict is fail." in capsys.readouterr().out


# A codex exec of the test. It logs each call, and writes message n of the plan to the file of
# -o. The plan item "no file" writes no file, and "exit 3" exits with 3.
FAKE_CODEX = """import json, os, sys
if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.169.0")
    sys.exit(0)
prompt = sys.stdin.read()
plan = json.loads(open(os.environ["FAKE_PLAN"]).read())
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt,
        "nookku": sorted(k for k in os.environ if k.startswith("NOOKKU_"))}) + "\\n")
said = plan[min(prompt.count("\\nYou: "), len(plan) - 1)]
if said == "exit 3":
    sys.exit(3)
print("progress text on stdout")
if said != "no file":
    with open(sys.argv[sys.argv.index("-o") + 1], "w") as out:
        out.write(said + "\\n")
"""


@pytest.fixture
def fake_codex(fake: Path) -> Path:
    bin_dir = fake / "bin"
    script = bin_dir / "codex.py"
    script.write_text(FAKE_CODEX)
    codex = bin_dir / "codex"
    codex.write_text(f'#!/bin/sh\nexec {shlex.join([sys.executable, str(script)])} "$@"\n')
    codex.chmod(0o755)
    return fake


RUNNERS = json.loads(
    (Path(__file__).parents[1] / "conformance" / "persona_runner" / "runners.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", RUNNERS, ids=[c["name"] for c in RUNNERS])
def test_the_runner_cases_of_the_conformance_suite(case: dict, tmp_path: Path) -> None:
    data = {} if "value" not in case else {"persona_runner": case["value"]}
    if "error" in case:
        with pytest.raises(ConfigError) as e:
            check(data)
        assert str(e.value) == case["error"]
        return
    runner = check(data).get("persona_runner", simulated_user.DEFAULT_RUNNER)
    want = case["expect"]

    def fill(text: str) -> str:
        return text.replace("<folder>", str(tmp_path)).replace(
            "<system prompt>", simulated_user.SYSTEM
        )

    assert simulated_user.command(runner, tmp_path) == [fill(a) for a in want["argv"]]
    assert simulated_user.harness(runner) == want["harness"]
    assert (runner if isinstance(runner, list) else None) == want["command"]
    message = fill(want["message"])
    if message != "stdout":
        assert message == str(tmp_path / simulated_user.CODEX_MESSAGE)


def test_the_codex_runner_reads_the_message_file(
    fake_codex: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOOKKU_TEST_ID", "the tester's test")
    root, path = _setup(fake_codex, ["My teapot came broken.", "GOAL MET"], runner="codex")
    passed, lines, folder = bridge.run_persona(root, path)
    assert passed, lines
    turns = relay_turns(folder)
    # The message is the -o file, not the progress text on stdout.
    assert [(t["harness"], t["said"]) for t in turns] == [
        ("simulated-user", "My teapot came broken.")
    ]
    result = json.loads((folder / simulated_user.RESULT).read_text())
    assert result == {
        "harness": "codex",
        "command": None,
        "version": "0.169.0",
        "turns": 1,
        "limit": 8,
        "ended": "goal",
        "error": None,
    }
    assert seal.verify(folder)["intact"]
    calls = _calls(fake_codex)
    assert len(calls) == 2
    for call in calls:
        cwd = call["cwd"]
        assert Path(cwd).name.startswith("nookku-simulated-user-")
        assert call["argv"][-5:] == ["-C", cwd, "-o", str(Path(cwd) / "message.txt"), "-"]
        assert call["argv"][:6] == [
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
        ]
        assert call["nookku"] == []
        # codex exec has no system prompt flag, so the prompt starts with the system prompt.
        assert call["prompt"].startswith(simulated_user.SYSTEM + "\n\n")
        assert PERSONA["goal"] in call["prompt"]


@pytest.mark.parametrize(
    ("plan", "error"),
    [
        (["no file"], "codex exec wrote no message.txt"),
        (["exit 3"], "codex exec exited with 3"),
    ],
)
def test_a_failed_codex_session_fails_the_run(
    fake_codex: Path, homes: tuple, plan: list[str], error: str
) -> None:
    root, path = _setup(fake_codex, plan, runner="codex")
    passed, lines, folder = bridge.run_persona(root, path)
    assert not passed
    assert f"FAIL: The simulated user stopped: {error}" in lines
    result = json.loads((folder / simulated_user.RESULT).read_text())
    assert (result["harness"], result["ended"], result["error"]) == ("codex", "error", error)


def test_a_declared_command_writes_each_message(fake: Path, homes: tuple) -> None:
    command = [sys.executable, str(fake / "bin" / "claude.py"), "--quiet"]
    root, path = _setup(fake, ["Where is my teapot?", "GOAL MET"], runner=command)
    passed, lines, folder = bridge.run_persona(root, path)
    assert passed, lines
    assert [t["said"] for t in relay_turns(folder)] == ["Where is my teapot?"]
    result = json.loads((folder / simulated_user.RESULT).read_text())
    assert result["harness"] == "command"
    assert result["command"] == command
    # A declared command has no version.
    assert result["version"] is None
    calls = _calls(fake)
    assert [c["argv"] for c in calls] == [["--quiet"], ["--quiet"]]
    assert all(c["nookku"] == [] for c in calls)
    assert all(Path(c["cwd"]).name.startswith("nookku-simulated-user-") for c in calls)


def test_a_failed_declared_command_fails_the_run(fake: Path, homes: tuple) -> None:
    command = [sys.executable, str(fake / "bin" / "claude.py")]
    root, path = _setup(fake, ["exit 3"], runner=command)
    passed, lines, folder = bridge.run_persona(root, path)
    assert not passed
    assert "FAIL: The simulated user stopped: the declared command exited with 3" in lines
    assert json.loads((folder / simulated_user.RESULT).read_text())["harness"] == "command"


def test_a_runner_that_is_not_valid_starts_no_test(tmp_path: Path, homes: tuple) -> None:
    root, path = _setup(tmp_path, ["Hello."], runner="gemini")
    with pytest.raises(bridge.BridgeError, match="'persona_runner' must be"):
        bridge.run_persona(root, path)
    assert not (root / ".nookku" / "current.json").exists()

"""Save a test as a script: nookku script save and the page button (#350, SPEC.md section 7.10)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from nookku import bridge, kit, policy, script, script_save
from nookku.audit import audit
from nookku.cli import main
from nookku.record import Writer

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
TEST_ID = "20261013-090000-ab12"
# A U+2028, a trailing line feed, a CR LF, the escape text of a lone surrogate (6 characters,
# section 2), an emoji and spaces at the end. The script must keep each byte of each one. A real
# lone surrogate cannot be in a valid relay record (section 2), so a test below checks that a
# record with one gives an error and no script.
MESSAGES = [
    "Do you ship to Chennai?\u2028Line two",
    "Return order #4471, please.\n",
    "Two lines\r\nwith CR LF",
    "The escape text \\ud83d is 6 characters",
    "Is the teapot in stock? \U0001f375  ",
    "All 3 in one: \\udc00 and\u2028a new line at the end\n",
]


def write_test(root: Path, messages: list[str], test: str = TEST_ID) -> Path:
    folder = root / ".nookku" / "tests" / test
    folder.mkdir(parents=True)
    writer = Writer(folder / "relay.jsonl")
    for said in messages:
        writer.append({"type": "turn", "harness": "pane", "said": said, "shown": "ok", "ok": True})
    return folder


def test_the_script_keeps_each_byte_of_each_said_text(tmp_path: Path) -> None:
    write_test(tmp_path, MESSAGES)
    path, count = script_save.save(tmp_path, TEST_ID)
    # The file name records the source test id.
    assert path == tmp_path / ".nookku" / "scripts" / f"{TEST_ID}.jsonl"
    assert count == len(MESSAGES)
    data = path.read_bytes()
    messages, form = script.parse(data)
    assert (messages, form) == (MESSAGES, "jsonl")
    assert [m.encode() for m in messages] == [m.encode() for m in MESSAGES]
    # One row for each turn: json.dumps escapes the line feed, and U+2028 stays as it is.
    assert data.count(b"\n") == len(MESSAGES)
    assert "\u2028".encode() in data
    assert list(path.parent.iterdir()) == [path]


def test_a_said_with_a_lone_surrogate_writes_no_script(tmp_path: Path) -> None:
    folder = write_test(tmp_path, ["Hi"])
    # A row that a broken writer wrote: the said text has a lone surrogate U+D83D.
    row = {"v": "0.2", "ts": 1.0, "type": "turn", "said": "a \ud83d b", "shown": None}
    row |= {"said_sha256": "0" * 64, "shown_sha256": None, "harness": "pane"}
    with (folder / "relay.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    with pytest.raises(script_save.SaveError, match="surrogate"):
        script_save.save(tmp_path, TEST_ID)
    assert not (tmp_path / ".nookku" / "scripts").exists()


def test_a_test_with_no_turn_or_a_bad_id_writes_no_script(tmp_path: Path) -> None:
    write_test(tmp_path, [])
    with pytest.raises(script_save.SaveError, match="has no turn"):
        script_save.save(tmp_path, TEST_ID)
    for test in ("../tests", "20261013-090000-zz99", "/etc"):
        with pytest.raises(script_save.SaveError, match="test"):
            script_save.save(tmp_path, test)
    assert not (tmp_path / ".nookku" / "scripts").exists()


def test_the_command_saves_the_latest_or_the_named_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_test(tmp_path, MESSAGES[:2])
    assert main(["script", "save", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    path = tmp_path / ".nookku" / "scripts" / f"{TEST_ID}.jsonl"
    assert f"Saved 2 messages of test {TEST_ID} to {path}" in out
    assert f"Run it with: nookku run --script .nookku/scripts/{TEST_ID}.jsonl" in out
    assert main(["script", "save", TEST_ID, "--root", str(tmp_path)]) == 0
    assert script.parse(path.read_bytes())[0] == MESSAGES[:2]
    assert main(["script", "save", "nothing", "--root", str(tmp_path)]) == 2
    write_test(tmp_path, [], "20261014-090000-cd34")
    assert main(["script", "save", "20261014-090000-cd34", "--root", str(tmp_path)]) == 1
    assert "has no turn" in capsys.readouterr().err


def test_the_page_answer_saves_only_a_test_id(tmp_path: Path) -> None:
    write_test(tmp_path, MESSAGES)
    status, answer = script_save.answer(tmp_path, {"test": TEST_ID})
    assert status == 200 and answer["saved"] and answer["messages"] == len(MESSAGES)
    assert answer["path"] == str(tmp_path / ".nookku" / "scripts" / f"{TEST_ID}.jsonl")
    assert "nookku run --script .nookku/scripts/" in answer["text"]
    for body in ({}, {"test": 1}, ["x"], None):
        assert script_save.answer(tmp_path, body)[0] == 400
    status, answer = script_save.answer(tmp_path, {"test": "../../x"})
    assert status == 200 and not answer["saved"] and "not a test id" in answer["error"]


@pytest.fixture
def homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))


def test_a_script_saved_from_a_toy_shop_test_runs_with_no_script_mismatch(
    tmp_path: Path, homes: None
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    cur = bridge.start(root, "tester-1")
    try:
        for said in MESSAGES:
            shown, ok = bridge.send(cur, said)
            Writer(Path(cur["dir"]) / "relay.jsonl").append(
                {"type": "turn", "harness": "pane", "said": said, "shown": shown, "ok": ok}
            )
    finally:
        bridge.end(root)
    path, _ = script_save.save(root, cur["test"])
    passed, lines, folder = bridge.run_script(root, path)
    assert passed, lines
    assert f"Turns: {len(MESSAGES)} of {len(MESSAGES)} messages" in lines
    report = audit(folder / "tap.jsonl", folder / "relay.jsonl", folder / "script.jsonl")
    assert report.exit == 0
    assert not [b for b in report.breaks if b.kind == "script_mismatch"]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["script"]["source"] == str(path.resolve())
    assert cur["test"] in manifest["script"]["source"]


def _decision(root: Path, tool: str, tool_input: dict[str, str]) -> str | None:
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "cwd": str(root),
    }
    answer = kit.handle(event, root, "claude-code")
    return None if answer is None else answer["hookSpecificOutput"]["permissionDecision"]


def test_the_guard_denies_a_model_write_to_a_saved_script(tmp_path: Path) -> None:
    write_test(tmp_path, MESSAGES)
    path, _ = script_save.save(tmp_path, TEST_ID)
    name = f".nookku/scripts/{TEST_ID}.jsonl"
    # With no test, a model write would change the messages of the next scripted test.
    assert _decision(tmp_path, "Write", {"file_path": str(path), "content": "x"}) == "deny"
    assert _decision(tmp_path, "Bash", {"command": f"echo '{{}}' > {name}"}) == "deny"
    assert _decision(tmp_path, "Bash", {"command": f"rm -rf .nookku/{kit.SCRIPTS}"}) == "deny"
    # A read stays free.
    assert _decision(tmp_path, "Read", {"file_path": str(path)}) is None
    assert _decision(tmp_path, "Bash", {"command": f"cat {name}"}) is None
    # The guard cannot tell a run from a write, so a model run of the path is denied too.
    policy.set_key(tmp_path, "scripts", "model")
    assert _decision(tmp_path, "Bash", {"command": f"nookku run --script {name}"}) == "deny"
    assert _decision(tmp_path, "Bash", {"command": "nookku run --script a.jsonl"}) is None

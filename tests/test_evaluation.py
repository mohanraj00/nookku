import hashlib
import json
import shutil
from pathlib import Path

import pytest

from nookku import bridge, evaluation, kit, mcp, trace
from nookku.cli import main
from nookku.record import Writer

CASE = Path(__file__).resolve().parent.parent / "conformance" / "trace" / "claude_code_toy_shop"
TEST = "20261006-080000-cc01"


def project(tmp_path: Path, config: dict | None = None, ended: float | None = 2.0) -> Path:
    """A project with one test folder: the Claude Code trace case."""
    state = tmp_path / ".nookku"
    folder = state / "tests" / TEST
    shutil.copytree(CASE, folder, ignore=shutil.ignore_patterns("expect_*"))
    manifest = json.loads((folder / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps({**manifest, "started": 1.0, "ended": ended}))
    conf = {"entry": ["python", "agent.py"], **(config or {})}
    (state / "config.json").write_text(json.dumps(conf))
    trace.build(folder)
    return tmp_path


def test_pending_is_the_latest_ended_test_with_no_report(tmp_path: Path) -> None:
    root = project(tmp_path)
    folder = root / ".nookku" / "tests" / TEST
    assert evaluation.pending(root) == folder
    (folder / evaluation.REPORT).write_text("# Report\n")
    assert evaluation.pending(root) is None


def test_a_check_test_gets_no_evaluation(tmp_path: Path) -> None:
    # nookku check runs a test and ends it. The next nookku end must not evaluate it (#102).
    root = project(tmp_path)
    folder = root / ".nookku" / "tests" / TEST
    relay = Writer(folder / "relay.jsonl")
    row = {"type": "turn", "said": "Hello", "shown": "Hi", "ok": True}
    relay.append({**row, "harness": bridge.CHECK_HARNESS})
    assert evaluation.is_check(folder)
    assert evaluation.pending(root) is None
    assert evaluation.config_note(root) is None
    answer = kit.handle(event(root, "nookku end"), root, "codex")
    assert answer is not None and answer["decision"] == "block"
    # A turn from a harness makes it a test of the tester again.
    relay.append({**row, "harness": "codex"})
    assert not evaluation.is_check(folder)
    assert evaluation.pending(root) == folder


def test_a_test_with_no_turns_or_a_broken_relay_record_is_not_a_check_test(tmp_path: Path) -> None:
    folder = project(tmp_path) / ".nookku" / "tests" / TEST
    assert not evaluation.is_check(folder)
    (folder / "relay.jsonl").write_text("{broken\n")
    assert not evaluation.is_check(folder)


def test_no_evaluation_if_the_config_turns_it_off_or_the_test_runs(tmp_path: Path) -> None:
    assert evaluation.pending(project(tmp_path / "off", {"evaluate": False})) is None
    assert evaluation.pending(project(tmp_path / "running", ended=None)) is None
    assert evaluation.enabled(project(tmp_path / "default"))


@pytest.mark.parametrize(
    "text",
    ['{"evaluate": true, "nope": 1}', "{broken", "[]"],
    ids=["unknown-key", "not-json", "not-object"],
)
def test_a_broken_config_starts_no_evaluation(
    tmp_path: Path, text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # The one reader of config.json decides (#119). A file that it refuses starts no evaluation,
    # and the end text says why.
    root = project(tmp_path)
    (root / ".nookku" / "config.json").write_text(text)
    assert evaluation.enabled(root) is False
    assert evaluation.pending(root) is None
    note = evaluation.config_note(root)
    assert note is not None
    assert note.startswith("nookku: no evaluation starts: ")
    assert note.endswith("Correct the file, then type: nookku end")
    answer = kit.handle(event(root, "nookku end"), root, "codex")
    assert answer["decision"] == "block"
    assert answer["reason"].endswith(note)
    assert main(["end", "--evaluation", "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["evaluation"] is None
    assert out["text"].endswith(note)
    # A plain end in a shell, after the test ended before, also names the error.
    assert main(["end", "--root", str(root)]) == 0
    assert capsys.readouterr().out == f"No test runs. Relay mode is off.\n{note}\n"


def test_no_config_note_if_no_test_needs_an_evaluation(tmp_path: Path) -> None:
    root = project(tmp_path, ended=None)
    (root / ".nookku" / "config.json").write_text("{broken")
    assert evaluation.config_note(root) is None
    assert evaluation.config_note(project(tmp_path / "valid")) is None


def test_the_transcript_shows_each_turn_with_its_trace(tmp_path: Path) -> None:
    root = project(tmp_path)
    text = evaluation.transcript(root / ".nookku" / "tests" / TEST)
    seal_line, text = text.split("\n", 1)
    assert seal_line == "Seal: none. The records of this test have no seal."
    assert text.startswith(f"nookku transcript with trace, test {TEST}: 3 turns, 11 ")
    turn1 = text.split("════ turn 1 ════")[1].split("════ turn 2 ════")[0]
    assert "[trace.jsonl:5] claude-code tool_call: shop.lookup_order\n" in turn1
    assert 'input: {"order": "4471"}\nresult:\n{"status": "delivered"}\n' in turn1
    assert "ToolSearch (a harness tool)" in turn1
    turn2 = text.split("════ turn 2 ════")[1]
    assert "- tool_error: lookup_order: no such order [trace.jsonl:8]" in turn2
    assert "(no reply: status 500, the agent failed)" in turn2
    outside = text.split("════ model items outside each turn ════")[1]
    assert "[trace.jsonl:1] claude-code message, user:\nWarm up.\n" in outside
    assert "error:\nno tool_result in the session file\n" in outside


def test_a_changed_byte_in_the_tap_record_makes_the_transcript_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    folder = root / ".nookku" / "tests" / TEST
    tap = folder / "tap.jsonl"
    # One byte of a reply changes, and its hash stays.
    tap.write_text(tap.read_text().replace("was delivered.", "was delivereD.", 1))
    text = evaluation.transcript(folder)
    first, second, rest = text.split("\n", 2)
    assert first.startswith(f"Record: INVALID. {tap}: line 1: field reply_sha256 does not match")
    assert first.endswith("Do not trust these records. This transcript shows no turn.")
    assert second == "Seal: none. The records of this test have no seal."
    assert rest == ""
    assert "delivereD" not in text
    assert "exact" not in text
    assert main(["trace", "--root", str(root)]) == 2
    assert "line 1: field reply_sha256" in capsys.readouterr().err


def test_an_invalid_trace_line_makes_the_transcript_invalid(tmp_path: Path) -> None:
    root = project(tmp_path)
    folder = root / ".nookku" / "tests" / TEST
    with (folder / "trace.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("[1]\n")
    text = evaluation.transcript(folder)
    assert text.startswith("Record: INVALID. ")
    assert "trace.jsonl: line 12: not a JSON object" in text.split("\n")[0]
    assert "════ turn 1 ════" not in text


def test_a_long_text_is_cut_and_points_to_its_line() -> None:
    item = {"harness": "codex", "kind": "message", "role": "assistant", "output": "x" * 2500}
    text = evaluation.render_item(item, 7)
    assert text.endswith("(cut at 2000 characters: the full text is in trace.jsonl:7)\n")


def test_a_model_api_call_shows_its_status_and_error() -> None:
    item = {
        "harness": "model_api",
        "session": "openai",
        "kind": "message",
        "role": "assistant",
        "input": {"path": "/chat/completions"},
        "output": None,
        "error": "Rate limit reached",
        "exit_code": 429,
    }
    assert evaluation.render_item(item, 4) == (
        "[trace.jsonl:4] model_api message, assistant: openai /chat/completions, status 429:\n"
        "\nerror:\nRate limit reached\n"
    )


def test_each_decision_shows_on_one_line_and_a_refusal_is_not_an_error(tmp_path: Path) -> None:
    case = CASE.parent / "model_api_decisions"
    items = [json.loads(x) for x in (case / "expect_trace.jsonl").read_text().split("\n") if x]
    text = "".join(evaluation.render_item(it, n) for n, it in enumerate(items, 1))
    assert text == (
        "[trace.jsonl:1] model_api message, user:\n"
        "My teapot set arrived with a broken lid.\n"
        "question damaged (predicate)\n"
        "question department (choice): billing, shipping, other\n"
        "question severity (score): Low, Medium, High\n"
        "question mood (choice): calm, angry\n"
        "image: image/png, 43 bytes, sha256 "
        "8408fd233fa12533815c36b05827df10defdc749b48e092da75d2004ce847cca\n"
        "[trace.jsonl:2] model_api message, assistant: openai /v1/decisions, status 200:\n"
        "damaged: probability 0.97\n"
        "department: shipping (0.95), confidence 0.93\n"
        "severity: score 1.2, confidence 0.5\n"
        "mood: refusal (the model did not answer this question)\n"
        "[trace.jsonl:3] model_api message, user:\n"
        "I was charged twice for order 5120.\n"
        "question department (choice): billing, shipping, other\n"
        "question refund_due (choice): true, false\n"
        "[trace.jsonl:4] model_api message, assistant: openai /decisions, status 200:\n"
        "department: billing (0.95), confidence 0.93\n"
        "refund_due: true (0.8), confidence 0.7\n"
    )
    assert "error" not in text


def test_the_prompt_names_the_test_and_its_folder(tmp_path: Path) -> None:
    folder = tmp_path / "tests" / TEST
    text = evaluation.prompt(folder)
    assert f"nookku transcript --trace --test {TEST}" in text
    assert f"`{folder}/report.md`" in text
    assert "{" + "folder}" not in text and "{" + "test}" not in text


def event(root: Path, prompt: str) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "session_id": "tester"}


def test_the_kit_gives_the_model_the_evaluation_at_end(tmp_path: Path) -> None:
    root = project(tmp_path)
    answer = kit.handle(event(root, "nookku end"), root, "codex")
    assert answer is not None
    context = answer["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("nookku: no test runs. Relay mode is off.\n\n# Evaluate test")
    assert "decision" not in answer
    # With the evaluation off, the prompt stays blocked.
    off = project(tmp_path / "off", {"evaluate": False})
    assert kit.handle(event(off, "nookku end"), off, "codex")["decision"] == "block"


@pytest.mark.parametrize(
    ("name", "denied"),
    [("tap.jsonl", True), ("sessions/codex/r.jsonl", True), ("report.md", False)],
)
def test_after_a_test_the_kit_protects_the_records(tmp_path: Path, name: str, denied: bool) -> None:
    root = project(tmp_path)
    path = root / ".nookku" / "tests" / TEST / name
    write = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(path)},
    }
    answer = kit.handle(write, root, "claude-code")
    assert (answer is not None) == denied
    if denied:
        reason = kit.RECORDS_REASON.format(name=str(path))
        assert answer["hookSpecificOutput"]["permissionDecisionReason"] == reason


def test_cli_end_evaluation_and_transcript_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    assert main(["end", "--evaluation", "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["text"] == "No test runs. Relay mode is off."
    assert out["evaluation"].startswith(f"# Evaluate test {TEST}")
    assert main(["transcript", "--trace", "--root", str(root)]) == 0
    assert "════ turn 3 ════" in capsys.readouterr().out
    assert main(["transcript", "--trace", "--test", "nope", "--root", str(root)]) == 2


def test_the_kit_config_takes_the_evaluate_key(tmp_path: Path) -> None:
    root = project(tmp_path, {"evaluate": False})
    assert kit.Config.load(root).evaluate is False
    # A prompt in relay mode with no test still gets the relay's own answer, not a config error.
    kit.set_mode(root, True)
    answer = kit.handle(event(root, "hello"), root, "codex")
    assert "no test runs" in answer["reason"]


OTEL_CASE = CASE.parent / "otel_toy_shop"
# The app prompt of each model turn: the toy shop rules and the output schema (#152).
# It has no character that JSON escapes, so it shows the same in an attribute and in a message.
PROMPT = "You are the toy shop support agent. Give the reply as one string. " * 5


def _item(turn: int, kind: str, file: str, line: int, **fields: object) -> dict:
    harness = "otel" if file == "otel.jsonl" else "claude-code"
    base = {"v": "0.3", "type": "model_item", "turn": turn, "harness": harness, "session": "s1"}
    base.update({"ts": 0, "kind": kind, "role": None, "server": None, "name": None})
    base.update({"input": None, "output": None, "error": None, "exit_code": None})
    base.update({"harness_internal": False, "service": None})
    return {**base, **fields, "source": {"file": file, "line": line}}


def compact_folder(tmp_path: Path) -> Path:
    """A test with 2 model turns. Each turn sends PROMPT to the model, and the harness also
    sends it in the OTel user_prompt log."""
    folder = tmp_path / "test"
    shutil.copytree(OTEL_CASE, folder, ignore=shutil.ignore_patterns("expect_*"))
    session = "sessions/claude-code/s1.jsonl"
    items = []
    for turn in (1, 2):
        attributes = {"event.name": "user_prompt", "prompt": PROMPT, "prompt_length": "1"}
        items.append(_item(turn, "log", "otel.jsonl", turn, name="user_prompt", input=attributes))
        items.append(_item(turn, "message", session, turn, role="user", output=PROMPT))
        reply = f"toy shop reply {turn}"
        items.append(_item(turn, "message", session, turn + 2, role="assistant", output=reply))
    (folder / "trace.jsonl").write_text("".join(json.dumps(it) + "\n" for it in items))
    return folder


def test_a_compact_transcript_shows_each_prompt_body_one_time(tmp_path: Path) -> None:
    folder = compact_folder(tmp_path)
    full = evaluation.transcript(folder)
    assert full.count(PROMPT) == 4
    assert "Compact:" not in full
    text = evaluation.transcript(folder, compact=True)
    assert text.count(PROMPT) == 1
    assert "\nCompact: a text of 200 or more characters" in text
    digest = hashlib.sha256(PROMPT.encode()).hexdigest()
    same = f"(compact: the same text as [trace.jsonl:2], sha256 {digest}, {len(PROMPT)} characters)"
    turn1, turn2 = text.split("════ turn 1 ════")[1].split("════ turn 2 ════")
    # The OTel attribute has the text of the session message of the same turn.
    assert f'"prompt": "{same}"' in turn1
    assert f"[trace.jsonl:2] claude-code message, user:\n{PROMPT}\n" in turn1
    # In turn 2, the attribute and the message point to the first full text.
    assert f'"prompt": "{same}"' in turn2
    assert f"[trace.jsonl:5] claude-code message, user:\n{same}\n" in turn2
    # A short text and each other item do not change.
    assert '"event.name": "user_prompt"' in turn2
    assert "toy shop reply 2" in turn2


def test_a_compact_transcript_shows_a_repeated_otel_prompt_with_no_session_one_time(
    tmp_path: Path,
) -> None:
    folder = compact_folder(tmp_path)
    lines = (folder / "trace.jsonl").read_text().splitlines()
    kept = [line for line in lines if json.loads(line)["kind"] == "log"]
    (folder / "trace.jsonl").write_text("\n".join(kept) + "\n")
    text = evaluation.transcript(folder, compact=True)
    assert text.count(PROMPT) == 1
    assert "(compact: the same text as [trace.jsonl:1], sha256 " in text


def test_the_config_key_and_the_flags_choose_the_compact_transcript(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path, {"transcript_compact": True})
    folder = root / ".nookku" / "tests" / TEST
    source = compact_folder(tmp_path / "source")
    for name in ("tap.jsonl", "trace.jsonl"):
        (folder / name).write_text((source / name).read_text())
    args = ["transcript", "--trace", "--root", str(root)]
    assert main(args) == 0
    assert capsys.readouterr().out.count(PROMPT) == 1
    assert main([*args, "--no-compact"]) == 0
    assert capsys.readouterr().out.count(PROMPT) == 4
    (root / ".nookku" / "config.json").write_text(json.dumps({"entry": ["python", "agent.py"]}))
    assert main(args) == 0
    assert capsys.readouterr().out.count(PROMPT) == 4
    assert main([*args, "--compact"]) == 0
    assert capsys.readouterr().out.count(PROMPT) == 1


def test_the_config_refuses_a_compact_value_that_is_not_a_boolean(tmp_path: Path) -> None:
    root = project(tmp_path, {"transcript_compact": "yes"})
    with pytest.raises(kit.TranscriptError, match="transcript_compact"):
        kit.transcript_text(root, trace=True)


@pytest.mark.parametrize("compact", [True, False])
def test_the_mcp_transcript_takes_compact(tmp_path: Path, compact: bool) -> None:
    root = project(tmp_path, {"transcript_compact": not compact})
    folder = root / ".nookku" / "tests" / TEST
    source = compact_folder(tmp_path / "source")
    for name in ("tap.jsonl", "trace.jsonl"):
        (folder / name).write_text((source / name).read_text())
    arguments = {"trace": True, "compact": compact, "page_tokens": 100000}
    text = mcp.call(root, "transcript", arguments)["content"][0]["text"]
    assert text.startswith(kit.transcript_text(root, trace=True, compact=compact))
    assert text.count(PROMPT) == (1 if compact else 4)


def test_the_transcript_shows_version_untested_one_time_for_each_version(tmp_path: Path) -> None:
    folder = tmp_path / "20261006-080000-vv01"
    shutil.copytree(
        CASE.parent / "untested_versions", folder, ignore=shutil.ignore_patterns("expect_*")
    )
    manifest = json.loads((folder / "manifest.json").read_text())
    first = manifest["model_sessions"][0]
    for n in range(2, 6):
        file = f"sessions/claude-code/s{n}.jsonl"
        shutil.copyfile(folder / first["file"], folder / file)
        manifest["model_sessions"].append({**first, "session": f"s{n}", "file": file})
    (folder / "manifest.json").write_text(json.dumps(manifest))
    report = trace.build(folder)
    # findings.json keeps one finding for each session: 5 Claude Code and 1 Codex.
    assert report["counts"]["version_untested"] == 6
    text = evaluation.transcript(folder)
    loose = text.split("Findings with no turn:\n")[1].split("\n════")[0]
    assert loose.splitlines() == [
        "- version_untested: version 2.1.999, tested: 2.1.286, 2.1.292 (claude-code, 5 sessions)",
        "- version_untested: version 0.161.0, tested: 0.160.0, 0.162.1 (codex, 1 session)",
    ]

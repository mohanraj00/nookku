import json
import shutil
from pathlib import Path

import pytest

from verbatim_relay import evaluation, kit, trace
from verbatim_relay.cli import main

CASE = Path(__file__).resolve().parent.parent / "conformance" / "trace" / "claude_code_toy_shop"
TEST = "20261006-080000-cc01"


def project(tmp_path: Path, config: dict | None = None, ended: float | None = 2.0) -> Path:
    """A project with one test folder: the Claude Code trace case."""
    state = tmp_path / ".verbatim-relay"
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
    folder = root / ".verbatim-relay" / "tests" / TEST
    assert evaluation.pending(root) == folder
    (folder / evaluation.REPORT).write_text("# Report\n")
    assert evaluation.pending(root) is None


def test_no_evaluation_if_the_config_turns_it_off_or_the_test_runs(tmp_path: Path) -> None:
    assert evaluation.pending(project(tmp_path / "off", {"evaluate": False})) is None
    assert evaluation.pending(project(tmp_path / "running", ended=None)) is None
    assert evaluation.enabled(tmp_path / "no-config")


def test_the_transcript_shows_each_turn_with_its_trace(tmp_path: Path) -> None:
    root = project(tmp_path)
    text = evaluation.transcript(root / ".verbatim-relay" / "tests" / TEST)
    seal_line, text = text.split("\n", 1)
    assert seal_line == "Seal: none. The records of this test have no seal."
    assert text.startswith(f"verbatim-relay transcript with trace, test {TEST}: 3 turns, 11 ")
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
    assert f"verbatim-relay transcript --trace --test {TEST}" in text
    assert f"`{folder}/report.md`" in text
    assert "{" + "folder}" not in text and "{" + "test}" not in text


def event(root: Path, prompt: str) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "session_id": "tester"}


def test_the_kit_gives_the_model_the_evaluation_at_end(tmp_path: Path) -> None:
    root = project(tmp_path)
    answer = kit.handle(event(root, "verbatim-relay end"), root, "codex")
    assert answer is not None
    context = answer["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("verbatim-relay: no test runs. Relay mode is off.\n\n# Evaluate test")
    assert "decision" not in answer
    # With the evaluation off, the prompt stays blocked.
    off = project(tmp_path / "off", {"evaluate": False})
    assert kit.handle(event(off, "verbatim-relay end"), off, "codex")["decision"] == "block"


@pytest.mark.parametrize(
    ("name", "denied"),
    [("tap.jsonl", True), ("sessions/codex/r.jsonl", True), ("report.md", False)],
)
def test_after_a_test_the_kit_protects_the_records(tmp_path: Path, name: str, denied: bool) -> None:
    root = project(tmp_path)
    path = root / ".verbatim-relay" / "tests" / TEST / name
    write = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(path)},
    }
    answer = kit.handle(write, root, "claude-code")
    assert (answer is not None) == denied
    if denied:
        assert answer["hookSpecificOutput"]["permissionDecisionReason"] == kit.RECORDS_REASON


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
    # A prompt in relay mode with no test still gets the kit's own answer, not a config error.
    kit.set_mode(root, True)
    answer = kit.handle(event(root, "hello"), root, "codex")
    assert "no test runs" in answer["reason"]

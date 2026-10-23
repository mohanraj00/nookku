"""Regression checks for the local proof checks of issue #456."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import proof_egress as pe
import proof_sessions as ps
import proof_spec_classes as pc


def test_discovery_checks_new_removed_and_changed_project_files(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    (tmp_path / "app.py").write_text("toy shop")
    (tmp_path / ".nookku/config.json").write_text("{}")
    before = pe.digest(tmp_path)
    (tmp_path / "app.py").unlink()
    (tmp_path / "sitecustomize.py").write_text("changed")
    (tmp_path / ".nookku/config.json").write_text('{"evaluate": false}')
    after = pe.digest(tmp_path)
    assert set(before) | set(after) == {"app.py", "sitecustomize.py", ".nookku/config.json"}
    assert pe.changed_files(before, after) == [".nookku/config.json", "app.py", "sitecustomize.py"]


def test_discovery_excludes_only_its_answer_files_and_test_folder(tmp_path: Path) -> None:
    state = tmp_path / ".nookku"
    (state / "tests/old").mkdir(parents=True)
    (state / "tests/old/trace.jsonl").write_text("record")
    for name in ("discovery.json", "egress.json"):
        (state / name).write_text("answer")
    (state / "config.json").write_text("{}")
    assert set(pe.digest(tmp_path)) == {".nookku/config.json"}


def test_egress_requires_the_app_model_api() -> None:
    data = json.loads((pe.pr.ROOT / "proofs/egress/plugin-claude-code.json").read_text())
    answer = copy.deepcopy(data["answer"])
    http = next(p for p in answer["mcp_servers"] if p["transport"] == "http")
    stdio = next(p for p in answer["mcp_servers"] if p["transport"] == "stdio")
    pg = next(p for p in answer["databases"] if p["record"] == "proxy")
    lite = next(p for p in answer["databases"] if p["record"] == "driver")
    egress = {
        "unseen": [],
        "driver": [lite["name"]],
        "proxies": {
            stdio["name"]: "stdio",
            http["name"]: http["url"],
            pg["name"]: "postgresql://proxy",
            "anthropic": "http://127.0.0.1:9000",
        },
    }
    answer["model_apis"] = [{"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": None}]
    assert pe.e1(answer, egress, http["url"])
    for apis in ([], [{"api": "openai", "env": "OPENAI_BASE_URL", "url": None}]):
        answer["model_apis"] = apis
        assert not pe.e1(answer, egress, http["url"])


@pytest.mark.parametrize("text", ["", " ", None])
def test_an_empty_codex_answer_fails_the_session_proof(tmp_path: Path, text: str | None) -> None:
    row = {"type": "exchange", "reply": "Claude answer.\n\nSecond opinion: " + (text or "")}
    (tmp_path / "tap.jsonl").write_text(json.dumps(row) + "\n")
    assert not ps.codex_answered(tmp_path)


def test_a_codex_answer_passes_the_session_check(tmp_path: Path) -> None:
    row = {"type": "exchange", "reply": "Claude answer.\n\nSecond opinion: Hello."}
    (tmp_path / "tap.jsonl").write_text(json.dumps(row) + "\n")
    assert ps.codex_answered(tmp_path)


@pytest.mark.parametrize("rows", [1, 2])
def test_the_sample_report_check_accepts_the_row_word(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: int
) -> None:
    import test_docs

    folder = tmp_path / "proofs/report"
    folder.mkdir(parents=True)
    report = "| Class | Turn | Evidence | Issue |\n"
    report += "| business_rule | 1 | tap.jsonl:1 | toy shop rule |\n" * rows
    report += "- first note\n- second note\n"
    (folder / "toy.json").write_text(json.dumps({"report": report}))
    word = "row" if rows == 1 else "rows"
    (tmp_path / "README.md").write_text(
        "## A sample report\n```markdown\n" + report + "```\n"
        f"The full report has {rows} {word} and 2 notes.\n"
        "[data](proofs/report/toy.json)\n## Next\n"
    )
    monkeypatch.setattr(test_docs, "ROOT", tmp_path)
    test_docs.test_the_sample_report_of_the_readme_is_an_excerpt_of_its_data()


def test_a_separator_in_the_claude_answer_cannot_hide_an_empty_codex_answer(tmp_path: Path) -> None:
    row = {
        "type": "exchange",
        "reply": "Quoted text\n\nSecond opinion: not the Codex answer.\n\nSecond opinion: ",
    }
    (tmp_path / "tap.jsonl").write_text(json.dumps(row) + "\n")
    assert not ps.codex_answered(tmp_path)


def test_discovery_accepts_only_added_guard_rows() -> None:
    def row(tool: str, detail: str, harness: str = "claude-code") -> bytes:
        item = {"v": "0.2", "ts": 1.0, "type": "blocked_call", "harness": harness}
        item |= {"tool": tool, "detail": detail}
        return json.dumps(item).encode() + b"\n"

    calls = [("Bash", '{"command": "cat .nookku/mode"}'), ("Read", '{"file_path": "x"}')]
    cc = {"claude-code", "plugin"}
    bash, read = row(*calls[0]), row(*calls[1])
    assert pe.guard_rows(b"", bash, cc, calls) == 1
    assert pe.guard_rows(read, read + bash, cc, calls) == 1
    assert pe.guard_rows(b"", bash + read, cc, calls) == 2
    # Each row needs a different call, and the old bytes must stay.
    assert pe.guard_rows(b"", bash + bash, cc, calls) is None
    assert pe.guard_rows(read, bash, cc, calls) is None
    assert pe.guard_rows(b"", bash[:-1], cc, calls) is None
    assert pe.guard_rows(read[:-1], read[:-1] + bash, cc, calls) is None
    # A row that the model wrote: no matching call, a short row, another harness or more keys.
    assert pe.guard_rows(b"", row("Bash", "rm app.py"), cc, calls) is None
    assert pe.guard_rows(b"", b'{"type":"blocked_call"}\n', cc, calls) is None
    assert pe.guard_rows(b"", row(*calls[0], harness="codex"), cc, calls) is None
    assert pe.guard_rows(b"", bash, set(), calls) is None
    extra = json.loads(bash)
    extra["note"] = "toy shop"
    assert pe.guard_rows(b"", json.dumps(extra).encode() + b"\n", cc, calls) is None
    assert pe.guard_rows(b"", b'{"type":"user","text":"toy shop"}\n', cc, calls) is None
    assert pe.guard_rows(b"", b"[]\n", cc, calls) is None
    assert pe.guard_rows(b"", b"not json\n", cc, calls) is None


def test_the_tool_calls_of_a_claude_output_give_the_guard_detail() -> None:
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "I read the toy shop."},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "cat app.py"}},
                ]
            },
        },
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        {"type": "assistant", "message": {"content": "no list"}},
    ]
    assert pe.pr.tool_calls(events) == [("Bash", '{"command": "cat app.py"}')]
    long = {"type": "tool_use", "name": "Write", "input": {"content": "x" * 400}}
    detail = pe.pr.tool_calls([{"type": "assistant", "message": {"content": [long]}}])[0][1]
    assert len(detail) == 300


@pytest.mark.parametrize("path", ["APP_SPEC.md", "spec/1.md", "/toy/test/spec/1.md"])
def test_a_spec_class_can_cite_its_sealed_spec_copy(path: str) -> None:
    assert pc.cites(f"turn 2; {path}:20", 2, range(18, 25), "spec/1.md")


@pytest.mark.parametrize(
    "evidence",
    [
        "turn 2; spec/2.md:20",
        "turn 2; OTHER_APP_SPEC.md:20",
        "turn 2; spec/1.md:9",
        "turn 3; spec/1.md:20",
    ],
)
def test_a_spec_class_needs_its_own_file_section_and_turn(evidence: str) -> None:
    assert not pc.cites(evidence, 2, range(18, 25), "spec/1.md")

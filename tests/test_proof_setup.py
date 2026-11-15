"""The checks of scripts/proof_setup.py that need no model (#511)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from proof_setup import PARTS, checks_run, missing_parts, passed

FULL = (
    "- **In and out:** app.py, class Shop.\n"
    "- **Model harnesses:** claude-code.\n"
    "- **Backends:** STOCK_URL.\n"
    "- **Store:** state.json.\n"
    "- **Rules and docs:** RULES.md.\n"
)


@pytest.mark.parametrize(("part", "word"), [(p, w) for p, ws in PARTS.items() for w in ws])
def test_each_word_names_its_part(part: str, word: str) -> None:
    assert part not in missing_parts(f"- **{word.upper()}:** a file.")


def test_the_words_of_run_1_name_the_store() -> None:
    # Run 1 of v0.5.6 wrote "Data files", and the S2 of that version failed.
    assert missing_parts(FULL.replace("**Store:**", "**Data files:**")) == []


def test_a_missing_part_is_named() -> None:
    assert missing_parts(FULL) == []
    assert missing_parts(FULL.replace("- **Store:** state.json.\n", "")) == ["store"]
    assert missing_parts("") == list(PARTS)


def test_checks_run_pairs_each_check_with_its_output() -> None:
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "ls"}},
                    {
                        "type": "tool_use",
                        "id": "b",
                        "name": "Bash",
                        "input": {"command": "nookku check"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "a", "content": "x"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "b",
                        "content": [{"type": "text", "text": "Audit: exit 0\nPASS"}],
                    },
                ]
            },
        },
    ]
    # A system event can hold a text message, and a prompt event a text content.
    events += [{"type": "system", "message": "x"}, {"type": "user", "message": {"content": "y"}}]
    runs = checks_run(events)
    assert runs == [{"command": "nookku check", "output": "Audit: exit 0\nPASS"}]
    assert passed(runs[0]["output"])


def test_only_a_pass_line_passes() -> None:
    assert not passed("FAIL: The entry sent no reply.")
    assert not passed("PASSED")
    assert passed("Reply: hi\n  PASS  \n")

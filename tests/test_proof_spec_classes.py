"""Check the rule text at each spec citation in the class proof."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import proof_spec_classes as pc

SPEC = (pc.FULL / "APP_SPEC.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("cls", ["off_path", "boundary", "tone"])
@pytest.mark.parametrize("kind", ["rule", "blank", "other_rule", "outside", "no_turn"])
def test_a_row_needs_the_rule_text_and_turn(cls: str, kind: str) -> None:
    lines = SPEC.split("\n")
    part = pc.parts(SPEC)[pc.PARTS[cls]]
    rule = {
        "off_path": "2. Stock:",
        "boundary": "- It does not answer questions",
        "tone": "- It is polite and direct.",
    }[cls]
    line = next(n for n, text in enumerate(lines, 1) if text.startswith(rule))
    if kind == "blank":
        line = next(n for n in part if not lines[n - 1])
    elif kind == "other_rule":
        other = {
            "off_path": "1. Order status:",
            "boundary": "- The agent follows",
            "tone": "- The agent is",
        }
        line = next(n for n in part if lines[n - 1].startswith(other[cls]))
    elif kind == "outside":
        line = 1
    turn = pc.EXPECTED[cls]
    evidence = f"APP_SPEC.md:{line}"
    if kind != "no_turn":
        evidence = f"turn {turn}; {evidence}"
    row = pc.pr.rows(f"| {cls} | {turn} | {evidence} | toy shop rule |\n")[0]
    assert pc.cites(row["evidence"], turn, part) is (kind == "rule")


def test_tone_accepts_the_sentence_limit() -> None:
    line = next(n for n, text in enumerate(SPEC.split("\n"), 1) if "2 sentences or fewer" in text)
    assert pc.cites(f"turn 4; APP_SPEC.md:{line}", 4, pc.parts(SPEC)["Persona"])


@pytest.mark.parametrize("path", ["APP_SPEC.md", "spec/1.md", "/toy/test/spec/1.md"])
def test_the_check_reads_the_selected_spec_text(path: str) -> None:
    shifted = "\n\n" + SPEC
    line = next(n for n, text in enumerate(shifted.split("\n"), 1) if "2. Stock:" in text)
    part = pc.parts(shifted)["User goals"]
    evidence = f"turn 2; {path}:{line}"
    assert pc.cites(evidence, 2, part, "spec/1.md", spec_text=shifted)
    changed = shifted.replace(
        "The agent checks the stock and tells the customer the number of items left.",
        "The agent tells the customer to read the newsletter.",
    )
    assert not pc.cites(evidence, 2, part, "spec/1.md", spec_text=changed)


def test_the_check_records_each_cited_line() -> None:
    part = pc.parts(SPEC)["User goals"]
    evidence = "turn 2; APP_SPEC.md:18, APP_SPEC.md:19, APP_SPEC.md:20, APP_SPEC.md:7"
    assert pc.citation_checks(evidence, 2, part, spec_text=SPEC) == {
        7: False,
        18: False,
        19: False,
        20: True,
    }

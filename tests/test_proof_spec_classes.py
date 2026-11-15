"""Check the rule text at each spec citation in the class proof."""

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

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


def test_the_control_reply_keeps_each_rule_of_the_spec() -> None:
    assert pc.CONTROL_REPLY in pc.PLANTED
    assert pc.CONTROL_REPLY.count(".") <= 2 and "4471" in pc.CONTROL_REPLY
    order = json.loads((pc.FULL / "state.json").read_text(encoding="utf-8"))["orders"]["4471"]
    assert order["status"] in pc.CONTROL_REPLY and order["tracking"] in pc.CONTROL_REPLY


@pytest.mark.parametrize(
    ("replies", "kept"),
    [
        ([pc.CONTROL_REPLY + "\n", "a", "b", "c"], True),
        (["Order 4471 is delivered. Have a great day, dude!"], False),
        ([None, "a"], False),
        ([], False),
    ],
)
def test_the_proof_checks_the_control_reply(replies: list[str | None], kept: bool) -> None:
    assert pc.control_kept(replies) is kept


def spec_test(tmp_path: Path, copied: bool) -> tuple[Path, Path, dict[str, Any]]:
    project, folder = tmp_path / "project", tmp_path / "test"
    project.mkdir()
    (folder / "spec").mkdir(parents=True)
    data = SPEC.encode("utf-8")
    (project / "APP_SPEC.md").write_bytes(data)
    (folder / "spec" / "2.md").write_bytes(data)
    item = {"path": "APP_SPEC.md", "sha256": hashlib.sha256(data).hexdigest()}
    manifest: dict[str, Any] = {"spec": [{"path": "RULES.md", "sha256": "0" * 64}, item]}
    if copied:
        manifest["spec_copies"] = True
    return folder, project, manifest


@pytest.mark.parametrize("copied", [True, False])
def test_the_proof_reads_the_spec_of_the_test(tmp_path: Path, copied: bool) -> None:
    folder, project, manifest = spec_test(tmp_path, copied)
    path = "spec/2.md" if copied else "APP_SPEC.md"
    assert pc.read_spec(folder, project, manifest) == (path, SPEC)


@pytest.mark.parametrize(
    ("change", "cause"),
    [
        ("no_list", "the manifest has no spec list"),
        ("no_app_spec", "the spec list of the manifest has no APP_SPEC.md"),
        ("no_copy", "the test folder has no copy spec/2.md"),
        ("symlink", "the copy spec/2.md is not a file"),
        ("changed", "the copy of APP_SPEC.md changed after the start of the test"),
    ],
)
def test_a_missing_spec_input_has_a_clear_cause(tmp_path: Path, change: str, cause: str) -> None:
    folder, project, manifest = spec_test(tmp_path, True)
    copy = folder / "spec" / "2.md"
    if change == "no_list":
        del manifest["spec"]
    elif change == "no_app_spec":
        manifest["spec"] = manifest["spec"][:1]
    elif change == "no_copy":
        copy.unlink()
    elif change == "symlink":
        copy.unlink()
        copy.symlink_to(project / "APP_SPEC.md")
    else:
        copy.write_text(SPEC + "\nThe agent can use slang.\n", encoding="utf-8")
    with pytest.raises(pc.SpecInputError) as e:
        pc.read_spec(folder, project, manifest)
    assert str(e.value) == cause

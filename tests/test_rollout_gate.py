"""The toy rollout controller of examples/rollout-gate/ (docs/how-to/gate-a-rollout.md, #519)."""

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "rollout-gate"
SUBJECT = "sha256:" + "ab" * 32
PASS = {
    "v": 1,
    "gate": "gate-1",
    "subject": SUBJECT,
    "verdict": "pass",
    "problems": [],
    "reasons": [],
}
REASON = {"test": "stock-questions", "check": "limits"}


@pytest.fixture(scope="module")
def controller() -> Any:
    spec = importlib.util.spec_from_file_location("controller", EXAMPLE / "controller.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gate(tmp_path: Path, result: Any, sealed: bytes | None = None) -> tuple[Path, Path]:
    """A gate folder with result.json, and the copy of its seal."""
    gate = tmp_path / "gate-1"
    gate.mkdir()
    data = result if isinstance(result, bytes) else json.dumps(result).encode()
    (gate / "result.json").write_bytes(data)
    seal = tmp_path / "gate-1.json"
    digest = hashlib.sha256(data if sealed is None else sealed).hexdigest()
    seal.write_text(json.dumps({"files": {"result.json": digest}}))
    return gate, seal


def test_a_pass_for_the_subject_promotes(controller: Any, tmp_path: Path) -> None:
    gate, seal = _gate(tmp_path, PASS)
    decision = controller.decide(gate, seal, SUBJECT)
    assert decision == {
        "action": "promote",
        "reason": "the verdict is pass for this subject",
        "gate": "gate-1",
        "subject": SUBJECT,
    }
    assert controller.main(["--gate", str(gate), "--seal", str(seal), "--subject", SUBJECT]) == 0


def test_a_fail_stops_and_gives_the_reasons(controller: Any, tmp_path: Path) -> None:
    gate, seal = _gate(tmp_path, dict(PASS, verdict="fail", reasons=[REASON]))
    decision = controller.decide(gate, seal, SUBJECT)
    assert decision["action"] == "stop" and decision["reason"] == "the verdict is not pass"
    assert decision["reasons"] == [REASON] and decision["problems"] == []
    assert controller.main(["--gate", str(gate), "--seal", str(seal), "--subject", SUBJECT]) == 1


@pytest.mark.parametrize("verdict", [None, "PASS", "passed", True, 1])
def test_only_the_word_pass_promotes(controller: Any, tmp_path: Path, verdict: Any) -> None:
    gate, seal = _gate(tmp_path, dict(PASS, verdict=verdict))
    assert controller.decide(gate, seal, SUBJECT)["action"] == "stop"


def test_a_result_for_another_subject_stops(controller: Any, tmp_path: Path) -> None:
    gate, seal = _gate(tmp_path, PASS)
    decision = controller.decide(gate, seal, "sha256:" + "cd" * 32)
    assert (
        decision["action"] == "stop" and decision["reason"] == "the result is for another subject"
    )


def test_a_changed_result_stops(controller: Any, tmp_path: Path) -> None:
    # The copy of the seal has the SHA-256 of the result with the verdict fail.
    sealed = json.dumps(dict(PASS, verdict="fail", reasons=[REASON])).encode()
    gate, seal = _gate(tmp_path, PASS, sealed)
    decision = controller.decide(gate, seal, SUBJECT)
    assert decision["action"] == "stop" and "SHA-256" in decision["reason"]


@pytest.mark.parametrize("result", [b"not json", b"[]", b'"pass"'])
def test_a_result_that_is_not_an_object_stops(
    controller: Any, tmp_path: Path, result: bytes
) -> None:
    gate, seal = _gate(tmp_path, result)
    assert controller.decide(gate, seal, SUBJECT) == {
        "action": "stop",
        "reason": "result.json is not a JSON object",
    }


@pytest.mark.parametrize(
    "copy", ["not json", "[]", "{}", '{"files": []}', '{"files": {"result.json": null}}']
)
def test_a_copy_of_the_seal_with_no_sha256_stops(
    controller: Any, tmp_path: Path, copy: str
) -> None:
    gate, seal = _gate(tmp_path, PASS)
    seal.write_text(copy)
    decision = controller.decide(gate, seal, SUBJECT)
    assert decision["action"] == "stop" and "SHA-256" in decision["reason"]


@pytest.mark.parametrize("missing", ["result", "seal"])
def test_a_missing_file_stops(controller: Any, tmp_path: Path, missing: str) -> None:
    gate, seal = _gate(tmp_path, PASS)
    (gate / "result.json" if missing == "result" else seal).unlink()
    decision = controller.decide(gate, seal, SUBJECT)
    assert decision["action"] == "stop" and decision["reason"].startswith("cannot read ")


def test_the_gate_file_of_the_example_is_valid() -> None:
    from nookku import gate

    tests = gate.parse((EXAMPLE / "gate.json").read_bytes())
    assert [t["name"] for t in tests] == ["stock-questions"]

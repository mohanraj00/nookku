from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

from nookku import commands, gate, record, script, seal, verdict
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
TOY_SPEC = ROOT / "examples" / "toy-shop-full" / "APP_SPEC.md"
REFUND = ["What is your refund policy?", "Do you ship to Pune?"]
PRICE = ["What is the price of the blue mug?", "Is the teapot in stock?"]
SUBJECT = "sha256:ab12cd34"
CASES = sorted(p for p in (ROOT / "conformance" / "gate").iterdir() if p.is_dir())


def _shop(tmp_path: Path, tests: list[dict]) -> tuple[Path, Path]:
    """A toy shop project with 2 scripts and a gate file with the given tests."""
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    shutil.copy(TOY_SPEC, root / "APP_SPEC.md")
    conf = {
        "entry": [sys.executable, str(TOY_SHOP)],
        "entries": {"shop": [sys.executable, str(TOY_SHOP)]},
        "models": [],
        "spec": ["APP_SPEC.md"],
    }
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    (root / "gates" / "scripts").mkdir(parents=True)
    for name, messages in (("refund", REFUND), ("price", PRICE)):
        text = "".join(json.dumps({"said": m}) + "\n" for m in messages)
        (root / "gates" / "scripts" / f"{name}.jsonl").write_text(text)
    path = root / "gates" / "gate.json"
    path.write_text(json.dumps({"v": 1, "tests": tests}))
    return root, path


def _run(root: Path, path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    argv = ["gate", "run", str(path), "--subject", SUBJECT, "--root", str(root), "--json"]
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


TWO = [
    {"name": "refund", "script": "scripts/refund.jsonl", "entry": "shop"},
    {"name": "price", "script": "scripts/price.jsonl", "limits": {"agent_error": 0}},
]


def test_a_gate_with_2_passing_tests_passes_and_names_the_subject(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO)
    code, out = _run(root, path, capsys)
    assert code == 0, out
    result = out["result"]
    assert result["verdict"] == "pass"
    assert result["subject"] == SUBJECT
    assert [t["name"] for t in result["tests"]] == ["refund", "price"]
    checks = [c["check"] for c in result["tests"][0]["checks"]]
    assert checks == [
        "missing_test",
        "evidence",
        "script",
        "entry",
        "verdict",
        "limits",
        "audit",
        "turns",
        "codex_hooks",
    ]
    folder = Path(out["gate"])
    assert folder.parent == root / ".nookku" / "gates"
    # The result is plain JSON, and the seal covers each file of the folder.
    assert json.loads((folder / gate.RESULT).read_text()) == result
    sealed = json.loads((folder / seal.SEAL).read_text())["files"]
    assert {gate.GATE_FILE, gate.RUN, gate.RESULT, "inputs/refund/script.jsonl"} <= set(sealed)
    assert main(["gate", "verify", "--root", str(root)]) == 0


def test_a_test_that_changes_a_later_script_does_not_change_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO)
    price = root / "gates" / "scripts" / "price.jsonl"
    declared = price.read_bytes()
    real = gate.bridge.run_script
    seen: list[bytes] = []

    def run_script(*args: object, **kwargs: object) -> object:
        seen.append(Path(str(args[1])).read_bytes())
        price.write_text(json.dumps({"said": "a changed message"}) + "\n")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gate.bridge, "run_script", run_script)
    code, out = _run(root, path, capsys)
    assert code == 0, out
    assert seen[1] == declared
    folder = (
        Path(out["gate"])
        if Path(out["gate"]).is_dir()
        else root / ".nookku" / "gates" / out["gate"]
    )
    assert (folder / "inputs" / "price" / "script.jsonl").read_bytes() == declared


def test_a_test_that_changes_the_config_fails_the_later_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO)
    config = root / ".nookku" / "config.json"
    real = gate.bridge.run_script
    calls: list[int] = []

    def run_script(*args: object, **kwargs: object) -> object:
        out = real(*args, **kwargs)  # type: ignore[arg-type]
        if not calls:
            # The first entry puts another start into the config for the next test.
            data = json.loads(config.read_text())
            data["entry"] = [*data["entry"], "--other"]
            config.write_text(json.dumps(data))
        calls.append(1)
        return out

    monkeypatch.setattr(gate.bridge, "run_script", run_script)
    code, out = _run(root, path, capsys)
    assert code == 1, out
    assert out["result"]["reasons"] == [{"test": "price", "check": "entry"}]


def _folder(root: Path, out: dict) -> Path:
    gate_id = Path(out["gate"])
    return gate_id if gate_id.is_dir() else root / ".nookku" / "gates" / out["gate"]


def test_a_test_that_changes_a_later_snapshot_stops_the_later_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO)
    declared = (root / "gates" / "scripts" / "price.jsonl").read_bytes()
    real = gate.bridge.run_script

    def run_script(*args: object, **kwargs: object) -> object:
        out = real(*args, **kwargs)  # type: ignore[arg-type]
        # The first entry writes another script into the snapshot of the next test.
        later = Path(str(args[1])).parent.parent / "price" / "script.jsonl"
        later.write_text(json.dumps({"said": "a changed message"}) + "\n")
        return out

    monkeypatch.setattr(gate.bridge, "run_script", run_script)
    code, out = _run(root, path, capsys)
    assert code == 1, out
    assert out["result"]["reasons"] == [{"test": "price", "check": "missing_test"}]
    folder = _folder(root, out)
    assert (folder / "inputs" / "price" / "script.jsonl").read_bytes() == declared
    assert gate.verify(folder)[1] is None


def test_a_snapshot_change_after_the_check_fails_the_script_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO)
    declared = (root / "gates" / "scripts" / "price.jsonl").read_bytes()
    real = gate.bridge.run_script

    def run_script(*args: object, **kwargs: object) -> object:
        snapshot = Path(str(args[1]))
        if snapshot.parent.name == "price":
            # A process of the first entry changes the snapshot after the gate compared it.
            snapshot.write_text(json.dumps({"said": "a changed message"}) + "\n")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gate.bridge, "run_script", run_script)
    code, out = _run(root, path, capsys)
    assert code == 1, out
    assert {"test": "price", "check": "script"} in out["result"]["reasons"]
    folder = _folder(root, out)
    assert (folder / "inputs" / "price" / "script.jsonl").read_bytes() == declared
    assert gate.verify(folder)[1] is None


def test_a_test_that_breaks_a_gate_limit_fails_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The toy shop gives the fallback reply 2 times, and the gate allows 0 repeated replies.
    tests = [{"name": "refund", "script": "scripts/refund.jsonl"}]
    root, path = _shop(tmp_path, tests)
    text = "".join(json.dumps({"said": m}) + "\n" for m in ["Hello", "Hello again"])
    (root / "gates" / "scripts" / "refund.jsonl").write_text(text)
    tests[0]["limits"] = {"repeated_reply": 0}
    path.write_text(json.dumps({"v": 1, "tests": tests}))
    code, out = _run(root, path, capsys)
    assert code == 1, out
    result = out["result"]
    assert result["verdict"] == "fail"
    assert result["reasons"] == [{"test": "refund", "check": "limits"}]
    limits = next(c for c in result["tests"][0]["checks"] if c["check"] == "limits")
    assert limits["text"] == "repeated_reply: 1, the limit is 0."
    assert main(["gate", "verify", "--root", str(root)]) == 1


def test_a_missing_script_fails_the_gate_with_missing_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tests = [*TWO, {"name": "returns", "script": "scripts/returns.jsonl"}]
    root, path = _shop(tmp_path, tests)
    code, out = _run(root, path, capsys)
    assert code == 1, out
    result = out["result"]
    assert result["reasons"] == [{"test": "returns", "check": "missing_test"}]
    assert [t["verdict"] for t in result["tests"]] == ["pass", "pass", "fail"]
    assert result["tests"][2]["test"] is None


def test_a_declared_answer_key_fails_until_a_check_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tests = [{"name": "refund", "script": "scripts/refund.jsonl", "answer_key": "key.json"}]
    root, path = _shop(tmp_path, tests)
    (path.parent / "key.json").write_text("{}")
    code, out = _run(root, path, capsys)
    assert code == 1, out
    assert out["result"]["reasons"] == [{"test": "refund", "check": "answer_key"}]
    # The run copies the key into the result folder, so the seal covers it.
    assert (Path(out["gate"]) / "inputs" / "refund" / "answer_key").read_text() == "{}"


def test_a_replay_of_the_same_agent_passes_and_a_changed_reply_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[:1])
    code, out = _run(root, path, capsys)
    assert code == 0, out
    base = out["result"]["tests"][0]["test"]
    # The seeded fault: a second entry of the toy shop changes the reply of turn 2.
    changed = root / "changed_agent.py"
    changed.write_text(TOY_SHOP.read_text().replace("Chennai and Pune.", "Chennai only."))
    conf = json.loads((root / ".nookku" / "config.json").read_text())
    conf["entries"]["changed"] = [sys.executable, str(changed)]
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    replay = {"base": base, "changed": 0}
    tests = [
        {"name": "same", "script": "scripts/refund.jsonl", "entry": "shop", "replay": replay},
        {"name": "fault", "script": "scripts/refund.jsonl", "entry": "changed", "replay": replay},
    ]
    path.write_text(json.dumps({"v": 1, "tests": tests}))
    code, out = _run(root, path, capsys)
    assert code == 1, out
    result = out["result"]
    assert result["reasons"] == [{"test": "fault", "check": "changed_turns"}]
    same, fault = result["tests"]
    assert same["verdict"] == "pass"
    assert same["replay"] == {
        "base": base,
        "test": same["test"],
        "most": 0,
        "changed": 0,
        "turns": [],
    }
    assert fault["replay"]["turns"] == [2]
    assert fault["checks"][-1]["text"] == "1 changed turns, the limit is 0. The turns: 2."
    # The ledger pins the base records before test 1, and the verify of the gate still passes.
    ledger = json.loads((Path(out["gate"]) / gate.RUN).read_text())
    assert set(ledger["tests"][0]["replay"]["files"]) == {"relay.jsonl", "tap.jsonl"}
    assert gate.verify(_folder(root, out))[1] is None


def test_a_base_that_changes_after_the_run_fails_missing_base(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[:1])
    _, out = _run(root, path, capsys)
    base = out["result"]["tests"][0]["test"]
    replay = {"base": base, "changed": 0}
    path.write_text(json.dumps({"v": 1, "tests": [{**TWO[0], "replay": replay}]}))
    code, out = _run(root, path, capsys)
    assert code == 0, out
    with (root / ".nookku" / "tests" / base / "tap.jsonl").open("a") as fh:
        fh.write("\n")
    folder = _folder(root, out)
    _, problem = gate.verify(folder)
    assert problem is not None and "missing_base" in problem


def test_a_replay_that_breaks_a_rule_is_refused() -> None:
    for replay, error in (
        ({"base": "t-1"}, 'only the keys "base" and "changed"'),
        ({"base": "../t", "changed": 0}, "the replay base must be a test id"),
        ({"base": "t-1", "changed": -1}, "the replay changed must be a whole number"),
    ):
        test = {"name": "a", "script": "s.jsonl", "replay": replay}
        with pytest.raises(gate.GateError, match=re.escape(error)):
            gate.parse(json.dumps({"v": 1, "tests": [test]}).encode())


def test_a_change_after_the_run_breaks_the_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO)
    code, out = _run(root, path, capsys)
    assert code == 0, out
    folder = Path(out["gate"])
    result = folder / gate.RESULT
    original = result.read_bytes()
    result.write_text(original.decode().replace('"fail"', '"pass"'))
    # A change of the folder and of both seals: the verify computes the result again.
    data = json.loads(original)
    data["tests"][0]["checks"][0]["text"] = "changed"
    result.write_text(json.dumps(data))
    seal.write(folder)
    report, why = gate.verify(folder)
    assert report is None
    assert why == f"{gate.RESULT} is not the result of the sealed files and the test folders."
    # The verify of a changed result.json is not a pass, so the exit code is 2.
    assert main(["gate", "verify", folder.name, "--root", str(root)]) == 2
    result.write_bytes(original)
    seal.write(folder)
    assert gate.verify(folder)[0] is not None
    # A rebuild of a test changes its seal, and the gate pins the old files.
    test = root / ".nookku" / "tests" / data["tests"][0]["test"]
    (test / "verdict.json").write_text((test / "verdict.json").read_text() + " ")
    seal.update(test, ["verdict.json"])
    report, why = gate.verify(folder)
    assert report is None
    assert "The new result has refund evidence: verdict.json in the copy of the test seal" in why
    capsys.readouterr()
    assert main(["gate", "verify", folder.name, "--root", str(root)]) == 2


def test_a_broken_seal_of_the_gate_cannot_be_used(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[:1])
    _run(root, path, capsys)
    folder = gate.find(root, None)
    assert folder is not None
    (folder / gate.RUN).write_text("{}")
    assert main(["gate", "verify", str(folder), "--root", str(root)]) == 2
    assert "cannot be used" in capsys.readouterr().out
    shutil.rmtree(seal.home() / "seals")
    (folder / gate.RUN).unlink()
    assert gate.verify(folder)[0] is None


ONE = b'{"v": 1, "tests": [%s]}'
PROOF = b'{"v": 1, "tests": [{"name": "a", "script": "s"}], "proofs": [%s]}'


def test_2_projects_in_the_same_second_get_different_gate_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both projects share NOOKKU_HOME, so the seal copies share one folder.
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    names = {gate._new_folder(tmp_path / p).name for p in ("a", "b", "a")}
    assert len(names) == 3
    assert all(name.startswith(gate.PREFIX) for name in names)


@pytest.mark.parametrize(
    "data, error",
    [
        (b"[]", 'the keys "v" and "tests"'),
        (b'{"v": 2, "tests": []}', "version must be 1"),
        (b'{"v": true, "tests": []}', "version must be 1"),
        (b'{"v": 1, "tests": []}', "1 to 200 tests"),
        (b'{"v": 1, "v": 1, "tests": []}', "occurs 2 times"),
        (b'{"v": 1, "tests": [{"name": "a"}]}', "has no script"),
        (b'{"v": 1, "tests": [{"name": "a/b", "script": "s"}]}', "form of a test id"),
        (b'{"v": 1, "tests": [{"name": "a", "script": "/s"}]}', "relative"),
        (b'{"v": 1, "tests": [{"name": "a", "script": "s", "proofs": []}]}', "proofs"),
        (ONE % b'{"name": "a", "script": "s"}, {"name": "a", "script": "s"}', "earlier"),
        (ONE % b'{"name": "a", "script": "s", "limits": {"tone": 0}}', "not a check"),
        (ONE % b'{"name": "a", "script": "s", "limits": {"agent_error": -1}}', "whole"),
        (b"\xff", "not UTF-8"),
        (b'{"v": 1, "tests": [], "more": 1}', 'optional "proofs"'),
        (PROOF % b'{"path": "a"}', '"max_age"'),
        (PROOF % b'{"path": "/a", "max_age": 1}', "relative"),
        (PROOF % b'{"path": "a", "max_age": 0}', "from 1"),
        (PROOF % b'{"path": "a", "max_age": true}', "from 1"),
        (PROOF % b'{"path": "a", "max_age": 1}, {"path": "a", "max_age": 1}', "earlier"),
        (PROOF % b'{"path": "a", "max_age": 1, "bound": {"field": []}}', '"field" and "most"'),
        (PROOF % b'{"path": "a", "max_age": 1, "bound": {"field": [], "most": 1}}', "1 to 32"),
        (PROOF % b'{"path": "a", "max_age": 1, "bound": {"field": [1], "most": 1}}', "keys"),
        (PROOF % b'{"path": "a", "max_age": 1, "bound": {"field": ["e"], "most": "1"}}', "number"),
        (PROOF % b'{"path": "a", "max_age": 1, "bound": {"field": ["e"], "most": NaN}}', "number"),
    ],
)
def test_a_gate_file_that_breaks_a_rule_is_refused(data: bytes, error: str) -> None:
    with pytest.raises(gate.GateError, match=error):
        gate.parse(data)


def test_a_bad_gate_file_or_subject_runs_no_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO)
    for subject in ("", "a\nb", "x" * 513):
        argv = ["gate", "run", str(path), "--subject", subject, "--root", str(root)]
        assert main(argv) == 2
    path.write_text("{}")
    assert main(["gate", "run", str(path), "--subject", SUBJECT, "--root", str(root)]) == 2
    assert not (root / ".nookku" / "gates").exists()
    assert not (root / ".nookku" / "tests").exists()
    capsys.readouterr()


@pytest.mark.parametrize(
    "command, denied",
    [
        ("nookku gate run gate.json --subject x", True),
        ("nookku gate --root . run gate.json --subject x", True),
        ("nookku gate verify", False),
        ("nookku gate verify gate-20261112-101010 --json", False),
    ],
)
def test_the_relay_denies_a_gate_run_of_the_model(command: str, denied: bool) -> None:
    assert (commands.drive(command) is not None) == denied


def _case_test(folder: Path, given: dict) -> bytes:
    """A sealed test folder with the records of a case, and the bytes of its script."""
    folder.mkdir(parents=True)
    during = given.get("during") or [None] * len(given["messages"])
    rows = [
        {"said": m} if after is None else {"said": m, "during": after}
        for m, after in zip(given["messages"], during, strict=True)
    ]
    body = "".join(json.dumps(r) + "\n" for r in rows).encode()
    manifest = {
        "test": folder.name,
        "entry": given["entry"],
        "entry_name": given["entry_name"],
        "policy": {},
        "config_sha256": {},
        "spec": [],
        "script": {"source": None, "file": "script.jsonl", "sha256": script.sha256(body)},
        "verdict": {"limits": given["limits"], "unread": []},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    findings = {"counts": given["counts"]}
    if "second_messages" in given:
        findings["second_messages"] = given["second_messages"]
    (folder / "findings.json").write_text(json.dumps(findings))
    verdict.build(folder)
    (folder / "audit.json").write_text(json.dumps(given["audit"]))
    _records(folder, given["messages"], given["replies"], given.get("tap"))
    (folder / "script.jsonl").write_bytes(body)
    seal.write(folder)
    return body


def _records(folder: Path, messages: list, oks: list, tap: list | None) -> None:
    """The relay record of a case test and, if the case gives the reply of each turn, the tap
    record."""
    relay = record.Writer(folder / "relay.jsonl")
    for m, ok in zip(messages, oks, strict=True):
        relay.append({"type": "turn", "harness": "script", "said": m, "shown": "", "ok": ok})
    if tap is None:
        return
    exchanges = record.Writer(folder / "tap.jsonl")
    for m, reply in zip(messages, tap, strict=True):
        exchanges.append({"type": "exchange", "input": m, "status": 200, "reply": reply})


def _case_base(folder: Path, given: dict) -> None:
    """A sealed base test of a replay check, with only its relay and tap records."""
    folder.mkdir(parents=True)
    _records(folder, given["messages"], [True] * len(given["messages"]), given["tap"])
    seal.write(folder)


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_each_case_gives_its_result(case: Path, tmp_path: Path) -> None:
    given = json.loads((case / "case.json").read_text(encoding="utf-8"))
    data = (case / "gate.json").read_bytes()
    tests_dir = tmp_path / "tests"
    for base, records in given.get("bases", {}).items():
        _case_base(tests_dir / base, records)
    inputs, rows = {}, []
    for test in gate.parse(data):
        name = test["name"]
        pin = None if test["replay"] is None else gate.base_pin(tests_dir, test["replay"]["base"])
        if name not in given["tests"]:
            rows.append(gate.ledger_row(name, None, given["errors"][name], None, pin))
            continue
        folder = tests_dir / f"t-{name}"
        inputs[name] = {"script.jsonl": _case_test(folder, given["tests"][name])}
        if "persona" in given["tests"][name]:
            inputs[name]["persona"] = given["tests"][name]["persona"].encode("utf-8")
        pinned = {"entry": given["tests"][name]["entry"], "policy": {}, "spec": []}
        pinned["config_sha256"] = {}
        rows.append(gate.ledger_row(name, folder, None, pinned, pin))
    proof_rows, copies = [], {}
    for n, proof in enumerate(gate.parse_proofs(data), 1):
        found = given["proofs"][proof["path"]]
        body = None if found["text"] is None else found["text"].encode("utf-8")
        row = gate.proof_row(
            proof["path"], body, found["modified"], found["checked"], found["error"]
        )
        proof_rows.append(row)
        if body is not None:
            copies[n] = body
    ledger = {
        "v": 1,
        "gate": "gate-case",
        "subject": given["subject"],
        "tests_dir": str(tests_dir),
        "tests": rows,
        "proofs": proof_rows,
    }
    expect = json.loads((case / "expect_result.json").read_text(encoding="utf-8"))
    expect["gate_sha256"] = seal.sha256_of(data)
    evidence = gate.read_evidence(ledger)
    assert gate.compute("gate-case", data, inputs, ledger, evidence, copies) == expect


def test_the_cases_cover_a_pass_a_fail_and_a_missing_test() -> None:
    assert {c.name for c in CASES} >= {"pass", "fail", "missing_test"}
    proofs = {"proof_pass", "proof_missing", "proof_stale", "proof_above_limit"}
    assert {c.name for c in CASES} >= proofs


def test_a_turn_with_a_unicode_line_separator_is_one_turn() -> None:
    text = "Hello\u2028world \u2029 and \u0085"
    data = (
        json.dumps({"type": "turn", "said": text, "ok": True}, ensure_ascii=False) + "\n"
    ).encode()
    assert gate._turns(data) == [(text, True)]


MEASURE = "reports/measure.json"


def _proofs(path: Path, proofs: list[dict]) -> None:
    """Add proof files to the gate file of _shop."""
    data = json.loads(path.read_text())
    path.write_text(json.dumps({**data, "proofs": proofs}))


def _measure(root: Path, name: str, bound: float, age: int = 0) -> dict:
    """A proof file in the gates folder with the field error_bound, and its declaration."""
    file = root / "gates" / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"run": {"error_bound": bound}}))
    if age:
        old = time.time() - age
        os.utime(file, (old, old))
    return {
        "path": name,
        "max_age": 86400,
        "bound": {"field": ["run", "error_bound"], "most": 0.05},
    }


def test_a_fresh_proof_file_in_its_bound_passes_and_the_seal_covers_its_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[1:])
    _proofs(path, [_measure(root, MEASURE, 0.03)])
    code, out = _run(root, path, capsys)
    assert code == 0, out
    body = (root / "gates" / MEASURE).read_bytes()
    [proof] = out["result"]["proofs"]
    assert proof["path"] == MEASURE and proof["value"] == 0.03
    assert (proof["verdict"], proof["failures"]) == ("pass", [])
    assert proof["sha256"] == seal.sha256_of(body) and 0 <= proof["age"] <= 86400
    folder = Path(out["gate"])
    assert (folder / gate.PROOFS / "1").read_bytes() == body
    assert "proofs/1" in json.loads((folder / seal.SEAL).read_text())["files"]
    [row] = json.loads((folder / gate.RUN).read_text())["proofs"]
    assert row["sha256"] == proof["sha256"] and row["error"] is None
    assert row["checked"] - row["modified"] == proof["age"]
    assert main(["gate", "verify", folder.name, "--root", str(root)]) == 0
    assert f"Proof file {MEASURE}: pass." in capsys.readouterr().out


def test_a_missing_stale_or_above_limit_proof_file_fails_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[1:])
    declared = [
        {"path": "reports/none.json", "max_age": 86400},
        _measure(root, "reports/old.json", 0.03, age=3 * 86400),
        _measure(root, "reports/wide.json", 0.08),
        {**_measure(root, "reports/text.json", 0.03), "bound": {"field": ["x"], "most": 1}},
    ]
    _proofs(path, declared)
    code, out = _run(root, path, capsys)
    assert code == 1, out
    result = out["result"]
    assert result["verdict"] == "fail"
    assert all(t["verdict"] == "pass" for t in result["tests"])
    assert result["reasons"] == [
        {"proof": "reports/none.json", "check": "missing"},
        {"proof": "reports/old.json", "check": "stale"},
        {"proof": "reports/wide.json", "check": "above_limit"},
        {"proof": "reports/text.json", "check": "above_limit"},
    ]
    none, old, wide, text = result["proofs"]
    assert none["sha256"] is None and none["failures"][0]["text"].startswith("The file is missing")
    assert old["failures"][0]["text"].endswith("seconds old, the limit is 86400.")
    assert wide["failures"] == [
        {"reason": "above_limit", "text": "The value is 0.08, the limit is 0.05."}
    ]
    assert text["failures"][0]["text"] == 'The file has no field ["x"].'
    assert main(["gate", "verify", "--root", str(root)]) == 1


def test_a_change_of_a_proof_copy_breaks_the_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[1:])
    _proofs(path, [_measure(root, MEASURE, 0.03)])
    _, out = _run(root, path, capsys)
    folder = Path(out["gate"])
    (folder / gate.PROOFS / "1").write_text(json.dumps({"run": {"error_bound": 0.01}}))
    seal.write(folder)
    report, why = gate.verify(folder)
    assert report is None
    assert why is not None and why.startswith(f"{gate.RESULT} is not the result")
    # The copy of a later read of the project file does not count: the run pinned its bytes.
    (folder / gate.PROOFS / "1").unlink()
    seal.write(folder)
    assert gate.verify(folder)[0] is None


def test_a_proof_file_that_is_a_pipe_is_missing_and_the_read_does_not_wait(
    tmp_path: Path,
) -> None:
    pipe = tmp_path / "measure.json"
    os.mkfifo(pipe)
    assert gate.read_proof(pipe) == (None, None, "the path is not a regular file")
    assert gate.read_proof(tmp_path / "none")[2].startswith("cannot read the file")
    assert gate.read_proof(tmp_path)[2] is not None


PERSONA = {"persona": "A customer with a return of a damaged mug.", "goal": "Get a refund."}


def _persona(path: Path, name: str, value: object) -> str:
    """Write a persona file next to the gate file and give its path in the gate file."""
    (path.parent / "personas").mkdir(exist_ok=True)
    body = value if isinstance(value, str) else json.dumps(value)
    (path.parent / "personas" / f"{name}.json").write_text(body)
    return f"personas/{name}.json"


def test_a_persona_set_names_the_persona_of_each_test_in_the_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, [])
    tests = [
        {**TWO[0], "persona": _persona(path, "refund", {**PERSONA, "turns": 2})},
        {
            **TWO[1],
            "persona": _persona(
                path, "price", {"persona": "A new customer.", "goal": "Get the price.", "turns": 1}
            ),
        },
    ]
    path.write_text(json.dumps({"v": 1, "tests": tests}))
    code, out = _run(root, path, capsys)
    assert code == 0, out
    first = out["result"]["tests"][0]["persona"]
    body = (path.parent / "personas" / "refund.json").read_bytes()
    assert first == {**PERSONA, "sha256": seal.sha256_of(body)}
    assert out["result"]["tests"][1]["persona"]["persona"] == "A new customer."
    folder = Path(out["gate"])
    assert (folder / "inputs" / "refund" / "persona").read_bytes() == body
    assert gate.verify(folder) == (out["result"], None)
    lines = gate.summary(out["result"])
    assert lines[0].startswith("refund (") and ", persona: A customer with a return" in lines[0]


def test_a_test_with_no_persona_has_no_persona_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[1:])
    _, out = _run(root, path, capsys)
    assert "persona" not in out["result"]["tests"][0]
    assert "persona" not in gate.summary(out["result"])[0]


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        json.dumps({"persona": "A customer.", "goal": "Get a refund."}),
        json.dumps({**PERSONA, "turns": 2, "name": "extra"}),
        json.dumps({**PERSONA, "persona": " ", "turns": 2}),
    ],
)
def test_a_persona_file_that_breaks_the_rule_stops_its_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str
) -> None:
    root, path = _shop(tmp_path, [])
    tests = [{**TWO[1], "persona": _persona(path, "price", body)}]
    path.write_text(json.dumps({"v": 1, "tests": tests}))
    code, out = _run(root, path, capsys)
    assert code == 1, out
    result = out["result"]
    assert result["reasons"] == [{"test": "price", "check": "missing_test"}]
    assert result["tests"][0]["test"] is None
    # The copy of a file that breaks the rule is not in inputs/, so the result has no persona.
    assert result["tests"][0]["persona"] is None
    row = json.loads((Path(out["gate"]) / gate.RUN).read_text())["tests"][0]
    assert row["error"].startswith("persona personas/price.json: ")


def test_an_older_result_with_no_persona_still_verifies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, [])
    tests = [{**TWO[1], "persona": _persona(path, "price", {**PERSONA, "turns": 1})}]
    path.write_text(json.dumps({"v": 1, "tests": tests}))
    _, out = _run(root, path, capsys)
    folder = Path(out["gate"])
    # Nookku 0.5.9 and older wrote no key persona in result.json.
    older = json.loads((folder / gate.RESULT).read_text())
    del older["tests"][0]["persona"]
    (folder / gate.RESULT).write_text(json.dumps(older, indent=1) + "\n")
    seal.write(folder)
    assert gate.verify(folder) == (older, None)
    # A persona that is not the persona of the copy is not an older result.
    older["tests"][0]["persona"] = {**PERSONA, "sha256": "0" * 64}
    (folder / gate.RESULT).write_text(json.dumps(older, indent=1) + "\n")
    seal.write(folder)
    report, problem = gate.verify(folder)
    assert report is None and problem and problem.startswith("result.json is not the result")


def test_a_gate_with_no_proof_files_keeps_the_result_format_of_0_5_7(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = _shop(tmp_path, TWO[1:])
    code, out = _run(root, path, capsys)
    assert code == 0, out
    folder = Path(out["gate"])
    # A gate folder of Nookku 0.5.7 has no key "proofs" in run.json and in result.json.
    assert "proofs" not in json.loads((folder / gate.RUN).read_text())
    assert "proofs" not in json.loads((folder / gate.RESULT).read_text())
    assert not (folder / gate.PROOFS).exists()
    assert gate.verify(folder)[0] is not None
    # An empty list is a declaration: the result then has an empty list.
    _proofs(path, [])
    _, out = _run(root, path, capsys)
    assert out["result"]["proofs"] == []


def test_a_very_large_integer_gives_a_compare_and_not_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    big = 10**400
    assert gate._field(json.dumps({"e": big}).encode(), ["e"]) == (big, None)
    root, path = _shop(tmp_path, TWO[1:])
    file = root / "gates" / MEASURE
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps({"e": big}))
    declared = [
        {"path": MEASURE, "max_age": 86400, "bound": {"field": ["e"], "most": 0.05}},
        {"path": MEASURE + "x", "max_age": 86400, "bound": {"field": ["e"], "most": big}},
    ]
    shutil.copy(file, root / "gates" / (MEASURE + "x"))
    _proofs(path, declared)
    code, out = _run(root, path, capsys)
    assert code == 1, out
    above, same = out["result"]["proofs"]
    assert above["value"] == big and above["failures"][0]["reason"] == "above_limit"
    assert (same["verdict"], same["value"]) == ("pass", big)
    assert main(["gate", "verify", "--root", str(root)]) == 1


TIMED = b'{"said": "a"}\n{"said": "b", "during": 0.5}\n{"said": "c"}\n{"said": "d", "during": 1}\n'


@pytest.mark.parametrize(
    ("script_bytes", "findings", "late"),
    [
        (TIMED, {"second_messages": [{"turn": 2}, {"turn": 4}]}, []),
        (TIMED, {"second_messages": [{"turn": 2}, "x", {"turn": "4"}]}, [4]),
        (TIMED, {"second_messages": "all"}, [2, 4]),
        (TIMED, {}, [2, 4]),
        (TIMED, None, [2, 4]),
        (TIMED, [], [2, 4]),
        # A script with no `during` has no check.
        (b'{"said": "a"}\n{"said": "b"}\n', {}, None),
        # The check `turns` fails for a script that is not valid.
        (b"not a script", {}, None),
        (None, {}, None),
    ],
)
def test_a_message_with_during_needs_its_row_in_the_findings(
    script_bytes: bytes | None, findings: object, late: list[int] | None
) -> None:
    data = None if findings is None else json.dumps(findings).encode()
    assert gate._late_messages(script_bytes, data) == late

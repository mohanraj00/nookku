from __future__ import annotations

import json
import re
import shutil
import sys
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
        (b"[]", 'only the keys "v" and "tests"'),
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
    body = "".join(json.dumps({"said": m}) + "\n" for m in given["messages"]).encode()
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
    (folder / "findings.json").write_text(json.dumps({"counts": given["counts"]}))
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
        pinned = {"entry": given["tests"][name]["entry"], "policy": {}, "spec": []}
        pinned["config_sha256"] = {}
        rows.append(gate.ledger_row(name, folder, None, pinned, pin))
    ledger = {
        "v": 1,
        "gate": "gate-case",
        "subject": given["subject"],
        "tests_dir": str(tests_dir),
        "tests": rows,
    }
    expect = json.loads((case / "expect_result.json").read_text(encoding="utf-8"))
    expect["gate_sha256"] = seal.sha256_of(data)
    assert gate.compute("gate-case", data, inputs, ledger, gate.read_evidence(ledger)) == expect


def test_the_cases_cover_a_pass_a_fail_and_a_missing_test() -> None:
    assert {c.name for c in CASES} >= {"pass", "fail", "missing_test"}


def test_a_turn_with_a_unicode_line_separator_is_one_turn() -> None:
    text = "Hello\u2028world \u2029 and \u0085"
    data = (
        json.dumps({"type": "turn", "said": text, "ok": True}, ensure_ascii=False) + "\n"
    ).encode()
    assert gate._turns(data) == [(text, True)]

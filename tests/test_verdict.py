"""The verdict of a test and its exit code for CI (#514, SPEC.md section 7.14)."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from nookku import bridge, seal, trace, verdict
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
CASES = sorted(p for p in (ROOT / "conformance" / "verdict").iterdir() if p.is_dir())
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
TOY_SPEC = ROOT / "examples" / "toy-shop-full" / "APP_SPEC.md"
# 4 messages with 4 different replies of the toy shop agent: refund, ship, price and the
# fallback reply. Each reply is different from the reply before it.
SCRIPT = [
    "What is your refund policy?",
    "Do you ship to Pune?",
    "What is the price of the blue mug?",
    "Is the teapot in stock?",
]
# A planted defect: for each second message, the agent sends its last reply again. The 4
# messages then give 2 runs of the same reply, and the toy shop allows 1 (APP_SPEC.md).
REPEAT_DEFECT = f"""
import json, runpy, sys
answer = runpy.run_path({str(TOY_SHOP)!r})["answer"]
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    history = request["history"]
    reply = history[-1]["reply"] if len(history) % 2 else answer(request["message"])
    out = {{"v": 1, "id": request["id"], "reply": reply}}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_each_case_gives_its_verdict(case: Path, tmp_path: Path) -> None:
    given = json.loads((case / "case.json").read_text(encoding="utf-8"))
    folder = tmp_path / case.name
    folder.mkdir()
    manifest = given.get("manifest")
    if manifest is None:
        files = [(path, text) for path, text in given["files"]]
        manifest = {"test": case.name, "verdict": verdict.read(files)}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if given["counts"] is not None:
        report = {"counts": given["counts"]}
        if "answers" in given:
            report["answers"] = given["answers"]
        (folder / "findings.json").write_text(json.dumps(report))
    if "adjudications" in given:
        (folder / verdict.ADJUDICATIONS).write_text(given["adjudications"], encoding="utf-8")
    expect = json.loads((case / "expect_verdict.json").read_text(encoding="utf-8"))
    assert verdict.build(folder) == expect
    assert json.loads((folder / verdict.FILE).read_text(encoding="utf-8")) == expect


def test_the_cases_cover_each_finding_class() -> None:
    # A new check of the trace needs a new row in each expected verdict.
    for case in CASES:
        expect = json.loads((case / "expect_verdict.json").read_text(encoding="utf-8"))
        assert [c["check"] for c in expect["classes"]] == list(trace.CHECKS), case.name


@pytest.mark.parametrize(
    "key",
    [
        None,
        [],
        {"limits": {"agent_error": -1}, "unread": []},
        {"limits": {"agent_error": True}, "unread": []},
        {"limits": {"no_such_check": 0}, "unread": []},
        {"limits": {}, "unread": [{"file": "APP_SPEC.md", "problem": "x"}]},
        {"limits": {}},
    ],
)
def test_a_manifest_key_that_is_not_valid_fails_the_verdict(tmp_path: Path, key: object) -> None:
    counts = dict.fromkeys(trace.CHECKS, 0)
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t", "verdict": key}))
    (tmp_path / "findings.json").write_text(json.dumps({"counts": counts}))
    report = verdict.build(tmp_path)
    assert report["verdict"] == "fail"
    assert report["problems"] == ["The key verdict of manifest.json is not valid."]


def test_a_class_with_a_limit_and_no_valid_count_fails(tmp_path: Path) -> None:
    limits = {"limits": {"agent_error": 0, "tool_error": 0}, "unread": []}
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t", "verdict": limits}))
    counts = {**dict.fromkeys(trace.CHECKS, 0), "agent_error": "0", "span_error": 1.5}
    del counts["tool_error"]
    (tmp_path / "findings.json").write_text(json.dumps({"counts": counts}))
    report = verdict.build(tmp_path)
    failed = [c["check"] for c in report["classes"] if c["verdict"] == "fail"]
    assert failed == ["agent_error", "tool_error"]
    # A class with no limit and no valid count passes: the verdict does not judge it.
    span = next(c for c in report["classes"] if c["check"] == "span_error")
    assert span == {"check": "span_error", "count": None, "most": None, "verdict": "pass"}
    assert report["verdict"] == "fail" and report["problems"] == []


def test_the_summary_names_each_reason_on_one_line() -> None:
    report = {
        "verdict": "fail",
        "limits": {"agent_error": 0},
        "classes": [
            {"check": "agent_error", "count": 2, "most": 0, "verdict": "fail"},
            {"check": "tool_error", "count": None, "most": 1, "verdict": "fail"},
            {"check": "span_error", "count": 9, "most": None, "verdict": "pass"},
        ],
        "problems": ['APP_SPEC.md line 7: "a\\nb" is not a finding class of the trace.'],
    }
    assert verdict.summary(report) == (
        "Verdict: fail. agent_error: 2, the limit is 0; tool_error: no valid count, the limit "
        'is 1; APP_SPEC.md line 7: "a\\nb" is not a finding class of the trace.'
    )
    assert verdict.summary({**report, "verdict": "pass"}) == "Verdict: pass (1 limit)."
    assert verdict.summary(None) == "Verdict: fail. The test folder has no valid verdict.json."
    # A test with adjudications shows the line, also with no limit, with the counts (#548).
    passed = {"verdict": "pass", "limits": {}, "classes": [], "problems": []}
    assert not verdict.shown(passed, False)
    tally = {
        "mismatches": 3,
        "open": 0,
        "agent_wrong": 1,
        "key_wrong": 1,
        "both_acceptable": 1,
        "counted": 1,
    }
    assert verdict.shown({**passed, "adjudications": tally}, False)
    assert verdict.summary({**passed, "adjudications": tally}) == (
        "Verdict: pass (0 limits). Adjudications: 3 answer_key_mismatch before, 1 after "
        "(0 open, 1 agent_wrong, 1 key_wrong, 1 both_acceptable)."
    )
    failed = {
        "verdict": "fail",
        "limits": {"answer_key_mismatch": 0},
        "classes": [{"check": "answer_key_mismatch", "count": 3, "most": 0, "verdict": "fail"}],
        "problems": [],
        "adjudications": {**tally, "mismatches": None, "open": None, "counted": None},
    }
    assert verdict.summary(failed) == (
        "Verdict: fail. answer_key_mismatch: no valid count, the limit is 0. Adjudications: "
        "no valid count answer_key_mismatch before, no valid count after (no valid count open, "
        "1 agent_wrong, 1 key_wrong, 1 both_acceptable)."
    )


def _shop(tmp_path: Path, entry: list[str]) -> Path:
    """A toy shop project with the app spec of the full toy shop and its Verdict table."""
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    shutil.copy(TOY_SPEC, root / "APP_SPEC.md")
    conf = {"entry": entry, "models": [], "spec": ["APP_SPEC.md"]}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    (root / "script.jsonl").write_text("".join(json.dumps({"said": s}) + "\n" for s in SCRIPT))
    return root


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    script = str(root / "script.jsonl")
    code = main(["run", "--script", script, "--root", str(root), "--verdict", "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_a_scripted_toy_shop_test_passes_its_limits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path, [sys.executable, str(TOY_SHOP)])
    code, out = _run(root, capsys)
    assert code == 0, out
    assert "Verdict: pass (2 limits)." in out["report"]
    folder = bridge.latest_test(root)
    assert folder is not None
    found = json.loads((folder / verdict.FILE).read_text())
    assert found["verdict"] == "pass"
    assert found["limits"] == {"agent_error": 0, "repeated_reply": 1}
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["verdict"] == {"limits": found["limits"], "unread": []}
    # The seal covers verdict.json.
    assert verdict.FILE in json.loads((folder / seal.SEAL).read_text())["files"]
    assert seal.verify(folder)["intact"]


def test_a_planted_defect_that_breaks_a_limit_fails_the_scripted_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    defect = tmp_path / "defect.py"
    defect.write_text(REPEAT_DEFECT)
    root = _shop(tmp_path, [sys.executable, str(defect)])
    code, out = _run(root, capsys)
    assert code == 1, out
    # The audit is clean: only the verdict fails the run.
    assert "Audit: exit 0" in out["report"]
    assert "Verdict: fail. repeated_reply: 2, the limit is 1." in out["report"]
    assert "FAIL: The verdict is fail. Read verdict.json in the test folder." in out["report"]
    folder = bridge.latest_test(root)
    assert folder is not None
    found = json.loads((folder / verdict.FILE).read_text())
    row = next(c for c in found["classes"] if c["check"] == "repeated_reply")
    assert row == {"check": "repeated_reply", "count": 2, "most": 1, "verdict": "fail"}
    # Without --verdict, the run gives the verdict and keeps the exit code of the audit.
    script = str(root / "script.jsonl")
    assert main(["run", "--script", script, "--root", str(root)]) == 0
    assert "Verdict: fail." in capsys.readouterr().out
    # nookku trace --verdict rebuilds the verdict from the sealed records and exits with 1.
    assert main(["trace", str(folder), "--root", str(root), "--verdict"]) == 1
    text = capsys.readouterr().out
    assert "Verdict: fail. repeated_reply: 2, the limit is 1." in text
    assert main(["trace", str(folder), "--root", str(root)]) == 0
    assert seal.verify(folder)["intact"]


# A planted bad citation: the toy shop agent gives its reply as JSON, with a source locator that
# the agent did not read. The test has no model and no tool result, so no locator resolves.
CITATION_DEFECT = f"""
import json, runpy, sys
answer = runpy.run_path({str(TOY_SHOP)!r})["answer"]
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    text = json.dumps({{"reply": answer(request["message"]), "sources": ["policy/shipping#2"]}})
    out = {{"v": 1, "id": request["id"], "reply": text}}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""
CITATION_SPEC = """# Toy shop

## Verdict

| Finding | Most |
|---|---|
| `citation_not_read` | 0 |
"""


def test_a_planted_bad_citation_fails_the_scripted_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    defect = tmp_path / "defect.py"
    defect.write_text(CITATION_DEFECT)
    root = _shop(tmp_path, [sys.executable, str(defect)])
    (root / "APP_SPEC.md").write_text(CITATION_SPEC)
    conf_path = root / ".nookku" / "config.json"
    conf = json.loads(conf_path.read_text())
    conf_path.write_text(json.dumps({**conf, "citation_field": "sources"}))
    code, out = _run(root, capsys)
    assert code == 1, out
    assert "Audit: exit 0" in out["report"]
    assert "Verdict: fail. citation_not_read: 4, the limit is 0." in out["report"]
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["trace"]["citation_field"] == "sources"
    findings = json.loads((folder / "findings.json").read_text())["findings"]
    cited = [f for f in findings if f["check"] == "citation_not_read"]
    assert [f["turn"] for f in cited] == [1, 2, 3, 4]
    assert cited[0]["detail"] == '"policy/shipping#2": no tool result of this turn contains it'


# A seeded fault of the answer key (SPEC.md section 7.17): the agent gives the count 12 for
# each message, and the key gives 3 for the teapot. The key also has a question that the
# script does not ask.
COUNT_AGENT = f"""
import json, runpy, sys
answer = runpy.run_path({str(TOY_SHOP)!r})["answer"]
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    text = json.dumps({{"reply": answer(request["message"]), "count": 12}})
    out = {{"v": 1, "id": request["id"], "reply": text}}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""
KEY_SPEC = """# Toy shop

## Answer key

| File | Field | Match | Tolerance |
|---|---|---|---|
| `keys/stock.json` | `count` | number | 0.5 |

## Verdict

| Finding | Most |
|---|---|
| `answer_key_mismatch` | 0 |
"""
STOCK_KEY = {
    "source": "the stock list of the toy shop",
    "version": "1",
    "answers": [
        {"question": "What is the price of the blue mug?", "answer": 12.4},
        {"question": "Is the teapot in stock?", "answer": 3},
        {"question": "Do you sell spoons?", "answer": 0},
    ],
}


def test_a_seeded_answer_key_mismatch_fails_the_scripted_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = tmp_path / "count.py"
    agent.write_text(COUNT_AGENT)
    root = _shop(tmp_path, [sys.executable, str(agent)])
    (root / "APP_SPEC.md").write_text(KEY_SPEC)
    (root / "keys").mkdir()
    key = json.dumps(STOCK_KEY).encode()
    (root / "keys" / "stock.json").write_bytes(key)
    code, out = _run(root, capsys)
    assert code == 1, out
    assert "Audit: exit 0" in out["report"]
    assert "Verdict: fail. answer_key_mismatch: 1, the limit is 0." in out["report"]
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["answer_key"] == {
        "file": "keys/stock.json",
        "sha256": hashlib.sha256(key).hexdigest(),
        "source": "the stock list of the toy shop",
        "version": "1",
        "field": "count",
        "match": "number",
        "tolerance": "0.5",
    }
    assert (folder / "answer_key.json").read_bytes() == key
    seal = json.loads((folder / "seal.json").read_text())
    assert seal["files"]["answer_key.json"] == hashlib.sha256(key).hexdigest()
    findings = json.loads((folder / "findings.json").read_text())["findings"]
    keyed = [f for f in findings if f["check"].startswith("answer_key")]
    assert keyed == [
        {
            "check": "answer_key_mismatch",
            "turn": 4,
            "detail": '"Is the teapot in stock?": the key gives 3, and the reply gives 12',
        },
        {
            "check": "answer_key_missing",
            "turn": None,
            "detail": '"Do you sell spoons?": no turn asked it',
        },
    ]


# An adjudication of a person (SPEC.md section 7.17, #548): the mismatch of the seeded fault
# stays in findings.json, and a `key_wrong` outcome takes it out of the count of the limit.
def _adjudicate(root: Path, folder: Path, *words: str) -> int:
    base = ["adjudicate", folder.name, "--root", str(root), "--author", "Asha"]
    return main([*base, *words])


def test_an_adjudication_changes_the_count_of_the_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = tmp_path / "count.py"
    agent.write_text(COUNT_AGENT)
    root = _shop(tmp_path, [sys.executable, str(agent)])
    (root / "APP_SPEC.md").write_text(KEY_SPEC)
    (root / "keys").mkdir()
    (root / "keys" / "stock.json").write_bytes(json.dumps(STOCK_KEY).encode())
    assert _run(root, capsys)[0] == 1
    folder = bridge.latest_test(root)
    assert folder is not None
    report = json.loads((folder / "findings.json").read_text())
    assert [(a["turn"], a["result"]) for a in report["answers"]] == [(3, "match"), (4, "mismatch")]
    assert "adjudications" not in json.loads((folder / verdict.FILE).read_text())
    findings = (folder / "findings.json").read_bytes()
    file = folder / verdict.ADJUDICATIONS

    # A command that names no mismatch, or has a value that is not valid, writes no row.
    for words in (
        ("--turn", "3", "--outcome", "key_wrong", "--reason", "The key is old."),
        ("--turn", "9", "--outcome", "key_wrong", "--reason", "The key is old."),
        ("--turn", "4", "--outcome", "accepted", "--reason", "The key is old."),
        ("--turn", "4", "--outcome", "key_wrong", "--reason", " "),
    ):
        assert _adjudicate(root, folder, *words) == 2
        assert "no adjudication was written" in capsys.readouterr().err
        assert not file.exists()

    words = ("--turn", "4", "--outcome", "key_wrong", "--reason", "The shop has 12 teapots.")
    assert _adjudicate(root, folder, *words) == 0
    out = capsys.readouterr().out
    assert f"Test {folder.name}, turn 4: key_wrong, by Asha." in out
    assert (
        "Verdict: pass (1 limit). Adjudications: 1 answer_key_mismatch before, 0 after "
        "(0 open, 0 agent_wrong, 1 key_wrong, 0 both_acceptable)." in out
    )
    (row,) = [json.loads(line) for line in file.read_text().splitlines()]
    assert {k: v for k, v in row.items() if k != "ts"} == {
        "v": 1,
        "turn": 4,
        "question": "Is the teapot in stock?",
        "outcome": "key_wrong",
        "reason": "The shop has 12 teapots.",
        "author": "Asha",
    }
    # findings.json keeps the mismatch, and the seal covers the new row and the new verdict.
    assert (folder / "findings.json").read_bytes() == findings
    assert seal.verify(folder)["intact"]
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "pass"
    assert found["classes"][4] == {
        "check": "answer_key_mismatch",
        "count": 1,
        "most": 0,
        "verdict": "pass",
    }
    assert main(["trace", str(folder), "--root", str(root), "--verdict"]) == 0
    assert "Adjudications: 1 answer_key_mismatch before, 0 after" in capsys.readouterr().out
    assert seal.verify(folder)["intact"]

    # A later row for the same turn is the current decision of the person.
    words = ("--turn", "4", "--outcome", "agent_wrong", "--reason", "The shelf has 3 teapots.")
    assert _adjudicate(root, folder, *words) == 0
    out = capsys.readouterr().out
    assert "Verdict: fail. answer_key_mismatch: 1, the limit is 0. Adjudications: 1 " in out
    assert "1 after (0 open, 1 agent_wrong, 0 key_wrong, 0 both_acceptable)." in out
    assert main(["trace", str(folder), "--root", str(root), "--verdict"]) == 1
    capsys.readouterr()

    # A row that the command did not write breaks the seal, so the verdict is not used.
    text = file.read_text().splitlines()[0] + "\n"
    file.write_text(text)
    assert verdict.checked(folder)[0] is None
    words = ("--turn", "4", "--outcome", "key_wrong", "--reason", "The key is old.")
    assert _adjudicate(root, folder, *words) == 2
    assert "no adjudication was written. " in capsys.readouterr().err
    assert file.read_text() == text


def test_the_checked_verdict_reads_the_adjudications_of_the_seal(tmp_path: Path) -> None:
    case = ROOT / "conformance" / "verdict" / "adjudications_pass"
    given = json.loads((case / "case.json").read_text(encoding="utf-8"))
    folder = tmp_path / "home" / "t1"
    folder.mkdir(parents=True)
    files = [(path, text) for path, text in given["files"]]
    manifest = {"test": "t1", "verdict": verdict.read(files)}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    report = {"counts": given["counts"], "answers": given["answers"]}
    (folder / "findings.json").write_text(json.dumps(report))
    (folder / verdict.ADJUDICATIONS).write_text(given["adjudications"])
    assert verdict.build(folder)["verdict"] == "pass"
    base = tmp_path / "home"
    assert seal.write(folder, base) is None
    found, why = verdict.checked(folder, base)
    assert why is None and found is not None and found["verdict"] == "pass"
    # Without the rows, the verdict of the same records is fail: 2 open mismatches.
    assert (
        verdict.compute("t1", manifest, [], (folder / "findings.json").read_bytes())["verdict"]
        == "fail"
    )
    (folder / verdict.ADJUDICATIONS).write_text(given["adjudications"] * 2)
    assert verdict.checked(folder, base) == (
        None,
        "The seal is not intact with a copy. " + seal.summary(seal.verify(folder, base)),
    )


def test_a_path_of_the_adjudications_that_is_not_a_file_fails_the_verdict(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"test": "t1"}))
    (tmp_path / "findings.json").write_text(json.dumps({"counts": {}}))
    (tmp_path / verdict.ADJUDICATIONS).mkdir()
    report = verdict.build(tmp_path)
    assert report["verdict"] == "fail"
    assert report["problems"] == ["adjudications.jsonl is not a file that the verdict can read."]
    assert report["adjudications"]["open"] is None


# The entry cannot read the answer key in the test folder (SPEC.md section 7.17). This agent
# gives the keyed answer of each question if it can read the copy, and it puts a symlink at the
# path of the copy. The bridge writes the copy after the entry stops, and follows no symlink.
READ_AGENT = COUNT_AGENT.replace(
    "for raw in sys.stdin.buffer:",
    "import os, pathlib\n"
    "copy = pathlib.Path(os.environ['NOOKKU_TEST_DIR'], 'answer_key.json')\n"
    "key = {}\n"
    "if copy.is_file():\n"
    "    key = {a['question']: a['answer'] for a in json.loads(copy.read_text())['answers']}\n"
    "copy.symlink_to(os.environ['TARGET'])\n"
    "for raw in sys.stdin.buffer:",
).replace('"count": 12}', '"count": key.get(request["message"], 12)}')


def test_the_entry_cannot_read_the_answer_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = tmp_path / "read.py"
    agent.write_text(READ_AGENT)
    target = tmp_path / "target.txt"
    target.write_text("not the key")
    monkeypatch.setenv("TARGET", str(target))
    root = _shop(tmp_path, [sys.executable, str(agent)])
    (root / "APP_SPEC.md").write_text(KEY_SPEC)
    (root / "keys").mkdir()
    key = json.dumps(STOCK_KEY).encode()
    (root / "keys" / "stock.json").write_bytes(key)
    code, out = _run(root, capsys)
    assert code == 1, out
    assert "Verdict: fail. answer_key_mismatch: 1, the limit is 0." in out["report"]
    folder = bridge.latest_test(root)
    assert folder is not None
    copy = folder / "answer_key.json"
    assert not copy.is_symlink() and copy.read_bytes() == key
    assert target.read_text() == "not the key"
    seal = json.loads((folder / "seal.json").read_text())
    assert seal["files"]["answer_key.json"] == hashlib.sha256(key).hexdigest()


def test_trace_verdict_rebuilds_a_missing_verdict_and_adds_it_to_the_seal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path, [sys.executable, str(TOY_SHOP)])
    assert _run(root, capsys)[0] == 0
    folder = bridge.latest_test(root)
    assert folder is not None
    # A test of Nookku 0.5.6 or earlier has no verdict.json and no verdict in its seal.
    (folder / verdict.FILE).unlink()
    data = json.loads((folder / seal.SEAL).read_text())
    del data["files"][verdict.FILE]
    (folder / seal.SEAL).write_text(json.dumps(data))
    copy = seal.copy_path(folder.name)
    copy.write_text(json.dumps({**data, "copy": True}))
    assert main(["trace", str(folder), "--root", str(root), "--verdict"]) == 0
    assert "Verdict: pass (2 limits)." in capsys.readouterr().out
    assert seal.verify(folder)["intact"]


def test_trace_verdict_fails_when_the_rebuild_cannot_write_the_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _shop(tmp_path, [sys.executable, str(TOY_SHOP)])
    assert _run(root, capsys)[0] == 0
    folder = bridge.latest_test(root)
    assert folder is not None

    def broken(folder: Path) -> dict:
        raise OSError("disk full")

    monkeypatch.setattr(verdict, "build", broken)
    assert main(["trace", str(folder), "--root", str(root), "--verdict"]) == 1
    out = capsys.readouterr()
    assert "verdict.json was not rebuilt" in out.err
    assert "Verdict: fail. The test folder has no valid verdict.json." in out.out
    # The seal keeps the old verdict.json, so the folder stays intact.
    assert seal.verify(folder)["intact"]


FAKE_PASS = {"verdict": "pass", "classes": [], "problems": []}


def test_a_replaced_verdict_after_the_end_fails_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Another user can write the tests folder (#532). The user replaces verdict.json after the
    # bridge seals it and before the run reads it. The run must not trust the file.
    defect = tmp_path / "defect.py"
    defect.write_text(REPEAT_DEFECT)
    root = _shop(tmp_path, [sys.executable, str(defect)])
    real_end = bridge.end

    def end_and_replace(*args: object, **kwargs: object) -> object:
        out = real_end(*args, **kwargs)  # type: ignore[arg-type]
        folder = bridge.latest_test(root)
        assert folder is not None
        (folder / verdict.FILE).write_text(json.dumps(FAKE_PASS))
        return out

    monkeypatch.setattr(bridge, "end", end_and_replace)
    code, out = _run(root, capsys)
    assert code == 1, out
    line = next(x for x in out["report"] if x.startswith("Verdict:"))
    assert line.startswith("Verdict: fail. The seal is not intact with a copy.")
    assert "changed: verdict.json" in line


def test_a_replaced_verdict_and_seal_fail_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The user also writes seal.json again. The copy of the seal outside the folder differs.
    defect = tmp_path / "defect.py"
    defect.write_text(REPEAT_DEFECT)
    root = _shop(tmp_path, [sys.executable, str(defect)])
    real_end = bridge.end

    def end_and_reseal(*args: object, **kwargs: object) -> object:
        out = real_end(*args, **kwargs)  # type: ignore[arg-type]
        folder = bridge.latest_test(root)
        assert folder is not None
        (folder / verdict.FILE).write_text(json.dumps(FAKE_PASS))
        data = json.loads((folder / seal.SEAL).read_text())
        data["files"][verdict.FILE] = seal.sha256_of((folder / verdict.FILE).read_bytes())
        (folder / seal.SEAL).write_text(json.dumps(data))
        return out

    monkeypatch.setattr(bridge, "end", end_and_reseal)
    code, out = _run(root, capsys)
    assert code == 1, out
    line = next(x for x in out["report"] if x.startswith("Verdict:"))
    assert line.startswith("Verdict: fail. The seal is not intact with a copy.")


def test_trace_verdict_does_not_trust_a_verdict_replaced_after_the_rebuild(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    defect = tmp_path / "defect.py"
    defect.write_text(REPEAT_DEFECT)
    root = _shop(tmp_path, [sys.executable, str(defect)])
    assert _run(root, capsys)[0] == 1
    folder = bridge.latest_test(root)
    assert folder is not None
    real_update = seal.update

    def update_and_replace(folder: Path, names: list[str], base: Path | None = None) -> None:
        real_update(folder, names, base)
        (folder / verdict.FILE).write_text(json.dumps(FAKE_PASS))

    monkeypatch.setattr(seal, "update", update_and_replace)
    assert main(["trace", str(folder), "--root", str(root), "--verdict", "--json"]) == 1
    err = capsys.readouterr().err
    assert "The seal is not intact with a copy." in err and "changed: verdict.json" in err


def test_trace_verdict_fails_with_no_copy_of_the_seal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # With no copy outside the folder, seal.json is in the folder that another user can write.
    root = _shop(tmp_path, [sys.executable, str(TOY_SHOP)])
    assert _run(root, capsys)[0] == 0
    folder = bridge.latest_test(root)
    assert folder is not None
    seal.copy_path(folder.name).unlink()
    data = json.loads((folder / seal.SEAL).read_text())
    (folder / seal.SEAL).write_text(json.dumps({**data, "copy": False}))
    assert main(["trace", str(folder), "--root", str(root), "--verdict"]) == 1
    assert "The seal is not intact with a copy." in capsys.readouterr().err
    # Without --verdict, the rebuild still works.
    assert main(["trace", str(folder), "--root", str(root)]) == 0


def test_the_checked_verdict_needs_the_verdict_of_the_sealed_records(tmp_path: Path) -> None:
    # A verdict.json that the seal covers, but that is not the verdict of the manifest and
    # findings.json, is not used.
    folder = tmp_path / "20261031-090000-ab12"
    folder.mkdir()
    limits = {"limits": {"agent_error": 0}, "unread": []}
    (folder / "manifest.json").write_text(json.dumps({"test": folder.name, "verdict": limits}))
    counts = {**dict.fromkeys(trace.CHECKS, 0), "agent_error": 1}
    (folder / "findings.json").write_text(json.dumps({"counts": counts}))
    assert verdict.build(folder)["verdict"] == "fail"
    assert verdict.checked(folder)[0] is None  # no seal yet
    seal.write(folder)
    found, why = verdict.checked(folder)
    assert why is None and found is not None and found["verdict"] == "fail"
    (folder / verdict.FILE).write_text(json.dumps(FAKE_PASS))
    seal.write(folder)
    assert verdict.checked(folder) == (
        None,
        "verdict.json is not the verdict of manifest.json and findings.json.",
    )


def test_the_checked_verdict_compares_the_bytes_that_it_reads_with_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file can change after the check of the seal and before the read. The process compares
    # the bytes that it reads with the SHA-256 of the copy of the seal.
    folder = tmp_path / "20261031-090000-cd34"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"test": folder.name}))
    (folder / "findings.json").write_text(json.dumps({"counts": {}}))
    verdict.build(folder)
    seal.write(folder)
    (folder / verdict.FILE).write_text(json.dumps(FAKE_PASS))
    monkeypatch.setattr(seal, "verify", lambda folder, base=None: {"intact": True, "copy": "same"})
    assert verdict.checked(folder) == (None, "verdict.json is not the file of the seal.")

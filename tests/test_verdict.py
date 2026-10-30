"""The verdict of a test and its exit code for CI (#514, SPEC.md section 7.14)."""

from __future__ import annotations

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
        (folder / "findings.json").write_text(json.dumps({"counts": given["counts"]}))
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

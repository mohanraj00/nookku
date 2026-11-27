"""The verifier command and its claims, entry protocol and report (SPEC.md section 11)."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from nookku.cli import main
from nookku.config import FILE as CONFIG_FILE

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "toy-shop-verifier"
CASE = ROOT / "conformance" / "verifier"
MUG = {"id": "mug", "text": "The café has a mug.\nIt is blue.", "seeded": False}


def _config(root: Path, argv: list[str]) -> None:
    path = root / CONFIG_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"entries": {"stock": argv}}), encoding="utf-8")


def _claims(root: Path, rows: list[dict]) -> Path:
    path = root / "claims.json"
    data = {"source": "Toy shop stock list", "version": "spring", "claims": rows}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_the_toy_shop_verifier_rates(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for name in ("claims.json", "stock_verifier.py"):
        shutil.copyfile(EXAMPLE / name, tmp_path / name)
    _config(tmp_path, [sys.executable, "stock_verifier.py"])

    assert main(["verifier", "run", "claims.json", "--entry", "stock"]) == 0
    assert "wrote verifier.json" in capsys.readouterr().out
    report = json.loads(Path("verifier.json").read_text(encoding="utf-8"))
    assert report["errors"] == 0
    assert report["refutation_rate"] == {"numerator": 2, "denominator": 3, "rate": 2 / 3}
    assert report["false_refutation_rate"] == {"numerator": 1, "denominator": 5, "rate": 0.2}
    assert (
        report["claim_set"]["sha256"]
        == hashlib.sha256(Path("claims.json").read_bytes()).hexdigest()
    )


def test_the_verifier_report_matches_the_conformance_case(tmp_path):
    replies = CASE / "replies.json"
    command = f"""
import json, sys
from pathlib import Path
claim = json.loads(sys.stdin.buffer.readline())
assert set(claim) == {{"id", "text"}} and not sys.stdin.buffer.read()
print(json.loads(Path({str(replies)!r}).read_text())[claim["id"]])
"""
    _config(tmp_path, [sys.executable, "-c", command])
    out = tmp_path / "report.json"
    args = ["verifier", "run", str(CASE / "claims.json"), "--entry", "stock"]
    assert main([*args, "--root", str(tmp_path), "--out", str(out)]) == 0
    assert json.loads(out.read_bytes()) == json.loads((CASE / "expect.json").read_bytes())


@pytest.mark.parametrize(
    "change, message",
    [
        ({"claims": [MUG, MUG]}, "duplicate claim id 'mug'"),
        ({"claims": [{"id": "mug", "seeded": False}]}, "'text' must be a Unicode string"),
        ({"claims": [{**MUG, "seeded": 1}]}, "'seeded' must be a boolean"),
        ({"version": 1}, "'version' must be a Unicode string"),
        ({"claims": {}}, "'claims' must be a list"),
    ],
)
def test_the_cli_refuses_an_invalid_claim_set(tmp_path, capsys, change, message):
    claims = _claims(tmp_path, [MUG])
    data = json.loads(claims.read_bytes())
    claims.write_text(json.dumps({**data, **change}), encoding="utf-8")

    assert main(["verifier", "run", str(claims), "--entry", "stock", "--root", str(tmp_path)]) == 2
    assert message in capsys.readouterr().err
    assert not (tmp_path / "verifier.json").exists()


@pytest.mark.parametrize(
    "output, code, reason",
    [
        (b'{"verdict": "refuted"}\n', 3, "entry exited with code 3"),
        (b'log\n{"verdict": "refuted"}\n', 0, "invalid reply"),
        (b'{"verdict": "refuted", "verdict": "refuted"}\n', 0, "invalid reply"),
        (b"\xff\n", 0, "invalid reply"),
    ],
)
def test_entry_failure_records_an_error(tmp_path, monkeypatch, output, code, reason):
    monkeypatch.chdir(tmp_path)
    claims = _claims(tmp_path, [MUG])
    command = f"import sys; sys.stdout.buffer.write({output!r}); sys.exit({code})"
    _config(tmp_path, [sys.executable, "-c", command])

    assert main(["verifier", "run", str(claims), "--entry", "stock"]) == 0
    report = json.loads(Path("verifier.json").read_bytes())
    assert report["claims"] == [{"id": "mug", "seeded": False, "verdict": "error", "error": reason}]
    assert report["errors"] == 1
    assert report["refutation_rate"] == {"numerator": 0, "denominator": 0, "rate": None}
    assert report["false_refutation_rate"] == {"numerator": 0, "denominator": 1, "rate": 0.0}


def test_a_timeout_does_not_stop_the_next_claim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    claims = _claims(tmp_path, [{**MUG, "id": "slow", "seeded": True}, MUG])
    command = f"""
import json, sys, time
claim = json.loads(sys.stdin.buffer.readline())
if claim["id"] == "slow":
    time.sleep(30)
assert claim == {{"id": "mug", "text": {MUG["text"]!r}}}
print('{{"verdict": "supported"}}')
"""
    _config(tmp_path, [sys.executable, "-c", command])

    assert main(["verifier", "run", str(claims), "--entry", "stock", "--timeout", "3"]) == 0
    report = json.loads(Path("verifier.json").read_bytes())
    assert report["claims"] == [
        {"id": "slow", "seeded": True, "verdict": "error", "error": "timeout"},
        {"id": "mug", "seeded": False, "verdict": "supported", "error": None},
    ]
    assert report["errors"] == 1

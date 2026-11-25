"""The finding record of a confirmed defect: the reader, the export and the schema (#575)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from nookku import __version__, bridge, commands, finding_record, issues, seal
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
CASES = sorted((ROOT / "conformance" / "finding").glob("*.json"))
SCRIPT = ["What is the price of the blue mug?", "Is the teapot in stock?"]
SUBJECT = "sha256:ab12cd34"
# A word that the check test changes to NaN, which is not a number of JSON.
NAN = "NAN"
# The agent gives the count 12 for each message. The key gives 12.4 for the mug, which is in
# the tolerance, and 3 for the teapot, which is a mismatch in turn 2.
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
"""
TINY = "0.000000001"
STOCK_KEY = {
    "source": "the stock list of the toy shop",
    "version": "1",
    "answers": [
        {"question": "What is the price of the blue mug?", "answer": 12.4},
        # A small tolerance: the text of its Decimal has an exponent, 1E-9.
        {"question": "Is the teapot in stock?", "answer": 3, "match": "number", "tolerance": TINY},
    ],
}
REPORT = """# Evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| unsupported_reply | 2 | trace.jsonl:7 | The reply gives a count that no tool result has. |
"""


def _shop(tmp_path: Path) -> Path:
    """A toy shop project with an answer key and a script of 2 messages."""
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    agent = tmp_path / "count.py"
    agent.write_text(COUNT_AGENT)
    (root / "APP_SPEC.md").write_text(KEY_SPEC)
    (root / "keys").mkdir()
    (root / "keys" / "stock.json").write_text(json.dumps(STOCK_KEY))
    conf = {"entry": [sys.executable, str(agent)], "models": [], "spec": ["APP_SPEC.md"]}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    (root / "script.jsonl").write_text("".join(json.dumps({"said": s}) + "\n" for s in SCRIPT))
    return root


def _test(root: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    main(["run", "--script", str(root / "script.jsonl"), "--root", str(root), "--json"])
    capsys.readouterr()
    folder = bridge.latest_test(root)
    assert folder is not None
    return folder


def _adjudicate(root: Path, folder: Path, outcome: str) -> None:
    words = ["--turn", "2", "--outcome", outcome, "--reason", "The stock list gives 3."]
    assert main(["adjudicate", folder.name, "--root", str(root), "--author", "Asha", *words]) == 0


def _export(
    root: Path, capsys: pytest.CaptureFixture[str], *words: str
) -> tuple[int, list[dict[str, Any]], str]:
    code = main(["finding", "export", "--root", str(root), *words])
    shown = capsys.readouterr()
    return code, [json.loads(line) for line in shown.out.splitlines()], shown.err


def test_an_adjudicated_mismatch_and_an_issue_row_of_a_person_give_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path)
    folder = _test(root, capsys)
    _adjudicate(root, folder, "agent_wrong")
    (folder / issues.REPORT).write_text(REPORT)
    assert main(["evaluation", "import", folder.name, "--root", str(root)]) == 0
    words = ["--class", "business_rule", "--turn", "1", "--evidence", "turn 1"]
    add = ["evaluation", "add", folder.name, "--root", str(root), "--author", "Asha"]
    assert main([*add, *words, "--text", "The price has no tax."]) == 0
    capsys.readouterr()

    code, records, err = _export(root, capsys, folder.name, "--subject", SUBJECT)
    assert code == 0 and "2 finding records" in err
    assert [finding_record.problem(r) for r in records] == [None, None]
    key, issue = records
    assert list(key) == list(finding_record.FIELDS)
    reply = json.loads(key["turn"]["reply"])
    assert key["turn"] == {"number": 2, "input": SCRIPT[1], "reply": key["turn"]["reply"]}
    assert reply["count"] == 12
    assert key["script"]["messages"] == SCRIPT
    assert key["script"]["sha256"] == seal.sha256_of((root / "script.jsonl").read_bytes())
    # The tolerance has no exponent, so the reader of the record accepts it.
    assert key["expected"] == {
        "value": "3",
        "match": "number",
        "tolerance": TINY,
        "field": "count",
    }
    assert key["observed"] == "12" and key["issue"] is None
    adjudication = key["adjudication"]
    assert {**adjudication, "ts": 0} == {
        "outcome": "agent_wrong",
        "reason": "The stock list gives 3.",
        "author": "Asha",
        "author_type": "human",
        "ts": 0,
    }
    assert key["id"] == f"{folder.name}/answer_key_mismatch/2"
    assert (key["subject"], key["gate"], key["nookku"]) == (SUBJECT, None, __version__)
    # The seal of the record is the copy of the seal, and it covers each source file.
    copy = seal.copy_path(folder.name).read_bytes()
    assert key["seal"]["text"].encode() == copy
    assert key["seal"]["sha256"] == seal.sha256_of(copy)
    names = ["manifest.json", "tap.jsonl", "findings.json", "answer_key.json"]
    assert list(key["seal"]["files"]) == [*names, "adjudications.jsonl", "script.jsonl"]
    assert key["seal"]["files"] == {n: seal.hashes(folder)[n] for n in key["seal"]["files"]}
    # The issue row of the person is row 2 of evaluation.json. The model row is not confirmed.
    assert issue["id"] == f"{folder.name}/issue_row/2"
    assert issue["issue"] == {
        "class": "business_rule",
        "evidence": "turn 1",
        "text": "The price has no tax.",
    }
    assert issue["turn"]["number"] == 1 and issue["expected"] is None
    assert issue["adjudication"]["author_type"] == "human" and issue["adjudication"]["ts"] is None
    # The export changes no file, so the seal is still intact.
    assert seal.verify(folder)["intact"]

    code, records, _ = _export(root, capsys, folder.name, "--subject", SUBJECT, "--model-rows")
    assert code == 0 and [r["id"].rsplit("/", 2)[1:] for r in records] == [
        ["answer_key_mismatch", "2"],
        ["issue_row", "1"],
        ["issue_row", "2"],
    ]
    model = records[1]["adjudication"]
    assert (model["author"], model["author_type"]) == (None, "model")
    assert finding_record.problem(records[1]) is None


@pytest.mark.parametrize("outcome", [None, "key_wrong", "both_acceptable"])
def test_a_mismatch_that_is_not_agent_wrong_gives_no_record(
    outcome: str | None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path)
    folder = _test(root, capsys)
    if outcome is not None:
        _adjudicate(root, folder, outcome)
        capsys.readouterr()
    code, records, err = _export(root, capsys, "--subject", SUBJECT)
    assert (code, records) == (0, []) and "0 finding records" in err


def test_the_last_row_of_a_turn_is_its_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path)
    folder = _test(root, capsys)
    _adjudicate(root, folder, "agent_wrong")
    _adjudicate(root, folder, "key_wrong")
    capsys.readouterr()
    assert _export(root, capsys, "--subject", SUBJECT)[1] == []


def test_the_export_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _shop(tmp_path)
    folder = _test(root, capsys)
    _adjudicate(root, folder, "agent_wrong")
    capsys.readouterr()
    # No subject, and a subject that breaks the rule of a gate run.
    code, records, err = _export(root, capsys, folder.name)
    assert (code, records) == (2, []) and "--subject" in err
    code, records, err = _export(root, capsys, folder.name, "--subject", "a\nb")
    assert (code, records) == (2, []) and "control character" in err
    # A row that the command did not write breaks the seal, so the export gives no record.
    with (folder / "adjudications.jsonl").open("a") as f:
        f.write("{}\n")
    code, records, err = _export(root, capsys, folder.name, "--subject", SUBJECT)
    assert (code, records) == (2, []) and "Seal: BROKEN" in err


def test_a_gate_run_gives_the_records_of_its_tests_with_its_subject(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _shop(tmp_path)
    gate_file = root / "gate.json"
    gate_file.write_text(
        json.dumps({"v": 1, "tests": [{"name": "stock", "script": "script.jsonl"}]})
    )
    main(["gate", "run", str(gate_file), "--subject", SUBJECT, "--root", str(root), "--json"])
    capsys.readouterr()
    folder = bridge.latest_test(root)
    assert folder is not None
    gate_folder = next((root / ".nookku" / "gates").iterdir())
    code, records, _ = _export(root, capsys, "--gate", gate_folder.name)
    assert (code, records) == (0, [])
    _adjudicate(root, folder, "agent_wrong")
    capsys.readouterr()
    # The adjudication wrote verdict.json again, so the gate result does not verify. The
    # export still reads the gate run, because the adjudication changed no other pinned file.
    assert main(["gate", "verify", gate_folder.name, "--root", str(root)]) == 2
    capsys.readouterr()
    code, records, _ = _export(root, capsys, "--gate", gate_folder.name)
    assert code == 0 and len(records) == 1
    record = records[0]
    assert finding_record.problem(record) is None
    assert record["subject"] == SUBJECT and record["test"] == folder.name
    assert record["gate"] == {
        "id": gate_folder.name,
        "name": "stock",
        "result_sha256": seal.sha256_of((gate_folder / "result.json").read_bytes()),
    }
    # --gate takes the subject of the gate run, and no TEST.
    code, records, err = _export(root, capsys, "--gate", gate_folder.name, "--subject", "x")
    assert (code, records) == (2, []) and "--gate takes no TEST" in err
    # A pinned file that is not the file of the gate run stops the export.
    rebuilt = json.loads((folder / "findings.json").read_text())
    (folder / "findings.json").write_text(json.dumps(rebuilt, indent=3))
    seal.update(folder, ["findings.json"])
    assert seal.verify(folder)["intact"]
    code, records, err = _export(root, capsys, "--gate", gate_folder.name)
    assert (code, records) == (2, [])
    assert "findings.json is not the file that the gate run pinned" in err
    # A gate folder with a broken seal gives no record.
    (gate_folder / "result.json").write_text("{}")
    code, records, err = _export(root, capsys, "--gate", gate_folder.name)
    assert (code, records) == (2, []) and "Seal: BROKEN" in err


def test_the_check_command_names_each_line_that_is_not_a_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    valid = json.loads(CASES[-1].read_text(encoding="utf-8"))["record"]
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps(valid) + "\n", encoding="utf-8")
    assert main(["finding", "check", str(path)]) == 0
    assert f"line 1: ok {valid['id']}" in capsys.readouterr().out
    no_seal = {k: v for k, v in valid.items() if k != "seal"}
    lines = [json.dumps(valid), json.dumps(no_seal), "{", json.dumps({**valid, "x": NAN})]
    path.write_text("\n".join(lines).replace('"NAN"', "NaN"), encoding="utf-8")
    assert main(["finding", "check", str(path), "--json"]) == 1
    shown = json.loads(capsys.readouterr().out)
    assert shown["records"] == 4 and shown["valid"] is False
    assert [r["problem"] for r in shown["lines"]] == [
        None,
        "it has no field seal",
        "it is not JSON",
        "it is not JSON",
    ]
    assert main(["finding", "check", str(tmp_path / "none.jsonl")]) == 2
    path.write_bytes(b"\xff")
    assert main(["finding", "check", str(path)]) == 2
    capsys.readouterr()


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_each_case_gives_its_problem(case: Path) -> None:
    given = json.loads(case.read_text(encoding="utf-8"))
    assert finding_record.problem(given["record"]) == given["expect"]["problem"]
    # The schema checks the form only. It passes a record with a digest that does not match.
    schema = json.loads(finding_record.schema_text())
    assert _valid(given["record"], schema) == given["expect"]["schema"]


def test_the_cases_cover_the_issue_and_the_version_rules() -> None:
    names = {c.stem for c in CASES}
    wanted = {"valid_answer_key_mismatch", "valid_issue_row", "missing_field"}
    wanted |= {"seal_digest_mismatch", "valid_unknown_field", "unknown_major_version"}
    assert wanted <= names


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"record": "other"}, "its record is not nookku.finding"),
        ({"version": 1}, "its version is not a string of the form <major>.<minor>"),
        ({"version": "1"}, "its version is not a string of the form <major>.<minor>"),
        ({"kind": "tone"}, "its kind is not answer_key_mismatch or issue_row"),
        ({"test": " "}, "it has no test text"),
        ({"script": {"messages": [], "sha256": None}}, "its script has no messages list"),
        ({"turn": None}, "its turn is null"),
        ({"expected": None}, "its expected is not an object"),
        ({"observed": 12}, "its observed is not a string or null"),
        ({"issue": {}}, "its issue is not null"),
        ({"subject": ""}, "the subject must have 1 to 512 characters"),
        ({"gate": {"id": "g"}}, "its gate has no key name"),
        ({"id": "\ud83d"}, "it has a lone surrogate U+D83D at character 0"),
    ],
)
def test_the_reader_names_the_first_problem(change: dict[str, Any], problem: str) -> None:
    valid = json.loads((CASES[0].parent / "valid_answer_key_mismatch.json").read_text())["record"]
    assert finding_record.problem({**valid, **change}) == problem
    assert finding_record.problem([valid]) == "it is not a JSON object"


@pytest.mark.parametrize(
    "name", ["valid_answer_key_mismatch", "valid_issue_row", "valid_gate_record"]
)
def test_the_reader_gives_a_problem_and_no_error_for_each_wrong_value(name: str) -> None:
    valid = json.loads((CASES[0].parent / f"{name}.json").read_text(encoding="utf-8"))["record"]
    schema = json.loads(finding_record.schema_text())
    junk: list[Any] = [None, True, 0, 1.5, "", "x", [], ["x"], {}, {"x": 1}]
    for field, value in valid.items():
        for wrong in junk:
            if wrong != value:
                changed = {**valid, field: wrong}
                found = finding_record.problem(changed)
                # A null is valid in some fields of some kinds. Then the schema agrees.
                assert isinstance(found, str) or _valid(changed, schema), (field, wrong)
        if not isinstance(value, dict):
            continue
        for key in finding_record.KEYS[field]:
            less = {**valid, field: {k: v for k, v in value.items() if k != key}}
            assert finding_record.problem(less) == f"its {field} has no key {key}"
            assert not _valid(less, schema)
            for wrong in junk:
                if wrong != value[key]:
                    changed = {**valid, field: {**value, key: wrong}}
                    found = finding_record.problem(changed)
                    assert isinstance(found, str) or _valid(changed, schema), (field, key, wrong)


def test_the_schema_names_each_field_of_the_reader(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["finding", "schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["required"] == list(finding_record.FIELDS)
    assert list(schema["properties"]) == list(finding_record.FIELDS)
    assert schema["properties"]["kind"]["enum"] == list(finding_record.KINDS)
    assert schema["properties"]["record"]["const"] == finding_record.NAME
    assert re.fullmatch(schema["properties"]["version"]["pattern"], finding_record.VERSION)
    # No object of the schema refuses a field that it does not name.
    assert '"additionalProperties": false' not in finding_record.schema_text()


def test_the_relay_lets_the_model_export_and_check() -> None:
    # The command only reads, and each value of a record is in a file that the model can read.
    for command in ("nookku finding export --subject x", "nookku finding check records.jsonl"):
        assert commands.drive(command) is None


def test_the_reader_of_the_how_to_page_reads_the_cases() -> None:
    page = (ROOT / "docs" / "how-to" / "import-a-finding-record.md").read_text(encoding="utf-8")
    (code,) = re.findall(r"```python\n(.*?)```", page, re.DOTALL)
    scope: dict[str, Any] = {}
    exec(code, scope)
    for case in CASES:
        given = json.loads(case.read_text(encoding="utf-8"))
        line = json.dumps(given["record"])
        if given["expect"]["problem"] is None:
            made = scope["regression_case"](scope["read_finding"](line))
            turn = given["record"]["turn"]
            assert len(made["messages"]) == (2 if turn is None else turn["number"])
            assert made["origin"]["subject"] == SUBJECT
        elif case.stem.startswith(("unknown_major", "seal_")):
            # The short reader of the page checks the version and the seal digest.
            with pytest.raises(ValueError):
                scope["read_finding"](line)


_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "null": type(None),
    "integer": int,
    "number": (int, float),
}


def _valid(value: Any, schema: dict[str, Any]) -> bool:
    """A check of a value with the keywords of JSON Schema that the schema of a record uses."""
    known = {"$schema", "$id", "title", "description", "type", "const", "enum", "required"}
    known |= {"properties", "additionalProperties", "items", "minItems", "pattern", "anyOf"}
    known |= {"oneOf", "minimum", "maximum", "minLength", "maxLength"}
    assert set(schema) <= known, set(schema) - known
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if isinstance(value, bool) or not any(isinstance(value, _TYPES[n]) for n in names):
            return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, str):
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)):
            return False
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if number and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            return False
        if not all(_valid(v, schema.get("items", {})) for v in value):
            return False
    if isinstance(value, dict):
        if any(name not in value for name in schema.get("required", [])):
            return False
        named = schema.get("properties", {})
        if not all(_valid(value[k], s) for k, s in named.items() if k in value):
            return False
        other = schema.get("additionalProperties", {})
        if not all(_valid(v, other) for k, v in value.items() if k not in named):
            return False
    if "anyOf" in schema and not any(_valid(value, s) for s in schema["anyOf"]):
        return False
    return "oneOf" not in schema or sum(_valid(value, s) for s in schema["oneOf"]) == 1

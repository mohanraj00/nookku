import json
from pathlib import Path

import pytest

from nookku import seal
from nookku.cli import main
from nookku.record import Writer, loads

CASE = Path(__file__).resolve().parents[1] / "conformance/openinference/missing-stock-span.json"
TEST = "20261109-100000-ab12"


@pytest.mark.parametrize("source", ["phoenix", "langfuse"])
def test_a_proxy_call_without_an_exported_span_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    case = loads(CASE.read_bytes())
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = tmp_path / ".nookku" / "tests" / TEST
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"started": 0.5, "ended": 2.5}\n')
    Writer(folder / "tap.jsonl").append(
        {
            "type": "exchange",
            "input": "Is the teapot in stock?",
            "reply": "The teapot is in stock.",
            "status": 200,
            "started": 1.0,
            "ts": 2.0,
        }
    )
    rows = [{"type": "call", "backend": "stock", "status": 200, **c} for c in case["calls"]]
    (folder / "backend.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert seal.write(folder) is None
    export = tmp_path / "spans.json"
    export.write_text(json.dumps(case[source]))
    assert (
        main(["trace", "--root", str(tmp_path), TEST, "--json", "--openinference", str(export)])
        == 0
    )
    report = loads(capsys.readouterr().out)
    assert report["openinference"]["spans"] == 1
    assert report["findings"] == [case["finding"]]
    text = (folder / "openinference.jsonl").read_text()
    assert "toy-credential" not in text and "toy prompt text" not in text
    trace = [loads(line) for line in (folder / "trace.jsonl").read_text().splitlines()]
    imported = next(it for it in trace if it["harness"] == "openinference")
    assert imported["turn"] == 1
    assert imported["source"] == {"file": "openinference.jsonl", "line": 1}
    assert seal.verify(folder)["intact"]

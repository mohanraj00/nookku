"""The trace steps and the time of each turn on the chat page (#353)."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from test_page import base, make_folder, request, start_page, write_current

from nookku import page_trace, trace
from nookku.record import Writer

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "conformance" / "trace"
NODE = shutil.which("node")
TRACE_JS = Path(str(resources.files("nookku").joinpath("page").joinpath("trace.js")))


def toy_shop(root: Path) -> Path:
    """A test of the full toy shop: 2 exchanges, the calls to the stock and payments backends,
    and the direct calls to the model API. The files come from the trace conformance cases, which
    have the same tap windows."""
    folder = make_folder(root)
    for name in ("tap.jsonl", "backend.jsonl", "manifest.json"):
        shutil.copy(CASES / "backend_toy_shop" / name, folder / name)
    shutil.copy(CASES / "model_api_toy_shop" / "model_api.jsonl", folder / "model_api.jsonl")
    relay = Writer(folder / "relay.jsonl")
    # The tap refused this message, so the tap has no exchange for it.
    relay.append(
        {"type": "turn", "harness": "pane", "said": "hi", "shown": "nookku: no", "ok": False}
    )
    for n in (20, 40):
        said, shown = "toy shop message", f"toy shop reply at {n}"
        relay.append({"type": "turn", "harness": "pane", "said": said, "shown": shown, "ok": True})
    return folder


def end(folder: Path) -> None:
    """Write `ended` into the manifest, as the end of a test does."""
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["ended"] = 1791273650.0
    (folder / "manifest.json").write_text(json.dumps(manifest))


def expected(turn: int) -> list[tuple[str, str | None, Any]]:
    """The steps of a turn in the expected traces of the 2 conformance cases."""
    rows = []
    for case in ("backend_toy_shop", "model_api_toy_shop"):
        lines = (CASES / case / "expect_trace.jsonl").read_text().splitlines()
        rows += [json.loads(line) for line in lines]
    rows.sort(key=lambda r: r["ts"])
    return [(r["harness"], r["name"], r["ts"]) for r in rows if r["turn"] == turn]


def shape(steps: list[dict[str, Any]]) -> list[tuple[str, str | None, Any]]:
    return sorted(((s["harness"], s["name"], s["ts"]) for s in steps), key=lambda s: s[2])


def test_the_steps_are_grouped_by_the_turn_of_their_reply(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    data = page_trace.steps(folder, running=False)
    first, second, third = data["turns"]
    assert first == {"exchange": None, "started": None, "ended": None, "steps": []}
    assert (second["exchange"], third["exchange"]) == (1, 2)
    # The time of a turn is from the tap `started` time to the end of the reply.
    assert third["ended"] - third["started"] == 10.0
    assert shape(second["steps"]) == expected(1)
    assert shape(third["steps"]) == expected(2)
    kinds = {(s["harness"], s["kind"]) for s in second["steps"]}
    assert {("backend", "http"), ("model_api", "message"), ("model_api", "tool_call")} <= kinds
    # A step after the last turn of a test that ended belongs to no turn.
    assert data["pending"] == []
    assert all("turn" not in s and trace.CALL_ID not in s for s in second["steps"])


def test_after_the_end_the_steps_come_from_trace_jsonl(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    live = page_trace.steps(folder, running=False)
    trace.build(folder)
    end(folder)
    (folder / "backend.jsonl").unlink()
    (folder / "model_api.jsonl").unlink()
    ended = page_trace.steps(folder, running=False)
    assert [shape(t["steps"]) for t in ended["turns"]] == [shape(t["steps"]) for t in live["turns"]]


def test_a_text_with_u2028_in_trace_jsonl_keeps_its_step(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    trace.build(folder)
    end(folder)
    lines = (folder / "trace.jsonl").read_text(encoding="utf-8").split("\n")
    row = json.loads(lines[0])
    row["output"] = "line one\u2028line two"
    lines[0] = json.dumps(row, ensure_ascii=False)
    (folder / "trace.jsonl").write_text("\n".join(lines), encoding="utf-8")
    data = page_trace.steps(folder, running=False)
    outputs = [s["output"] for t in data["turns"] for s in t["steps"]]
    assert "line one\u2028line two" in outputs


def test_a_test_with_no_end_reads_the_live_rows_and_not_trace_jsonl(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    # `nookku trace` before the end writes a trace.jsonl that does not change after that.
    trace.build(folder)
    row = json.loads((folder / "backend.jsonl").read_text().splitlines()[0])
    row |= {"started": 1791273615.0, "ts": 1791273615.5, "path": "/new"}
    with (folder / "backend.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    # A running test, and a test whose bridge stopped with no end, use the live rows.
    for running in (True, False):
        found = page_trace.steps(folder, running=running)["turns"][1]["steps"]
        assert "GET /new" in [s["name"] for s in found]
    end(folder)
    found = page_trace.steps(folder, running=False)["turns"][1]["steps"]
    assert "GET /new" not in [s["name"] for s in found]


def test_the_cache_keeps_the_answers_of_a_few_tests_only(tmp_path: Path) -> None:
    for n in range(page_trace.CACHE_SIZE + 3):
        root = tmp_path / str(n)
        toy_shop(root)
        assert page_trace.answer(root, "api/trace")[0] == 200
    assert len(page_trace._cache) <= page_trace.CACHE_SIZE


def test_a_running_test_shows_the_steps_that_wait_for_a_reply(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    data = page_trace.steps(folder, running=True)
    # The stock call at 45 is after the last exchange (40): its message waits for the reply.
    assert [(s["harness"], s["name"]) for s in data["pending"]] == [("backend", "GET /stock/image")]


def test_the_page_updates_when_a_new_trace_row_arrives(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    write_current(tmp_path, folder, "http://127.0.0.1:9/", None)
    server = start_page(tmp_path)
    try:
        status, _, body = request(server, "GET", base(server) + "api/trace")
        assert status == 200
        before = json.loads(body)
        assert before["test"] == folder.name and before["error"] is None
        row = json.loads((folder / "backend.jsonl").read_text().splitlines()[0])
        row |= {"started": 1791273615.0, "ts": 1791273615.5, "path": "/new"}
        with (folder / "backend.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        _, _, body = request(server, "GET", base(server) + "api/trace/" + folder.name)
        after = json.loads(body)
        names = [s["name"] for s in after["turns"][1]["steps"]]
        assert "GET /new" in names and len(names) == len(before["turns"][1]["steps"]) + 1
        status, _, body = request(server, "GET", base(server) + "api/trace/nothing")
        assert status == 404 and json.loads(body)["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_a_tap_record_that_is_not_valid_gives_an_error(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    with (folder / "tap.jsonl").open("a") as f:
        f.write('{"v": "0.2", "type": "exchange"\n')
    status, data = page_trace.answer(tmp_path, "api/trace")
    assert status == 200 and data["turns"] == [] and "tap.jsonl" in data["error"]


# A small DOM for node, as in test_page_render.py.
HARNESS = """
const trace = require(process.argv[2]);
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.className = ""; }
  append(...cs) { this.kids.push(...cs); }
  set textContent(v) { this.kids = [{ text: String(v) }]; }
  get textContent() { return this.kids.map((k) => k.text !== undefined ? k.text : k.textContent)
    .join(""); }
}
global.document = { createElement: (t) => new El(t) };
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const li = trace.block(input, false);
const tags = [];
(function walk(n) { if (n.tag) { tags.push(n.tag); n.kids.forEach(walk); } })(li);
process.stdout.write(JSON.stringify({ text: li.textContent, tags: tags }));
"""


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
def test_a_step_shows_as_text_and_not_as_html(tmp_path: Path) -> None:
    script = tmp_path / "harness.js"
    script.write_text(HARNESS)
    evil = '<img src=x onerror="alert(1)">'
    step = {"harness": "backend", "kind": "http", "name": "GET /stock", "ts": 12.5}
    step |= {"input": {"q": evil}, "output": evil, "error": None, "exit_code": 200}
    turn = {"exchange": 1, "started": 10.0, "ended": 20.0, "steps": [step]}
    done = subprocess.run(
        [str(NODE), str(script), str(TRACE_JS)],
        input=json.dumps(turn),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(done.stdout)
    assert "Turn time 10.0 s, 1 trace step" in out["text"]
    assert "+2.5 s backend http GET /stock status 200" in out["text"]
    assert evil in out["text"] and "img" not in out["tags"]

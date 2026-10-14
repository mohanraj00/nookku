"""Tests of the export of a test as one HTML file (#354)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from test_dashboard import make_test
from test_page import base, request, start_page
from test_page_trace import end_and_build, expected, shape, toy_shop

from nookku import cli, export, page, seal
from nookku.record import Writer

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")
PAGE = Path(str(resources.files("nookku").joinpath("page")))
# A 1x1 PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
TEST_ID = "20261013-090000-aa11"
REPLY = (
    "Here is the mug: ![mug](images/mug.png)\n"
    "Our [shop](https://shop.example/mugs) and ![web](https://cdn.example/a.png).\n"
    "</script><script>alert(1)</script> <img src=x onerror=alert(2)>\n"
    "A big file: ![big](images/big.png) and a state file: ![tok](.nookku/secret.png)\n"
    "[the manual](docs/manual.pdf)"
)
TEST: dict[str, Any] = {
    "id": TEST_ID,
    "started": 1_800_000_000.0,
    "turns": [
        ("Is the mug dishwasher safe?", REPLY, REPLY),
        ("Do you ship to Chennai?", "Yes, we ship to Chennai.", "Yes, we ship to Chennai!"),
    ],
    "findings": [{"check": "tool_error", "turn": 1, "detail": "stock tool failed"}],
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "mug.png").write_bytes(PNG)
    (tmp_path / "images" / "big.png").write_bytes(PNG + b"\0" * 64)
    folder = make_test(tmp_path, TEST, sealed=False)
    (tmp_path / ".nookku" / "secret.png").write_bytes(PNG)
    Writer(folder / "notes.jsonl").append(
        {"type": "note", "turn": 1, "rating": "up", "comment": "Good </script> answer"}
    )
    step = {
        "v": "0.3", "type": "model_item", "turn": 1, "harness": "claude-code", "session": "s",
        "ts": 1_800_000_001.0, "kind": "tool_call", "role": None, "server": "shop",
        "name": "get_stock", "input": {"item": "mug"}, "output": "12 in stock", "error": None,
        "exit_code": None, "harness_internal": False, "service": None,
        "source": {"file": "s.jsonl", "line": 3},
    }  # fmt: skip
    (folder / "trace.jsonl").write_text(json.dumps(step) + "\n")
    seal.write(folder)
    return tmp_path


def data_of(html: str) -> dict[str, Any]:
    m = re.search(r'<script type="application/json" id="nookku-data">(.*?)</script>', html, re.S)
    assert m
    found: dict[str, Any] = json.loads(m.group(1))
    return found


def outside_data(html: str) -> str:
    block = r'<script type="application/json" id="nookku-data">.*?</script>'
    return re.sub(block, "", html, flags=re.S)


def test_the_export_holds_the_chat_the_steps_the_notes_the_audit_and_the_seal(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "MAX_MEDIA", len(PNG) + 10)
    html = export.build(project, project / ".nookku" / "tests" / TEST_ID).decode()
    data = data_of(html)
    assert [t["said"] for t in data["turns"]] == [t[0] for t in TEST["turns"]]
    assert data["turns"][0]["shown"] == REPLY
    assert data["steps"]["1"][0]["name"] == "get_stock"
    assert data["notes"][0]["comment"] == "Good </script> answer"
    assert [b["class"] for b in data["breaks"]] == ["altered_reply"]
    assert data["summary"]["seal"] == "intact"
    assert data["findings"][0]["check"] == "tool_error"
    # The file in the project goes in. The big file and the file in the state folder do not.
    assert data["media"]["images/mug.png"].startswith("data:image/png;base64,")
    assert data["big"] == ["images/big.png"]
    assert ".nookku/secret.png" not in data["media"]


def test_no_text_can_end_a_script_block_and_the_page_makes_no_external_url(project: Path) -> None:
    html = export.build(project, project / ".nookku" / "tests" / TEST_ID).decode()
    # 1 data block and 2 scripts: the "</script>" texts of the agent and the note are escapes.
    assert html.count("</script>") == 3
    assert "alert(" not in outside_data(html).split("<script>", 1)[0]
    page_html = outside_data(html)
    assert not re.search(r"\b(src|href)\s*=", page_html.split("<body>", 1)[1])
    assert not re.search(r"<(link|iframe|img|video|object|embed)\b", page_html)
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', html)
    assert csp
    assert "http" not in csp.group(1)
    assert "default-src 'none'" in csp.group(1)
    assert "'unsafe-inline'" not in csp.group(1)


def test_the_page_route_sends_the_file_with_no_token(project: Path) -> None:
    server = start_page(project)
    try:
        status, headers, body = request(server, "GET", base(server) + f"api/export/{TEST_ID}")
        assert status == 200
        assert headers["content-disposition"] == f'attachment; filename="{TEST_ID}.html"'
        assert server.token.encode() not in body
        # render.js names 127.0.0.1 in a comment, so check the address of this server.
        assert f"127.0.0.1:{server.server_address[1]}".encode() not in body
        assert data_of(body.decode())["test"]["id"] == TEST_ID
        status, _, _ = request(server, "GET", base(server) + "api/export/no-such-test")
        assert status == 404
        status, _, _ = request(server, "GET", base(server) + "api/export/..%2F..%2Fx")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()


def test_the_command_writes_the_file(
    project: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path_factory.mktemp("share") / "test.html"
    assert cli.main(["export", TEST_ID, "--root", str(project), "--out", str(out)]) == 0
    assert data_of(out.read_text())["test"]["id"] == TEST_ID
    assert f"Wrote test {TEST_ID} to {out}" in capsys.readouterr().out


def test_the_export_does_not_write_into_a_record(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = project / ".nookku" / "tests" / TEST_ID
    relay = folder / "relay.jsonl"
    before = relay.read_bytes()
    # A path in the test folder.
    assert cli.main(["export", TEST_ID, "--root", str(project), "--out", str(relay)]) == 1
    assert "was not written" in capsys.readouterr().err
    # A symlink at the output name that points to a record.
    link = project / "share.html"
    link.symlink_to(relay)
    assert cli.main(["export", TEST_ID, "--root", str(project), "--out", str(link)]) == 1
    assert "not a regular file" in capsys.readouterr().err
    # A folder link into the state folder.
    (project / "out").symlink_to(folder)
    target = project / "out" / "relay.jsonl"
    assert cli.main(["export", TEST_ID, "--root", str(project), "--out", str(target)]) == 1
    # A hard link at the output name: the export replaces the name, not the record.
    hard = project / "hard.html"
    os.link(relay, hard)
    assert cli.main(["export", TEST_ID, "--root", str(project), "--out", str(hard)]) == 0
    assert relay.read_bytes() == before
    assert hard.read_bytes() != before
    assert not any(p.name.endswith(".tmp") for p in project.iterdir())


def test_a_test_with_no_trace_and_no_notes_still_exports(tmp_path: Path) -> None:
    make_test(tmp_path, {**TEST, "turns": TEST["turns"][1:]})
    data = data_of(export.build(tmp_path, tmp_path / ".nookku" / "tests" / TEST_ID).decode())
    assert data["steps"] == {}
    assert data["notes"] == []
    assert data["errors"] == []


def test_a_broken_trace_gives_a_problem_and_no_steps(project: Path) -> None:
    folder = project / ".nookku" / "tests" / TEST_ID
    (folder / "trace.jsonl").write_text("not json\n")
    data = data_of(export.build(project, folder).decode())
    assert data["steps"] == {}
    assert any(e.startswith("trace.jsonl: line 1") for e in data["errors"]), data["errors"]


def test_the_steps_go_to_the_turn_that_the_audit_pairs_with_their_exchange(
    tmp_path: Path,
) -> None:
    # The tap has no exchange for turn 1, so exchange 1 belongs to turn 2.
    folder = toy_shop(tmp_path)
    end_and_build(folder)
    data = data_of(export.build(tmp_path, folder).decode())
    assert "1" not in data["steps"]
    assert shape(data["steps"]["2"]) == expected(1)
    assert shape(data["steps"]["3"]) == expected(2)


def test_a_text_with_u2028_in_the_trace_keeps_its_step(tmp_path: Path) -> None:
    folder = toy_shop(tmp_path)
    end_and_build(folder)
    lines = (folder / "trace.jsonl").read_text(encoding="utf-8").split("\n")
    row = json.loads(lines[0])
    row["output"] = "line one\u2028line two"
    lines[0] = json.dumps(row, ensure_ascii=False)
    (folder / "trace.jsonl").write_text("\n".join(lines), encoding="utf-8")
    data = data_of(export.build(tmp_path, folder).decode())
    outputs = [s["output"] for rows in data["steps"].values() for s in rows]
    assert "line one\u2028line two" in outputs
    assert not data["errors"]


def test_paths_finds_the_file_targets_of_a_reply() -> None:
    text = (
        "![a](images/a.png) [b](<docs/b c.mp4>) ![c](file:///tmp/c.gif) ![d](https://x/d.png) "
        '![e](images/e(1).png) ![f](images/f\\(2\\).png "a title") [g](notes.txt)'
    )
    assert export.paths(text) == [
        "images/a.png", "docs/b c.mp4", "/tmp/c.gif", "images/e(1).png", "images/f(2).png",
    ]  # fmt: skip
    assert export.paths("x" * (export.RENDER_LIMIT + 1) + " ![a](a.png)") == []


def test_a_path_in_plain_text_adds_no_file(project: Path) -> None:
    """Only a Markdown link or image of a reply names a file of the export. A path in the prose
    of a reply does not put the file into the export."""
    assert export.paths("See images/mug.png and <images/mug.png> and [mug] (images/mug.png)") == []
    folder = project / ".nookku" / "tests" / TEST_ID
    data = data_of(export.build(project, folder).decode())
    assert list(data["media"]) == ["images/mug.png", "images/big.png"]


def test_a_number_that_is_not_finite_gives_a_problem_not_a_crash(project: Path) -> None:
    folder = project / ".nookku" / "tests" / TEST_ID
    (folder / "manifest.json").write_text('{"started": NaN, "ended": Infinity}')
    trace = (folder / "trace.jsonl").read_text().replace("1800000001.0", "NaN")
    (folder / "trace.jsonl").write_text(trace)
    (folder / "findings.json").write_text('{"findings": [{"check": "x", "turn": NaN}]}')
    data = data_of(export.build(project, folder).decode())
    assert data["test"]["started"] is None and data["test"]["ended"] is None
    assert data["steps"]["1"][0]["ts"] is None
    assert export.NOT_FINITE in data["errors"]


def test_the_export_defines_each_color_that_its_styles_use(project: Path) -> None:
    html = export.build(project, project / ".nookku" / "tests" / TEST_ID).decode()
    style = re.search(r"<style>(.*?)</style>", html, re.S)
    assert style
    used = set(re.findall(r"var\((--[\w-]+)", style.group(1)))
    defined = set(re.findall(r"(--[\w-]+)\s*:", style.group(1)))
    assert used and used <= defined
    assert "prefers-color-scheme: dark" in style.group(1)


def test_with_no_dir_fd_the_export_writes_nothing(
    project: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A system with no dir_fd (Windows) cannot check the open folder, so the export refuses."""
    monkeypatch.setattr(os, "supports_dir_fd", set())
    out = tmp_path_factory.mktemp("share") / "test.html"
    with pytest.raises(export.ExportError, match="dir_fd"):
        export.write(project, project / ".nookku" / "tests" / TEST_ID, out)
    assert list(out.parent.iterdir()) == []


# The offline tree of render.js and export.js: each source must be a data: URI, and no node may
# have a link.
OFFLINE = """
const render = require(process.argv[2]);
const exp = require(process.argv[3]);
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
exp.start({ media: input.media, big: [] });
const found = [];
function walk(n) {
  if (typeof n === "string") return;
  found.push({ t: n.t, a: n.a });
  for (const c of n.c || []) walk(c);
}
for (const text of input.texts) exp.offline(render.render(text)).forEach(walk);
process.stdout.write(JSON.stringify(found));
"""


@needs_node
def test_the_offline_tree_has_no_link_no_button_and_only_data_sources(tmp_path: Path) -> None:
    script = tmp_path / "offline.js"
    script.write_text(OFFLINE)
    texts = [
        REPLY,
        "![svg](data:image/svg+xml;base64,PHN2Zy8+) ![v](clip.mp4) ![s](images/a.svg)",
        "<https://shop.example> and https://shop.example/x and <mailto:a@b.example>",
        "![p](data:image/png;base64,iVBORw0KGgo=) [x](javascript:alert(1))",
    ]
    media = {"images/mug.png": "data:image/png;base64,AAAA", "clip.mp4": "data:video/mp4;base64,AA"}
    assert NODE is not None
    result = subprocess.run(
        [NODE, str(script), str(PAGE / "render.js"), str(PAGE / "export.js")],
        input=json.dumps({"texts": texts, "media": media}),
        capture_output=True,
        text=True,
        check=True,
    )
    nodes = json.loads(result.stdout)
    assert nodes
    for n in nodes:
        assert n["t"] not in ("a", "button", "iframe")
        assert "href" not in n["a"] and "data-src" not in n["a"]
        if "src" in n["a"]:
            assert n["a"]["src"].startswith("data:")
    shown = [n["a"]["src"] for n in nodes if "src" in n["a"]]
    assert "data:image/png;base64,AAAA" in shown
    assert "data:video/mp4;base64,AA" in shown
    assert "data:image/svg+xml;base64,PHN2Zy8+" in shown
    assert [n["t"] for n in nodes if n["a"].get("src", "").startswith("data:image/svg")] == ["img"]


def test_the_page_has_the_export_button() -> None:
    html = page.page_file("index.html").decode()
    assert 'id="export"' in html
    assert '<script src="export_button.js" defer></script>' in html
    assert "export_button.js" in page.FILES


def test_the_export_script_makes_no_html_from_text() -> None:
    for name in ("export.js", "export_button.js"):
        js = (PAGE / name).read_text()
        assert not re.search(r"https?://", js)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
            assert bad not in js
        assert "new Function" not in js and "DOMParser" not in js
    # The export file loads nothing. The button gets only the export, with the page key that
    # key.js adds (SPEC.md section 5, "Session").
    assert "fetch(" not in (PAGE / "export.js").read_text()
    button = (PAGE / "export_button.js").read_text()
    assert re.findall(r"fetch\(([^,]*),", button) == ['"api/export/" + encodeURIComponent(test)']


def test_an_item_that_is_not_an_object_gives_a_problem(project: Path) -> None:
    folder = project / ".nookku" / "tests" / TEST_ID
    (folder / "audit.json").write_text('{"exit": 1, "breaks": [null, {"class": "x"}]}')
    (folder / "findings.json").write_text('{"findings": ["text"]}')
    data = data_of(export.build(project, folder).decode())
    assert data["breaks"] == [{"class": "x"}]
    assert data["findings"] == []
    assert "audit.json: 1 items of breaks are not JSON objects" in data["errors"]
    assert "findings.json: 1 items of findings are not JSON objects" in data["errors"]


def test_the_hash_of_the_csp_is_of_the_text_with_lf_only(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout on Windows can give the page files CR LF. The HTML parser makes LF of each
    CR LF before the CSP check, so the hash must be of the text with LF."""
    original = page.page_file
    monkeypatch.setattr(page, "page_file", lambda name: original(name).replace(b"\n", b"\r\n"))
    html = export.build(project, project / ".nookku" / "tests" / TEST_ID).decode()
    assert "\r" not in html
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert [export._sha(s) for s in scripts] == [
        export._sha(original(n).decode()) for n in export.SCRIPTS
    ]
    for script in scripts:
        assert export._sha(script) in html

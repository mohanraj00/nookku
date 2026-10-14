"""Tests of the replies of the chat page as Markdown, images, videos and files (#347)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from test_page import base, make_folder, request, start_page, write_current

from nookku import page

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")
RENDER = Path(str(resources.files("nookku").joinpath("page").joinpath("render.js")))

# A small DOM for node: it records each element and each attribute that render.js makes.
HARNESS = """
const render = require(process.argv[1]);
const made = [];
class El {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.kids = []; this.hidden = false;
    made.push(this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  appendChild(c) { this.kids.push(c); return c; }
  append(...cs) { for (const c of cs) this.appendChild(c); }
  addEventListener() {}
  set textContent(v) { this.kids = [{ text: String(v) }]; }
  get textContent() { return this.kids.map((k) => k.text !== undefined ? k.text : k.textContent)
    .join(""); }
}
const doc = { createElement: (t) => new El(t), createTextNode: (t) => ({ text: String(t) }),
  createDocumentFragment: () => new El("#fragment") };
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = {};
if (input.load !== undefined) {
  const button = new El("button");
  button.setAttribute("data-kind", input.load.kind);
  button.setAttribute("data-src", input.load.src);
  button.getAttribute = (k) => button.attrs[k] ?? null;
  button.ownerDocument = doc;
  button.parentNode = { replaceWith: (e) => { out.replaced = e.tag; } };
  render.load(button);
} else if (input.tree !== undefined) {
  render.toDom(input.tree, doc);
} else {
  out.tree = render.render(input.text);
  const li = render.reply(doc, "agent", "agent", input.text);
  out.raw = li.kids[2].textContent;
  out.rawHidden = li.kids[2].hidden;
}
out.made = made.filter((e) => e.tag !== "#fragment")
  .map((e) => ({ tag: e.tag, attrs: e.attrs, props: { className: e.className, type: e.type } }));
process.stdout.write(JSON.stringify(out));
"""

TOY_REPLY = """# Your order at the toy shop

Thanks! Here is **order #4471**, with _2 items_ and `free` shipping.

| Item | Qty | Price |
|:-----|:---:|------:|
| Wooden train | 1 | $24 |
| Kite | 1 | $9 |

1. Pack the order.
2. Ship it.
   - Tracking comes by email.

> Returns are free for 30 days.

![The train](images/train.png)
![How to fly the kite](media/kite.mp4)
![The shop logo](art/logo.svg)
![A banner](https://example.com/banner)
![A dot](data:image/png;base64,iVBORw0KGgo=)

Your receipt: [receipt.pdf](docs/receipt.pdf). Help: [support](https://example.com/help).

```vega-lite
{"mark": "bar"}
```

```mermaid
graph TD; A-->B
```
"""

HOSTILE = """<script>alert(1)</script>
<img src=x onerror="alert(2)">
[click](javascript:alert(3)) [click2](JaVaScRiPt:alert(4)) [click3]( java\tscript:alert(5))
[data](data:text/html,<script>alert(6)</script>)
![x](javascript:alert(7)) ![y](data:text/html;base64,PHNjcmlwdD4=)
<a href="javascript:alert(8)">a</a> <iframe src="javascript:alert(9)"></iframe>
<svg onload=alert(10)></svg>
**<b onmouseover=alert(11)>bold</b>**
| <script>x</script> | h |
|---|---|
| <img onerror=alert(12)> | c |
```html
<script>alert(13)</script>
```
"""


def node(data: dict[str, Any]) -> dict[str, Any]:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "-e", HARNESS, str(RENDER)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    out: dict[str, Any] = json.loads(done.stdout)
    return out


def walk(tree: Any) -> list[dict[str, Any]]:
    """Each element of a tree of render.js."""
    found: list[dict[str, Any]] = []
    for n in tree:
        if isinstance(n, dict):
            found.append(n)
            found.extend(walk(n["c"]))
    return found


def texts(tree: Any) -> str:
    return "".join(n if isinstance(n, str) else texts(n["c"]) for n in tree)


@needs_node
def test_a_reply_with_script_onerror_and_a_script_link_runs_no_script() -> None:
    out = node({"text": HOSTILE})
    tags = {e["tag"] for e in out["made"]}
    assert tags <= {"li", "p", "button", "pre", "div", "a", "strong", "code", "br", "table",
                    "thead", "tbody", "tr", "th", "td"}  # fmt: skip
    assert "script" not in tags and "iframe" not in tags and "img" not in tags
    for e in out["made"]:
        for name, value in e["attrs"].items():
            assert not name.lower().startswith("on"), e
            assert "script" not in value.lower(), e
            if name == "href":
                assert value.startswith(("https:", "http:", "mailto:")), e
    # The HTML of the reply shows as text.
    shown = texts(out["tree"])
    assert "<script>alert(1)</script>" in shown
    assert '<img src=x onerror="alert(2)">' in shown
    assert "<script>alert(13)</script>" in shown
    assert "click" in shown and "click2" in shown


@needs_node
def test_to_dom_drops_a_tag_an_attribute_or_a_url_that_is_not_on_its_list() -> None:
    tree = [
        {"t": "script", "a": {}, "c": ["alert(1)"]},
        {"t": "a", "a": {"href": "javascript:alert(2)", "onclick": "alert(3)"}, "c": ["a"]},
        {"t": "img", "a": {"src": "javascript:alert(4)", "onerror": "alert(5)"}, "c": []},
        {"t": "iframe", "a": {"src": "files/x.svg", "sandbox": "allow-scripts"}, "c": []},
        {"t": "a", "a": {"href": "files/x.pdf"}, "c": []},
    ]
    out = node({"tree": tree})
    made = out["made"]
    assert [e["tag"] for e in made] == ["a", "img", "iframe", "a"]
    assert made[0]["attrs"] == {} and made[1]["attrs"] == {} and made[3]["attrs"] == {}
    assert made[2]["attrs"] == {"src": "files/x.svg", "sandbox": ""}


@needs_node
def test_a_toy_shop_reply_shows_markdown_a_table_media_and_a_file() -> None:
    out = node({"text": TOY_REPLY})
    tree = out["tree"]
    found = walk(tree)
    tags = [e["t"] for e in found]
    for tag in ("h1", "strong", "em", "code", "table", "th", "td", "ol", "ul", "blockquote"):
        assert tag in tags, tag
    th = [e for e in found if e["t"] == "th"]
    assert [e["a"].get("class") for e in th] == ["left", "center", "right"]
    imgs = [e["a"] for e in found if e["t"] == "img"]
    assert imgs[0]["src"] == "files/images%2Ftrain.png" and imgs[0]["alt"] == "The train"
    assert imgs[1]["src"] == "data:image/png;base64,iVBORw0KGgo="
    assert len(imgs) == 2
    videos = [e["a"] for e in found if e["t"] == "video"]
    assert videos == [
        {"src": "files/media%2Fkite.mp4", "controls": "", "preload": "metadata", "class": "media"}
    ]
    frames = [e["a"] for e in found if e["t"] == "iframe"]
    assert len(frames) == 1 and frames[0]["src"] == "files/art%2Flogo.svg"
    assert frames[0]["sandbox"] == ""
    buttons = [e["a"] for e in found if e["t"] == "button"]
    # A web image loads only after a click on its button.
    assert buttons == [
        {
            "type": "button",
            "class": "load",
            "data-kind": "image",
            "data-src": "https://example.com/banner",
            "data-alt": "A banner",
        },
        {"type": "button", "class": "open", "data-path": "docs/receipt.pdf"},
    ]
    links = [e["a"]["href"] for e in found if e["t"] == "a"]
    assert links == ["https://example.com/help"]
    # A chart fence shows as code, with no chart library.
    code = [texts(e["c"]) for e in found if e["t"] == "pre"]
    assert code == ['{"mark": "bar"}', "graph TD; A-->B"]
    langs = [texts(e["c"]) for e in found if e["a"].get("class") == "lang"]
    assert langs == ["vega-lite (shown as code)", "mermaid (shown as code)"]


@needs_node
@pytest.mark.parametrize(
    "text",
    [TOY_REPLY, HOSTILE, "a\r\nb\rc  \n\n\tend ", "Ünïcödé € ₹ \u2028 emoji \U0001f600"],
)
def test_the_text_button_shows_each_byte_of_the_reply(text: str) -> None:
    out = node({"text": text})
    assert out["raw"] == text
    assert out["rawHidden"] is True


@needs_node
def test_a_long_or_deep_reply_does_not_stop_the_page() -> None:
    long = "*" * 200_001
    out = node({"text": long})
    assert out["tree"] == [{"t": "pre", "a": {}, "c": [long]}]
    deep = "> " * 500 + "x\n" + "- " * 500 + "y\n" + "*_" * 5000 + "z" + "_*" * 5000
    out = node({"text": deep})
    assert "x" in texts(out["tree"]) and "z" in texts(out["tree"])
    out = node({"text": "*a " * 20000 + "_b " * 20000})
    assert len(texts(out["tree"])) > 0


# ---- The page server ----


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A project with a test folder and a folder outside the project."""
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    folder = make_folder(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    return root, folder, outside


def get_file(
    server: page.PageServer, path: str, **headers: str
) -> tuple[int, dict[str, str], bytes]:
    from urllib.parse import quote

    return request(server, "GET", base(server) + "files/" + quote(path, safe=""), headers=headers)


def test_the_page_serves_an_image_a_video_and_an_svg_of_the_project(
    project: tuple[Path, Path, Path],
) -> None:
    root, folder, _ = project
    (root / "images").mkdir()
    (root / "images" / "train.png").write_bytes(b"\x89PNG fake")
    (root / "kite.mp4").write_bytes(b"0123456789")
    (root / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'
    )
    (folder / "chart.png").write_bytes(b"chart")
    server = start_page(root)
    try:
        status, headers, body = get_file(server, "images/train.png")
        assert status == 200 and body == b"\x89PNG fake"
        assert headers["content-type"] == "image/png"
        assert headers["x-content-type-options"] == "nosniff"
        # A file answer runs no script, also when a person opens it in a tab.
        assert headers["content-security-policy"] == page.FILE_CSP
        assert "sandbox" in page.FILE_CSP and "script-src" not in page.FILE_CSP
        status, headers, _ = get_file(server, str(root / "logo.svg"))
        assert status == 200 and headers["content-type"] == "image/svg+xml"
        assert headers["content-security-policy"].endswith("sandbox")
        status, headers, body = get_file(server, "kite.mp4", Range="bytes=2-5")
        assert status == 206 and body == b"2345"
        assert headers["content-range"] == "bytes 2-5/10"
        status, _, body = get_file(server, "kite.mp4", Range="bytes=-3")
        assert status == 206 and body == b"789"
        status, headers, _ = get_file(server, "kite.mp4", Range="bytes=20-")
        assert status == 416 and headers["content-range"] == "bytes */10"
        status, _, body = get_file(server, str(folder / "chart.png"))
        assert status == 200 and body == b"chart"
        # The page itself keeps its own strict CSP.
        _, headers, _ = request(server, "GET", base(server))
        assert headers["content-security-policy"] == page.CSP
    finally:
        server.shutdown()
        server.server_close()


def test_a_path_outside_the_project_or_the_test_folder_is_refused(
    project: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, outside = project
    (outside / "secret.png").write_bytes(b"SECRET-BYTES")
    (outside / "secret.pdf").write_bytes(b"SECRET-BYTES")
    (root / "link.png").symlink_to(outside / "secret.png")
    (root / "link.pdf").symlink_to(outside / "secret.pdf")
    (root / ".nookku" / "current.png").write_bytes(b"STATE-BYTES")
    (root / ".nookku" / "current.pdf").write_bytes(b"STATE-BYTES")
    (root / "notes.pdf").write_bytes(b"%PDF")
    (root / "run.sh").write_text("echo hi\n")
    (root / "page.html").write_text("<script>x</script>")
    opened: list[Path] = []
    monkeypatch.setattr(page, "launch", lambda path: opened.append(path))
    names = [
        str(outside / "secret.png"),
        "../outside/secret.png",
        "link.png",
        ".nookku/current.png",
        "notes.pdf",
        "missing.png",
        "",
        "images",
    ]
    server = start_page(root)
    try:
        for name in names:
            status, _, body = get_file(server, name)
            assert status == 404, name
            assert b"SECRET-BYTES" not in body and b"STATE-BYTES" not in body
        for name in (str(outside / "secret.pdf"), "../outside/secret.pdf", "link.pdf",
                     ".nookku/current.pdf", "missing.pdf"):  # fmt: skip
            status, _, body = request(server, "POST", base(server) + "api/open", {"path": name})
            assert status == 403, name
            assert json.loads(body) == {"opened": False, "error": page.OPEN_REFUSED}
        for name in ("run.sh", "page.html"):
            status, _, body = request(server, "POST", base(server) + "api/open", {"path": name})
            assert status == 403 and "does not open a file of the type" in json.loads(body)["error"]
        status, _, _ = request(server, "POST", base(server) + "api/open", {"said": "x"})
        assert status == 400
        assert opened == []
        # A click on the page opens a PDF of the project with the system app.
        status, _, body = request(server, "POST", base(server) + "api/open", {"path": "notes.pdf"})
        assert status == 200 and json.loads(body) == {"opened": True, "error": None}
        # The system app gets a private copy of the checked file.
        assert len(opened) == 1 and opened[0].name == "notes.pdf"
        assert opened[0].read_bytes() == b"%PDF"
        assert not opened[0].is_relative_to(root.resolve())
        assert opened[0].parent.stat().st_mode & 0o077 == 0
    finally:
        server.shutdown()
        server.server_close()


def test_open_needs_the_token_and_the_origin_of_the_page(
    project: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = project
    (root / "notes.pdf").write_bytes(b"%PDF")
    opened: list[Path] = []
    monkeypatch.setattr(page, "launch", lambda path: opened.append(path))
    server = start_page(root)
    try:
        body = {"path": "notes.pdf"}
        assert request(server, "POST", "/p/wrong/api/open", body)[0] == 404
        assert request(server, "POST", base(server) + "api/open", body, {"Origin": ""})[0] == 403
        evil = {"Origin": "http://evil.example"}
        assert request(server, "POST", base(server) + "api/open", body, evil)[0] == 403
        assert request(server, "GET", base(server) + "api/open")[0] == 404
        assert get_file(server, "notes.pdf")[0] == 404
        assert opened == []
    finally:
        server.shutdown()
        server.server_close()


def test_the_running_test_folder_is_allowed_also_outside_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    folder = tmp_path / "elsewhere" / "20261013-090000-ab12"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"started": 1.0, "ended": None}))
    (folder / "shot.png").write_bytes(b"shot")
    write_current(root, folder, "http://127.0.0.1:1", "t")
    server = start_page(root)
    try:
        status, _, body = get_file(server, str(folder / "shot.png"))
        assert status == 200 and body == b"shot"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    ("header", "want"),
    [
        (None, None),
        ("bytes=0-", (0, 9)),
        ("bytes=3-4", (3, 4)),
        ("bytes=8-100", (8, 9)),
        ("bytes=-4", (6, 9)),
        ("bytes=-100", (0, 9)),
        ("bytes=0-1,4-5", None),
        ("items=0-1", None),
    ],
)
def test_byte_range(header: str | None, want: tuple[int, int] | None) -> None:
    assert page.byte_range(header, 10) == want


@pytest.mark.parametrize("header", ["bytes=-", "bytes=10-", "bytes=5-2"])
def test_a_byte_range_that_is_not_valid_raises(header: str) -> None:
    with pytest.raises(ValueError):
        page.byte_range(header, 10)


def test_launch_uses_the_system_app_with_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(page.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(page.subprocess, "Popen", lambda args, **_: calls.append(args))
    monkeypatch.setattr(page.sys, "platform", "darwin")
    assert page.launch(tmp_path / "a.pdf") is None
    monkeypatch.setattr(page.sys, "platform", "linux")
    assert page.launch(tmp_path / "a.pdf") is None
    assert calls == [
        ["/usr/bin/open", str(tmp_path / "a.pdf")],
        ["/usr/bin/xdg-open", str(tmp_path / "a.pdf")],
    ]
    monkeypatch.setattr(page.shutil, "which", lambda name: None)
    assert page.launch(tmp_path / "a.pdf") == page.NO_OPENER.format(name="xdg-open")
    assert os.path.isabs(calls[0][1])


def test_a_file_that_changes_after_the_check_is_refused(
    project: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process of the test can swap a checked path for a link to another file. The server
    checks the open file, so it refuses the file."""
    root, _, outside = project
    (root / "a.png").write_bytes(b"A")
    (root / "b.png").write_bytes(b"B")
    (outside / "secret.png").write_bytes(b"SECRET-BYTES")
    checked = page.allowed_file
    calls: list[str] = []

    def swap(base: Path, name: str) -> Path | None:
        # The first check sees a.png. Then a.png becomes a link to a file outside, and the
        # second check sees b.png.
        calls.append(name)
        if len(calls) % 2 == 1:
            return checked(base, name)
        return checked(base, "b.png")

    monkeypatch.setattr(page, "allowed_file", swap)
    assert page.open_checked(root, "a.png") is None
    monkeypatch.setattr(page, "allowed_file", checked)
    found = page.open_checked(root, "a.png")
    assert found is not None
    os.close(found[0])
    # A symlink at the last part of a checked path does not open.
    real = (root / "a.png").resolve()
    monkeypatch.setattr(page, "allowed_file", lambda base, name: real)
    real.unlink()
    real.symlink_to(outside / "secret.png")
    assert page.open_checked(root, "a.png") is None


@needs_node
@pytest.mark.parametrize(
    ("kind", "src", "want"),
    [
        ("image", "https://example.com/a.png", "img"),
        ("video", "https://example.com/a.mp4", "video"),
        ("svg", "https://example.com/a.svg", "iframe"),
        ("image", "javascript:alert(1)", None),
        ("script", "https://example.com/a.js", None),
    ],
)
def test_a_click_on_load_shows_only_a_web_image_video_or_svg(
    kind: str, src: str, want: str | None
) -> None:
    out = node({"load": {"kind": kind, "src": src}})
    assert out.get("replaced") == want
    made = [e for e in out["made"] if e["tag"] != "button"]
    if want == "iframe":
        assert made[0]["attrs"]["sandbox"] == ""
    if want is None:
        assert made == []

"""Tests of the replies of the chat page as Markdown, images, videos and files (#347)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from test_page import (
    base,
    cookie_only,
    make_folder,
    request,
    session_headers,
    start_page,
    write_current,
)

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
} else if (input.forTest !== undefined) {
  out.tree = render.forTest(input.forTest)(render.render(input.text));
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
    # The span is the label of the button "Text" (#391).
    assert tags <= {"li", "p", "button", "span", "pre", "div", "a", "strong", "code", "br",
                    "table", "thead", "tbody", "tr", "th", "td"}  # fmt: skip
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


@needs_node
@pytest.mark.parametrize(
    "text",
    [
        "[" * 199_000,
        "[a](" * 49_000,
        "[a](<" * 39_000,
        "*a " * 66_000,
        "_a " * 66_000,
        "`a ``b " * 28_000,
        "<" * 199_000,
        "http " * 39_000,
        "- a\n" + "\n" * 100_000 + "  b\n",
        "**[x](a *b _c `d " * 11_000,
        "a|b\n" + " " * 190_000 + "x",
        "# a" + " " * 190_000 + "x",
        "```" + " " * 199_000 + "`",
        "a\n~~~" + " " * 199_000 + "`",
    ],
    # A short id: pytest puts the id in the environment of node, and Linux refuses an
    # environment string over 128 KiB.
    ids=[
        "brackets",
        "links",
        "angles",
        "stars",
        "under",
        "ticks",
        "lt",
        "http",
        "list",
        "mixed",
        "table",
        "heading",
        "fence",
        "fence-in-paragraph",
    ],
)
def test_a_reply_of_many_open_marks_renders_in_linear_time(text: str) -> None:
    """Each of these texts took quadratic time in a first form of the renderer. On a laptop,
    each takes less than 50 ms now. The bound of 5 s includes the start of node."""
    started = time.monotonic()
    node({"text": text})
    assert time.monotonic() - started < 5


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
        # The page asks for a file under the session path, with the session cookie and the page
        # key (key.js). The cookie alone gets nothing.
        both = session_headers(303, headers)
        path = page.SESSION_PATH + "files/images%2Ftrain.png"
        status, _, body = request(server, "GET", path, headers=both)
        assert status == 200 and body == b"\x89PNG fake"
        assert request(server, "GET", path, headers=cookie_only(both))[0] == 404
        assert request(server, "GET", path)[0] == 404
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
    # The page server removes the private copies when it stops.
    assert not opened[0].parent.exists()


def test_a_failed_open_removes_its_copy(
    project: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the system app does not start, no copy stays in the temporary folder."""
    root, _, _ = project
    (root / "notes.pdf").write_bytes(b"%PDF")
    given: list[Path] = []

    def fail(path: Path) -> str:
        given.append(path)
        return "no app"

    monkeypatch.setattr(page, "launch", fail)
    copies: list[Path] = []
    assert page.open_answer(root, {"path": "notes.pdf"}, copies) == (
        500,
        {"opened": False, "error": "no app"},
    )
    assert len(given) == 1 and not given[0].parent.exists()
    assert copies == []


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


@needs_node
def test_for_test_adds_the_encoded_test_id_only_to_a_file_of_the_page_server() -> None:
    """The chat page of a test that the dashboard opened names that test in each file (#398)."""
    out = node({"text": TOY_REPLY, "forTest": "a&b?c d"})
    found = walk(out["tree"])
    sources = [e["a"]["src"] for e in found if "src" in e["a"]]
    query = "?test=a%26b%3Fc%20d"
    assert sources == [
        "files/images%2Ftrain.png" + query,
        "files/media%2Fkite.mp4" + query,
        "files/art%2Flogo.svg" + query,
        "data:image/png;base64,iVBORw0KGgo=",
    ]
    # The change does not change a text of the reply.
    plain = walk(node({"text": TOY_REPLY})["tree"])
    assert [texts(e["c"]) for e in found] == [texts(e["c"]) for e in plain]


def older_test(root: Path, name: str = "20261012-080000-cd34") -> Path:
    """A test that ended before the test of make_folder started."""
    folder = root / ".nookku" / "tests" / name
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"started": 1.0, "ended": 2.0}))
    return folder


def get_test_file(
    server: page.PageServer, path: str, query: str, **headers: str
) -> tuple[int, dict[str, str], bytes]:
    from urllib.parse import quote

    url = base(server) + "files/" + quote(path, safe="") + "?" + query
    return request(server, "GET", url, headers=headers)


def test_a_file_of_an_older_test_opens_from_the_dashboard(
    project: tuple[Path, Path, Path],
) -> None:
    """The dashboard opens the chat page of an older test. The page names that test in the query,
    and the server sends the file of its folder (#398)."""
    root, folder, _ = project
    old = older_test(root)
    (old / "chart.png").write_bytes(b"OLD-CHART")
    (folder / "chart.png").write_bytes(b"NEW-CHART")
    (root / "train.png").write_bytes(b"train")
    query = f"test={old.name}"
    server = start_page(root)
    try:
        # With no test, the server sends only a file of the shown test: the latest test.
        assert get_file(server, str(old / "chart.png"))[0] == 404
        status, headers, body = get_test_file(server, str(old / "chart.png"), query)
        assert status == 200 and body == b"OLD-CHART"
        assert headers["content-security-policy"] == page.FILE_CSP
        status, _, body = get_test_file(server, str(old / "chart.png"), query, Range="bytes=4-")
        assert status == 206 and body == b"CHART"
        # A file of the project still opens.
        assert get_test_file(server, "train.png", query)[2] == b"train"
        # The page of the latest test can name its own test.
        status, _, body = get_test_file(server, str(folder / "chart.png"), f"test={folder.name}")
        assert status == 200 and body == b"NEW-CHART"
        # The page asks under the session path. The cookie and the page key are still necessary.
        _, headers, _ = request(server, "GET", base(server))
        both = session_headers(303, headers)
        name = str(old / "chart.png").replace("/", "%2F")
        path = page.SESSION_PATH + "files/" + name + "?" + query
        status, _, body = request(server, "GET", path, headers=both)
        assert status == 200 and body == b"OLD-CHART"
        wrong = {**cookie_only(both), page.PAGE_HEADER: "x" * len(server.page_key)}
        for headers in (cookie_only(both), {page.PAGE_HEADER: both[page.PAGE_HEADER]}, wrong, {}):
            status, _, body = request(server, "GET", path, headers=headers)
            assert status == 404 and b"OLD-CHART" not in body, headers
        # The Host and Origin checks stay.
        status, _, body = request(server, "GET", path, headers={**both, "Host": "example.com"})
        assert status == 403 and b"OLD-CHART" not in body
        evil = {**both, "Origin": "http://evil.example"}
        assert request(server, "GET", path, headers=evil)[0] == 403
    finally:
        server.shutdown()
        server.server_close()


def test_a_path_outside_the_older_test_folder_is_refused(
    project: tuple[Path, Path, Path],
) -> None:
    root, folder, outside = project
    old = older_test(root)
    (outside / "secret.png").write_bytes(b"SECRET-BYTES")
    (old / "link.png").symlink_to(outside / "secret.png")
    (folder / "shot.png").write_bytes(b"OTHER-TEST")
    (old / "sub").mkdir()
    (old / "sub" / "up.png").symlink_to(folder / "shot.png")
    (root / ".nookku" / "state.png").write_bytes(b"STATE-BYTES")
    (old / "notes.pdf").write_bytes(b"%PDF")
    names = [
        str(outside / "secret.png"),
        str(old / ".." / ".." / ".." / ".." / "outside" / "secret.png"),
        str(old / "link.png"),
        str(old / "sub" / "up.png"),
        # A file of another test folder is in the state folder, so it is refused.
        str(folder / "shot.png"),
        ".nookku/state.png",
        str(old / "notes.pdf"),
        str(old / "missing.png"),
    ]
    server = start_page(root)
    try:
        for name in names:
            status, _, body = get_test_file(server, name, f"test={old.name}")
            assert status == 404, name
            assert b"SECRET" not in body and b"OTHER-TEST" not in body and b"STATE" not in body
    finally:
        server.shutdown()
        server.server_close()


def test_a_bad_or_unknown_test_id_of_a_file_is_refused(
    project: tuple[Path, Path, Path],
) -> None:
    root, folder, outside = project
    (folder / "chart.png").write_bytes(b"CHART")
    (outside / "secret.png").write_bytes(b"SECRET-BYTES")
    # A symlink in the test folders is not a test folder.
    link = "20261011-070000-ef56"
    (root / ".nookku" / "tests" / link).symlink_to(outside)
    chart = str(folder / "chart.png")
    own = f"test={folder.name}"
    bad = ["test=", "x=1", f"{own}&{own}", "test=%00", "test=%FF", f"{own}&x=1", "test", "&"]
    unknown = ["test=nope", "test=..", "test=.", "test=%2E%2E%2Ftests", f"test=..%2F{folder.name}"]
    server = start_page(root)
    try:
        for query in [*bad, f"Test={folder.name}"]:
            status, _, body = get_test_file(server, chart, query)
            assert status == 400, query
            assert b"CHART" not in body
        for query in [*unknown, f"test={link}"]:
            status, _, body = get_test_file(server, chart, query)
            assert status == 404, query
            assert json.loads(body) == {"error": f"nookku page: {page.NO_TEST}"}
        status, _, body = get_test_file(server, str(outside / "secret.png"), f"test={link}")
        assert status == 404 and b"SECRET" not in body
        # Only a file route takes a query.
        for route in ("api/turns", f"api/turns/{folder.name}", "api/tests", ""):
            assert request(server, "GET", base(server) + route + "?" + own)[0] == 404, route
        assert get_test_file(server, chart, own)[2] == b"CHART"
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
    """A process of the test can swap a part of a checked path for a symlink to another place.
    The server opens each part with no symlink, so it refuses the file."""
    root, _, outside = project
    (root / "images").mkdir()
    (root / "images" / "a.png").write_bytes(b"A")
    (outside / "a.png").write_bytes(b"SECRET-BYTES")
    found = page.open_checked(root, "images/a.png")
    assert found is not None
    with os.fdopen(found[0], "rb") as f:
        assert f.read() == b"A"
    checked = (root / "images" / "a.png").resolve()
    monkeypatch.setattr(page, "allowed_file", lambda base, name, shown=None: checked)
    # After the check, the folder becomes a symlink to a folder outside the project.
    (root / "images").rename(root / "old")
    (root / "images").symlink_to(outside)
    assert page.open_checked(root, "images/a.png") is None
    # After the check, the file becomes a symlink to a file outside the project.
    (root / "images").unlink()
    (root / "old").rename(root / "images")
    checked.unlink()
    checked.symlink_to(outside / "a.png")
    assert page.open_checked(root, "images/a.png") is None


def test_a_system_with_no_dir_fd_refuses_the_file(
    project: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no dir_fd, the server cannot check the open file atomically, so it refuses it."""
    root, _, _ = project
    (root / "a.png").write_bytes(b"A")
    monkeypatch.setattr(os, "supports_dir_fd", set())
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
        ("image", "https://127.0.0.1:9999/a.png", None),
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


LOOPBACK = [
    "http://127.0.0.1:9999/p/s/",
    "http://LOCALHOST:9999/p/s/",
    "https://localhost./p/s/",
    "http://shop.localhost:9999/",
    "http://127.1:9999/",
    "http://0x7f000001/",
    "http://127.8.9.10/",
    "http://0.0.0.0:9999/",
    "http://[::1]:9999/",
    "http://[0:0:0:0:0:0:0:1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://[::]:9999/",
]


@needs_node
@pytest.mark.parametrize("url", LOOPBACK)
def test_a_reply_link_or_media_to_a_loopback_host_shows_as_text(url: str) -> None:
    # A cookie has no port: a click on a link to another port of 127.0.0.1 would send the
    # session cookie of the page to it.
    text = f"[status]({url}) <{url}> {url} ![a]({url}x.png) ![b]({url}x.mp4)"
    out = node({"text": text})
    for e in walk(out["tree"]) + [{"a": m["attrs"]} for m in out["made"]]:
        for name in ("href", "src", "data-src"):
            assert name not in e["a"], e
    assert "status" in texts(out["tree"])
    tree = [{"t": "a", "a": {"href": url}, "c": ["a"]}, {"t": "img", "a": {"src": url}, "c": []}]
    made = node({"tree": tree})["made"]
    assert made[0]["attrs"] == {} and made[1]["attrs"] == {}


@needs_node
def test_a_reply_link_to_another_host_stays_a_link() -> None:
    out = node({"text": "[help](https://example.com/help) http://127.0.0.2.example.com/"})
    hrefs = [e["a"]["href"] for e in walk(out["tree"]) if e["t"] == "a"]
    assert hrefs == ["https://example.com/help", "http://127.0.0.2.example.com/"]


# ---- The page key (SPEC.md section 5, "Session") ----

KEY = Path(str(resources.files("nookku").joinpath("page").joinpath("key.js")))
KEY_HARNESS = """
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = { sent: [], replaced: null, stored: null, posted: [] };
const peers = [];
class Channel {
  constructor(name) { this.name = name; this.listeners = []; peers.push(this); }
  addEventListener(kind, f) { this.listeners.push(f); }
  postMessage(data) {
    out.posted.push(data);
    if (data.ask && input.peer) {
      setTimeout(() => this.listeners.forEach((f) => f({ data: { key: input.peer } })), 10);
    }
  }
}
const store = new Map(input.stored ? [["nookku-page-key", input.stored]] : []);
const win = {
  location: { hash: input.hash, pathname: "/p/s/", href: "http://127.0.0.1:5000/p/s/" + input.hash,
    origin: "http://127.0.0.1:5000" },
  history: { replaceState: (a, b, url) => { out.replaced = url; } },
  sessionStorage: input.noStorage ? null : {
    getItem: (k) => store.has(k) ? store.get(k) : null,
    setItem: (k, v) => { store.set(k, v); out.stored = v; },
  },
  BroadcastChannel: Channel, Headers: Headers, setTimeout: setTimeout, clearTimeout: clearTimeout,
  fetch: async (url, init) => {
    const headers = init && init.headers ? Object.fromEntries(new Headers(init.headers)) : {};
    out.sent.push({ url: String(url), key: headers["x-nookku-page"] || null });
    return { ok: true };
  },
};
global.window = win;
require(process.argv[1]);
(async () => {
  await win.fetch("api/turns");
  await win.fetch("https://example.com/x.png");
  // Another tab asks for the key.
  peers[0].listeners.forEach((f) => f({ data: { ask: true } }));
  process.stdout.write(JSON.stringify(out));
})();
"""


def key_node(data: dict[str, Any]) -> dict[str, Any]:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "-e", KEY_HARNESS, str(KEY)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    out: dict[str, Any] = json.loads(done.stdout)
    return out


GIVEN = "A" * 43


@needs_node
def test_the_page_takes_the_key_from_the_fragment_and_sends_it_only_to_its_server() -> None:
    out = key_node({"hash": "#k=" + GIVEN})
    # The fragment goes away from the address bar and the history.
    assert out["replaced"] == "/p/s/"
    assert out["stored"] == GIVEN
    assert out["sent"] == [
        {"url": "api/turns", "key": GIVEN},
        {"url": "https://example.com/x.png", "key": None},
    ]
    # The tab gives the key to a new tab of the same origin.
    assert {"key": GIVEN} in out["posted"]


@needs_node
def test_a_reload_takes_the_key_from_the_session_storage_of_the_tab() -> None:
    out = key_node({"hash": "", "stored": GIVEN})
    assert out["replaced"] is None
    assert out["sent"][0] == {"url": "api/turns", "key": GIVEN}


@needs_node
def test_a_new_tab_asks_an_open_tab_for_the_key() -> None:
    out = key_node({"hash": "", "peer": GIVEN})
    assert {"ask": True} in out["posted"]
    assert out["sent"][0] == {"url": "api/turns", "key": GIVEN}


@needs_node
@pytest.mark.parametrize("hash_", ["", "#k=short", "#20261013-090000-ab12"])
def test_a_tab_with_no_key_sends_no_key(hash_: str) -> None:
    """The server then refuses each request of data with page.NO_KEY. A hash that is not a key,
    for example the test id of the dashboard, stays for app.js."""
    out = key_node({"hash": hash_, "noStorage": True})
    assert out["replaced"] is None
    assert out["sent"][0] == {"url": "api/turns", "key": None}


KEY_FILE_HARNESS = """
const loads = [];
globalThis.NookkuPage = { fileSrc: (e, src) => loads.push({ tag: e.tag, src: src }) };
const render = require(process.argv[1]);
const made = [];
class El {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.kids = []; made.push(this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  appendChild(c) { this.kids.push(c); return c; }
}
const doc = { createElement: (t) => new El(t), createTextNode: (t) => ({ text: String(t) }),
  createDocumentFragment: () => new El("#fragment") };
render.toDom(render.render(require("fs").readFileSync(0, "utf8")), doc);
const media = made.filter((e) => ["img", "video", "iframe"].includes(e.tag));
process.stdout.write(JSON.stringify({ loads: loads, src: media.map((e) => e.attrs.src || null) }));
"""


@needs_node
def test_the_page_loads_a_file_of_its_server_with_the_page_key() -> None:
    """An element cannot send the page key, so key.js loads the file and gives a blob: URL."""
    assert NODE is not None
    text = "![t](images/train.png) ![k](kite.mp4) ![l](logo.svg) ![d](data:image/png;base64,AA==)"
    done = subprocess.run(
        [NODE, "-e", KEY_FILE_HARNESS, str(RENDER)],
        input=text,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    out = json.loads(done.stdout)
    assert out["loads"] == [
        {"tag": "img", "src": "files/images%2Ftrain.png"},
        {"tag": "video", "src": "files/kite.mp4"},
        {"tag": "iframe", "src": "files/logo.svg"},
    ]
    # No element asks the server for a file with the cookie only.
    assert out["src"] == [None, None, None, "data:image/png;base64,AA=="]


UNC = [
    "\\\\host\\share\\a.png",
    "//host/share/a.png",
    "\\/host/share/a.png",
    "/\\host\\share\\a.png",
    "\\\\?\\UNC\\host\\share\\a.png",
]


@needs_node
def test_a_reply_does_not_name_a_network_path_of_windows() -> None:
    """On Windows, a check of a network path (UNC) sends the credentials of the person to the
    host. Thus the page shows such a path as text, and asks the server for no file."""
    assert NODE is not None
    names = [*UNC, "file:////host/share/a.png", "file:///%5C%5Chost/share/a.png"]
    script = (
        "const r = require(process.argv[1]);"
        "const names = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(names.map((n) => r.target(n).kind)));"
    )
    done = subprocess.run(
        [NODE, "-e", script, str(RENDER)],
        input=json.dumps(names),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(done.stdout) == ["none"] * len(names)
    tree = node({"text": "".join(f"![x]({n.replace(chr(92), '/')}) " for n in UNC[:2])})["tree"]
    assert not [e for e in walk(tree) if e["t"] in ("img", "button")]


@pytest.mark.parametrize("name", UNC)
def test_the_server_refuses_a_network_path_before_it_checks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    checked: list[Path] = []
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: checked.append(self))
    assert page.unc(name)
    assert page.allowed_file(tmp_path, name) is None
    assert checked == []
    assert not page.unc("images/train.png") and not page.unc("/tmp/a.png")
    assert not page.unc("C:\\shop\\a.png")


SIZE_HARNESS = """
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = { cancelled: 0, elements: [] };
const win = {
  location: { hash: "#k=" + "A".repeat(43), pathname: "/p/s/", origin: "http://127.0.0.1:5000",
    href: "http://127.0.0.1:5000/p/s/" },
  history: { replaceState: () => {} },
  sessionStorage: null, BroadcastChannel: undefined, Headers: Headers,
  setTimeout: setTimeout, clearTimeout: clearTimeout,
  fetch: async (url) => ({
    ok: true,
    headers: new Headers(
      input.sizes[url] === null ? {} : { "Content-Length": String(input.sizes[url]) }),
    body: { cancel: () => { out.cancelled += 1; } },
    blob: async () => new Blob(["x"]),
  }),
};
global.window = win;
require(process.argv[1]);
(async () => {
  for (const src of Object.keys(input.sizes)) {
    const attrs = { name: src };
    win.NookkuPage.fileSrc({ setAttribute: (k, v) => { attrs[k] = v; } }, src);
    out.elements.push(attrs);
  }
  await new Promise((r) => setTimeout(r, 50));
  process.stdout.write(JSON.stringify(out));
})();
"""


@needs_node
def test_the_page_loads_a_file_only_up_to_its_limits() -> None:
    mib = 1024 * 1024
    sizes = {"f/a.png": 30 * mib, "f/b.mp4": 33 * mib, "f/c.png": None, "f/d.mp4": 30 * mib}
    sizes |= {"f/e.mp4": 30 * mib, "f/f.mp4": 30 * mib, "f/h.mp4": 30 * mib, "f/g.png": 10}
    done = subprocess.run(
        [NODE or "node", "-e", SIZE_HARNESS, str(KEY)],
        input=json.dumps({"sizes": sizes}),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    out = json.loads(done.stdout)
    errors = {e["name"]: e.get("data-error") for e in out["elements"]}
    too_large = "the file is larger than the limit of the page"
    # 32 MiB for one file, 128 MiB for all files, and no size is no load.
    assert errors == {
        "f/a.png": None,
        "f/b.mp4": too_large,
        "f/c.png": too_large,
        "f/d.mp4": None,
        "f/e.mp4": None,
        "f/f.mp4": None,
        "f/h.mp4": too_large,
        "f/g.png": None,
    }
    assert out["cancelled"] == 3

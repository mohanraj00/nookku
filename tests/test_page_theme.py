"""The 2 themes and the keyboard shortcuts of the pages (#355)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from nookku import page

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")
FOLDER = Path(__file__).resolve().parent.parent / "src" / "nookku" / "page"
PAGES = ("index.html", "dashboard.html", "diff.html")
# Each pair of a text color and its background on the pages. WCAG AA asks for 4.5:1.
TEXT_PAIRS = [
    ("fg", "bg"),
    ("fg", "tester"),
    ("fg", "agent"),
    ("fg", "error-bg"),
    ("muted", "bg"),
    ("muted", "agent"),
    ("muted", "tester"),
    ("accent", "bg"),
    ("accent", "agent"),
    ("accent", "tester"),
    ("on-accent", "accent"),
    ("error-fg", "error-bg"),
    ("error-fg", "bg"),
    ("error-fg", "agent"),
    # The chat page (#391).
    ("fg", "surface"),
    ("fg", "raise"),
    ("tester-fg", "tester"),
    ("muted", "surface"),
    ("muted", "raise"),
    ("muted", "ok-bg"),
    ("accent", "surface"),
    ("error-fg", "surface"),
    ("error-fg", "raise"),
    ("accent", "raise"),
    ("ok", "bg"),
    ("ok", "surface"),
    ("ok", "ok-bg"),
    ("warn-fg", "warn-bg"),
    ("error-fg", "surface"),
]
# The border of a control and its background, and the focus ring. WCAG AA asks for 3:1 (1.4.11).
CONTROL_PAIRS = [
    ("control-line", "bg"),
    ("control-line", "surface"),
    # The key help puts the border of a key on raise.
    ("control-line", "raise"),
    # The border of a failed bubble, the alert and the end confirm.
    ("error-line", "surface"),
    ("error-line", "bg"),
    ("focus", "bg"),
    ("focus", "surface"),
]


def block(css: str, selector: str) -> dict[str, str]:
    """The custom properties of the first rule with this selector."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", match.group(1)))


def themes() -> dict[str, dict[str, str]]:
    css = (FOLDER / "theme.css").read_text()
    media = css[css.index("@media (prefers-color-scheme: dark)") :]
    return {
        "light": block(css, ":root"),
        "dark": block(css, ':root[data-theme="dark"]'),
        "system dark": block(media, ':root:not([data-theme="light"])'),
    }


def luminance(color: str) -> float:
    assert re.fullmatch(r"#[0-9a-f]{6}", color), color
    parts = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_2_themes_define_each_color_variable() -> None:
    found = themes()
    assert found["light"].keys() == found["dark"].keys()
    # The dark theme of the system and the dark theme of the switch are the same.
    assert found["dark"] == found["system dark"]
    # Each variable that a page file uses comes from theme.css, and only theme.css defines one.
    for path in FOLDER.glob("*.css"):
        text = path.read_text()
        for name in re.findall(r"var\(--([\w-]+)\)", text):
            assert name in found["light"], (path.name, name)
        if path.name != "theme.css":
            assert not re.search(r"--[\w-]+\s*:", text), path.name


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_each_color_pair_meets_wcag_aa(theme: str) -> None:
    colors = themes()[theme]
    for fg, bg in TEXT_PAIRS:
        assert contrast(colors[fg], colors[bg]) >= 4.5, (theme, fg, bg)
    for fg, bg in CONTROL_PAIRS:
        assert contrast(colors[fg], colors[bg]) >= 3, (theme, fg, bg)


@pytest.mark.parametrize("name", PAGES)
def test_each_page_loads_the_theme_and_the_keys(name: str) -> None:
    html = (FOLDER / name).read_text()
    # theme.js runs in <head> before the first paint. theme.css comes last, so its rules win.
    assert '<script src="theme.js"></script>' in html
    assert '<script src="keys.js" defer></script>' in html
    links = re.findall(r'<link rel="stylesheet" href="([^"]+)">', html)
    assert links[-2:] == ["keys.css", "theme.css"]
    for ref in re.findall(r'(?:src|href)="([^"#]+\.(?:js|css))"', html):
        assert ref in page.FILES, ref
    names = ("theme.css", "theme.js", "keys.css", "keys.js", "search.js", "menu.js", "chat.css")
    for new in (*names, "app.css"):
        text = page.page_file(new).decode()
        assert not re.search(r"https?://", text), new
        for sink in ("innerHTML", "insertAdjacentHTML", "outerHTML", "eval(", "fetch("):
            assert sink not in text, new


@pytest.mark.parametrize("name", PAGES)
def test_each_page_has_the_header_and_the_menu_of_the_chat_page(name: str) -> None:
    """Each page has the same style (#391): app.css first, the header with the mark, and the
    menu with the theme and the width."""
    html = (FOLDER / name).read_text()
    links = re.findall(r'<link rel="stylesheet" href="([^"]+)">', html)
    assert links[0] == "app.css"
    assert '<header class="top">' in html
    assert '<span class="mark" aria-hidden="true">N</span>' in html
    assert '<script src="icons.js" defer></script>' in html
    assert '<script src="menu.js" defer></script>' in html
    picks = {"theme": ["auto", "light", "dark"], "width": ["auto", "narrow", "wide"]}
    for pick, values in picks.items():
        assert re.findall(rf'data-pick="{pick}" data-v="(\w+)"', html) == values


# A small DOM for node. It has only what theme.js and keys.js use.
DOM = """
const events = [];
class Element {
  constructor(tag, id) {
    this.tagName = tag.toUpperCase(); this.id = id || ""; this.kids = []; this.attrs = {};
    this.listeners = {}; this.clicks = 0; this.value = ""; this.type = ""; this.disabled = false;
    this.isContentEditable = false; this.dataset = {}; this.open = false; this.shown = true;
  }
  addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
  append(...kids) { this.kids.push(...kids); }
  click() { this.clicks += 1; }
  focus() { document.activeElement = this; }
  select() {}
  scrollIntoView() {}
  setSelectionRange() {}
  getClientRects() { return this.shown ? [1] : []; }
  hasAttribute(name) { return name in this.attrs; }
  setAttribute(name, value) { this.attrs[name] = value; }
  contains(other) { return other === this; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
global.Element = Element;
global.HTMLTableRowElement = class extends Element {};
const byId = {};
function make(tag, id) { const e = new Element(tag, id); if (id) byId[id] = e; return e; }
const body = make("body");
let items = [];
const listeners = {};
global.window = {};
global.CustomEvent = class {
  constructor(type, init) { this.type = type; this.detail = init.detail; }
};
function told(sent) {
  document.dispatchEvent(new CustomEvent("nookku:send", { detail: { said: "toy shop hi", sent } }));
}
global.document = {
  body: body, activeElement: body, documentElement: { dataset: {} },
  createElement: (tag) => make(tag),
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => (sel === "header" ? byId.header || null : null),
  querySelectorAll: () => items,
  addEventListener: (kind, fn) => { (listeners[kind] = listeners[kind] || []).push(fn); },
  dispatchEvent: (e) => { (listeners[e.type] || []).forEach((fn) => fn(e)); },
};
function fire(target, key, mods) {
  const e = Object.assign({ key: key, target: target, currentTarget: target, shiftKey: false,
    ctrlKey: false, metaKey: false, altKey: false, isComposing: false, keyCode: 0,
    defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } }, mods || {});
  // The event goes to the target, then to the document.
  (target.listeners.keydown || []).forEach((fn) => fn(e));
  e.currentTarget = document;
  (listeners.keydown || []).forEach((fn) => fn(e));
  return e;
}
"""

KEYS_CHECK = """
const said = make("textarea", "said");
const send = make("button", "send");
const search = make("input", "search"); search.type = "search";
const row = make("li"); const row2 = make("li"); const hidden = make("li"); hidden.shown = false;
items = [row, hidden, row2];
require(process.argv[2]);
(listeners.DOMContentLoaded || []).forEach((fn) => fn());
const out = {};
// Enter in the message box sends. Shift+Enter and Enter with Ctrl do not.
fire(said, "Enter"); out.enter = send.clicks;
fire(said, "Enter", { shiftKey: true }); fire(said, "Enter", { ctrlKey: true });
fire(said, "Enter", { isComposing: true }); out.others = send.clicks;
send.disabled = true; fire(said, "Enter"); out.disabled = send.clicks; send.disabled = false;
// No other key sends, in the message box or on the page.
const keys = ["j", "k", "?", "/", " ", "Escape", "ArrowUp", "ArrowDown", "s", "Tab"];
for (const k of keys) { fire(said, k); fire(body, k); fire(send, k); }
out.noSend = send.clicks;
// The ? of the loop opened the list. Close it.
if (body.kids[0]) { body.kids[0].close(); }
// No shortcut works while the tester types in a text field.
const note = make("textarea");
document.activeElement = note;
out.typing = ["j", "k", "?", "/"].map((k) => fire(note, k).defaultPrevented)
  .concat(["j", "?", "/"].map((k) => fire(search, k).defaultPrevented));
out.focusWhileTyping = document.activeElement === note;
// Up puts the last unsent message back in an empty box only.
told(false);
said.value = "draft"; fire(said, "ArrowUp"); out.upFull = said.value;
said.value = ""; fire(said, "ArrowUp"); out.upEmpty = said.value;
told(true);
said.value = ""; fire(said, "ArrowUp"); out.upAfterSent = said.value;
// j and k move over the visible items. / goes to the search. ? opens the list.
document.activeElement = body;
fire(body, "j"); out.j1 = document.activeElement === row;
fire(body, "j"); out.j2 = document.activeElement === row2;
fire(body, "j"); out.j3 = document.activeElement === row2;
fire(body, "k"); out.k1 = document.activeElement === row;
fire(body, "/"); out.slash = document.activeElement === search;
fire(body, "?"); const dialog = body.kids[0]; out.help = Boolean(dialog && dialog.open);
fire(body, "j"); out.jWithHelp = document.activeElement === search;
out.sendAtEnd = send.clicks;
process.stdout.write(JSON.stringify(out));
"""

THEME_CHECK = """
const header = make("header", "header");
Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
require(process.argv[2]);
const out = { start: document.documentElement.dataset.theme || "auto" };
(listeners.DOMContentLoaded || []).forEach((fn) => fn());
const button = header.kids[0].kids[0];
out.label = button.textContent;
const seen = [];
for (let i = 0; i < 3; i += 1) {
  button.listeners.click[0]();
  seen.push(document.documentElement.dataset.theme || "auto");
}
out.seen = seen;
process.stdout.write(JSON.stringify(out));
"""


def run_node(tmp_path: Path, check: str, script: str) -> dict[str, object]:
    harness = tmp_path / "harness.js"
    harness.write_text(DOM + check)
    done = subprocess.run(
        [str(NODE), str(harness), str(FOLDER / script)],
        capture_output=True,
        text=True,
        check=True,
    )
    result: dict[str, object] = json.loads(done.stdout)
    return result


@needs_node
def test_only_enter_in_the_message_box_sends_and_no_key_fires_while_typing(
    tmp_path: Path,
) -> None:
    out = run_node(tmp_path, KEYS_CHECK, "keys.js")
    assert out["enter"] == 1
    assert out["others"] == 1 and out["disabled"] == 1 and out["noSend"] == 1
    assert out["typing"] == [False] * 7 and out["focusWhileTyping"] is True
    assert out["upFull"] == "draft" and out["upEmpty"] == "toy shop hi"
    assert out["upAfterSent"] == ""
    assert out["j1"] and out["j2"] and out["j3"] and out["k1"]
    assert out["slash"] and out["help"] and out["jWithHelp"]
    assert out["sendAtEnd"] == 1


@needs_node
def test_the_theme_switch_works_if_the_browser_refuses_the_storage(tmp_path: Path) -> None:
    out = run_node(tmp_path, THEME_CHECK, "theme.js")
    assert out["start"] == "auto" and out["label"] == "Theme: auto"
    assert out["seen"] == ["light", "dark", "auto"]


PICKS_CHECK = """
Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
const picks = [];
for (const [pick, v] of [["theme", "auto"], ["theme", "light"], ["theme", "dark"],
    ["width", "auto"], ["width", "narrow"], ["width", "wide"]]) {
  const b = make("button"); b.dataset.pick = pick; b.dataset.v = v; picks.push(b);
}
items = picks;
const header = make("header", "header");
require(process.argv[2]);
const out = { start: Object.assign({}, document.documentElement.dataset) };
(listeners.DOMContentLoaded || []).forEach((fn) => fn());
out.button = header.kids.length;
const checked = () => picks.map((b) => b.attrs["aria-checked"]);
out.before = checked();
picks[2].listeners.click[0]();
picks[4].listeners.click[0]();
out.dark = Object.assign({}, document.documentElement.dataset);
out.after = checked();
picks[0].listeners.click[0]();
picks[3].listeners.click[0]();
out.auto = Object.assign({}, document.documentElement.dataset);
const key = (b, k) => {
  const e = { key: k, stopped: false, preventDefault() { this.stopped = true; } };
  b.listeners.keydown[0](e);
  return e.stopped;
};
out.keys = [key(picks[0], "ArrowRight"), key(picks[1], "ArrowLeft"), key(picks[0], "ArrowLeft"),
  key(picks[3], "End"), key(picks[5], "Home"), key(picks[3], "a")];
out.byKeys = checked();
out.focus = picks.indexOf(document.activeElement);
process.stdout.write(JSON.stringify(out));
"""


@needs_node
def test_the_menu_sets_the_theme_and_the_width_if_the_browser_refuses_the_storage(
    tmp_path: Path,
) -> None:
    out = run_node(tmp_path, PICKS_CHECK, "theme.js")
    # Auto is the default of both. A page with the menu gets no "Theme" button.
    assert out["start"] == {} and out["button"] == 0
    assert out["before"] == ["true", "false", "false", "true", "false", "false"]
    assert out["dark"] == {"theme": "dark", "width": "narrow"}
    assert out["after"] == ["false", "false", "true", "false", "true", "false"]
    assert out["auto"] == {}
    # The arrow keys move in one group and go round. Home and End go to the ends.
    # Another key does nothing.
    assert out["keys"] == [True, True, True, True, True, False]
    assert out["byKeys"] == ["false", "false", "true", "true", "false", "false"]
    assert out["focus"] == 3


def test_the_chat_page_has_the_menu_of_the_theme_and_the_width() -> None:
    html = (FOLDER / "index.html").read_text()
    picks = re.findall(r'data-pick="(\w+)" data-v="(\w+)"', html)
    assert picks == [
        ("theme", "auto"), ("theme", "light"), ("theme", "dark"),
        ("width", "auto"), ("width", "narrow"), ("width", "wide"),
    ]  # fmt: skip
    # The page does not say "byte for byte" to the tester (#391).
    assert "byte for byte" not in html

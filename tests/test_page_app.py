"""Tests of the script of the chat page, app.js, in node with a small DOM (#327, #391)."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")
APP = Path(str(resources.files("nookku").joinpath("page").joinpath("app.js")))

DOM = """
const ids = {};
const listeners = {};
const events = [];
class ClassList {
  constructor(el) { this.el = el; }
  get list() { return this.el.className.split(" ").filter(Boolean); }
  add(c) { if (!this.contains(c)) this.el.className = [...this.list, c].join(" "); }
  remove(c) { this.el.className = this.list.filter((x) => x !== c).join(" "); }
  toggle(c, on) { if (on === undefined) on = !this.contains(c); on ? this.add(c) : this.remove(c); }
  contains(c) { return this.list.includes(c); }
}
class El {
  constructor(tag, id) {
    this.tag = tag; this.kids = []; this.dataset = {}; this.listeners = {}; this.hidden = false;
    this.value = ""; this.disabled = false; this.text = ""; this.className = ""; this.attrs = {};
    this.parent = null; this.style = {}; this.scrollHeight = 50;
    this.scrollTop = 0; this.title = "";
    this.classList = new ClassList(this);
    if (id) { ids[id] = this; this.id = id; }
  }
  set textContent(v) { this.kids = []; this.text = String(v); }
  get textContent() { return this.text + this.kids.map((k) => k.textContent).join(""); }
  append(...cs) { for (const c of cs) { c.parent = this; this.kids.push(c); } }
  prepend(...cs) { for (const c of cs) c.parent = this; this.kids.unshift(...cs); }
  before(...cs) {
    const at = this.parent.kids.indexOf(this);
    for (const c of cs) c.parent = this.parent;
    this.parent.kids.splice(at, 0, ...cs);
  }
  replaceChildren(...cs) { this.kids = []; this.text = ""; this.append(...cs); }
  remove() { if (this.parent) this.parent.kids = this.parent.kids.filter((k) => k !== this); }
  get lastElementChild() { return this.kids[this.kids.length - 1] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
  click() { (this.listeners.click || []).forEach((fn) => fn()); }
  focus() {}
  setSelectionRange() {}
  querySelector() { return null; }
}
// All nodes below a node, the node first.
function walk(n, out) { out = out || []; out.push(n); (n.kids || []).forEach((k) => walk(k, out));
  return out; }
function find(n, cls) { return walk(n).filter((k) => k.classList && k.classList.contains(cls)); }
for (const id of ["test", "pill", "start", "end", "empty", "endcard", "turns", "error",
    "error-text", "error-close", "banner", "banner-text", "said", "send", "bridge", "count", "box",
    "endbar", "foot", "scroll", "save-script", "export", "end-test", "end-test-menu",
    "endconfirm"]) {
  new El(id === "said" ? "textarea" : "div", id);
}
global.document = {
  getElementById: (id) => ids[id],
  createElement: (tag) => new El(tag),
  createTextNode: (text) => { const n = new El("#text"); n.text = String(text); return n; },
  querySelectorAll: () => [],
  addEventListener: (kind, fn) => { (listeners[kind] = listeners[kind] || []).push(fn); },
  dispatchEvent: (e) => { events.push(e); (listeners[e.type] || []).forEach((fn) => fn(e)); },
};
global.window = { location: { hash: "" }, addEventListener: () => {} };
global.CustomEvent = class {
  constructor(type, init) { this.type = type; this.detail = init.detail; }
};
// Each call of parts records the test of its change, or null if it has no change (#398).
const changes = [];
global.NookkuRender = { forTest: (id) => ({ test: id }), parts: (doc, text, change) => {
  changes.push(change === undefined ? null : change.test);
  const shown = new El("div"); shown.textContent = text;
  const raw = new El("pre"); raw.textContent = text; raw.hidden = true;
  return { toggle: new El("button"), shown: shown, raw: raw };
} };
// The first timer of app.js is its poll. A check calls timer() to start a new poll.
let timer = null;
global.setInterval = (fn) => { if (timer === null) timer = fn; return 0; };
// Each fetch waits until the check resolves it.
const pending = [];
global.fetch = (url, init) => new Promise((resolve, reject) => {
  pending.push({ url: url, init: init, answer: (data) => resolve({ json: async () => data }),
    fail: () => reject(new Error("no answer")) });
});
const tick = () => new Promise((r) => setTimeout(r, 0));
const ticks = async () => { for (let i = 0; i < 4; i += 1) await tick(); };
const TEST = { id: "t1", running: true, started: 1, ended: null };
function answer(list, test) {
  return { error: null, test: test === undefined ? TEST : test, turns: list };
}
function turns(n) {
  const list = [];
  for (let i = 0; i < n; i += 1) {
    list.push({ said: "hi " + i, shown: "reply " + i, ok: true, harness: "pane" });
  }
  return answer(list);
}
function type(text) { ids.said.value = text; (ids.said.listeners.input || []).forEach((f) => f()); }
require(process.argv[1]);
(listeners.DOMContentLoaded || []).forEach((fn) => fn());
"""


def run(check: str) -> dict[str, Any]:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "-e", DOM + "(async () => {\nconst out = {};\n" + check + "\n"
         "process.stdout.write(JSON.stringify(out));\n})();",
         str(APP)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    out: dict[str, Any] = json.loads(done.stdout)
    return out


ANSWERS_CHECK = """
// The first poll starts at DOMContentLoaded. A send starts a second request, and its end starts
// a third poll. The answer of the first poll comes last.
const poll1 = pending.shift();
type("hi 2");
ids.send.listeners.click[0]();
await tick();
const sent = pending.shift();
sent.answer({ sent: true, ok: true, shown: "reply 2" });
await ticks();
const poll2 = pending.shift();
poll2.answer(turns(3));
await ticks();
out.afterNew = ids.turns.kids.length;
const block = ids.turns.kids[0];
// The old answer of the first poll comes now, with fewer turns.
poll1.answer(turns(1));
await ticks();
out.afterOld = ids.turns.kids.length;
out.sameBlock = ids.turns.kids[0] === block;
"""

FAILED_POLL_CHECK = """
// The first poll waits. A send starts a second request, and its end starts a third poll,
// which fails. Then the old answer of the first poll comes.
const poll1 = pending.shift();
type("hi 2");
ids.send.listeners.click[0]();
await tick();
pending.shift().answer({ sent: true, ok: true, shown: "reply 2" });
await ticks();
const turnsAfterSend = ids.turns.kids.length;
pending.shift().fail();
await ticks();
out.error = ids["banner-text"].textContent;
out.bannerShown = !ids.banner.hidden;
poll1.answer(turns(1));
await ticks();
out.errorAfterOld = ids["banner-text"].textContent;
out.sameTurns = ids.turns.kids.length === turnsAfterSend;
// A later poll that succeeds removes the banner.
timer();
pending.shift().answer(turns(1));
await ticks();
out.bannerAfter = ids.banner.hidden;
"""

DRAFT_CHECK = """
pending.shift().answer(turns(0));
await tick();
for (const typed of [null, "the next message"]) {
  type("hi");
  ids.send.listeners.click[0]();
  await tick();
  // The tester types during the send.
  if (typed !== null) ids.said.value = typed;
  pending.shift().answer({ sent: true, ok: true, shown: "reply" });
  await ticks();
  pending.shift().answer(turns(1));
  await ticks();
  out[typed === null ? "unchanged" : "typed"] = ids.said.value;
}
"""

STATE = """
const state = () => ({
  pill: ids.pill.textContent, pillClass: ids.pill.className, empty: ids.empty.hidden ? null :
    ids.empty.dataset.kind, emptyText: ids.empty.textContent, box: !ids.box.hidden,
  endbar: !ids.endbar.hidden, said: !ids.said.disabled, bridge: ids.bridge.textContent,
  bridgeTitle: ids.bridge.title, end: ids.end.hidden ? null : ids.end.textContent,
  card: ids.endcard.hidden ? null : ids.endcard.textContent, save: !ids["save-script"].disabled,
  test: ids.test.textContent, turns: ids.turns.kids.length,
  endTest: [!ids["end-test"].hidden, !ids["end-test-menu"].hidden] });
"""


def run_polls(*answers: str, extra: str = "") -> dict[str, Any]:
    lines = [STATE]
    for i, data in enumerate(answers):
        if i > 0:
            lines.append("timer();")
        lines.append(f"pending.shift().answer({data});\nawait ticks();\nout.s{i} = state();")
    return run("\n".join(lines) + "\n" + extra)


@needs_node
def test_an_old_poll_answer_does_not_make_the_chat_again() -> None:
    out = run(ANSWERS_CHECK)
    # 3 turns: one block for each turn.
    assert out["afterNew"] == 3
    assert out["afterOld"] == 3 and out["sameBlock"] is True


@needs_node
def test_a_send_keeps_the_text_that_the_tester_typed_during_the_send() -> None:
    out = run(DRAFT_CHECK)
    assert out["unchanged"] == ""
    assert out["typed"] == "the next message"


@needs_node
def test_an_old_poll_answer_after_a_failed_poll_keeps_the_error() -> None:
    out = run(FAILED_POLL_CHECK)
    assert str(out["error"]).startswith("The page server does not answer")
    assert "nookku chat" in str(out["error"]) and out["bannerShown"] is True
    assert out["errorAfterOld"] == out["error"]
    assert out["sameTurns"] is True and out["bannerAfter"] is True


@needs_node
def test_the_header_the_box_and_the_empty_states_follow_the_test() -> None:
    ended = '{ id: "t1", running: false, started: 1000, ended: 1000 + 28 * 60 + 31 }'
    out = run_polls(
        "answer([], null)",
        "answer([])",
        "turns(2)",
        f"answer(turns(2).turns, {ended})",
        extra=(
            'document.dispatchEvent(new CustomEvent("nookku:notes", { detail: '
            '{ test: "t1", up: 1, down: 0, comments: 1 } }));\nout.notes = state();'
        ),
    )
    none, first, chat, end = out["s0"], out["s1"], out["s2"], out["s3"]
    assert (none["pill"], none["pillClass"], none["empty"]) == ("No test", "pill none", "none")
    assert "nookku start" in none["emptyText"] and none["said"] is False
    assert none["bridge"] == "Bridge mode off" and none["save"] is False
    assert (first["pill"], first["pillClass"], first["empty"]) == ("Running", "pill run", "first")
    assert first["bridge"] == "Bridge mode on" and first["said"] is True
    assert first["bridgeTitle"] == (
        "The agent gets each message as you typed it. The harness model does not see it."
    )
    assert "byte for byte" not in first["emptyText"]
    assert chat["empty"] is None and chat["turns"] == 2 and chat["test"] == "t1"
    assert (end["pill"], end["box"], end["endbar"], end["said"]) == ("Ended", False, True, False)
    assert end["end"].startswith("Test ended at ") and end["card"].startswith("This test ended")
    assert "2 turns" in end["card"] and "28 min 31 s" in end["card"]
    # "End test" shows only while the shown test runs (#391).
    assert none["endTest"] == end["endTest"] == [False, False]
    assert first["endTest"] == chat["endTest"] == [True, True]
    assert "type the prompt nookku end in the harness" in end["card"]
    assert "1 thumbs up" in out["notes"]["card"] and "1 comment" in out["notes"]["card"]


TURNS = """answer([
  { said: "<img src=x onerror=alert(1)>", shown: "reply", ok: true, harness: "pane" },
  { said: "Where is order 1042?", shown: "It shipped.", ok: true, harness: "claude-code" },
  { said: "hi", shown: "nookku: the tap does not answer.", ok: false, harness: "pane" },
  { said: "Hello?", shown: null, ok: null, harness: "codex" },
  { said: "x", shown: "y", ok: true, harness: "script" },
])"""

TURNS_CHECK = """
const li = ids.turns.kids;
out.ids = li.map((t) => [t.dataset.turn, t.dataset.test]);
out.bubble = find(li[0], "bubble")[0].textContent;
out.sources = li.map((t) => find(t, "src")[0].textContent);
out.states = li.map((t) => find(t, "state")[0].textContent);
out.who = li.map((t) => find(t, "who").map((w) => w.textContent).join(""));
out.failed = li[2].kids[0].className;
out.sys = find(li[2], "sys")[0].textContent;
out.quiet = find(li[3], "quiet")[0].textContent;
out.slots = li.map((t) => Object.keys(t._slots).sort().join(","));
// "Put back in the box" puts the exact text back in an empty box only.
const back = find(li[2], "outline")[0];
ids.said.value = "draft";
back.click();
out.full = ids.said.value;
ids.said.value = "";
back.click();
out.empty = ids.said.value;
"""


@needs_node
def test_each_turn_shows_its_source_its_state_and_its_text() -> None:
    out = run_polls(TURNS, extra=TURNS_CHECK)
    assert out["ids"] == [[str(n), "t1"] for n in range(1, 6)]
    # The text goes in as text, with no change.
    assert out["bubble"] == "<img src=x onerror=alert(1)>"
    assert out["sources"] == ["page", "Claude Code", "page", "Codex", "script"]
    assert out["states"] == ["Sent", "Sent", "Not sent", "Sent", "Sent"]
    assert out["who"][0] == "Agentturn 1 · shown on this page only"
    assert out["who"][1] == "Agentturn 2" and out["who"][4] == "Agentturn 5"
    assert out["who"][2] == "" and out["who"][3] == ""
    assert out["failed"] == "msg failed"
    assert out["sys"] == "nookku: the tap does not answer.Put back in the box"
    assert out["quiet"] == "The relay showed no reply for this turn."
    assert set(out["slots"]) == {
        "noteBox,notes,panel,sent,steps,time",
        "noteBox,notes,panel,sent,steps",
    }
    assert out["full"] == "draft" and out["empty"] == "hi"


SEND_CHECK = """
const sendEvents = () => events.filter((e) => e.type === "nookku:send").map((e) => e.detail);
type("toy shop hi");
out.enabled = !ids.send.disabled;
ids.send.listeners.click[0]();
await tick();
out.busy = ids.send.className;
out.pending = ids.turns.kids.map((t) => t.className);
out.sending = find(ids.turns.kids[0], "state")[0].textContent;
out.wait = find(ids.turns.kids[0], "wait")[0].textContent;
const req = pending.shift();
out.body = JSON.parse(req.init.body);
req.answer({ sent: false, ok: false, shown: "nookku: no test runs. Nothing was sent." });
await ticks();
out.error = ids["error-text"].textContent;
out.errorShown = !ids.error.hidden;
out.afterBusy = ids.send.className;
out.afterPending = ids.turns.kids.length;
pending.shift().answer(turns(0));
await ticks();
// A turn with ok: false is in the record, but it did not reach the agent.
type("hi again");
ids.send.listeners.click[0]();
await tick();
pending.shift().answer({ sent: true, ok: false, shown: "nookku: the tap does not answer." });
await ticks();
out.error2 = ids["error-text"].textContent;
out.events = sendEvents();
ids["error-close"].listeners.click[0]();
out.closed = ids.error.hidden;
"""


@needs_node
def test_a_send_shows_its_state_and_a_failed_send_shows_the_error() -> None:
    out = run_polls("answer([])", extra=SEND_CHECK)
    assert out["enabled"] is True
    assert "busy" in out["busy"] and out["pending"] == ["turn pending"]
    assert out["sending"] == "Sending" and out["wait"] == "0 s since the send"
    assert out["body"] == {"said": "toy shop hi", "test": "t1"}
    assert out["error"] == "nookku: no test runs. Nothing was sent." and out["errorShown"]
    assert "busy" not in out["afterBusy"] and out["afterPending"] == 0
    assert out["error2"] == "nookku: the tap does not answer."
    assert out["events"] == [
        {"said": "toy shop hi", "sent": False},
        {"said": "hi again", "sent": False},
    ]
    assert out["closed"] is True


@needs_node
def test_the_count_shows_code_points_and_the_box_grows_to_its_limit() -> None:
    out = run_polls(
        "answer([])",
        extra=(
            'ids.said.scrollHeight = 900; type("€ \U0001f600");\n'
            "out.count = ids.count.textContent; out.height = ids.said.style.height;\n"
            'type(""); out.none = ids.count.textContent; out.off = ids.send.disabled;'
        ),
    )
    assert out["count"] == "3 characters" and out["height"] == "240px"
    assert out["none"] == "" and out["off"] is True


FILE_TEST_CHECK = """
pending.shift().answer(turns(2));
await ticks();
out.noHash = changes.splice(0);
// The dashboard opens the page of a test with #<test id>.
window.location.hash = "#t1";
timer();
const poll = pending.shift();
out.url = poll.url;
poll.answer(answer([{ said: "hi", shown: "![train](train.png)", ok: true, harness: "pane" }]));
await ticks();
out.withHash = changes.splice(0);
"""


@needs_node
def test_a_page_that_the_dashboard_opened_names_its_test_in_each_file() -> None:
    """The dashboard opens the page of an older test. Each file of a reply then names that test,
    because the file route serves only the shown test without it (#398)."""
    out = run(FILE_TEST_CHECK)
    assert out["noHash"] == [None, None]
    assert out["url"] == "api/turns/t1"
    assert out["withHash"] == ["t1"]

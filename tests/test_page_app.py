"""Tests of the script of the chat page, app.js, in node with a small DOM."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pytest

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")
APP = Path(str(resources.files("nookku").joinpath("page").joinpath("app.js")))

DOM = """
const ids = {};
const listeners = {};
class El {
  constructor(tag, id) {
    this.tag = tag; this.kids = []; this.dataset = {}; this.listeners = {}; this.hidden = false;
    this.value = ""; this.disabled = false; this.textContent = "";
    if (id) ids[id] = this;
  }
  append(...cs) { this.kids.push(...cs); }
  replaceChildren() { this.kids = []; }
  remove() {}
  get lastElementChild() { return this.kids[this.kids.length - 1]; }
  addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
}
for (const [tag, id] of [["p", "test"], ["p", "start"], ["p", "end"], ["ol", "turns"],
    ["p", "error"], ["textarea", "said"], ["button", "send"]]) {
  new El(tag, id);
}
global.document = {
  getElementById: (id) => ids[id],
  createElement: (tag) => new El(tag),
  addEventListener: (kind, fn) => { (listeners[kind] = listeners[kind] || []).push(fn); },
  dispatchEvent: () => {},
  body: { scrollHeight: 0 },
};
global.window = { location: { hash: "" }, scrollTo: () => {}, addEventListener: () => {} };
global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init; } };
global.NookkuRender = { reply: () => new El("li") };
global.setInterval = () => 0;
// Each fetch waits until the check resolves it.
const pending = [];
global.fetch = (url, init) => new Promise((resolve) => {
  pending.push({ url: url, init: init, answer: (data) => resolve({ json: async () => data }) });
});
const tick = () => new Promise((r) => setTimeout(r, 0));
function turns(n) {
  const list = [];
  for (let i = 0; i < n; i += 1) {
    list.push({ said: "hi " + i, shown: "reply " + i, ok: true, harness: "pane" });
  }
  return { error: null, test: { id: "t1", running: true, started: 1, ended: null }, turns: list };
}
require(process.argv[1]);
(listeners.DOMContentLoaded || []).forEach((fn) => fn());
"""


def run(check: str) -> dict[str, object]:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "-e", DOM + check, str(APP)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    out: dict[str, object] = json.loads(done.stdout)
    return out


ANSWERS_CHECK = """
(async () => {
  const out = {};
  // The first poll starts at DOMContentLoaded. A send starts a second request, and its end starts
  // a third poll. The answer of the first poll comes last.
  const poll1 = pending.shift();
  ids.said.value = "hi 2";
  ids.send.listeners.click[0]();
  await tick();
  const sent = pending.shift();
  sent.answer({ sent: true, ok: true, shown: "reply 2" });
  await tick(); await tick();
  const poll2 = pending.shift();
  poll2.answer(turns(3));
  await tick(); await tick();
  out.afterNew = ids.turns.kids.length;
  const block = ids.turns.kids[0];
  // The old answer of the first poll comes now, with fewer turns.
  poll1.answer(turns(1));
  await tick(); await tick();
  out.afterOld = ids.turns.kids.length;
  out.sameBlock = ids.turns.kids[0] === block;
  process.stdout.write(JSON.stringify(out));
})();
"""

DRAFT_CHECK = """
(async () => {
  const out = {};
  pending.shift().answer(turns(0));
  await tick();
  for (const typed of [null, "the next message"]) {
    ids.said.value = "hi";
    ids.send.listeners.click[0]();
    await tick();
    // The tester types during the send.
    if (typed !== null) ids.said.value = typed;
    pending.shift().answer({ sent: true, ok: true, shown: "reply" });
    await tick(); await tick();
    pending.shift().answer(turns(1));
    await tick(); await tick();
    out[typed === null ? "unchanged" : "typed"] = ids.said.value;
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


@needs_node
def test_an_old_poll_answer_does_not_make_the_chat_again() -> None:
    out = run(ANSWERS_CHECK)
    # 3 turns: 3 tester blocks and 3 reply blocks.
    assert out["afterNew"] == 6
    assert out["afterOld"] == 6 and out["sameBlock"] is True


@needs_node
def test_a_send_keeps_the_text_that_the_tester_typed_during_the_send() -> None:
    out = run(DRAFT_CHECK)
    assert out["unchanged"] == ""
    assert out["typed"] == "the next message"

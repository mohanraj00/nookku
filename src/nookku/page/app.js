// The chat page of nookku (#327, #391). Each text of the agent or the tester goes into the page
// with textContent, or as DOM nodes from render.js (#347), never as HTML, so that a reply cannot
// run code on the page. The page sends each message as the tester typed it, byte for byte.
"use strict";
const POLL_MS = 1000;
// The highest box for a message, in pixels: about 10 lines.
const BOX_MAX = 240;
let shownCount = 0;
let shownTest = null;
let sending = false;
// The test of the last answer, and the counts of the notes of notes.js.
let shownData = null;
let counts = null;
// The error of the last poll, if any. The banner shows it. A later poll that succeeds removes it.
let pollError = null;
// The number of the last poll, and of the last poll that the page showed. An answer can come
// after the answer of a later poll. The page shows only an answer of a later poll, so that an
// old answer does not make the chat again (and remove a comment that the tester types).
let pollCount = 0;
let shownPoll = 0;
// The start of the send that runs, for the seconds of the wait.
let sendStart = 0;

const SOURCES = {
  pane: ["chat", "page"],
  "claude-code": ["term", "Claude Code"],
  codex: ["term", "Codex"],
  script: ["script", "script"],
};
const BRIDGE_ON = "The agent gets each message as you typed it. The harness model does not see it.";

function el(id) {
  return document.getElementById(id);
}

function make(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) {
    node.className = cls;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function icon(name) {
  return typeof NookkuIcons !== "undefined" ? [NookkuIcons.icon(name)] : [];
}

function button(cls, text, iconName) {
  const node = make("button", "btn " + cls);
  node.type = "button";
  node.append(...(iconName ? icon(iconName) : []));
  if (text) {
    node.append(make("span", null, text));
  }
  return node;
}

function clock(ts) {
  return typeof ts === "number" ? new Date(ts * 1000).toLocaleTimeString() : null;
}

function when(ts) {
  return typeof ts === "number" ? new Date(ts * 1000).toLocaleString() : null;
}

function length(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) {
    return s + " s";
  }
  const m = Math.floor(s / 60);
  return m < 60 ? m + " min " + (s % 60) + " s" : Math.floor(m / 60) + " h " + (m % 60) + " min";
}

function plural(n, one, many) {
  return n + " " + (n === 1 ? one : many);
}

// ---- Copy ----

// Copy a text to the clipboard in the click handler, and show the result on the button.
function copyText(target, text) {
  const words = target.querySelector ? target.querySelector("span") : null;
  const before = words ? words.textContent : target.getAttribute("aria-label");
  function show(result) {
    if (words) {
      words.textContent = result;
    } else {
      target.setAttribute("aria-label", result);
      target.title = result;
    }
    target.classList.add("done");
    setTimeout(() => {
      if (words) {
        words.textContent = before;
      } else {
        target.setAttribute("aria-label", before);
        target.title = before;
      }
      target.classList.remove("done");
    }, 1500);
  }
  let copied;
  try {
    copied = navigator.clipboard.writeText(text);
  } catch (e) {
    copied = Promise.reject(e);
  }
  copied.then(
    () => show("Copied"),
    () => show("Copy failed"),
  );
}

// ---- Turns ----

// The message of the tester: a bubble, its source, its time and its state.
function testerNode(said, harness, state) {
  const box = make("div", "msg" + (state === "sent" ? "" : " " + state));
  const bubble = make("pre", "bubble", said);
  const meta = make("div", "meta");
  const [iconName, label] = SOURCES[harness] || ["term", harness];
  const src = make("span", "src");
  src.append(...icon(iconName), make("span", null, label));
  const sent = make("span", "t-num");
  const tag = make("span", "state");
  if (state === "sending") {
    tag.append(make("span", "spin"), make("span", null, "Sending"));
  } else if (state === "failed") {
    tag.classList.add("bad");
    tag.append(...icon("alert"), make("span", null, "Not sent"));
  } else {
    tag.classList.add("ok");
    tag.append(...icon("check"), make("span", null, "Sent"));
  }
  meta.append(src, sent, tag);
  box.append(bubble, meta);
  return { node: box, sent: sent };
}

// The tool row of a turn: the slots of notes.js and trace.js, with the buttons between them.
function toolRow(middle) {
  const row = make("div", "tools");
  const notes = make("span", "slot");
  const steps = make("span", "slot");
  row.append(notes, ...middle, make("span", "gap"), steps);
  return { row: row, notes: notes, steps: steps };
}

// The reply of the agent: an avatar, no bubble, and the tool row under it.
function agentNode(turn, number) {
  const box = make("div", "agent");
  const avatar = make("div", "avatar");
  avatar.append(...icon("bot"));
  const reply = make("div", "reply");
  const who = make("div", "who", "Agent");
  const small = make("small", "t-num", "turn " + number);
  const time = make("span");
  small.append(time);
  if (turn.harness === "pane") {
    small.append(document.createTextNode(" · shown on this page only"));
  }
  who.append(small);
  const parts = NookkuRender.parts(document, turn.shown);
  parts.toggle.classList.add("btn");
  parts.toggle.prepend(...icon("text"));
  const copy = button("icon copy", "", "copy");
  copy.setAttribute("aria-label", "Copy the exact text");
  copy.title = "Copy the exact text";
  copy.addEventListener("click", () => copyText(copy, turn.shown));
  const tools = toolRow([parts.toggle, copy]);
  const noteBox = make("div");
  const panel = make("div");
  reply.append(who, parts.shown, parts.raw, tools.row, noteBox, panel);
  box.append(avatar, reply);
  return { node: box, time: time, tools: tools, noteBox: noteBox, panel: panel };
}

// Put the text of a failed message back in an empty message box, as the Up key does.
function putBack(said, note) {
  const box = el("said");
  if (box.value !== "") {
    note.textContent = "Empty the message box first.";
    box.focus();
    return;
  }
  note.textContent = "";
  box.value = said;
  box.focus();
  box.setSelectionRange(said.length, said.length);
  boxChanged();
}

// A turn where the relay could not send the message (`ok: false`), or showed no reply.
function relayNode(turn) {
  const box = make("div");
  if (turn.shown === null) {
    box.className = "quiet";
    box.append(...icon("alert"), make("span", null, "The relay showed no reply for this turn."));
    return box;
  }
  box.className = "sys";
  const body = make("div");
  const act = make("div", "act");
  const back = button("outline", "Put back in the box");
  const note = make("span", "note");
  note.setAttribute("role", "status");
  back.addEventListener("click", () => putBack(turn.said, note));
  act.append(back, note);
  body.append(make("pre", null, turn.shown), act);
  box.append(...icon("alert"), body);
  return box;
}

function turnNode(turn, number, test) {
  const li = make("li", "turn");
  li.dataset.turn = String(number);
  li.dataset.test = test;
  const failed = turn.ok === false && turn.shown !== null;
  const tester = testerNode(turn.said, turn.harness, failed ? "failed" : "sent");
  li.append(tester.node);
  // notes.js and trace.js fill these slots (#352, #353).
  const slots = { sent: tester.sent };
  if (turn.shown !== null && turn.ok !== false) {
    const agent = agentNode(turn, number);
    li.append(agent.node);
    Object.assign(slots, {
      time: agent.time,
      notes: agent.tools.notes,
      steps: agent.tools.steps,
      noteBox: agent.noteBox,
      panel: agent.panel,
    });
  } else {
    const tools = toolRow([]);
    const noteBox = make("div");
    const panel = make("div");
    li.append(relayNode(turn), tools.row, noteBox, panel);
    Object.assign(slots, { notes: tools.notes, steps: tools.steps, noteBox, panel });
  }
  li._slots = slots;
  return li;
}

// The message that waits for its reply: a spinner, 3 dots, the seconds since the send, and the
// live trace rows of trace.js.
function pendingNode(said) {
  const li = make("li", "turn pending");
  const tester = testerNode(said, "pane", "sending");
  const box = make("div", "agent");
  const avatar = make("div", "avatar");
  avatar.append(...icon("bot"));
  const reply = make("div", "reply");
  const who = make("div", "who", "Agent");
  who.append(make("small", null, "waiting for the reply"));
  const dots = make("span", "dots");
  dots.setAttribute("aria-hidden", "true");
  dots.append(make("i"), make("i"), make("i"));
  const wait = make("span", "wait t-num", "0 s since the send");
  wait.id = "wait";
  const panel = make("div");
  reply.append(who, dots, wait, panel);
  box.append(avatar, reply);
  li.append(tester.node, box);
  li._slots = { panel: panel };
  return li;
}

function tick() {
  const wait = el("wait");
  if (wait && sending) {
    wait.textContent = Math.floor((Date.now() - sendStart) / 1000) + " s since the send";
  }
}

// ---- The states of the page ----

function emptyState(kind) {
  const box = el("empty");
  if (kind === null) {
    box.hidden = true;
    box.replaceChildren();
    return;
  }
  if (box.dataset.kind === kind && !box.hidden) {
    return;
  }
  box.dataset.kind = kind;
  const glyph = make("div", "glyph");
  if (kind === "none") {
    glyph.append(...icon("flag"));
    const cmd = make("span", "cmd", "nookku start ");
    const copy = button("outline", "Copy", "copy");
    copy.addEventListener("click", () => copyText(copy, "nookku start"));
    cmd.append(copy);
    box.replaceChildren(
      glyph,
      make("h2", null, "No test runs"),
      make("p", null, "Start a test in the harness. This page then shows it."),
      cmd,
    );
  } else {
    glyph.append(...icon("chat"));
    const keys = make("div", "keys");
    for (const [names, text] of [
      [["Enter"], " sends"],
      [["Shift", "Enter"], " adds a line"],
      [["↑"], " gets back an unsent message"],
    ]) {
      const item = make("span");
      names.forEach((name, i) => {
        item.append(...(i > 0 ? [document.createTextNode(" ")] : []), make("kbd", null, name));
      });
      item.append(document.createTextNode(text));
      keys.append(item);
    }
    const rule = make("p", "small");
    rule.append(
      ...icon("lock"),
      document.createTextNode(
        " Bridge mode is on. The agent gets your message as you typed it. The harness model " +
          "does not see it.",
      ),
    );
    box.replaceChildren(
      glyph,
      make("h2", null, "Send the first message to the agent"),
      make("p", null, "Write the message as a user of the agent."),
      keys,
      rule,
    );
  }
  box.hidden = false;
}

function endCard(test, turns) {
  const card = el("endcard");
  const stats = [plural(turns, "turn", "turns")];
  if (counts && counts.test === test.id) {
    stats.push(plural(counts.up, "thumbs up", "thumbs up"));
    stats.push(plural(counts.down, "thumbs down", "thumbs down"));
    stats.push(plural(counts.comments, "comment", "comments"));
  }
  if (typeof test.started === "number" && typeof test.ended === "number") {
    stats.push(length(test.ended - test.started));
  }
  const key = JSON.stringify([test.id, test.ended, stats]);
  if (card.dataset.key === key && !card.hidden) {
    return;
  }
  card.dataset.key = key;
  const row = make("div", "stats");
  row.append(...stats.map((s) => make("span", null, s)));
  const actions = make("div", "row2");
  const exportButton = button("primary", "Export", "export");
  exportButton.addEventListener("click", () => el("export").click());
  const saveButton = button("outline", "Save as script", "script");
  saveButton.addEventListener("click", () => el("save-script").click());
  const all = make("a", "btn outline");
  all.href = "dashboard.html";
  all.append(...icon("list"), make("span", null, "All tests"));
  actions.append(exportButton, saveButton, all);
  const ended = typeof test.ended === "number";
  const parts = [make("h3", null, ended ? "This test ended" : "This test stopped"), row, actions];
  if (ended) {
    // The prompt starts the evaluation of the latest test of the tester (SPEC.md section 9.1).
    parts.push(
      make(
        "p",
        "endnote",
        "To evaluate the latest test, type the prompt nookku end in the harness. " +
          "This also stops this page.",
      ),
    );
  }
  card.replaceChildren(...parts);
  card.hidden = false;
}

// The header, the message box and the bar at the end, for a test that runs, that ended, or for
// no test.
function showState(test, turns) {
  const pill = el("pill");
  const running = Boolean(test && test.running);
  const ended = Boolean(test && !test.running);
  if (!test) {
    pill.className = "pill none";
    pill.textContent = "No test";
  } else if (running) {
    pill.className = "pill run";
    pill.textContent = "Running";
  } else {
    pill.className = "pill end";
    pill.textContent = typeof test.ended === "number" ? "Ended" : "Stopped";
  }
  const id = el("test");
  id.textContent = test ? test.id : "";
  id.title = test ? test.id : "";
  for (const name of ["save-script", "export"]) {
    el(name).disabled = !test;
  }
  for (const mirror of document.querySelectorAll("#menu [data-click]")) {
    mirror.disabled = !test;
  }
  // "End test" ends only the shown test, and only while it runs (end_button.js).
  el("end-test").hidden = !running;
  el("end-test-menu").hidden = !running;
  if (!running) {
    el("endconfirm").hidden = true;
  }
  el("box").hidden = ended;
  el("foot").hidden = ended;
  el("endbar").hidden = !ended;
  const said = el("said");
  said.disabled = !running;
  said.placeholder = running ? "Message the agent" : "Start a test to send a message";
  const bridge = el("bridge");
  bridge.className = running ? "bridge" : "bridge off";
  bridge.textContent = running ? "Bridge mode on" : "Bridge mode off";
  bridge.title = running ? BRIDGE_ON : "No test runs, so the page sends nothing.";
  if (!test) {
    emptyState("none");
  } else if (running && turns === 0 && !sending) {
    emptyState("first");
  } else {
    emptyState(null);
  }
  if (ended) {
    endCard(test, turns);
  } else {
    el("endcard").hidden = true;
  }
  el("send").disabled = sending || !running || said.value === "";
}

function showSendError(text) {
  el("error-text").textContent = text || "";
  el("error").hidden = !text;
}

function pollResult(error) {
  pollError = error || null;
  el("banner-text").textContent = pollError || "";
  el("banner").hidden = pollError === null;
}

function scrollDown() {
  const scroll = el("scroll");
  scroll.scrollTop = scroll.scrollHeight;
}

function render(data) {
  pollResult(data.error);
  const test = data.test;
  shownData = data;
  // save.js, export_button.js and trace.js read the id of the test that the page shows. If the
  // shown test changes, close the confirm of "End test": it was for the test before.
  const shownId = test ? test.id : "";
  if (el("test").dataset.id !== shownId) {
    el("endconfirm").hidden = true;
  }
  el("test").dataset.id = shownId;
  const list = el("turns");
  if (!test) {
    el("start").hidden = true;
    el("end").hidden = true;
    list.replaceChildren();
    shownCount = 0;
    shownTest = null;
    showState(null, 0);
    return;
  }
  const started = clock(test.started);
  el("start").textContent = started ? "Test started at " + started : "Test started";
  el("start").title = when(test.started) || "";
  el("start").hidden = false;
  const ended = clock(test.ended);
  el("end").textContent = ended ? "Test ended at " + ended : "Test stopped";
  el("end").title = when(test.ended) || "";
  el("end").hidden = test.running;
  if (test.id !== shownTest || data.turns.length < shownCount) {
    list.replaceChildren();
    shownCount = 0;
    shownTest = test.id;
  }
  let number = shownCount;
  const added = [];
  for (const turn of data.turns.slice(shownCount)) {
    number += 1;
    added.push(turnNode(turn, number, test.id));
  }
  if (added.length > 0) {
    // The message that waits stays the last item of the list.
    const waiting = list.lastElementChild;
    if (waiting && waiting.classList.contains("pending")) {
      waiting.before(...added);
    } else {
      list.append(...added);
    }
    shownCount = data.turns.length;
  }
  showState(test, data.turns.length);
  if (added.length > 0) {
    scrollDown();
  }
}

// The dashboard opens the page of one test with #<test id> (#349). The page then shows that
// test. It can send only if that test runs.
function turnsUrl() {
  let id = "";
  try {
    id = decodeURIComponent(window.location.hash.slice(1));
  } catch (e) {
    id = window.location.hash.slice(1);
  }
  return id ? "api/turns/" + encodeURIComponent(id) : "api/turns";
}

async function refresh() {
  pollCount += 1;
  const poll = pollCount;
  try {
    const url = turnsUrl();
    const resp = await fetch(url, { cache: "no-store" });
    const data = await resp.json();
    // The hash can change during the request. Then a later request shows the new test.
    if (url === turnsUrl() && poll > shownPoll) {
      shownPoll = poll;
      render(data);
    }
  } catch (e) {
    if (poll > shownPoll) {
      // An older poll that answers later must not hide this error or show older turns.
      shownPoll = poll;
      pollResult(
        "The page server does not answer. The page tries again each second. To start it " +
          "again, run nookku chat in a separate terminal.",
      );
    }
  }
}

// keys.js keeps the last message that the page did not send, for the Up key (#355).
function tellSend(said, sent) {
  document.dispatchEvent(new CustomEvent("nookku:send", { detail: { said: said, sent: sent } }));
}

// The box grows with its text, from 1 line to about 10 lines.
function boxChanged() {
  const box = el("said");
  if (box.style) {
    box.style.height = "auto";
    const full = box.scrollHeight || 0;
    box.style.height = Math.min(full, BOX_MAX) + "px";
    // Show a scroll bar only when the text is longer than the box.
    box.style.overflowY = full > BOX_MAX ? "auto" : "hidden";
  }
  const n = Array.from(box.value).length;
  el("count").textContent = n === 0 ? "" : plural(n, "character", "characters");
  const running = Boolean(shownData && shownData.test && shownData.test.running);
  el("send").disabled = sending || !running || box.value === "";
}

function busy(on) {
  const send = el("send");
  send.classList.toggle("busy", on);
  send.setAttribute("aria-label", on ? "Sending" : "Send");
}

async function send() {
  const box = el("said");
  const said = box.value;
  if (sending || said === "") {
    return;
  }
  sending = true;
  sendStart = Date.now();
  el("send").disabled = true;
  busy(true);
  showSendError("");
  const pending = pendingNode(said);
  el("turns").append(pending);
  emptyState(null);
  scrollDown();
  try {
    const resp = await fetch("api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // The server sends only if the test that the page shows still runs.
      body: JSON.stringify({ said: said, test: shownTest }),
    });
    const data = await resp.json();
    // A turn with `ok: false` did not reach the agent, so Up can put it back.
    tellSend(said, Boolean(data.sent) && data.ok !== false);
    if (data.sent) {
      // The tester can type the next message during the send. Keep that text.
      if (box.value === said) {
        box.value = "";
      }
    }
    if (!data.sent || data.ok === false) {
      showSendError(data.shown || data.error || "nookku: nothing was sent.");
    }
  } catch (e) {
    tellSend(said, false);
    showSendError("nookku: the page server does not answer. Nothing was sent.");
  } finally {
    pending.remove();
    sending = false;
    busy(false);
    boxChanged();
    await refresh();
  }
}

document.addEventListener("nookku:notes", (e) => {
  counts = e.detail || null;
  if (shownData && shownData.test && !shownData.test.running) {
    endCard(shownData.test, shownData.turns.length);
  }
});

// end_button.js ended the test. Show the end now, not at the next poll.
document.addEventListener("nookku:ended", () => refresh());

document.addEventListener("DOMContentLoaded", () => {
  el("send").addEventListener("click", send);
  el("said").addEventListener("input", boxChanged);
  // keys.js puts a message back with the Up key, with no input event.
  el("said").addEventListener("keyup", boxChanged);
  el("error-close").addEventListener("click", () => showSendError(""));
  for (const copy of document.querySelectorAll("[data-copy]")) {
    copy.addEventListener("click", () => copyText(copy, copy.dataset.copy));
  }
  window.addEventListener("hashchange", refresh);
  refresh();
  setInterval(refresh, POLL_MS);
  setInterval(tick, 1000);
});

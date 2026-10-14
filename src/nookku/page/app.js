// The chat page of nookku (#327). Each text of the agent or the tester goes into the page with
// textContent, never as HTML, so that a reply cannot run code on the page.
"use strict";

const POLL_MS = 1000;
let shownCount = 0;
let shownTest = null;
let sending = false;
// The error of the last poll, if any. A later poll that succeeds removes it, but not the error
// of a send.
let pollError = null;

function el(id) {
  return document.getElementById(id);
}

function block(cls, who, text) {
  const li = document.createElement("li");
  li.className = "turn " + cls;
  const label = document.createElement("p");
  label.className = "who";
  label.textContent = who;
  const body = document.createElement("pre");
  body.className = "text";
  body.textContent = text;
  li.append(label, body);
  return li;
}

function when(ts) {
  return typeof ts === "number" ? new Date(ts * 1000).toLocaleString() : null;
}

function showError(text) {
  const box = el("error");
  box.textContent = text || "";
  box.hidden = !text;
}

function pollResult(error) {
  if (error) {
    pollError = error;
    showError(error);
  } else if (pollError !== null) {
    pollError = null;
    showError("");
  }
}

function render(data) {
  pollResult(data.error);
  const test = data.test;
  const list = el("turns");
  if (!test) {
    el("test").textContent = "No test yet. Start one in the harness with: nookku start";
    el("start").hidden = true;
    el("end").hidden = true;
    el("send").disabled = true;
    list.replaceChildren();
    shownCount = 0;
    shownTest = null;
    return;
  }
  el("test").textContent = test.running
    ? "Test " + test.id + " runs."
    : "Test " + test.id + " ended. Start a new test in the harness with: nookku start";
  const started = when(test.started);
  el("start").textContent = "The test started" + (started ? " at " + started : "") + ".";
  el("start").hidden = false;
  const ended = when(test.ended);
  el("end").textContent = "The test ended" + (ended ? " at " + ended : "") + ".";
  el("end").hidden = test.running;
  if (test.id !== shownTest || data.turns.length < shownCount) {
    list.replaceChildren();
    shownCount = 0;
    shownTest = test.id;
  }
  let number = shownCount;
  for (const turn of data.turns.slice(shownCount)) {
    number += 1;
    const sender = turn.harness === "script" ? "script" : "tester";
    list.append(block("tester", sender + " (" + turn.harness + ")", turn.said));
    if (turn.shown === null) {
      list.append(block("relay-error", "relay", "(the relay showed no reply)"));
    } else if (turn.ok === false) {
      list.append(block("relay-error", "relay error", turn.shown));
    } else {
      list.append(block("agent", "agent", turn.shown));
    }
    // notes.js puts the note controls of the turn on this block (#352).
    list.lastElementChild.dataset.turn = String(number);
  }
  if (data.turns.length > shownCount) {
    shownCount = data.turns.length;
    window.scrollTo(0, document.body.scrollHeight);
  }
  el("send").disabled = sending || !test.running;
}

async function refresh() {
  try {
    const resp = await fetch("api/turns", { cache: "no-store" });
    render(await resp.json());
  } catch (e) {
    pollError = "nookku: the page server does not answer. Start it again with: nookku page";
    showError(pollError);
  }
}

async function send() {
  const box = el("said");
  const said = box.value;
  if (sending || said === "") {
    return;
  }
  sending = true;
  el("send").disabled = true;
  // The box now shows the result of this send, so a later poll must not remove it.
  pollError = null;
  showError("");
  const pending = block("tester pending", "tester (sending)", said);
  el("turns").append(pending);
  try {
    const resp = await fetch("api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ said: said }),
    });
    const data = await resp.json();
    // A poll can fail while the send waits. The result of the send replaces its error.
    pollError = null;
    if (data.sent) {
      box.value = "";
    } else {
      showError(data.shown || data.error || "nookku: nothing was sent.");
    }
  } catch (e) {
    showError("nookku: the page server does not answer. Nothing was sent.");
  } finally {
    pending.remove();
    sending = false;
    await refresh();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  el("send").addEventListener("click", send);
  refresh();
  setInterval(refresh, POLL_MS);
});

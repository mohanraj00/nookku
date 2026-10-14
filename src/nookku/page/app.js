// The chat page of nookku (#327). Each text of the agent or the tester goes into the page with
// textContent, or as DOM nodes from render.js (#347), never as HTML, so that a reply cannot run
// code on the page.
"use strict";

const POLL_MS = 1000;
let shownCount = 0;
let shownTest = null;
let sending = false;
// The error of the last poll, if any. A later poll that succeeds removes it, but not the error
// of a send.
let pollError = null;
// The number of the last poll, and of the last poll that the page showed. An answer can come
// after the answer of a later poll. The page shows only an answer of a later poll, so that an
// old answer does not make the chat again (and remove a comment that the tester types).
let pollCount = 0;
let shownPoll = 0;

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
  // save.js reads the id of the test that the page shows.
  el("test").dataset.id = test ? test.id : "";
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
      list.append(NookkuRender.reply(document, "agent", "agent", turn.shown));
    }
    // notes.js puts the note controls of the turn on this block (#352), and trace.js puts the
    // trace steps of the turn after it (#353).
    list.lastElementChild.dataset.turn = String(number);
    list.lastElementChild.dataset.test = test.id;
  }
  if (data.turns.length > shownCount) {
    shownCount = data.turns.length;
    window.scrollTo(0, document.body.scrollHeight);
  }
  el("send").disabled = sending || !test.running;
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
      pollError = "nookku: the page server does not answer. Start it again with: nookku page";
      showError(pollError);
    }
  }
}

// keys.js keeps the last message that the page did not send, for the Up key (#355).
function tellSend(said, sent) {
  document.dispatchEvent(new CustomEvent("nookku:send", { detail: { said: said, sent: sent } }));
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
      // The server sends only if the test that the page shows still runs.
      body: JSON.stringify({ said: said, test: shownTest }),
    });
    const data = await resp.json();
    // A poll can fail while the send waits. The result of the send replaces its error.
    pollError = null;
    tellSend(said, Boolean(data.sent));
    if (data.sent) {
      // The tester can type the next message during the send. Keep that text.
      if (box.value === said) {
        box.value = "";
      }
    } else {
      showError(data.shown || data.error || "nookku: nothing was sent.");
    }
  } catch (e) {
    tellSend(said, false);
    showError("nookku: the page server does not answer. Nothing was sent.");
  } finally {
    pending.remove();
    sending = false;
    await refresh();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  el("send").addEventListener("click", send);
  window.addEventListener("hashchange", refresh);
  refresh();
  setInterval(refresh, POLL_MS);
});

// The diff page of nookku (#351): 2 tests side by side, turn by turn. The hash is
// #<old test id>/<new test id>. Each text goes into the page with textContent, never as HTML.
"use strict";

function el(id) {
  return document.getElementById(id);
}

function showError(text) {
  el("error-text").textContent = text || "";
  el("error").hidden = !text;
}

// The class of the pill of each state. A state that is not here shows as "none".
const STATE_PILL = { running: "run", ended: "end", stopped: "warn" };

function pill(text, kind) {
  const node = document.createElement("span");
  node.className = "pill " + (kind || "none");
  node.textContent = text;
  return node;
}

function cell(text, cls) {
  const td = document.createElement("td");
  td.textContent = text;
  if (cls) {
    td.className = cls;
  }
  return td;
}

function pillCell(state) {
  const td = document.createElement("td");
  td.append(pill(state, STATE_PILL[state]));
  return td;
}

// A count, or a dash if the test has no such file. A count above 0 shows as a problem.
function countCell(value) {
  if (typeof value !== "number") {
    return cell("-", "num");
  }
  return cell(String(value), value > 0 ? "num bad" : "num");
}

function testRow(side, test) {
  const tr = document.createElement("tr");
  const name = cell(test.id);
  for (const text of test.errors) {
    const problem = document.createElement("span");
    problem.className = "problem";
    problem.textContent = text;
    name.append(problem);
  }
  tr.append(
    cell(side),
    name,
    pillCell(test.state),
    cell(typeof test.turns === "number" ? String(test.turns) : "-", "num"),
    countCell(test.breaks),
    countCell(test.findings),
  );
  return tr;
}

function element(tag, text, cls) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (cls) {
    node.className = cls;
  }
  return node;
}

// One side of a turn: the equal words, and the deleted (old side) or inserted (new side) words.
function side(title, said, reply, words, mark) {
  const box = element("div", "", "side");
  box.append(element("h3", title));
  if (said === null) {
    box.append(element("p", "This test has no such turn.", "reply missing"));
    return box;
  }
  if (reply === null) {
    box.append(element("p", "No reply in the tap record.", "reply missing"));
    return box;
  }
  const text = element("p", "", "reply");
  for (const [op, part] of words) {
    if (op === "equal") {
      text.append(document.createTextNode(part));
    } else if (op === mark) {
      text.append(element(op === "delete" ? "del" : "ins", part));
    }
  }
  box.append(text);
  return box;
}

function turnItem(turn, oldId, newId) {
  const li = element("li", "", turn.changed ? "turn changed" : "turn");
  const head = element("h2", "Turn " + turn.n + " ");
  head.append(pill(turn.changed ? "Changed" : "Same", turn.changed ? "bad" : "ok"));
  li.append(head);
  if (turn.said_old === null || turn.said_new === null) {
    const only = turn.said_old === null ? newId : oldId;
    li.append(element("p", "Only test " + only + " has this turn.", "said"));
  }
  if (turn.said_changed && turn.said_old !== null && turn.said_new !== null) {
    li.append(element("p", "Message of " + oldId + ": " + turn.said_old, "said"));
    li.append(element("p", "Message of " + newId + ": " + turn.said_new, "said"));
  } else {
    li.append(element("p", "Message: " + (turn.said_old ?? turn.said_new), "said"));
  }
  const sides = element("div", "", "sides");
  sides.append(
    side("Old: " + oldId, turn.said_old, turn.reply_old, turn.words, "delete"),
    side("New: " + newId, turn.said_new, turn.reply_new, turn.words, "insert"),
  );
  li.append(sides);
  return li;
}

function ids() {
  const parts = window.location.hash.slice(1).split("/");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    return null;
  }
  try {
    return parts.map(decodeURIComponent);
  } catch (e) {
    return null;
  }
}

async function load() {
  el("tests").replaceChildren();
  el("turns").replaceChildren();
  el("summary").textContent = "";
  const hash = window.location.hash;
  const pair = ids();
  if (pair === null) {
    showError("nookku: select 2 tests on the dashboard to compare them.");
    return;
  }
  try {
    const resp = await fetch("api/diff/" + pair.map(encodeURIComponent).join("/"), {
      cache: "no-store",
    });
    const data = await resp.json();
    // The hash can change during the request. Then the request of the new hash shows its diff.
    if (hash !== window.location.hash) {
      return;
    }
    if (!data.old || !data.new) {
      showError(data.error || "nookku: the page server gave no diff.");
      return;
    }
    el("tests").replaceChildren(testRow("Old", data.old), testRow("New", data.new));
    if (data.error) {
      showError(data.error);
      return;
    }
    showError("");
    const n = data.turns.length;
    el("summary").textContent = data.changed + " of " + n + (n === 1 ? " turn" : " turns") + " changed.";
    el("turns").replaceChildren(...data.turns.map((t) => turnItem(t, data.old.id, data.new.id)));
  } catch (e) {
    if (hash !== window.location.hash) {
      return;
    }
    showError("nookku: the page server does not answer. Start it again with: nookku page");
  }
}

document.addEventListener("DOMContentLoaded", load);
window.addEventListener("hashchange", load);

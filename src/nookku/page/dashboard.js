// The dashboard of nookku (#349): one row for each test of the project. The server applies the
// filters and the sort. Each text goes into the page with textContent, never as HTML.
"use strict";

const POLL_MS = 5000;

function el(id) {
  return document.getElementById(id);
}

function showError(text) {
  el("error-text").textContent = text || "";
  el("error").hidden = !text;
}

// The class of the pill of each state and each seal. A value that is not here shows as "none".
const STATE_PILL = { running: "run", ended: "end", stopped: "warn" };
const SEAL_PILL = { intact: "ok", broken: "bad", unknown: "warn" };

// A cell with the value in a pill.
function pillCell(text, kind) {
  const td = document.createElement("td");
  const pill = document.createElement("span");
  pill.className = "pill " + (kind || "none");
  pill.textContent = text;
  td.append(pill);
  return td;
}

// With no rows, the page shows an empty state in place of the table.
function showEmpty(n) {
  const filtered = el("state").value !== "all" || el("has").value !== "all";
  el("empty").hidden = n !== 0;
  el("table").hidden = n === 0;
  el("empty-title").textContent = filtered ? "No test matches the filters" : "No tests yet";
  el("empty-text").textContent = filtered
    ? "Change the State or the Show filter to see more tests."
    : "To start a test, run this in the harness:";
  el("empty-cmd").hidden = filtered;
}

function when(ts) {
  return typeof ts === "number" ? new Date(ts * 1000).toLocaleString() : "-";
}

function cell(text, cls) {
  const td = document.createElement("td");
  td.textContent = text;
  if (cls) {
    td.className = cls;
  }
  return td;
}

// A count, or a dash if the test has no such file. A count above 0 shows as a problem.
function countCell(value) {
  if (typeof value !== "number") {
    return cell("-", "num");
  }
  return cell(String(value), value > 0 ? "num bad" : "num");
}

// The chat page of the test. It is read-only if the test does not run.
function open(id) {
  window.location.href = "./#" + encodeURIComponent(id);
}

function testRow(test) {
  const tr = document.createElement("tr");
  tr.tabIndex = 0;
  // keys.js finds the row of the same test again after a poll (#355).
  tr.dataset.id = test.id;
  tr.title = "Open the chat page of this test";
  const name = cell(test.id);
  for (const text of test.errors) {
    const problem = document.createElement("span");
    problem.className = "problem";
    problem.textContent = text;
    name.append(problem);
  }
  tr.append(
    pickCell(test),
    name,
    cell(when(test.started)),
    pillCell(test.state, STATE_PILL[test.state]),
    cell(typeof test.turns === "number" ? String(test.turns) : "-", "num"),
    countCell(test.breaks),
    countCell(test.findings),
    pillCell(test.seal, SEAL_PILL[test.seal]),
  );
  tr.addEventListener("click", () => open(test.id));
  tr.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      open(test.id);
    }
  });
  return tr;
}

function apiUrl() {
  return "api/tests/" + [el("state").value, el("has").value, el("order").value].join("/");
}

async function refresh() {
  try {
    const url = apiUrl();
    const resp = await fetch(url, { cache: "no-store" });
    const data = await resp.json();
    // A filter can change during the request. Then the request of the new filter shows its rows.
    if (url !== apiUrl()) {
      return;
    }
    if (data.error || !Array.isArray(data.tests)) {
      showError(data.error || "nookku: the page server gave no tests.");
      return;
    }
    showError("");
    el("tests").replaceChildren(...data.tests.map(testRow));
    const n = data.tests.length;
    el("count").textContent = n === 1 ? "1 test" : n + " tests";
    showEmpty(n);
  } catch (e) {
    showError("nookku: the page server does not answer. Start it again with: nookku chat");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  for (const id of ["state", "has", "order"]) {
    el(id).addEventListener("change", refresh);
  }
  el("filters").addEventListener("submit", (e) => e.preventDefault());
  refresh();
  setInterval(refresh, POLL_MS);
});

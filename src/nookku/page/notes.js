// The notes of the tester on the chat page (#352). Each reply block with a turn number gets a
// thumbs up, a thumbs down and a comment. The page server writes each note to notes.jsonl of
// the running test (SPEC.md section 2.3). Each text goes into the page with textContent or as
// the value of a text box, never as HTML.
"use strict";

const NOTES_POLL_MS = 1000;
const UP = "\u{1F44D}";
const DOWN = "\u{1F44E}";
// The last note of each turn, by turn number, and if the test of these notes runs.
let lastNotes = new Map();
let notesRunning = false;

function noteText(note) {
  if (!note) {
    return "No note.";
  }
  const parts = [];
  if (note.rating === "up") {
    parts.push("Thumbs up");
  } else if (note.rating === "down") {
    parts.push("Thumbs down");
  }
  if (note.comment) {
    parts.push("comment saved");
  }
  return "Your note: " + parts.join(", ") + ".";
}

function noteBar(li) {
  const bar = document.createElement("div");
  bar.className = "notebar";
  const up = document.createElement("button");
  up.type = "button";
  up.className = "notebar-rate";
  up.dataset.rating = "up";
  up.textContent = UP;
  up.setAttribute("aria-label", "Thumbs up");
  const down = document.createElement("button");
  down.type = "button";
  down.className = "notebar-rate";
  down.dataset.rating = "down";
  down.textContent = DOWN;
  down.setAttribute("aria-label", "Thumbs down");
  const comment = document.createElement("textarea");
  comment.className = "notebar-comment";
  comment.rows = 1;
  comment.placeholder = "Comment on this reply (only the evaluation reads it)";
  comment.setAttribute("aria-label", "Comment on turn " + li.dataset.turn);
  comment.addEventListener("input", () => {
    comment.dataset.dirty = "1";
  });
  const save = document.createElement("button");
  save.type = "button";
  save.className = "notebar-save";
  save.textContent = "Save comment";
  const status = document.createElement("p");
  status.className = "notebar-status";
  status.setAttribute("role", "status");
  up.addEventListener("click", () => saveNote(li, "up"));
  down.addEventListener("click", () => saveNote(li, "down"));
  save.addEventListener("click", () => saveNote(li, null));
  bar.append(up, down, comment, save, status);
  return bar;
}

function showNote(li) {
  let bar = li.querySelector(".notebar");
  if (!bar) {
    bar = noteBar(li);
    li.append(bar);
  }
  const note = lastNotes.get(Number(li.dataset.turn));
  for (const button of bar.querySelectorAll(".notebar-rate")) {
    const on = note !== undefined && note.rating === button.dataset.rating;
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.disabled = !notesRunning || bar.dataset.busy === "1";
  }
  const comment = bar.querySelector(".notebar-comment");
  if (comment.dataset.dirty !== "1" && document.activeElement !== comment) {
    comment.value = note && note.comment ? note.comment : "";
  }
  comment.disabled = !notesRunning;
  bar.querySelector(".notebar-save").disabled = !notesRunning || bar.dataset.busy === "1";
  if (bar.dataset.error !== "1") {
    bar.querySelector(".notebar-status").textContent = noteText(note);
  }
}

function showAllNotes() {
  for (const li of document.querySelectorAll("#turns li[data-turn]")) {
    showNote(li);
  }
}

async function saveNote(li, clicked) {
  const bar = li.querySelector(".notebar");
  const turn = Number(li.dataset.turn);
  const note = lastNotes.get(turn);
  const comment = bar.querySelector(".notebar-comment");
  // A thumb sets the rating. "Save comment" keeps the rating of the last note.
  const rating = clicked !== null ? clicked : note ? note.rating : null;
  const body = { turn: turn, rating: rating, comment: comment.value === "" ? null : comment.value };
  const status = bar.querySelector(".notebar-status");
  bar.dataset.busy = "1";
  bar.dataset.error = "";
  status.textContent = "Saving the note...";
  showNote(li);
  try {
    const resp = await fetch("api/note", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.saved) {
      comment.dataset.dirty = "";
    } else {
      bar.dataset.error = "1";
      status.textContent = data.error || "nookku: the page wrote no note.";
    }
  } catch (e) {
    bar.dataset.error = "1";
    status.textContent = "nookku: the page server does not answer. The page wrote no note.";
  } finally {
    bar.dataset.busy = "";
    await refreshNotes();
  }
}

async function refreshNotes() {
  try {
    const resp = await fetch("api/notes", { cache: "no-store" });
    const data = await resp.json();
    notesRunning = data.running === true && !data.error;
    lastNotes = new Map();
    for (const note of data.notes || []) {
      lastNotes.set(note.turn, note);
    }
  } catch (e) {
    notesRunning = false;
  }
  showAllNotes();
}

document.addEventListener("DOMContentLoaded", () => {
  // app.js adds the reply blocks. Put the note controls on each new block at once.
  new MutationObserver(showAllNotes).observe(document.getElementById("turns"), { childList: true });
  refreshNotes();
  setInterval(refreshNotes, NOTES_POLL_MS);
});

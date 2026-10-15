// The notes of the tester on the chat page (#352, #391). Each turn with a turn number gets a
// thumbs up, a thumbs down and a comment in its tool row. The page server writes each note to
// notes.jsonl of the running test (SPEC.md section 2.3). Each text goes into the page with
// textContent or as the value of a text box, never as HTML.
//
// app.js gives each turn `_slots.notes` (the place of the buttons in the tool row) and
// `_slots.noteBox` (the place of the comment box under the reply).
"use strict";

const NOTES_POLL_MS = 1000;
// The last note of each turn, by turn number, the test of these notes, and if it runs.
let lastNotes = new Map();
let notesTest = null;
let notesRunning = false;

function noteIcon(name) {
  return typeof NookkuIcons !== "undefined" ? [NookkuIcons.icon(name)] : [];
}

function noteButton(cls, label, icon, text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn " + cls + (text ? "" : " icon");
  button.append(...noteIcon(icon));
  if (text) {
    const words = document.createElement("span");
    words.textContent = text;
    button.append(words);
  } else {
    button.setAttribute("aria-label", label);
    button.title = label;
  }
  return button;
}

function noteBar(li) {
  const slots = li._slots;
  const up = noteButton("notebar-rate", "Thumbs up", "up");
  up.dataset.rating = "up";
  const down = noteButton("notebar-rate", "Thumbs down", "down");
  down.dataset.rating = "down";
  const open = noteButton("notebar-open", "Comment", "comment", "Comment");
  const editor = document.createElement("div");
  editor.className = "comment";
  editor.id = "comment-" + li.dataset.test + "-" + li.dataset.turn;
  editor.hidden = true;
  open.setAttribute("aria-expanded", "false");
  open.setAttribute("aria-controls", editor.id);
  const comment = document.createElement("textarea");
  comment.className = "notebar-comment";
  comment.rows = 2;
  comment.placeholder = "Comment on this reply. Only the evaluation reads it.";
  comment.setAttribute("aria-label", "Comment on turn " + li.dataset.turn);
  comment.addEventListener("input", () => {
    comment.dataset.dirty = "1";
  });
  const save = document.createElement("button");
  save.type = "button";
  save.className = "btn outline notebar-save";
  save.textContent = "Save comment";
  editor.append(comment, save);
  const saved = document.createElement("p");
  saved.className = "saved";
  saved.hidden = true;
  const status = document.createElement("p");
  status.className = "notebar-status";
  status.setAttribute("role", "status");
  up.addEventListener("click", () => saveNote(li, "up"));
  down.addEventListener("click", () => saveNote(li, "down"));
  save.addEventListener("click", () => saveNote(li, null));
  open.addEventListener("click", () => {
    editor.hidden = !editor.hidden;
    open.setAttribute("aria-expanded", editor.hidden ? "false" : "true");
    showNote(li);
    if (!editor.hidden) {
      comment.focus();
    }
  });
  slots.notes.replaceChildren(up, down, open);
  slots.noteBox.replaceChildren(editor, saved, status);
  li._notes = { up, down, open, editor, comment, save, saved, status };
  return li._notes;
}

function showNote(li) {
  if (!li._slots || !li._slots.notes) {
    return;
  }
  const bar = li._notes || noteBar(li);
  // A turn of another test gets no note and shows no note of this test.
  const same = li.dataset.test === notesTest;
  const open = notesRunning && same;
  const busy = bar.busy === true;
  const note = same ? lastNotes.get(Number(li.dataset.turn)) : undefined;
  for (const button of [bar.up, bar.down]) {
    const on = note !== undefined && note.rating === button.dataset.rating;
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.disabled = !open || busy;
  }
  bar.open.disabled = !open;
  const comment = bar.comment;
  if (comment.dataset.dirty !== "1" && document.activeElement !== comment) {
    comment.value = note && note.comment ? note.comment : "";
  }
  comment.disabled = !open;
  bar.save.disabled = !open || busy;
  // A saved comment shows as one line while the comment box is closed.
  const text = note && note.comment ? note.comment : "";
  bar.saved.textContent = text ? "Your comment: “" + text + "”" : "";
  bar.saved.hidden = !text || !bar.editor.hidden;
  if (!bar.error && !busy) {
    bar.status.textContent = "";
  }
}

function noteCounts() {
  const counts = { test: notesTest, up: 0, down: 0, comments: 0 };
  for (const note of lastNotes.values()) {
    if (note.rating === "up") counts.up += 1;
    if (note.rating === "down") counts.down += 1;
    if (note.comment) counts.comments += 1;
  }
  return counts;
}

function showAllNotes() {
  for (const li of document.querySelectorAll("#turns > li[data-turn]")) {
    showNote(li);
  }
  // app.js shows the counts in the end card of a test that ended.
  document.dispatchEvent(new CustomEvent("nookku:notes", { detail: noteCounts() }));
}

async function saveNote(li, clicked) {
  const bar = li._notes;
  const turn = Number(li.dataset.turn);
  const note = li.dataset.test === notesTest ? lastNotes.get(turn) : undefined;
  const comment = bar.comment;
  // A thumb sets the rating. "Save comment" keeps the rating of the last note.
  const rating = clicked !== null ? clicked : note ? note.rating : null;
  const body = {
    test: li.dataset.test,
    turn: turn,
    rating: rating,
    comment: comment.value === "" ? null : comment.value,
  };
  bar.busy = true;
  bar.error = false;
  bar.status.textContent = "Saving the note...";
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
      if (clicked === null) {
        bar.editor.hidden = true;
        bar.open.setAttribute("aria-expanded", "false");
      }
    } else {
      bar.error = true;
      bar.status.textContent = data.error || "nookku: the page wrote no note.";
    }
  } catch (e) {
    bar.error = true;
    bar.status.textContent = "nookku: the page server does not answer. The page wrote no note.";
  } finally {
    bar.busy = false;
    await refreshNotes();
  }
}

// The dashboard opens the page of one test with #<test id> (#349). Show the notes of that test.
function notesUrl() {
  let id = "";
  try {
    id = decodeURIComponent(window.location.hash.slice(1));
  } catch (e) {
    id = window.location.hash.slice(1);
  }
  return id ? "api/notes/" + encodeURIComponent(id) : "api/notes";
}

async function refreshNotes() {
  try {
    const resp = await fetch(notesUrl(), { cache: "no-store" });
    const data = await resp.json();
    notesTest = data.test;
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
  // app.js adds the turns. Put the note controls on each new turn at once.
  new MutationObserver(showAllNotes).observe(document.getElementById("turns"), { childList: true });
  refreshNotes();
  setInterval(refreshNotes, NOTES_POLL_MS);
});

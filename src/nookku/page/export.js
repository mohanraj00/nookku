// The page of a test export (#354): one HTML file with no page server. It shows the chat, the
// trace steps, the notes, the audit result and the seal state from the JSON block "nookku-data".
//
// Security: each text goes into the page with textContent, or as DOM nodes from render.js, never
// as HTML. Before render.js makes the nodes of a reply, offline() changes its tree: a link shows
// as text with its URL, a button goes away, and a source that is not a data: URI shows as text.
// An SVG shows only as an image, which runs no script and loads nothing. Thus the file loads
// nothing from the network.
"use strict";

(function (root) {
  // The data of the file, and its media files by path, from start().
  let data = null;
  let files = new Map();
  let big = new Set();
  // The paths of the media files that a reply shows.
  const used = new Set();

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  function when(ts) {
    return typeof ts === "number" ? new Date(ts * 1000).toLocaleString() : null;
  }

  // ---- The tree of a reply, with no network ----

  function code(text) {
    return { t: "code", a: {}, c: [String(text)] };
  }

  function fileText(path) {
    const why = big.has(path)
      ? " (the file is larger than the limit of the export)"
      : " (the file is not in the export)";
    return { t: "span", a: { class: "file" }, c: [code(path), why] };
  }

  function source(n) {
    let src = String(n.a.src || "");
    if (src.startsWith("files/")) {
      let path = null;
      try {
        path = decodeURIComponent(src.slice("files/".length));
      } catch (e) {
        return fileText(src);
      }
      if (!files.has(path)) {
        return fileText(path);
      }
      used.add(path);
      src = files.get(path);
    }
    if (!/^data:/i.test(src)) {
      return code(src);
    }
    if (/^data:image\/svg\+xml[;,]/i.test(src)) {
      // An SVG as an image runs no script and loads no other file.
      return { t: "img", a: { src: src, alt: n.a.title || n.a.alt || "SVG", class: "svg" }, c: [] };
    }
    if (n.t === "video") {
      return { t: "video", a: { src: src, controls: "", preload: "metadata", class: "media" }, c: [] };
    }
    if (n.t === "img") {
      return { t: "img", a: { src: src, alt: n.a.alt || "" }, c: [] };
    }
    return code(src);
  }

  function change(n) {
    if (typeof n === "string") {
      return n;
    }
    const a = n.a || {};
    if (n.t === "a") {
      return { t: "span", a: { class: "link" }, c: n.c.map(change).concat([" ", code(a.href || "")]) };
    }
    if (n.t === "span" && a.class === "remote") {
      const button = n.c.find((c) => typeof c !== "string" && c.t === "button");
      const url = button ? button.a["data-src"] : "";
      return {
        t: "span", a: { class: "remote" }, c: [code(url), " (a web file: the export does not load it)"],
      };
    }
    if (n.t === "span" && a.class === "file") {
      // A file that the page opens with "Open": show the path as text.
      const button = n.c.find((c) => typeof c !== "string" && c.t === "button");
      const path = button ? String(button.a["data-path"] || "") : "";
      const kids = n.c.filter((c) => c !== button).map(change);
      const label = kids.map((c) => (typeof c === "string" ? c : (c.c || []).join(""))).join("");
      if (path && label !== path) kids.push(" ", code(path));
      return { t: "span", a: { class: "file" }, c: kids };
    }
    if (n.t === "button") {
      return "";
    }
    if (n.t === "img" || n.t === "video" || n.t === "iframe") {
      return source(n);
    }
    return { t: n.t, a: a, c: (n.c || []).map(change) };
  }

  function offline(tree) {
    return tree.map(change);
  }

  // ---- The parts of the page ----

  function block(cls, who, text) {
    const li = el("li", "turn " + cls);
    li.append(el("p", "who", who), el("pre", "text", text));
    return li;
  }

  function noteBlock(note) {
    const parts = [];
    if (note.rating === "up") parts.push("Thumbs up.");
    if (note.rating === "down") parts.push("Thumbs down.");
    const box = el("div", "export-note");
    box.append(el("p", "who", "Tester note" + (parts.length ? ": " + parts.join(" ") : "")));
    if (note.comment) {
      box.append(el("pre", "text", note.comment));
    }
    return box;
  }

  function stepTitle(s) {
    const parts = [when(s.ts) || "no time", s.harness, s.kind];
    if (s.role) parts.push(s.role);
    if (s.name) parts.push(s.server ? s.server + "/" + s.name : s.name);
    if (s.exit_code !== null) parts.push("exit " + s.exit_code);
    if (s.internal) parts.push("harness tool");
    return parts.filter((p) => p).join(" · ");
  }

  function stepsBlock(list) {
    const box = el("details", "export-steps");
    box.append(el("summary", null, "Trace steps (" + list.length + ")"));
    const ol = el("ol", "export-step-list");
    for (const s of list) {
      const li = el("li", "export-step" + (s.error ? " export-step-error" : ""));
      li.append(el("p", "who", stepTitle(s)));
      for (const [label, value] of [["input", s.input], ["output", s.output], ["error", s.error]]) {
        if (value !== null && value !== undefined && value !== "") {
          li.append(el("p", "export-step-label", label), el("pre", "text", value));
        }
      }
      ol.append(li);
    }
    box.append(ol);
    return box;
  }

  // A media file of the data that no reply shows, for example a link in code. The page shows it
  // here, so the file holds no file that the page does not show.
  function unused() {
    const left = [...files.keys()].filter((path) => !used.has(path));
    if (left.length === 0) return;
    const box = el("section", "export-files");
    box.append(el("h2", null, "Other files in this export (" + left.length + ")"));
    box.append(el("p", "note", "A reply names these files, but it does not show them, for " +
      "example because the name is in code."));
    const ol = el("ol");
    for (const path of left) {
      const src = files.get(path);
      const media = /^data:video\//i.test(src)
        ? { t: "video", a: { src: src, controls: "", preload: "metadata", class: "media" }, c: [] }
        : { t: "img", a: { src: src, alt: path }, c: [] };
      const li = el("li");
      li.append(el("code", null, path), el("br"), NookkuRender.toDom([media], document));
      ol.append(li);
    }
    box.append(ol);
    document.querySelector("main").append(box);
  }

  const SEAL = {
    intact: "Seal: intact. No record changed after the end of the test.",
    broken: "Seal: broken. A record changed after the end of the test.",
    none: "Seal: none. The records of this test have no seal.",
    unknown: "Seal: unknown. A file of the test cannot be read.",
  };

  function auditText() {
    if (data.audit_exit === null || data.audit_exit === undefined) {
      return "Audit: none. The test has no audit.json.";
    }
    if (data.audit_exit === 2) {
      return "Audit: a record is missing or not valid (exit 2).";
    }
    const n = data.breaks.length;
    if (n === 0) return "Audit: clean (exit 0).";
    return "Audit: " + n + (n === 1 ? " break" : " breaks") + " (exit 1).";
  }

  function summary() {
    const s = data.summary;
    const box = document.getElementById("summary");
    const lines = [
      "State: " + s.state + ".",
      "Turns: " + (s.turns === null ? "unknown" : s.turns) + ".",
      auditText(),
      "Findings: " + data.findings.length + ".",
      SEAL[s.seal] || "Seal: " + s.seal + ".",
    ];
    if (s.state === "running") {
      lines.push("The test ran at the time of the export, so this file shows part of it.");
    }
    const ul = el("ul", "export-summary");
    for (const line of lines) ul.append(el("li", null, line));
    box.append(ul);
    const listed = [
      ["Breaks", data.breaks.map((b) => {
        let text = b.class + " (relay line " + (b.relay_line || "-") + ", tap line " +
          (b.tap_line || "-") + ")";
        const ev = b.evidence || {};
        if (ev.first_difference !== undefined) {
          text += ": first difference at character " + ev.first_difference + ": expected " +
            JSON.stringify(ev.expected) + ", got " + JSON.stringify(ev.actual);
        }
        return text;
      })],
      ["Findings", data.findings.map((f) =>
        f.check + " (" + (f.turn === null || f.turn === undefined ? "no turn" : "turn " + f.turn) +
        "): " + f.detail)],
      ["Problems", data.errors],
    ];
    for (const [title, items] of listed) {
      if (items.length === 0) continue;
      const details = el("details", "export-list");
      details.append(el("summary", null, title + " (" + items.length + ")"));
      const ol = el("ol");
      for (const item of items) ol.append(el("li", null, item));
      details.append(ol);
      box.append(details);
    }
    const exported = when(data.exported);
    box.append(el("p", "note", "Exported by nookku " + data.version +
      (exported ? " at " + exported : "") + "."));
  }

  function start(found) {
    data = found;
    files = new Map(Object.entries(data.media || {}));
    big = new Set(data.big || []);
  }

  function show() {
    start(JSON.parse(document.getElementById("nookku-data").textContent));
    const test = data.test;
    if (!test) {
      document.getElementById("test").textContent = "No test.";
      return;
    }
    document.title = "Nookku test " + test.id;
    document.getElementById("test").textContent = "Test " + test.id + ".";
    const started = when(test.started);
    const startMark = document.getElementById("start");
    startMark.textContent = "The test started" + (started ? " at " + started : "") + ".";
    startMark.hidden = false;
    if (test.ended !== null && test.ended !== undefined) {
      const ended = when(test.ended);
      const endMark = document.getElementById("end");
      endMark.textContent = "The test ended" + (ended ? " at " + ended : "") + ".";
      endMark.hidden = false;
    }
    try {
      summary();
    } catch (e) {
      // A damaged file of the test must not stop the chat.
      document.getElementById("summary").append(el("p", "note", "nookku: the summary failed."));
    }
    const notes = new Map();
    for (const note of data.notes) notes.set(note.turn, note);
    const list = document.getElementById("turns");
    data.turns.forEach((turn, i) => {
      const number = i + 1;
      const sender = turn.harness === "script" ? "script" : "tester";
      list.append(block("tester", sender + " (" + turn.harness + ")", turn.said));
      let li;
      if (turn.shown === null) {
        li = block("relay-error", "relay", "(the relay showed no reply)");
      } else if (turn.ok === false) {
        li = block("relay-error", "relay error", turn.shown);
      } else {
        li = NookkuRender.reply(document, "agent", "agent", turn.shown, offline);
      }
      if (notes.has(number)) li.append(noteBlock(notes.get(number)));
      const steps = data.steps[String(number)];
      if (steps && steps.length) li.append(stepsBlock(steps));
      list.append(li);
    });
    unused();
  }

  if (typeof module === "object" && module.exports) {
    // The tests of the export run offline() in node.
    module.exports = { offline: offline, start: start };
  } else {
    root.document.addEventListener("DOMContentLoaded", show);
  }
})(globalThis);

// The trace steps and the time of each turn on the chat page (#353). Under each reply, the page
// shows the time of the turn and its trace rows: the tool calls, the backend calls and the model
// API calls. The steps are collapsed by default. Each text of a step goes into the page with
// textContent, never as HTML, so that a step cannot run code on the page.
"use strict";

const NookkuTrace = (function () {
  const POLL_MS = 1000;
  let answer = null;

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

  function seconds(value) {
    return value.toFixed(1) + " s";
  }

  // The time of a turn: from the tap `started` time of the request to the end of the reply.
  function turnTime(turn) {
    if (typeof turn.started !== "number" || typeof turn.ended !== "number") {
      return null;
    }
    return Math.max(0, turn.ended - turn.started);
  }

  function title(step, start) {
    const parts = [];
    if (typeof step.ts === "number" && typeof start === "number") {
      parts.push("+" + seconds(Math.max(0, step.ts - start)));
    }
    parts.push(step.harness || "?");
    parts.push(step.kind || "?");
    if (step.server) {
      parts.push(step.server);
    }
    if (step.name) {
      parts.push(step.name);
    }
    if (step.role) {
      parts.push("(" + step.role + ")");
    }
    if (step.exit_code !== null && step.exit_code !== undefined) {
      parts.push("status " + step.exit_code);
    }
    if (step.error !== null && step.error !== undefined) {
      parts.push("error");
    }
    return parts.join(" ");
  }

  function text(value) {
    return typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }

  function field(name, value) {
    const box = make("div", "trace-field");
    box.append(make("p", "trace-name", name), make("pre", "trace-value", text(value)));
    return box;
  }

  function stepNode(step, start) {
    const li = make("li", "trace-step" + (step.error ? " trace-failed" : ""));
    const details = make("details");
    details.append(make("summary", null, title(step, start)));
    for (const name of ["input", "output", "error"]) {
      if (step[name] !== null && step[name] !== undefined) {
        details.append(field(name, step[name]));
      }
    }
    li.append(details);
    return li;
  }

  // The block of the steps of one turn, or of the turn that waits for its reply.
  function block(turn, pending) {
    const li = make("li", "trace" + (pending ? " trace-pending" : ""));
    const count = turn.steps.length;
    const time = pending ? null : turnTime(turn);
    let label = count + (count === 1 ? " trace step" : " trace steps");
    if (pending) {
      label += " so far";
    } else if (time !== null) {
      label = "Turn time " + seconds(time) + ", " + label;
    } else if (turn.exchange === null) {
      label = "The tap has no exchange for this turn, so it has no time and no steps";
    } else {
      label = "Turn time unknown, " + label;
    }
    const details = make("details");
    details.append(make("summary", "trace-summary", label));
    const list = make("ol", "trace-steps");
    for (const step of turn.steps) {
      list.append(stepNode(step, turn.started));
    }
    details.append(list);
    li.append(details);
    return li;
  }

  // Put a block after `owner`, or keep the block that is there if its data did not change.
  function place(owner, turn, pending) {
    const key = JSON.stringify(turn);
    const old = owner._trace;
    if (old && old._key === key && old.previousSibling === owner) {
      return;
    }
    const node = block(turn, pending);
    node._key = key;
    if (old) {
      const open = old.querySelector("details");
      node.querySelector("details").open = Boolean(open && open.open);
      old.remove();
    }
    owner._trace = node;
    owner.after(node);
  }

  function attach() {
    const list = document.getElementById("turns");
    const test = document.getElementById("test").dataset.id || "";
    if (!list) {
      return;
    }
    if (answer === null || answer.test !== test) {
      // No answer for this test, or the last answer was an error: the page shows no old steps.
      for (const node of list.querySelectorAll(":scope > li.trace")) {
        if (node.previousSibling) {
          node.previousSibling._trace = null;
        }
        node.remove();
      }
      return;
    }
    for (const owner of list.querySelectorAll(":scope > li[data-turn]")) {
      // `data-turn` is the 1-based number of the turn on the page.
      const turn = answer.turns[Number(owner.dataset.turn) - 1];
      if (turn) {
        place(owner, turn, false);
      }
    }
    const waiting = list.querySelector(":scope > li.pending");
    if (waiting && answer.pending.length > 0) {
      place(waiting, { steps: answer.pending, exchange: null, started: null, ended: null }, true);
    }
    // A block whose owner is gone or moved goes too.
    for (const node of list.querySelectorAll(":scope > li.trace")) {
      const owner = node.previousSibling;
      if (!owner || owner._trace !== node) {
        node.remove();
      }
    }
  }

  function showError(error) {
    let box = document.getElementById("trace-error");
    if (!box) {
      box = make("p", "trace-error");
      box.id = "trace-error";
      box.setAttribute("role", "status");
      document.getElementById("turns").before(box);
    }
    box.textContent = error || "";
    box.hidden = !error;
  }

  async function refresh() {
    const id = document.getElementById("test").dataset.id || "";
    const url = id ? "api/trace/" + encodeURIComponent(id) : "api/trace";
    try {
      const resp = await fetch(url, { cache: "no-store" });
      const data = await resp.json();
      showError(data.error);
      answer = data.error ? null : data;
    } catch (e) {
      // app.js shows the error when the page server does not answer.
      return;
    }
    attach();
  }

  function start() {
    const list = document.getElementById("turns");
    // app.js adds and removes the turns. Each change puts the known steps in place at once.
    new MutationObserver(attach).observe(list, { childList: true });
    refresh();
    setInterval(refresh, POLL_MS);
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", start);
  }
  return { block: block, title: title, turnTime: turnTime };
})();

if (typeof module !== "undefined") {
  module.exports = NookkuTrace;
}

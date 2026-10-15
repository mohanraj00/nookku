// The trace steps and the time of each turn on the chat page (#353, #391). Under each reply, the
// page shows the time of the turn and its trace rows: the tool calls, the backend calls and the
// model API calls. The steps are collapsed by default: a button "N steps" opens them. Each text
// of a step goes into the page with textContent, never as HTML, so that a step cannot run code on
// the page.
//
// app.js gives each turn on the page `_slots`: `steps` (the place of the button in the tool row),
// `panel` (the place of the rows in the reply), `time` (the turn time) and `sent` (the clock time
// of the message). The turn that waits for its reply has only `panel`, and its rows show open.
"use strict";

const NookkuTrace = (function () {
  const POLL_MS = 1000;
  let answer = null;
  let panels = 0;

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

  // The 4 columns of a step row: the time after the start of the turn, the source, the name and
  // the result.
  function columns(step, start) {
    const at =
      typeof step.ts === "number" && typeof start === "number"
        ? "+" + seconds(Math.max(0, step.ts - start))
        : "";
    const source = (step.harness || "?") + " " + (step.kind || "?");
    const name = [];
    if (step.server) {
      name.push(step.server);
    }
    if (step.name) {
      name.push(step.name);
    }
    if (step.role) {
      name.push("(" + step.role + ")");
    }
    const result = [];
    if (step.exit_code !== null && step.exit_code !== undefined) {
      result.push("status " + step.exit_code);
    }
    if (step.error !== null && step.error !== undefined) {
      result.push("error");
    }
    return [at, source, name.join(" "), result.join(" ")];
  }

  // The full text of a step row, in one line.
  function title(step, start) {
    return columns(step, start)
      .filter((part) => part !== "")
      .join(" ");
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
    const summary = make("summary", "trace-row");
    summary.title = title(step, start);
    const [at, source, name, result] = columns(step, start);
    summary.append(
      make("span", "trace-at", at),
      make("span", "trace-kind", source),
      make("span", "trace-n", name),
      make("span", "trace-result", result),
    );
    details.append(summary);
    for (const key of ["input", "output", "error"]) {
      if (step[key] !== null && step[key] !== undefined) {
        details.append(field(key, step[key]));
      }
    }
    li.append(details);
    return li;
  }

  // The words of the button and of the turn time.
  function summary(turn, pending) {
    const count = turn.steps.length;
    const steps = count + (count === 1 ? " step" : " steps") + (pending ? " so far" : "");
    const time = pending ? null : turnTime(turn);
    let label;
    if (pending) {
      label = count + (count === 1 ? " trace step" : " trace steps") + " so far";
    } else if (time !== null) {
      label = "Turn time " + seconds(time) + ", " + count + (count === 1 ? " trace step" : " trace steps");
    } else if (turn.exchange === null) {
      label = "The tap has no exchange for this turn, so it has no time and no steps";
    } else {
      label = "Turn time unknown, " + count + (count === 1 ? " trace step" : " trace steps");
    }
    return { steps: steps, time: time === null ? null : seconds(time), label: label };
  }

  // The rows of the steps of one turn, or of the turn that waits for its reply.
  function block(turn, pending) {
    const box = make("div", "trace" + (pending ? " trace-pending" : ""));
    const list = make("ol", "trace-steps");
    for (const step of turn.steps) {
      list.append(stepNode(step, turn.started));
    }
    box.append(list);
    box.setAttribute("aria-label", summary(turn, pending).label);
    return box;
  }

  function clockTime(ts) {
    return typeof ts === "number" ? new Date(ts * 1000).toLocaleTimeString() : "";
  }

  // The button "N steps" in the tool row of a turn.
  function stepsButton(owner, turn, rows) {
    const said = summary(turn, false);
    const button = make("button", "btn trace-toggle");
    button.type = "button";
    button.title = said.label;
    panels += 1;
    rows.id = "trace-" + panels;
    button.setAttribute("aria-controls", rows.id);
    const open = owner._traceOpen === true;
    button.setAttribute("aria-expanded", open ? "true" : "false");
    rows.hidden = !open;
    if (typeof NookkuIcons !== "undefined") {
      button.append(NookkuIcons.icon("chev"));
    }
    button.append(make("span", null, said.steps));
    button.addEventListener("click", () => {
      owner._traceOpen = rows.hidden;
      rows.hidden = !rows.hidden;
      button.setAttribute("aria-expanded", rows.hidden ? "false" : "true");
    });
    return button;
  }

  // Fill the slots of `owner` for `turn`, or keep them if the data did not change.
  function place(owner, turn, pending) {
    const slots = owner._slots;
    if (!slots) {
      return;
    }
    const key = JSON.stringify(turn);
    if (owner._traceKey === key) {
      return;
    }
    owner._traceKey = key;
    const rows = block(turn, pending);
    if (pending) {
      slots.panel.replaceChildren(...(turn.steps.length > 0 ? [rows] : []));
      return;
    }
    const said = summary(turn, false);
    if (slots.time) {
      slots.time.textContent = said.time ? " · " + said.time : "";
    }
    if (slots.sent) {
      slots.sent.textContent = clockTime(turn.started);
    }
    if (slots.steps) {
      if (turn.steps.length > 0) {
        slots.steps.replaceChildren(stepsButton(owner, turn, rows));
        slots.panel.replaceChildren(rows);
      } else {
        const note = make("span", "trace-none", "No steps");
        note.title = said.label;
        slots.steps.replaceChildren(note);
        slots.panel.replaceChildren();
      }
    }
  }

  function clear(owner) {
    const slots = owner._slots;
    owner._traceKey = null;
    if (!slots) {
      return;
    }
    for (const name of ["steps", "panel", "time", "sent"]) {
      if (slots[name]) {
        slots[name].replaceChildren();
      }
    }
  }

  function attach() {
    const list = document.getElementById("turns");
    const test = document.getElementById("test").dataset.id || "";
    if (!list) {
      return;
    }
    const owners = list.querySelectorAll(":scope > li[data-turn]");
    const waiting = list.querySelector(":scope > li.pending");
    if (answer === null || answer.test !== test) {
      // No answer for this test, or the last answer was an error: the page shows no old steps.
      for (const owner of owners) {
        clear(owner);
      }
      if (waiting) {
        clear(waiting);
      }
      return;
    }
    for (const owner of owners) {
      // `data-turn` is the 1-based number of the turn on the page.
      const turn = answer.turns[Number(owner.dataset.turn) - 1];
      if (turn) {
        place(owner, turn, false);
      }
    }
    if (waiting) {
      place(waiting, { steps: answer.pending, exchange: null, started: null, ended: null }, true);
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
      // The shown test can change during the request. Then a later request shows the new test.
      if ((document.getElementById("test").dataset.id || "") !== id) {
        return;
      }
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

  if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", start);
  }
  return { block: block, title: title, summary: summary, turnTime: turnTime, attach: attach };
})();

if (typeof module !== "undefined") {
  module.exports = NookkuTrace;
}

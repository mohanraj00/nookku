// The keyboard shortcuts of the pages (#355). Only Enter in the message box sends a message.
// No other key sends. No key works while the tester types in a text field, except Enter,
// Shift+Enter and Up in the message box. A key with Ctrl, Alt or Meta is for the browser.
"use strict";

(function () {
  const HELP = [
    ["Enter", "Send the message (in the message box)"],
    ["Shift+Enter", "Add a line (in the message box)"],
    ["Up", "Put the last unsent message back in an empty message box"],
    ["/", "Go to the search (dashboard)"],
    ["j", "Go to the next turn or test"],
    ["k", "Go to the previous turn or test"],
    ["?", "Show this list"],
    ["Esc", "Close this list"],
  ];
  // The items of j and k: each turn on the chat page and on the diff page, and each test on the
  // dashboard.
  const ITEMS = "#turns > li[data-turn], ol.turns > li.turn, #tests > tr";
  // The input types that take no text. A key on such a control can be a shortcut.
  const NO_TEXT = ["button", "checkbox", "radio", "submit", "reset", "range", "color", "file"];

  // The last message that the page did not send. app.js tells keys.js the result of each send.
  let unsent = "";
  let help = null;

  function typing(target) {
    if (!(target instanceof Element)) {
      return false;
    }
    if (target.isContentEditable) {
      return true;
    }
    const tag = target.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT") {
      return true;
    }
    return tag === "INPUT" && !NO_TEXT.includes(target.type);
  }

  function modified(e) {
    return e.ctrlKey || e.metaKey || e.altKey;
  }

  // Enter, Shift+Enter and Up in the message box of the chat page.
  function onMessageKey(e) {
    // A key that composes a character (for example in an input method) is not a shortcut.
    if (e.isComposing || e.keyCode === 229 || modified(e)) {
      return;
    }
    const box = e.currentTarget;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const send = document.getElementById("send");
      if (send && !send.disabled) {
        send.click();
      }
    } else if (e.key === "ArrowUp" && !e.shiftKey && box.value === "" && unsent !== "") {
      e.preventDefault();
      box.value = unsent;
      box.setSelectionRange(unsent.length, unsent.length);
    }
    // Shift+Enter adds a line: the text box does that itself.
  }

  function onSend(e) {
    const detail = e.detail || {};
    if (typeof detail.said !== "string") {
      return;
    }
    if (!detail.sent) {
      unsent = detail.said;
    } else if (detail.said === unsent) {
      unsent = "";
    }
  }

  function visible(node) {
    return node.getClientRects().length > 0;
  }

  // j and k: put the focus on the next or the previous item.
  function move(step) {
    const items = Array.from(document.querySelectorAll(ITEMS)).filter(visible);
    if (items.length === 0) {
      return;
    }
    const at = items.findIndex((item) => item.contains(document.activeElement));
    let next;
    if (at === -1) {
      next = step > 0 ? 0 : items.length - 1;
    } else {
      next = Math.min(Math.max(at + step, 0), items.length - 1);
    }
    const item = items[next];
    if (!item.hasAttribute("tabindex")) {
      item.tabIndex = -1;
    }
    item.focus({ preventScroll: true });
    item.scrollIntoView({ block: "center" });
  }

  function make(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function helpDialog() {
    const dialog = make("dialog");
    dialog.className = "keys-help";
    dialog.setAttribute("aria-labelledby", "keys-help-title");
    const title = make("h2", "Keyboard shortcuts");
    title.id = "keys-help-title";
    const table = make("table");
    const body = make("tbody");
    for (const [key, text] of HELP) {
      const row = make("tr");
      const name = make("th");
      name.scope = "row";
      name.append(make("kbd", key));
      row.append(name, make("td", text));
      body.append(row);
    }
    table.append(body);
    const close = make("button", "Close");
    close.type = "button";
    close.className = "btn outline";
    close.addEventListener("click", () => dialog.close());
    // A click on the backdrop closes the list.
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) {
        dialog.close();
      }
    });
    dialog.append(title, table, close);
    document.body.append(dialog);
    return dialog;
  }

  function showHelp() {
    if (help === null) {
      help = helpDialog();
    }
    if (!help.open) {
      help.showModal();
    }
  }

  function onKey(e) {
    if (e.defaultPrevented || e.isComposing || modified(e) || typing(e.target)) {
      return;
    }
    // The open list takes the keys. Esc closes it.
    if (help !== null && help.open) {
      return;
    }
    if (e.key === "?") {
      e.preventDefault();
      showHelp();
    } else if (e.key === "/") {
      const search = document.getElementById("search");
      if (search) {
        e.preventDefault();
        search.focus();
        search.select();
      }
    } else if ((e.key === "j" || e.key === "k") && !e.shiftKey) {
      e.preventDefault();
      move(e.key === "j" ? 1 : -1);
    }
  }

  // The dashboard makes its rows again on each poll. If the focus was on a row, put it on the new
  // row of the same test, so that j and k continue from there.
  function keepRowFocus(table) {
    let focused = null;
    table.addEventListener("focusin", (e) => {
      focused = e.target instanceof HTMLTableRowElement ? e.target : null;
    });
    new MutationObserver((changes) => {
      const lost = changes.some((c) => Array.from(c.removedNodes).includes(focused));
      if (!lost || !focused.dataset.id) {
        return;
      }
      const id = focused.dataset.id;
      focused = null;
      const row = Array.from(table.rows).find((r) => r.dataset.id === id);
      if (row && (document.activeElement === document.body || document.activeElement === null)) {
        row.focus({ preventScroll: true });
      }
    }).observe(table, { childList: true });
  }

  document.addEventListener("nookku:send", onSend);
  document.addEventListener("keydown", onKey);
  document.addEventListener("DOMContentLoaded", () => {
    const box = document.getElementById("said");
    if (box) {
      box.addEventListener("keydown", onMessageKey);
    }
    const tests = document.getElementById("tests");
    if (tests && tests.tagName === "TBODY") {
      keepRowFocus(tests);
    }
  });
})();

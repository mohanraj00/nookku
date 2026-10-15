// The menu of the header of the chat page (#391): the button with 3 dots opens it. The menu holds
// the theme and the width (theme.js), and a hint about the keys. On a narrow window, it also
// holds the 3 actions of the header. Each action of the menu clicks the button of the header,
// so that both use the same code.
"use strict";

(function () {
  function start() {
    const button = document.getElementById("more");
    const menu = document.getElementById("menu");
    if (!button || !menu) {
      return;
    }

    function show(open) {
      menu.hidden = !open;
      button.setAttribute("aria-expanded", open ? "true" : "false");
    }

    button.addEventListener("click", () => {
      show(menu.hidden);
      if (!menu.hidden) {
        const first = menu.querySelector("[aria-checked='true'], button, a");
        if (first) {
          first.focus();
        }
      }
    });
    for (const item of menu.querySelectorAll("[data-click]")) {
      item.addEventListener("click", () => {
        show(false);
        const target = document.getElementById(item.dataset.click);
        if (target && !target.disabled) {
          target.click();
        }
      });
    }
    // A click outside the menu closes it.
    document.addEventListener("click", (e) => {
      if (!menu.hidden && !menu.contains(e.target) && !button.contains(e.target)) {
        show(false);
      }
    });
    // Esc closes the menu and puts the focus back on its button.
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !menu.hidden) {
        e.preventDefault();
        show(false);
        button.focus();
      }
    });
    // The focus leaves the menu: close it.
    menu.addEventListener("focusout", (e) => {
      if (e.relatedTarget && !menu.contains(e.relatedTarget) && e.relatedTarget !== button) {
        show(false);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", start);
})();

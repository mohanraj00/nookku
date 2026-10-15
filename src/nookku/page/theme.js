// The theme and the width of the pages (#355, #391). The theme "auto" follows the system, "light"
// and "dark" do not. The width is the maximum width of the conversation of the chat page: "auto",
// "narrow" or "wide". This script runs in <head> without defer, so the page has its theme and its
// width before the first paint. The browser keeps each choice in localStorage. If the browser
// refuses the storage, each choice still works until the page closes.
//
// The chat page has a menu with a radio group for each choice: buttons with `data-pick` (the
// choice) and `data-v` (the value). A page with no such buttons gets one "Theme" button in its
// header.
"use strict";

(function () {
  const CHOICES = {
    theme: { key: "nookku-theme", names: ["auto", "light", "dark"], attr: "theme" },
    width: { key: "nookku-width", names: ["auto", "narrow", "wide"], attr: "width" },
  };

  function read(choice) {
    try {
      const value = window.localStorage.getItem(choice.key);
      return choice.names.includes(value) ? value : "auto";
    } catch (e) {
      return "auto";
    }
  }

  function write(choice, value) {
    try {
      window.localStorage.setItem(choice.key, value);
    } catch (e) {
      // The browser refuses the storage. The choice applies to this page only.
    }
  }

  function apply(choice, value) {
    if (value === "auto") {
      delete document.documentElement.dataset[choice.attr];
    } else {
      document.documentElement.dataset[choice.attr] = value;
    }
  }

  const current = {};
  for (const name of Object.keys(CHOICES)) {
    current[name] = read(CHOICES[name]);
    apply(CHOICES[name], current[name]);
  }

  function set(name, value) {
    const choice = CHOICES[name];
    if (!choice || !choice.names.includes(value)) {
      return;
    }
    current[name] = value;
    apply(choice, value);
    write(choice, value);
  }

  // The radio groups of the menu of the chat page.
  function wirePicks(buttons) {
    function show() {
      for (const button of buttons) {
        const on = current[button.dataset.pick] === button.dataset.v;
        button.setAttribute("aria-checked", on ? "true" : "false");
        button.tabIndex = on ? 0 : -1;
      }
    }
    for (const button of buttons) {
      button.addEventListener("click", () => {
        set(button.dataset.pick, button.dataset.v);
        show();
      });
    }
    show();
  }

  // The one button of a page with no menu: a click selects the next theme.
  function addButton(header) {
    const names = CHOICES.theme.names;
    const line = document.createElement("p");
    line.className = "theme";
    const button = document.createElement("button");
    button.type = "button";
    button.id = "theme";
    button.title = "Change the theme: auto, light or dark";
    button.textContent = "Theme: " + current.theme;
    button.addEventListener("click", () => {
      set("theme", names[(names.indexOf(current.theme) + 1) % names.length]);
      button.textContent = "Theme: " + current.theme;
    });
    line.append(button);
    header.append(line);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const buttons = Array.from(document.querySelectorAll("[data-pick]"));
    if (buttons.length > 0) {
      wirePicks(buttons);
      return;
    }
    const header = document.querySelector("header");
    if (header) {
      addButton(header);
    }
  });
})();

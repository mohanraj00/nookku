// The theme switch of the pages (#355). "auto" follows the system, "light" and "dark" do not.
// This script runs in <head> without defer, so the page has its theme before the first paint.
// The browser keeps the choice in localStorage. If the browser refuses the storage, the switch
// still works until the page closes.
"use strict";

(function () {
  const KEY = "nookku-theme";
  const NAMES = ["auto", "light", "dark"];

  function read() {
    try {
      const value = window.localStorage.getItem(KEY);
      return NAMES.includes(value) ? value : "auto";
    } catch (e) {
      return "auto";
    }
  }

  function write(value) {
    try {
      window.localStorage.setItem(KEY, value);
    } catch (e) {
      // The browser refuses the storage. The theme applies to this page only.
    }
  }

  function apply(value) {
    if (value === "auto") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = value;
    }
  }

  let current = read();
  apply(current);

  document.addEventListener("DOMContentLoaded", () => {
    const header = document.querySelector("header");
    if (!header) {
      return;
    }
    const line = document.createElement("p");
    line.className = "theme";
    const button = document.createElement("button");
    button.type = "button";
    button.id = "theme";
    button.title = "Change the theme: auto, light or dark";
    button.textContent = "Theme: " + current;
    button.addEventListener("click", () => {
      current = NAMES[(NAMES.indexOf(current) + 1) % NAMES.length];
      apply(current);
      write(current);
      button.textContent = "Theme: " + current;
    });
    line.append(button);
    header.append(line);
  });
})();

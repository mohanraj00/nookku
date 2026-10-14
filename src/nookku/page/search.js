// The search of the dashboard (#355). The page hides each row of a test that does not hold the
// search text. The search is in the page only: it sends no request.
"use strict";

(function () {
  function apply() {
    const box = document.getElementById("search");
    const rows = document.getElementById("tests").rows;
    const query = box.value.trim().toLowerCase();
    let shown = 0;
    for (const row of rows) {
      const hit = query === "" || row.textContent.toLowerCase().includes(query);
      row.hidden = !hit;
      if (hit) {
        shown += 1;
      }
    }
    document.getElementById("search-result").textContent =
      query === "" ? "" : shown + " of " + rows.length + " tests have this text.";
  }

  document.addEventListener("DOMContentLoaded", () => {
    const box = document.getElementById("search");
    box.addEventListener("input", apply);
    // Esc in an empty search box gives the keys back to the page, for example j and k.
    box.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && box.value === "") {
        box.blur();
      }
    });
    // dashboard.js puts new rows in the table on each poll. Apply the search to them.
    new MutationObserver(apply).observe(document.getElementById("tests"), { childList: true });
  });
})();

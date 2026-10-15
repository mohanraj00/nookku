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
    // With rows but no hit, show the empty state in place of a table with no rows. With no rows,
    // dashboard.js shows the empty state.
    if (rows.length > 0) {
      const none = shown === 0;
      document.getElementById("table").hidden = none;
      document.getElementById("empty").hidden = !none;
      if (none) {
        document.getElementById("empty-title").textContent = "No test has this text";
        document.getElementById("empty-text").textContent =
          "Change the search text to see more tests.";
        document.getElementById("empty-cmd").hidden = true;
      }
    }
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

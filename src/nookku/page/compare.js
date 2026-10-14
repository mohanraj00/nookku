// The "Compare" button of the dashboard (#351). The tester selects 2 tests with the check box of
// each row. The button opens the diff page of the 2 tests, with the older test on the left.
"use strict";

// The selected tests: the test id and the start time. The dashboard makes its rows again on each
// poll, so the selection lives here, not in the rows.
const picked = new Map();

function updateCompare() {
  const n = picked.size;
  document.getElementById("compare").disabled = n !== 2;
  document.getElementById("picked").textContent =
    n === 2 ? "2 tests selected." : "Select 2 tests to compare. " + n + " selected.";
}

// The first cell of a row of the dashboard: a check box that selects the test.
function pickCell(test) {
  const td = document.createElement("td");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = picked.has(test.id);
  box.setAttribute("aria-label", "Select test " + test.id + " to compare");
  // A click on the box selects the test. It does not open the chat page of the row.
  for (const kind of ["click", "keydown"]) {
    box.addEventListener(kind, (e) => e.stopPropagation());
  }
  box.addEventListener("change", () => {
    if (box.checked) {
      picked.set(test.id, typeof test.started === "number" ? test.started : 0);
    } else {
      picked.delete(test.id);
    }
    updateCompare();
  });
  td.append(box);
  return td;
}

function openDiff() {
  if (picked.size !== 2) {
    return;
  }
  const ids = [...picked.entries()].sort((a, b) => a[1] - b[1]).map((e) => e[0]);
  window.location.href = "diff.html#" + ids.map(encodeURIComponent).join("/");
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("compare").addEventListener("click", openDiff);
  updateCompare();
});

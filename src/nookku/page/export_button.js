// The "Export" button of the chat page (#354). A click downloads one HTML file of the test that
// the page shows, from api/export/<test id>. The file holds no page token and no page URL.
"use strict";

function exportTest() {
  const test = document.getElementById("test").dataset.id || "";
  const result = document.getElementById("export-result");
  if (test === "") {
    result.textContent = "nookku: no test to export. Start one in the harness with: nookku start";
    return;
  }
  result.textContent = "";
  const link = document.createElement("a");
  link.href = "api/export/" + encodeURIComponent(test);
  link.download = test + ".html";
  document.body.append(link);
  link.click();
  link.remove();
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("export").addEventListener("click", exportTest);
});

// The "Export" button of the chat page (#354). A click downloads one HTML file of the test that
// the page shows, from api/export/<test id>. The file holds no page token and no page URL.
// A link cannot send the page key, so the page gets the file with fetch (key.js adds the key)
// and saves it from a blob: URL (SPEC.md section 5, "Session").
"use strict";

async function exportTest() {
  const test = document.getElementById("test").dataset.id || "";
  const result = document.getElementById("export-result");
  if (test === "") {
    result.textContent = "nookku: no test to export. Start one in the harness with: nookku start";
    return;
  }
  result.textContent = "";
  let resp;
  try {
    resp = await fetch("api/export/" + encodeURIComponent(test), { cache: "no-store" });
  } catch (e) {
    result.textContent = "nookku: the page server does not answer. Nothing was exported.";
    return;
  }
  if (!resp.ok) {
    let error = "nookku: the export failed.";
    try {
      error = (await resp.json()).error || error;
    } catch (e) {
      // The answer is not JSON. Show the general error.
    }
    result.textContent = error;
    return;
  }
  const url = URL.createObjectURL(await resp.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = test + ".html";
  document.body.append(link);
  link.click();
  link.remove();
  // The browser starts the download at the click. Remove the blob a little later.
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("export").addEventListener("click", exportTest);
});

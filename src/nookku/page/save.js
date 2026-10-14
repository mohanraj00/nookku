// The "Save as script" button of the chat page (#350). The page server writes the said text of
// each turn of the test that the page shows into .nookku/scripts/<test id>.jsonl, byte for byte.
// The result goes into the page with textContent, never as HTML.
"use strict";

async function saveScript() {
  const result = document.getElementById("save-result");
  const button = document.getElementById("save-script");
  const test = document.getElementById("test").dataset.id || "";
  if (test === "") {
    result.textContent = "nookku: no test to save. Start one in the harness with: nookku start";
    return;
  }
  button.disabled = true;
  result.textContent = "Saving test " + test + ".";
  try {
    const resp = await fetch("api/save-script", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ test: test }),
    });
    const data = await resp.json();
    result.textContent = data.saved ? data.text : data.error || "nookku: the script was not saved.";
  } catch (e) {
    result.textContent = "nookku: the page server does not answer. The script was not saved.";
  } finally {
    button.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("save-script").addEventListener("click", saveScript);
});

// The "End test" button of the chat page (#391). A click shows a confirm in the page. The confirm
// sends the id of the shown test to api/end. The page server ends the test only if that test
// runs, with the steps of nookku end in a shell: no evaluation, and the page server continues, so
// the tester can export the test. app.js shows the button only while the shown test runs.
"use strict";

const NookkuEnd = (function () {
  const el = (id) => document.getElementById(id);
  const CHANGED = "nookku: the page now shows another test, so the page ended nothing.";
  let ending = false;
  // The id of the test that the tester agreed to end: the shown test when the confirm opened.
  let asked = null;

  function show(open) {
    asked = open ? el("test").dataset.id || null : null;
    el("endconfirm").hidden = !open;
    el("end-test").setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      el("endconfirm-no").focus();
    }
  }

  function result(text) {
    el("end-result").textContent = text || "";
  }

  async function confirm() {
    const test = asked;
    if (ending || test === null) {
      return;
    }
    // The shown test changed after the confirm opened: end nothing, so that no other test ends
    // with no confirm of its own.
    if ((el("test").dataset.id || null) !== test) {
      show(false);
      result(CHANGED);
      return;
    }
    ending = true;
    el("endconfirm-yes").disabled = true;
    result("");
    let data = null;
    try {
      const resp = await fetch("api/end", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ test: test }),
        cache: "no-store",
      });
      data = await resp.json();
    } catch (e) {
      data = { ended: false, error: "nookku: the page server does not answer. The test runs." };
    } finally {
      ending = false;
      el("endconfirm-yes").disabled = false;
    }
    show(false);
    if (!data || data.ended !== true) {
      result((data && data.error) || "nookku: the test did not end.");
      return;
    }
    // The next poll of app.js shows the end of the test.
    document.dispatchEvent(new CustomEvent("nookku:ended", { detail: { test: test } }));
  }

  function wire() {
    el("end-test").addEventListener("click", () => {
      result("");
      show(el("endconfirm").hidden);
    });
    el("endconfirm-no").addEventListener("click", () => {
      show(false);
      el("end-test").focus();
    });
    el("endconfirm-yes").addEventListener("click", confirm);
    el("endconfirm").addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        show(false);
      }
    });
  }

  if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", wire);
  }
  return { confirm: confirm, show: show };
})();

if (typeof module !== "undefined") {
  module.exports = NookkuEnd;
}

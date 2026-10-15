// The "End test" button of the chat page (#391). A click shows a confirm in the page. The confirm
// sends the id of the shown test to api/end. The page server ends the test only if that test
// runs, with the steps of nookku end in a shell: no evaluation, and the page server continues, so
// the tester can export the test. app.js shows the button only while the shown test runs.
"use strict";

const NookkuEnd = (function () {
  const el = (id) => document.getElementById(id);
  let ending = false;

  function show(open) {
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
    const test = el("test").dataset.id || "";
    if (ending || test === "") {
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

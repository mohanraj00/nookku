// The page key of the chat page (SPEC.md section 5, "Session").
//
// The page server gives the key one time, in the URL fragment of its redirect: #k=<key>. A
// browser sends no fragment to a server. This script runs before the other scripts of the page.
// It takes the key, removes the fragment from the address bar and the history, and adds the key
// in the header X-Nookku-Page to each request of the page to its own server. A browser sends the
// session cookie also to another port of the host, but no other origin can read the key.
//
// The key stays in sessionStorage of this tab, so that a reload works. sessionStorage is for one
// origin and one tab, and the browser removes it when the tab closes. A new tab of the page, for
// example from "Open chat", has no key. It asks the open tabs of the page for it with a
// BroadcastChannel, which is also for one origin only.
"use strict";

(function (root) {
  const NAME = "nookku-page-key";
  const HEADER = "X-Nookku-Page";
  // A request with init.poll is a poll that the page makes by itself. It gets this header, so that
  // the page server does not count it as a use of the tester (page_auto.POLL_HEADER, #439).
  const POLL = "X-Nookku-Poll";
  // The wait of a new tab for the key from another tab of the page.
  const ASK_MS = 500;
  let key = null;

  function keep(value) {
    key = value;
    try {
      root.sessionStorage.setItem(NAME, value);
    } catch (e) {
      // A browser can refuse sessionStorage. Then a reload has no key.
    }
  }

  const given = /^#k=([A-Za-z0-9_-]{16,128})$/.exec(root.location.hash);
  if (given) {
    keep(given[1]);
    try {
      root.history.replaceState(null, "", root.location.pathname);
    } catch (e) {
      root.location.hash = "";
    }
  } else {
    try {
      key = root.sessionStorage.getItem(NAME);
    } catch (e) {
      key = null;
    }
  }

  let channel = null;
  try {
    channel = new root.BroadcastChannel(NAME);
  } catch (e) {
    channel = null;
  }

  let ready = Promise.resolve();
  if (channel !== null) {
    if (key === null) {
      ready = new Promise((resolve) => {
        const timer = root.setTimeout(resolve, ASK_MS);
        channel.addEventListener("message", (event) => {
          const data = event.data;
          if (key === null && data && typeof data.key === "string") {
            keep(data.key);
            root.clearTimeout(timer);
            resolve();
          }
        });
        channel.postMessage({ ask: true });
      });
    }
    channel.addEventListener("message", (event) => {
      if (event.data && event.data.ask === true && key !== null) {
        channel.postMessage({ key: key });
      }
    });
  }

  // True if the URL goes to the server of this page.
  function own(input) {
    try {
      const url = new URL(typeof input === "string" ? input : input.url, root.location.href);
      return url.origin === root.location.origin;
    } catch (e) {
      return false;
    }
  }

  // Each request of the page to its own server gets the key. A request to another origin does
  // not.
  const plain = root.fetch.bind(root);
  root.fetch = async function (input, init) {
    if (!own(input)) {
      return plain(input, init);
    }
    await ready;
    const options = Object.assign({}, init || {});
    const headers = new root.Headers(options.headers || {});
    if (key !== null) {
      headers.set(HEADER, key);
    }
    if (options.poll === true) {
      headers.set(POLL, "1");
    }
    delete options.poll;
    options.headers = headers;
    return plain(input, options);
  };

  // A file of the page server, for an img, a video or an iframe. An element cannot send a header,
  // so the page loads the file with the key and gives the element a blob: URL. Each file loads
  // one time, and the page keeps it until the tab closes. Thus the page loads a file only up to
  // FILE_MAX bytes, and all files together only up to SUM_MAX bytes. These limits are design
  // values, not measurements. A video plays only after its whole file loads.
  const FILE_MAX = 32 * 1024 * 1024;
  const SUM_MAX = 128 * 1024 * 1024;
  let held = 0;
  const loaded = new Map();
  function fileSrc(element, src) {
    if (!loaded.has(src)) {
      loaded.set(
        src,
        root.fetch(src, { cache: "no-store" }).then((resp) => {
          if (!resp.ok) {
            throw new Error("the file did not load");
          }
          const length = resp.headers.get("Content-Length");
          const size = length === null ? NaN : Number(length);
          if (!(size >= 0) || size > FILE_MAX || held + size > SUM_MAX) {
            if (resp.body) {
              resp.body.cancel();
            }
            throw new Error("the file is larger than the limit of the page");
          }
          held += size;
          return resp.blob().then((blob) => URL.createObjectURL(blob));
        })
      );
    }
    loaded.get(src).then(
      (url) => element.setAttribute("src", url),
      (e) => {
        loaded.delete(src);
        const known = e instanceof Error && e.message.startsWith("the file");
        element.setAttribute("data-error", known ? e.message : "the file did not load");
      }
    );
  }

  root.NookkuPage = { fileSrc: fileSrc, HEADER: HEADER };
})(window);

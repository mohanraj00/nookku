// The icons of the chat page (#391). Each icon is an inline SVG that this script makes with
// createElementNS, from the shapes below. The page loads no icon file and no font.
"use strict";

const NookkuIcons = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const P = (d) => ["path", { d: d }];
  const SHAPES = {
    send: [P("M8 13V3.5M3.5 8 8 3.5 12.5 8")],
    check: [P("m3.5 8.5 3 3 6-7")],
    alert: [["circle", { cx: 8, cy: 8, r: 6 }], P("M8 5v3.5M8 11h.01")],
    up: [
      P(
        "M5 7v6H3V7zM5 7l2.5-4.5c1 0 1.7.8 1.5 1.8L8.6 7H12a1.2 1.2 0 0 1 1.2 1.4l-.8 3.8A1.5 " +
          "1.5 0 0 1 11 13H5",
      ),
    ],
    down: [
      P(
        "M5 9V3H3v6zM5 9l2.5 4.5c1 0 1.7-.8 1.5-1.8L8.6 9H12a1.2 1.2 0 0 0 1.2-1.4l-.8-3.8A1.5 " +
          "1.5 0 0 0 11 3H5",
      ),
    ],
    comment: [P("M3 4.5A1.5 1.5 0 0 1 4.5 3h7A1.5 1.5 0 0 1 13 4.5v5a1.5 1.5 0 0 1-1.5 1.5H7l-3 2.5V11h.5")],
    copy: [
      ["rect", { x: 5.5, y: 5.5, width: 7.5, height: 7.5, rx: 1.5 }],
      P("M10.5 5.5V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5"),
    ],
    text: [P("M3 4h10M3 8h10M3 12h6")],
    chev: [P("m6 4 4 4-4 4")],
    more: [
      ["circle", { cx: 3.5, cy: 8, r: 0.6 }],
      ["circle", { cx: 8, cy: 8, r: 0.6 }],
      ["circle", { cx: 12.5, cy: 8, r: 0.6 }],
    ],
    script: [P("M4 2.5h5.5L12 5v8.5H4zM9.5 2.5V5H12M6 8h4M6 10.5h4")],
    export: [P("M8 2.5v7.5M4.8 7 8 10l3.2-3M3 12.5h10")],
    list: [
      ["rect", { x: 2.5, y: 2.5, width: 4.5, height: 4.5, rx: 1 }],
      ["rect", { x: 9, y: 2.5, width: 4.5, height: 4.5, rx: 1 }],
      ["rect", { x: 2.5, y: 9, width: 4.5, height: 4.5, rx: 1 }],
      ["rect", { x: 9, y: 9, width: 4.5, height: 4.5, rx: 1 }],
    ],
    lock: [
      ["rect", { x: 3.5, y: 7, width: 9, height: 6.5, rx: 1.5 }],
      P("M5.5 7V5a2.5 2.5 0 0 1 5 0v2"),
    ],
    bot: [["rect", { x: 3, y: 5, width: 10, height: 7.5, rx: 2 }], P("M8 2.5V5M6 8.5h.01M10 8.5h.01")],
    chat: [P("M3 4.5A1.5 1.5 0 0 1 4.5 3h7A1.5 1.5 0 0 1 13 4.5v5a1.5 1.5 0 0 1-1.5 1.5H7l-3 2.5V11h.5")],
    term: [["rect", { x: 2, y: 3, width: 12, height: 10, rx: 1.5 }], P("m5 7 2 1.5L5 10M8.5 10.5H11")],
    x: [P("m4.5 4.5 7 7M11.5 4.5l-7 7")],
    flag: [P("M4 13.5V3M4 3.5h7.5l-1.5 2.5 1.5 2.5H4")],
  };

  // Put the shapes of the icon `name` into the SVG element `svg`, in place of its children.
  function fill(svg, name) {
    const doc = svg.ownerDocument || document;
    const parts = [];
    for (const [tag, attrs] of SHAPES[name] || []) {
      const part = doc.createElementNS(NS, tag);
      for (const key of Object.keys(attrs)) {
        part.setAttribute(key, String(attrs[key]));
      }
      parts.push(part);
    }
    svg.replaceChildren(...parts);
    return svg;
  }

  // A new icon element.
  function icon(name) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "ico");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    svg.dataset.icon = name;
    return fill(svg, name);
  }

  if (typeof document !== "undefined" && document.addEventListener) {
    // The icons of index.html are empty SVG elements with `data-icon`.
    document.addEventListener("DOMContentLoaded", () => {
      for (const svg of document.querySelectorAll("svg[data-icon]")) {
        fill(svg, svg.dataset.icon);
      }
    });
  }
  return { icon: icon, fill: fill, names: Object.keys(SHAPES) };
})();

if (typeof module !== "undefined") {
  module.exports = NookkuIcons;
}

// The Markdown renderer of the chat page (#347).
//
// Security: the renderer never parses HTML and never makes HTML text. It makes a tree of plain
// objects, and toDom makes DOM nodes from the tree with createElement and createTextNode. Thus
// HTML in a reply shows as text, and a reply cannot run code on the page. toDom accepts only the
// tags and the attributes of the lists below, and only a web URL, a data URI or a file of the
// page server as a link or a source. The page shows an SVG only in an iframe with "sandbox" and
// no "allow-scripts". The page shows a fence with the language vega-lite or mermaid as code.
//
// The renderer does not change the reply. The button "Text" shows the exact text of the reply.
"use strict";

(function (root) {
  // A longer reply shows as text, so that a slow parse cannot stop the page.
  const LIMIT = 200000;
  // A deeper nest of block quotes, lists or emphasis shows as text.
  const MAX_DEPTH = 16;
  // The path of the files of the page server, relative to the page URL.
  const FILES = "files/";
  const IMAGE = ["png", "jpg", "jpeg", "gif", "webp", "avif", "bmp", "ico"];
  const VIDEO = ["mp4", "webm", "ogv", "mov", "m4v"];
  const DATA_IMAGE = /^data:image\/(png|jpeg|gif|webp|avif|bmp);base64,[A-Za-z0-9+/=\s]*$/i;
  const DATA_VIDEO = /^data:video\/(mp4|webm|ogg);base64,[A-Za-z0-9+/=\s]*$/i;
  const DATA_SVG = /^data:image\/svg\+xml[;,]/i;
  const TAGS = new Set([
    "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "del", "code", "pre",
    "blockquote", "ul", "ol", "li", "hr", "table", "thead", "tbody", "tr", "th", "td", "a",
    "img", "video", "iframe", "span", "div", "button",
  ]);
  const ATTRS = new Set([
    "href", "src", "alt", "title", "class", "target", "rel", "start", "sandbox", "controls",
    "preload", "loading", "referrerpolicy", "data-path", "type", "data-kind", "data-src",
    "data-alt",
  ]);
  const NONE = { kind: "none" };

  function node(tag, attrs, children) {
    return { t: tag, a: attrs || {}, c: children || [] };
  }

  // ---- What a link or an image names ----

  // Return the kind of the target: "web" (an http or https URL), "mail", "data", "path" (a file
  // path, or a file URL), or "none" (the page does not show it, for example a script URL).
  function target(raw) {
    const text = raw.trim();
    if (text === "" || /[\u0000-\u001f\u007f]/.test(text)) {
      return NONE;
    }
    if (/^[A-Za-z]:[\\/]/.test(text)) {
      return { kind: "path", path: text };
    }
    const scheme = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(text);
    if (!scheme) {
      // A fragment, a query or a URL with no scheme is not a file.
      return /^[#?]|^\/\//.test(text) ? NONE : { kind: "path", path: text };
    }
    const name = scheme[1].toLowerCase();
    try {
      if (name === "http" || name === "https") {
        const url = new URL(text);
        return url.protocol === name + ":"
          ? { kind: "web", url: url.href, secure: name === "https", path: url.pathname }
          : NONE;
      }
      if (name === "mailto") {
        return { kind: "mail", url: text };
      }
      if (name === "data") {
        return { kind: "data", url: text };
      }
      if (name === "file") {
        const url = new URL(text);
        return url.host === "" ? { kind: "path", path: decodeURIComponent(url.pathname) } : NONE;
      }
    } catch (e) {
      return NONE;
    }
    return NONE;
  }

  function extension(path) {
    const m = /\.([A-Za-z0-9]+)$/.exec(path);
    return m ? m[1].toLowerCase() : "";
  }

  // "image", "video", "svg", or null if the page cannot show the target.
  function media(t) {
    if (t.kind === "data") {
      if (DATA_SVG.test(t.url)) return "svg";
      if (DATA_IMAGE.test(t.url)) return "image";
      if (DATA_VIDEO.test(t.url)) return "video";
      return null;
    }
    if (t.kind !== "path" && !(t.kind === "web" && t.secure)) {
      return null;
    }
    const ext = extension(t.path);
    if (ext === "svg") return "svg";
    if (IMAGE.includes(ext)) return "image";
    if (VIDEO.includes(ext)) return "video";
    return null;
  }

  function source(t) {
    return t.kind === "path" ? FILES + encodeURIComponent(t.path) : t.url;
  }

  function mediaNode(kind, t, alt) {
    if (t.kind === "web") {
      // A web file loads only after a click, so that the agent cannot make the page call a
      // server of its choice when the tester only reads the reply.
      const host = new URL(t.url).host;
      return node("span", { class: "remote" }, [
        node("button", {
          type: "button", class: "load", "data-kind": kind, "data-src": t.url, "data-alt": alt,
        }, ["Load the " + (kind === "svg" ? "SVG" : kind) + " from " + host]),
        " ",
        node("code", {}, [t.url]),
      ]);
    }
    return element(kind, source(t), alt);
  }

  function element(kind, src, alt) {
    if (kind === "image") {
      return node("img", { src: src, alt: alt, loading: "lazy", referrerpolicy: "no-referrer" });
    }
    if (kind === "video") {
      return node("video", { src: src, controls: "", preload: "metadata", class: "media" }, [alt]);
    }
    // An empty sandbox gives the SVG no script, no form and no origin of its own.
    return node("iframe", {
      src: src, sandbox: "", title: alt || "SVG", referrerpolicy: "no-referrer", class: "svg",
    });
  }

  function fileNode(path, label) {
    return node("span", { class: "file" }, [
      node("code", {}, [label || path]),
      node("button", { type: "button", class: "open", "data-path": path }, ["Open"]),
    ]);
  }

  function webLink(url, children) {
    return node("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, children);
  }

  // ---- Inline text ----

  // A link or an image at text[i] == "[": the label, the destination and the end, or null.
  function linkAt(text, i) {
    let depth = 0;
    let j = i;
    for (; j < text.length; j++) {
      const ch = text[j];
      if (ch === "\\") {
        j++;
      } else if (ch === "[") {
        depth++;
      } else if (ch === "]") {
        depth--;
        if (depth === 0) break;
      } else if (ch === "\n" && text[j + 1] === "\n") {
        return null;
      }
    }
    if (j >= text.length || text[j + 1] !== "(") {
      return null;
    }
    const label = text.slice(i + 1, j);
    let k = j + 2;
    while (text[k] === " ") k++;
    let dest;
    if (text[k] === "<") {
      const close = text.indexOf(">", k);
      if (close < 0 || text.slice(k, close).includes("\n")) return null;
      dest = text.slice(k + 1, close);
      k = close + 1;
    } else {
      let parens = 0;
      const start = k;
      for (; k < text.length; k++) {
        const ch = text[k];
        if (ch === "\\") {
          k++;
        } else if (ch === "(") {
          parens++;
        } else if (ch === ")") {
          if (parens === 0) break;
          parens--;
        } else if (/\s/.test(ch)) {
          break;
        }
      }
      dest = text.slice(start, k).replace(/\\([()])/g, "$1");
    }
    let title = "";
    const rest = /^\s*(?:"([^"]*)"|'([^']*)')?\s*\)/.exec(text.slice(k));
    if (!rest) {
      return null;
    }
    title = rest[1] || rest[2] || "";
    return { label: label, dest: dest, title: title, end: k + rest[0].length };
  }

  function image(m, whole, depth) {
    const t = target(m.dest);
    const kind = media(t);
    if (kind) {
      return [mediaNode(kind, t, m.label)];
    }
    if (t.kind === "path") {
      return [fileNode(t.path, m.label)];
    }
    // A web image often has no file extension in its URL.
    if (t.kind === "web" && t.secure) {
      return [mediaNode("image", t, m.label)];
    }
    if (t.kind === "web" || t.kind === "mail") {
      return [webLink(t.url, inline(m.label || t.url, depth + 1))];
    }
    return [whole];
  }

  function anchor(m, depth) {
    const t = target(m.dest);
    const label = inline(m.label, depth + 1);
    if (t.kind === "web" || t.kind === "mail") {
      return [webLink(t.url, label)];
    }
    if (t.kind === "path") {
      const kind = media(t);
      return kind ? [mediaNode(kind, t, m.label)] : [fileNode(t.path, m.label)];
    }
    // The page does not link to a script URL or a data URI. It shows the label as text.
    return label;
  }

  const DELIMS = ["**", "__", "~~", "*", "_"];
  const DELIM_TAG = { "**": "strong", __: "strong", "~~": "del", "*": "em", _: "em" };

  function isWord(ch) {
    return ch !== undefined && /[\p{L}\p{N}]/u.test(ch);
  }

  // The index of the delimiter that closes d, opened at start, or -1.
  function closing(text, start, d, missing) {
    if (missing.has(d)) return -1;
    let j = start;
    for (;;) {
      j = text.indexOf(d, j + 1);
      if (j < 0) {
        missing.add(d);
        return -1;
      }
      if (/\s/.test(text[j - 1])) continue;
      if (d.length === 1 && (text[j + 1] === d || text[j - 1] === d)) continue;
      if (d[0] === "_" && isWord(text[j + d.length])) continue;
      return j;
    }
  }

  function inline(text, depth) {
    if (depth > MAX_DEPTH) {
      return [text];
    }
    const out = [];
    const missing = new Set();
    let buf = "";
    let i = 0;
    const flush = () => {
      if (buf) {
        out.push(buf);
        buf = "";
      }
    };
    while (i < text.length) {
      const ch = text[i];
      if (ch === "\\" && /[!-/:-@[-`{-~]/.test(text[i + 1] || "")) {
        buf += text[i + 1];
        i += 2;
        continue;
      }
      if (ch === "\n") {
        flush();
        out.push(node("br"));
        i++;
        continue;
      }
      if (ch === "`") {
        let n = 1;
        while (text[i + n] === "`") n++;
        const fence = "`".repeat(n);
        let close = text.indexOf(fence, i + n);
        while (close >= 0 && text[close + n] === "`") {
          let m = close;
          while (text[m] === "`") m++;
          close = text.indexOf(fence, m);
        }
        if (close < 0) {
          buf += fence;
          i += n;
          continue;
        }
        let code = text.slice(i + n, close).replace(/\n/g, " ");
        if (code.length > 2 && code[0] === " " && code[code.length - 1] === " ") {
          code = code.slice(1, -1);
        }
        flush();
        out.push(node("code", {}, [code]));
        i = close + n;
        continue;
      }
      if (ch === "!" && text[i + 1] === "[") {
        const m = linkAt(text, i + 1);
        if (m) {
          flush();
          out.push(...image(m, text.slice(i, m.end), depth));
          i = m.end;
          continue;
        }
      }
      if (ch === "[") {
        const m = linkAt(text, i);
        if (m) {
          flush();
          out.push(...anchor(m, depth));
          i = m.end;
          continue;
        }
      }
      if (ch === "<") {
        const m = /^<((?:https?|mailto):[^\s<>]+)>/i.exec(text.slice(i, i + 2048));
        const t = m ? target(m[1]) : NONE;
        if (t.kind === "web" || t.kind === "mail") {
          flush();
          out.push(webLink(t.url, [m[1]]));
          i += m[0].length;
          continue;
        }
      }
      if ((ch === "h" || ch === "H") && !isWord(text[i - 1])) {
        const m = /^https?:[^\s<>]+/i.exec(text.slice(i, i + 2048));
        if (m) {
          const raw = m[0].replace(/[.,;:!?'")\]]+$/, "");
          const t = target(raw);
          if (t.kind === "web") {
            flush();
            out.push(webLink(t.url, [raw]));
            i += raw.length;
            continue;
          }
        }
      }
      const d = DELIMS.find((x) => text.startsWith(x, i));
      if (d && text[i + d.length] && !/\s/.test(text[i + d.length])) {
        const opens = d[0] !== "_" || !isWord(text[i - 1]);
        const close = opens ? closing(text, i + d.length, d, missing) : -1;
        if (close > i + d.length) {
          flush();
          out.push(node(DELIM_TAG[d], {}, inline(text.slice(i + d.length, close), depth + 1)));
          i = close + d.length;
          continue;
        }
        buf += d;
        i += d.length;
        continue;
      }
      buf += ch;
      i++;
    }
    flush();
    return out;
  }

  // ---- Blocks ----

  const FENCE = /^( {0,3})(`{3,}|~{3,})\s*([^\s`]*)[^`]*$/;
  const HEADING = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$/;
  const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
  const QUOTE = /^ {0,3}> ?/;
  const ITEM = /^( {0,12})([-*+]|\d{1,9}[.)])([ \t]+|$)/;
  const SEPARATOR = /^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$/;

  function blank(line) {
    return /^\s*$/.test(line);
  }

  function cells(line) {
    let text = line.trim();
    if (text.startsWith("|")) text = text.slice(1);
    if (text.endsWith("|") && !text.endsWith("\\|")) text = text.slice(0, -1);
    const out = [];
    let cell = "";
    for (let i = 0; i < text.length; i++) {
      if (text[i] === "\\" && text[i + 1] === "|") {
        cell += "|";
        i++;
      } else if (text[i] === "|") {
        out.push(cell.trim());
        cell = "";
      } else {
        cell += text[i];
      }
    }
    out.push(cell.trim());
    return out;
  }

  function isTable(lines, i) {
    return (
      i + 1 < lines.length &&
      lines[i].includes("|") &&
      SEPARATOR.test(lines[i + 1]) &&
      lines[i + 1].includes("-") &&
      cells(lines[i]).length === cells(lines[i + 1]).length
    );
  }

  function starts(lines, i) {
    const line = lines[i];
    return (
      FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) ||
      ITEM.test(line) || isTable(lines, i)
    );
  }

  function codeBlock(lang, code) {
    const children = [];
    if (lang) {
      const chart = lang === "mermaid" || lang === "vega-lite";
      children.push(node("p", { class: "lang" }, [chart ? lang + " (shown as code)" : lang]));
    }
    children.push(node("pre", {}, [node("code", {}, [code])]));
    return node("div", { class: "code" }, children);
  }

  function table(lines, i, depth) {
    const head = cells(lines[i]);
    const align = cells(lines[i + 1]).map((c) => {
      const left = c.startsWith(":");
      const right = c.endsWith(":");
      return left && right ? "center" : right ? "right" : left ? "left" : "";
    });
    const cell = (tag, text, n) =>
      node(tag, align[n] ? { class: align[n] } : {}, inline(text, depth + 1));
    const rows = [];
    let j = i + 2;
    for (; j < lines.length && !blank(lines[j]) && lines[j].includes("|"); j++) {
      const row = cells(lines[j]);
      rows.push(node("tr", {}, head.map((_, n) => cell("td", row[n] || "", n))));
    }
    const thead = node("thead", {}, [node("tr", {}, head.map((h, n) => cell("th", h, n)))]);
    const wrap = node("div", { class: "table" }, [node("table", {}, [thead, node("tbody", {}, rows)])]);
    return { node: wrap, end: j };
  }

  function list(lines, i, depth) {
    const first = ITEM.exec(lines[i]);
    const indent = first[1].length;
    const ordered = /\d/.test(first[2]);
    const items = [];
    let j = i;
    while (j < lines.length) {
      const m = ITEM.exec(lines[j]);
      if (!m || m[1].length !== indent || /\d/.test(m[2]) !== ordered) break;
      const column = m[0].length;
      const body = [lines[j].slice(column)];
      j++;
      while (j < lines.length) {
        const line = lines[j];
        if (blank(line)) {
          const next = lines.slice(j + 1).findIndex((l) => !blank(l));
          const after = next < 0 ? null : lines[j + 1 + next];
          if (after !== null && /^ */.exec(after)[0].length >= column) {
            body.push("");
            j++;
            continue;
          }
          break;
        }
        const lead = /^ */.exec(line)[0].length;
        if (lead >= column) {
          body.push(line.slice(column));
        } else if (ITEM.test(line) || starts(lines, j) || blank(body[body.length - 1])) {
          break;
        } else {
          body.push(line.trim());
        }
        j++;
      }
      items.push(node("li", {}, blocks(body, depth + 1)));
      if (j < lines.length && blank(lines[j])) {
        const next = lines.slice(j).findIndex((l) => !blank(l));
        if (next < 0) break;
        const m2 = ITEM.exec(lines[j + next]);
        if (!m2 || m2[1].length !== indent) break;
        j += next;
      }
    }
    const attrs = {};
    const start = ordered ? parseInt(first[2], 10) : 1;
    if (start !== 1) attrs.start = String(start);
    return { node: node(ordered ? "ol" : "ul", attrs, items), end: j };
  }

  function blocks(lines, depth) {
    if (depth > MAX_DEPTH) {
      return [node("p", {}, [lines.join("\n")])];
    }
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (blank(line)) {
        i++;
        continue;
      }
      let m = FENCE.exec(line);
      if (m) {
        const fence = m[2];
        const indent = m[1].length;
        const close = new RegExp("^ {0,3}" + (fence[0] === "`" ? "`" : "~") + "{" + fence.length + ",}[ \\t]*$");
        const body = [];
        i++;
        while (i < lines.length && !close.test(lines[i])) {
          body.push(lines[i].replace(new RegExp("^ {0," + indent + "}"), ""));
          i++;
        }
        i++;
        out.push(codeBlock(m[3], body.join("\n")));
        continue;
      }
      m = HEADING.exec(line);
      if (m) {
        out.push(node("h" + m[1].length, {}, inline(m[2] || "", depth)));
        i++;
        continue;
      }
      if (RULE.test(line)) {
        out.push(node("hr"));
        i++;
        continue;
      }
      if (QUOTE.test(line)) {
        const body = [];
        while (i < lines.length && QUOTE.test(lines[i])) {
          body.push(lines[i].replace(QUOTE, ""));
          i++;
        }
        out.push(node("blockquote", {}, blocks(body, depth + 1)));
        continue;
      }
      if (isTable(lines, i)) {
        const t = table(lines, i, depth);
        out.push(t.node);
        i = t.end;
        continue;
      }
      if (ITEM.test(line)) {
        const l = list(lines, i, depth);
        out.push(l.node);
        i = l.end;
        continue;
      }
      const para = [line.replace(/^\s+/, "")];
      i++;
      while (i < lines.length && !blank(lines[i]) && !starts(lines, i)) {
        para.push(lines[i].replace(/^\s+/, ""));
        i++;
      }
      out.push(node("p", {}, inline(para.join("\n"), depth)));
    }
    return out;
  }

  // The tree of a reply. A reply over LIMIT characters is one block of text.
  function render(text) {
    if (text.length > LIMIT) {
      return [node("pre", {}, [text])];
    }
    return blocks(text.split(/\r\n|\r|\n/), 0);
  }

  // ---- DOM ----

  function safeUrl(name, value) {
    if (name === "href") return /^(https?|mailto):/i.test(value);
    if (name === "src") return /^(https:|data:|files\/)/i.test(value);
    if (name === "data-src") return /^https:/i.test(value);
    return true;
  }

  function domNode(n, doc) {
    if (typeof n === "string") {
      return doc.createTextNode(n);
    }
    if (!TAGS.has(n.t)) {
      return doc.createTextNode("");
    }
    const e = doc.createElement(n.t);
    for (const name of Object.keys(n.a)) {
      const value = String(n.a[name]);
      if (ATTRS.has(name) && safeUrl(name, value)) {
        e.setAttribute(name, value);
      }
    }
    if (n.t === "iframe") {
      // Each iframe has an empty sandbox, also if a defect of the renderer gave it a value.
      e.setAttribute("sandbox", "");
    }
    for (const c of n.c) {
      e.appendChild(domNode(c, doc));
    }
    return e;
  }

  function toDom(nodes, doc) {
    const frag = doc.createDocumentFragment();
    for (const n of nodes) {
      frag.appendChild(domNode(n, doc));
    }
    return frag;
  }

  // ---- The block of a reply on the page ----

  // A turn of the agent: the reply as Markdown, and a button that shows the exact text.
  function reply(doc, cls, who, text) {
    const li = doc.createElement("li");
    li.className = "turn " + cls;
    const label = doc.createElement("p");
    label.className = "who";
    label.appendChild(doc.createTextNode(who + " "));
    const toggle = doc.createElement("button");
    toggle.type = "button";
    toggle.className = "toggle";
    toggle.textContent = "Text";
    toggle.title = "Show the exact text of the reply";
    label.appendChild(toggle);
    const raw = doc.createElement("pre");
    raw.className = "text";
    raw.textContent = text;
    raw.hidden = true;
    const shown = doc.createElement("div");
    shown.className = "text md";
    try {
      shown.appendChild(toDom(render(text), doc));
    } catch (e) {
      // If the renderer fails, the page shows the exact text.
      shown.hidden = true;
      raw.hidden = false;
      toggle.hidden = true;
    }
    toggle.addEventListener("click", () => {
      raw.hidden = !raw.hidden;
      shown.hidden = !shown.hidden;
      toggle.textContent = raw.hidden ? "Text" : "Markdown";
    });
    li.append(label, shown, raw);
    return li;
  }

  // A click on "Open" asks the page server to open the file with the system app.
  async function openFile(button) {
    let note = button.nextElementSibling;
    if (!note || !note.classList.contains("open-note")) {
      note = button.ownerDocument.createElement("span");
      note.className = "open-note";
      button.after(note);
    }
    button.disabled = true;
    try {
      const resp = await fetch("api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: button.getAttribute("data-path") }),
      });
      const data = await resp.json();
      note.textContent = data.opened ? "Opened." : data.error || "nookku: the file did not open.";
    } catch (e) {
      note.textContent = "nookku: the page server does not answer.";
    } finally {
      button.disabled = false;
    }
  }

  // A click on "Load" shows a web image, video or SVG in place of the button.
  function load(button) {
    const kind = button.getAttribute("data-kind");
    const src = button.getAttribute("data-src") || "";
    if (["image", "video", "svg"].includes(kind) && /^https:/i.test(src)) {
      const alt = button.getAttribute("data-alt") || "";
      button.parentNode.replaceWith(domNode(element(kind, src, alt), button.ownerDocument));
    }
  }

  function listen(doc) {
    doc.addEventListener("click", (event) => {
      const button = event.target.closest && event.target.closest("button.open, button.load");
      if (button && button.classList.contains("open")) {
        openFile(button);
      } else if (button) {
        load(button);
      }
    });
  }

  const api = {
    render: render, toDom: toDom, target: target, reply: reply, load: load, LIMIT: LIMIT,
  };
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.NookkuRender = api;
    listen(root.document);
  }
})(globalThis);

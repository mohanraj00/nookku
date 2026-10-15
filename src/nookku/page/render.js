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
  // The longest destination or title of a link.
  const LINK_MAX = 4096;
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

  // True if the URL goes to this computer (a loopback host). A cookie has no port, so the browser
  // sends the session cookie of the page to each port of the page host (SPEC.md section 5,
  // "Replies"). The URL parser gives the host in its normal form, for example 127.1 as 127.0.0.1.
  function loopback(text) {
    let host;
    try {
      host = new URL(text).hostname.toLowerCase().replace(/\.$/, "");
    } catch (e) {
      return true;
    }
    return (
      host === "localhost" ||
      host.endsWith(".localhost") ||
      /^127\.\d+\.\d+\.\d+$/.test(host) ||
      host === "0.0.0.0" ||
      host === "[::1]" ||
      host === "[::]" ||
      /^\[::ffff:(7f[0-9a-f]{2}:[0-9a-f]{1,4}|0:0)\]$/.test(host)
    );
  }

  // Return the kind of the target: "web" (an http or https URL), "mail", "data", "path" (a file
  // path, or a file URL), or "none" (the page does not show it, for example a script URL).
  function target(raw) {
    const text = raw.trim();
    if (text === "" || /[\u0000-\u001f\u007f]/.test(text)) {
      return NONE;
    }
    // A path that starts with 2 slashes or backslashes is a network path on Windows (UNC). A
    // check of it sends the credentials of the person to that host, so the page does not show it.
    if (/^[\\/]{2}/.test(text)) {
      return NONE;
    }
    if (/^[A-Za-z]:[\\/]/.test(text)) {
      return { kind: "path", path: text };
    }
    const scheme = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(text);
    if (!scheme) {
      // A fragment or a query is not a file.
      return /^[#?]/.test(text) ? NONE : { kind: "path", path: text };
    }
    const name = scheme[1].toLowerCase();
    try {
      if (name === "http" || name === "https") {
        const url = new URL(text);
        // A loopback URL shows as text, so that no click sends the session cookie to it.
        return url.protocol === name + ":" && !loopback(url.href)
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
        const path = decodeURIComponent(url.pathname);
        return url.host === "" && !/^[\\/]{2}/.test(path) ? { kind: "path", path: path } : NONE;
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

  // The index of the "]" that closes each "[" of a text, in one pass, so that a text with many
  // "[" and no "]" does not take quadratic time.
  function brackets(text) {
    const match = new Map();
    const open = [];
    for (let j = 0; j < text.length; j++) {
      const ch = text[j];
      if (ch === "\\") {
        j++;
      } else if (ch === "[") {
        open.push(j);
      } else if (ch === "]" && open.length > 0) {
        match.set(open.pop(), j);
      }
    }
    return match;
  }

  // A link or an image at text[i] == "[": the label, the destination and the end, or null.
  // A destination and a title are at most LINK_MAX characters, so each call takes bounded time.
  function linkAt(text, i, match) {
    const j = match.get(i);
    if (j === undefined || text[j + 1] !== "(") {
      return null;
    }
    const label = text.slice(i + 1, j);
    let k = j + 2;
    while (text[k] === " ") k++;
    let dest;
    if (text[k] === "<") {
      const at = text.slice(k, k + LINK_MAX).indexOf(">");
      const close = at < 0 ? -1 : k + at;
      if (close < 0 || text.slice(k, close).includes("\n")) return null;
      dest = text.slice(k + 1, close);
      k = close + 1;
    } else {
      let parens = 0;
      const start = k;
      for (; k < text.length; k++) {
        const ch = text[k];
        // A destination has no "[", so that each "[" starts at most one scan of the text.
        if (k - start > LINK_MAX || ch === "[") {
          return null;
        } else if (ch === "\\") {
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
    const rest = /^\s*(?:"([^"]*)"|'([^']*)')?\s*\)/.exec(text.slice(k, k + LINK_MAX));
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

  // Each index where the delimiter d can close, in one pass of the text.
  function closers(text, d) {
    const found = [];
    for (let j = text.indexOf(d, 1); j >= 0; j = text.indexOf(d, j + 1)) {
      if (/\s/.test(text[j - 1])) continue;
      if (d.length === 1 && (text[j + 1] === d || text[j - 1] === d)) continue;
      if (d[0] === "_" && isWord(text[j + d.length])) continue;
      found.push(j);
    }
    return found;
  }

  // The index of the delimiter that closes d, opened before start, or -1. A binary search in the
  // closers of d, so that many delimiters with no closer do not take quadratic time.
  function closing(text, start, d, cache) {
    if (!cache.has(d)) cache.set(d, closers(text, d));
    const list = cache.get(d);
    let lo = 0;
    let hi = list.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (list[mid] > start) hi = mid;
      else lo = mid + 1;
    }
    return lo < list.length ? list[lo] : -1;
  }

  function inline(text, depth) {
    if (depth > MAX_DEPTH) {
      return [text];
    }
    const out = [];
    const cache = new Map();
    const match = brackets(text);
    // The lengths of the backtick runs with no closing run.
    const noTicks = new Set();
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
        let close = noTicks.has(n) ? -1 : text.indexOf(fence, i + n);
        while (close >= 0 && text[close + n] === "`") {
          let m = close;
          while (text[m] === "`") m++;
          close = text.indexOf(fence, m);
        }
        if (close < 0) {
          noTicks.add(n);
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
        const m = linkAt(text, i + 1, match);
        if (m) {
          flush();
          out.push(...image(m, text.slice(i, m.end), depth));
          i = m.end;
          continue;
        }
      }
      if (ch === "[") {
        const m = linkAt(text, i, match);
        if (m) {
          flush();
          out.push(...anchor(m, depth));
          i = m.end;
          continue;
        }
      }
      if (ch === "<" && /^<(?:https?|mailto):/i.test(text.slice(i, i + 8))) {
        const m = /^<((?:https?|mailto):[^\s<>]+)>/i.exec(text.slice(i, i + 2048));
        const t = m ? target(m[1]) : NONE;
        if (t.kind === "web" || t.kind === "mail") {
          flush();
          out.push(webLink(t.url, [m[1]]));
          i += m[0].length;
          continue;
        }
      }
      if (/^https?:/i.test(text.slice(i, i + 6)) && !isWord(text[i - 1])) {
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
        const close = opens ? closing(text, i + d.length, d, cache) : -1;
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

  // The start of a fence. fence() checks the rest of the line with no regular expression: a
  // regular expression with 2 parts that both match a space took quadratic time on a long line.
  const FENCE_START = /^( {0,3})(`{3,}|~{3,})/;
  const HEADING = /^ {0,3}(#{1,6})(?=[ \t]|$)/;
  const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
  const QUOTE = /^ {0,3}> ?/;
  const ITEM = /^( {0,12})([-*+]|\d{1,9}[.)])([ \t]+|$)/;
  const SEPARATOR_CELL = /^:?-+:?$/;

  // The indent, the marker and the language of a fence line, or null. The rest of the line after
  // the marker must have no backtick. The language is its first word.
  function fence(line) {
    const m = FENCE_START.exec(line);
    if (!m) return null;
    const rest = line.slice(m[0].length);
    if (rest.indexOf("`") !== -1) return null;
    const lang = /^[^\s`]*/.exec(rest.replace(/^\s+/, ""))[0];
    return [m[0], m[1], m[2], lang];
  }

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

  function space(c) {
    return c === " " || c === "\t";
  }

  // A heading line, as {level, text}, or null. The text has no closing "#" marks. The loops
  // read the line from its end one time, with no backtracking regular expression.
  function heading(line) {
    const m = HEADING.exec(line);
    if (!m) return null;
    const text = line.slice(m[0].length);
    let end = text.length;
    while (end > 0 && space(text[end - 1])) end--;
    let k = end;
    while (k > 0 && text[k - 1] === "#") k--;
    if (k < end && (k === 0 || space(text[k - 1]))) end = k;
    while (end > 0 && space(text[end - 1])) end--;
    let start = 0;
    while (start < end && space(text[start])) start++;
    return { level: m[1].length, text: text.slice(start, end) };
  }

  // A separator line of a table, such as "| --- | :-: |". The check reads each cell one time,
  // with no backtracking regular expression over the full line, so the time is linear.
  function separator(line) {
    let text = line.trim();
    if (text.startsWith("|")) text = text.slice(1);
    if (text.endsWith("|")) text = text.slice(0, -1);
    return text.split("|").every((cell) => SEPARATOR_CELL.test(cell.trim()));
  }

  function isTable(lines, i) {
    return (
      i + 1 < lines.length &&
      lines[i].includes("|") &&
      separator(lines[i + 1]) &&
      cells(lines[i]).length === cells(lines[i + 1]).length
    );
  }

  function starts(lines, i) {
    const line = lines[i];
    return (
      fence(line) || heading(line) || RULE.test(line) || QUOTE.test(line) ||
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

  // For each line, the index of the first line at or after it that is not blank, or -1. One pass
  // from the end, so that many blank lines in a list do not take quadratic time.
  function filled(lines) {
    const next = new Array(lines.length);
    let n = -1;
    for (let j = lines.length - 1; j >= 0; j--) {
      if (!blank(lines[j])) n = j;
      next[j] = n;
    }
    return next;
  }

  function list(lines, i, depth, next) {
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
          const k = j + 1 < lines.length ? next[j + 1] : -1;
          const after = k < 0 ? null : lines[k];
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
        const k = next[j];
        if (k < 0) break;
        const m2 = ITEM.exec(lines[k]);
        if (!m2 || m2[1].length !== indent) break;
        j = k;
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
    let next = null;
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (blank(line)) {
        i++;
        continue;
      }
      let m = fence(line);
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
      const h = heading(line);
      if (h) {
        out.push(node("h" + h.level, {}, inline(h.text, depth)));
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
        next = next || filled(lines);
        const l = list(lines, i, depth, next);
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
    if (/^https?:/i.test(value) && loopback(value)) return false;
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
    // key.js loads a file of the page server with the page key (SPEC.md section 5, "Session").
    const page = root.NookkuPage;
    for (const name of Object.keys(n.a)) {
      const value = String(n.a[name]);
      if (!ATTRS.has(name) || !safeUrl(name, value)) {
        continue;
      }
      if (name === "src" && value.startsWith(FILES) && page) {
        page.fileSrc(e, value);
      } else {
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

  // The parts of a reply: the reply as Markdown (`shown`), its exact text (`raw`, hidden) and a
  // button that shows the one or the other (`toggle`). The export (#354) gives `change`, a
  // function that changes the tree before toDom makes nodes. The chat page puts the parts into
  // its own layout (#391).
  function parts(doc, text, change) {
    const toggle = doc.createElement("button");
    toggle.type = "button";
    toggle.className = "toggle";
    toggle.title = "Show the exact text of the reply";
    toggle.setAttribute("aria-pressed", "false");
    const label = doc.createElement("span");
    label.textContent = "Text";
    toggle.appendChild(label);
    const raw = doc.createElement("pre");
    raw.className = "text";
    raw.textContent = text;
    raw.hidden = true;
    const shown = doc.createElement("div");
    shown.className = "text md";
    try {
      const tree = render(text);
      shown.appendChild(toDom(change ? change(tree) : tree, doc));
    } catch (e) {
      // If the renderer fails, the page shows the exact text.
      shown.hidden = true;
      raw.hidden = false;
      toggle.hidden = true;
    }
    toggle.addEventListener("click", () => {
      raw.hidden = !raw.hidden;
      shown.hidden = !shown.hidden;
      label.textContent = raw.hidden ? "Text" : "Markdown";
      toggle.setAttribute("aria-pressed", raw.hidden ? "false" : "true");
    });
    return { toggle: toggle, shown: shown, raw: raw };
  }

  // A change for parts: each file of the page server names the test `id`, with the query
  // "?test=<id>" (#398). The dashboard opens the page of an older test, and the server then
  // checks each file against the folder of that test. The id goes into the URL only encoded.
  function forTest(id) {
    const query = "?test=" + encodeURIComponent(String(id));
    function walk(n) {
      if (typeof n === "string") {
        return n;
      }
      const a = Object.assign({}, n.a);
      if (typeof a.src === "string" && a.src.startsWith(FILES)) {
        a.src += query;
      }
      return node(n.t, a, n.c.map(walk));
    }
    return (tree) => tree.map(walk);
  }

  // A turn of the agent, as the export shows it: a label with the button, the reply as
  // Markdown, and the exact text.
  function reply(doc, cls, who, text, change) {
    const li = doc.createElement("li");
    li.className = "turn " + cls;
    const label = doc.createElement("p");
    label.className = "who";
    label.appendChild(doc.createTextNode(who + " "));
    const made = parts(doc, text, change);
    label.appendChild(made.toggle);
    li.append(label, made.shown, made.raw);
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
    if (["image", "video", "svg"].includes(kind) && /^https:/i.test(src) && !loopback(src)) {
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
    render: render, toDom: toDom, target: target, reply: reply, parts: parts, load: load,
    forTest: forTest, LIMIT: LIMIT,
  };
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.NookkuRender = api;
    listen(root.document);
  }
})(globalThis);

"""Export a test as one HTML file (#354).

The file holds the CSS, the script and the data inline. It shows the chat, the trace steps, the
notes, the audit result and the seal state, so a person with no project and no nookku can read
the test.

Security:
- The file loads nothing from the network. Its Content Security Policy permits only its own inline
  script and style (by hash), and images and videos from `data:` URIs. A web URL shows as text.
- The file runs no text of the agent as HTML or script. The page renderer (`page/render.js`) makes
  DOM nodes from a fixed list of tags, and `page/export.js` removes each link, button and source
  that is not a `data:` URI. The data is JSON in a `<script type="application/json">` block, with
  each `<`, `>` and `&` as a `\\u` escape, so a `</script>` in a text cannot end the block.
- The file holds no page token and no page URL.
- An image or a video that a reply names as a file goes into the file as a `data:` URI, with the
  file rule of the page (`page.open_checked`) for the exported test, up to a size limit.
- The export reads only. `write` never writes into the state folder, a test folder or a seal home,
  and replaces the name of the output file, so a link at that name cannot send the write to a
  record.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from nookku import __version__, dashboard, notes, page, seal, state

# The route of the page server, after the token: api/export/<test id>.
ROUTE = "api/export"
# The largest image or video file that goes into the file, and the largest sum of all of them.
# Above a limit, the file shows the path. These are chosen values, not measurements.
MAX_MEDIA = 4 << 20
MAX_TOTAL = 32 << 20
# The most file paths of one export that the export reads.
MAX_PATHS = 200
# The longest text of a trace step in the file. A longer text is cut, with a note.
MAX_STEP_TEXT = 4000
# The renderer shows a longer reply as text with no media (`LIMIT` in page/render.js).
RENDER_LIMIT = 200_000
# The page files that go into the export, in this order.
STYLES = ("app.css", "render.css", "export.css")
SCRIPTS = ("render.js", "export.js")

NO_ID = "nookku: no test has this id."
NO_TEST = "nookku: no test to export. Start one in the harness with: nookku start"
NOT_FINITE = "nookku: a file of the test has a number that is not finite. The export shows no value"


class ExportError(Exception):
    """The export cannot write the file."""


# ---- The files that a reply names ----

# The longest destination of a link (`LINK_MAX` in page/render.js).
LINK_MAX = 4096
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _path_of(raw: str) -> str | None:
    """The file path of a link target, with the rule of `target` in page/render.js, or None if
    the target is not a file of an image or a video type."""
    text = raw.strip()
    if Path(text).suffix.lower() not in page.MEDIA:
        return None
    if _DRIVE.match(text):
        return text
    if text.lower().startswith("file:"):
        parts = urlsplit(text)
        return unquote(parts.path) if parts.netloc == "" else None
    if _SCHEME.match(text) or text.startswith(("#", "?", "//")):
        return None
    return text


def _brackets(text: str) -> dict[int, int]:
    """The index of the "]" that closes each "[", as `brackets` in page/render.js."""
    match: dict[int, int] = {}
    opened: list[int] = []
    j = 0
    while j < len(text):
        ch = text[j]
        if ch == "\\":
            j += 1
        elif ch == "[":
            opened.append(j)
        elif ch == "]" and opened:
            match[opened.pop()] = j
        j += 1
    return match


def _destination(text: str, j: int) -> str | None:
    """The destination of the link whose label ends at text[j] == "]", with the grammar of
    `linkAt` in page/render.js, or None. A destination has no "[", so each "[" starts at most
    one scan."""
    if text[j + 1 : j + 2] != "(":
        return None
    k = j + 2
    while text[k : k + 1] == " ":
        k += 1
    if text[k : k + 1] == "<":
        close = text.find(">", k, k + LINK_MAX)
        if close < 0 or "\n" in text[k:close]:
            return None
        dest, k = text[k + 1 : close], close + 1
    else:
        parens, start = 0, k
        while k < len(text):
            ch = text[k]
            if k - start > LINK_MAX or ch == "[":
                return None
            if ch == "\\":
                k += 1
            elif ch == "(":
                parens += 1
            elif ch == ")":
                if parens == 0:
                    break
                parens -= 1
            elif ch.isspace():
                break
            k += 1
        dest = re.sub(r"\\([()])", r"\1", text[start:k])
    if not re.match(r"\s*(?:\"[^\"]*\"|'[^']*')?\s*\)", text[k : k + LINK_MAX]):
        return None
    return dest


def paths(text: str) -> list[str]:
    """The file path of each Markdown link or image of a reply that names an image or a video
    file, with the link grammar of page/render.js. The renderer does not parse a link in code,
    so the list can have a path that the reply does not show. The file shows each such file
    in a list at its end, so the file holds no file that it does not show."""
    if len(text) > RENDER_LIMIT:
        return []
    found = (_destination(text, j) for j in _brackets(text).values())
    named = (_path_of(d) for d in found if d is not None)
    return list(dict.fromkeys(p for p in named if p))


def media(root: Path, folder: Path, texts: list[str]) -> tuple[dict[str, str], list[str]]:
    """The `data:` URI of each image or video file that the texts name, by its path as the reply
    gives it, and the paths that are above a limit."""
    out: dict[str, str] = {}
    big: list[str] = []
    total = 0
    names = list(dict.fromkeys(p for t in texts for p in paths(t)))[:MAX_PATHS]
    for name in names:
        found = page.open_checked(root, name, folder)
        if found is None:
            continue
        fd, real = found
        with os.fdopen(fd, "rb") as f:
            kind = page.MEDIA.get(real.suffix.lower())
            size = os.fstat(f.fileno()).st_size
            if kind is None:
                continue
            if size > MAX_MEDIA or total + size > MAX_TOTAL:
                big.append(name)
                continue
            body = f.read(MAX_MEDIA + 1)
        if len(body) > MAX_MEDIA or total + len(body) > MAX_TOTAL:
            big.append(name)
            continue
        total += len(body)
        out[name] = f"data:{kind};base64,{base64.b64encode(body).decode('ascii')}"
    return out, big


# ---- The trace steps ----


def _cut(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= MAX_STEP_TEXT:
        return text
    return text[:MAX_STEP_TEXT] + f"\n(cut: the export holds the first {MAX_STEP_TEXT} characters)"


def steps(folder: Path) -> tuple[dict[int, list[dict[str, Any]]], str | None]:
    """The model items of trace.jsonl (SPEC.md section 8.2) for each turn, and an error. A test
    with no trace.jsonl has no steps and no error."""
    out: dict[int, list[dict[str, Any]]] = {}
    try:
        lines = (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return out, None
    except (OSError, ValueError) as e:
        return out, f"trace.jsonl: {e}"
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return {}, f"trace.jsonl:{number}: not valid JSON"
        if not isinstance(row, dict) or row.get("type") != "model_item":
            return {}, f"trace.jsonl:{number}: not a model_item row"
        turn = row.get("turn")
        if isinstance(turn, bool) or not isinstance(turn, int):
            continue
        ts, code = row.get("ts"), row.get("exit_code")
        number_ts = isinstance(ts, int | float) and not isinstance(ts, bool) and math.isfinite(ts)
        out.setdefault(turn, []).append(
            {
                "ts": ts if number_ts else None,
                "harness": _cut(row.get("harness")),
                "kind": _cut(row.get("kind")),
                "role": _cut(row.get("role")),
                "server": _cut(row.get("server")),
                "name": _cut(row.get("name")),
                "input": _cut(row.get("input")),
                "output": _cut(row.get("output")),
                "error": _cut(row.get("error")),
                "exit_code": code if isinstance(code, int) and not isinstance(code, bool) else None,
                "internal": row.get("harness_internal") is True,
                "line": number,
            }
        )
    return out, None


# ---- The data of the file ----


def _json_file(folder: Path, name: str) -> dict[str, Any] | None:
    try:
        data = json.loads((folder / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def data(root: Path, folder: Path) -> dict[str, Any]:
    """The data of the export of one test folder."""
    shown = page.view(root, folder.name)
    turn_rows: list[dict[str, Any]] = shown["turns"]
    texts = [t["shown"] for t in turn_rows if isinstance(t.get("shown"), str)]
    files, big = media(root, folder, texts)
    trace_steps, trace_error = steps(folder)
    note_rows = notes.view(root, folder.name)
    audit = _json_file(folder, "audit.json")
    findings = _json_file(folder, "findings.json")
    summary = dashboard.row(folder, dashboard.running_id(root))
    # The dashboard row gives each time of the manifest only if it is a finite number.
    test = shown["test"] and {**shown["test"], "started": summary["started"]}
    if test:
        test["ended"] = summary["ended"]
    errors = list(summary["errors"])
    errors += [e for e in (shown["error"], note_rows["error"], trace_error) if e]
    out = {
        "test": test,
        "summary": summary,
        "turns": turn_rows,
        "steps": {str(k): v for k, v in trace_steps.items()},
        "notes": note_rows["notes"],
        "breaks": audit.get("breaks") if audit and isinstance(audit.get("breaks"), list) else [],
        "audit_exit": audit.get("exit") if audit else None,
        "findings": (
            findings.get("findings")
            if findings and isinstance(findings.get("findings"), list)
            else []
        ),
        "media": files,
        "big": big,
        "max_media": MAX_MEDIA,
        "errors": errors,
        "exported": time.time(),
        "version": __version__,
    }
    clean, changed = _finite(out)
    found: dict[str, Any] = clean
    if changed:
        found["errors"].append(NOT_FINITE)
    return found


def _finite(value: Any) -> tuple[Any, bool]:
    """The value with None for each number that is not finite, and True if there was one. JSON
    has no NaN or Infinity (SPEC.md section 2), and a file of a test can have one."""
    if isinstance(value, float) and not math.isfinite(value):
        return None, True
    if isinstance(value, dict):
        pairs = [(k, _finite(v)) for k, v in value.items()]
        return {k: v for k, (v, _) in pairs}, any(c for _, (_, c) in pairs)
    if isinstance(value, list):
        items = [_finite(v) for v in value]
        return [v for v, _ in items], any(c for _, c in items)
    return value, False


def _json_block(value: Any) -> str:
    """JSON for a `<script type="application/json">` block. ASCII only, so a lone surrogate is a
    `\\u` escape. Each `<`, `>` and `&` is a `\\u` escape, so no text can end the block."""
    text = json.dumps(value, ensure_ascii=True, allow_nan=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _inline(name: str, end: str) -> str:
    text = page.page_file(name).decode("utf-8")
    if end in text.lower() or "<!--" in text:
        raise ExportError(f"the page file {name} cannot go inline")
    return text


def _sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def build(root: Path, folder: Path) -> bytes:
    """The HTML file of the export of one test folder."""
    style = "\n".join(_inline(n, "</style") for n in STYLES)
    scripts = [_inline(n, "</script") for n in SCRIPTS]
    csp = (
        "default-src 'none'; "
        f"script-src {' '.join(_sha(s) for s in scripts)}; style-src {_sha(style)}; "
        "img-src data:; media-src data:; base-uri 'none'; form-action 'none'"
    )
    tags = "".join(f"<script>{s}</script>\n" for s in scripts)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="referrer" content="no-referrer">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nookku test</title>
<style>{style}</style>
<script type="application/json" id="nookku-data">{_json_block(data(root, folder))}</script>
{tags}</head>
<body>
<header>
  <h1>Nookku test</h1>
  <p id="test"></p>
</header>
<main>
  <section id="summary" aria-label="Summary"></section>
  <p id="start" class="mark" hidden></p>
  <ol id="turns"></ol>
  <p id="end" class="mark" hidden></p>
</main>
<footer>
  <p class="note">An export of a nookku test. This file loads nothing from the network.</p>
</footer>
</body>
</html>
"""
    return html.encode("utf-8")


# ---- The output file ----


def _guarded(root: Path) -> list[Path]:
    """The folders that hold records or seals. The export never writes into them."""
    found = [state.state(root), seal.home(), seal.old_home(), *state.tests_newest_first(root)]
    return [p.resolve() for p in found]


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def _inside(fd: int, guarded: set[tuple[int, int]]) -> bool:
    """True if the folder of the descriptor, or a folder above it, is a guarded folder. The walk
    goes up with "..", so it checks the real folder, not a path that a link can change."""
    current = os.dup(fd)
    try:
        while True:
            st = os.fstat(current)
            if (st.st_dev, st.st_ino) in guarded:
                return True
            above = os.open("..", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0), dir_fd=current)
            up = os.fstat(above)
            os.close(current)
            current = above
            if (up.st_dev, up.st_ino) == (st.st_dev, st.st_ino):
                return False
    finally:
        os.close(current)


def write(root: Path, folder: Path, out: Path) -> Path:
    """Write the export of a test folder to `out`. Raise ExportError if the export must not
    write there. Return the path of the file."""
    body = build(root, folder)
    parent = out.parent.resolve()
    target = parent / out.name
    guarded = _guarded(root)
    if any(target == g or target.is_relative_to(g) for g in guarded):
        raise ExportError(
            f"{target} is in the state folder, a test folder or a seal home. Give another path."
        )
    # `os.rename` names the dir_fd support of `os.replace` too.
    if os.open not in os.supports_dir_fd or os.rename not in os.supports_dir_fd:
        # A system with no `dir_fd` (Windows): the path check above is the only check.
        return _write_plain(target, body)
    try:
        fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as e:
        raise ExportError(f"cannot open the folder {parent}: {e.strerror}") from e
    try:
        ids = {i for i in (_identity(g) for g in guarded) if i is not None}
        if _inside(fd, ids):
            raise ExportError(f"{parent} is in the state folder, a test folder or a seal home.")
        _replace_at(fd, out.name, body, target)
    finally:
        os.close(fd)
    return target


def _replace_at(fd: int, name: str, body: bytes, target: Path) -> None:
    """Write `body` to a new file in the folder `fd`, then give it the name `name`. An old entry
    with the name must be a regular file. The rename replaces the entry, so a hard link or a
    symlink at the name cannot send the bytes to another file."""
    try:
        old = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        old = None
    except OSError as e:
        raise ExportError(f"cannot read {target}: {e.strerror}") from e
    if old is not None and not (old.st_mode & 0o170000 == 0o100000):
        raise ExportError(f"{target} exists and is not a regular file. Give another path.")
    temp = f".{name}.{os.getpid()}.{time.time_ns()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        tf = os.open(temp, flags, 0o644, dir_fd=fd)
    except OSError as e:
        raise ExportError(f"cannot write in the folder of {target}: {e.strerror}") from e
    try:
        with os.fdopen(tf, "wb") as f:
            f.write(body)
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
    except OSError as e:
        with contextlib.suppress(OSError):
            os.unlink(temp, dir_fd=fd)
        raise ExportError(f"cannot write {target}: {e.strerror}") from e


def _write_plain(target: Path, body: bytes) -> Path:
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ExportError(f"{target} exists and is not a regular file. Give another path.")
    temp = target.with_name(f".{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with open(temp, "xb") as f:
            f.write(body)
        os.replace(temp, target)
    except OSError as e:
        temp.unlink(missing_ok=True)
        raise ExportError(f"cannot write {target}: {e.strerror}") from e
    return target


# ---- The page route ----


def answer(root: Path, rest: str) -> tuple[int, bytes | dict[str, Any], str]:
    """The answer to `api/export` (the test that the page shows) or `api/export/<test id>`: the
    status, the HTML file or the JSON of an error, and the name of the file."""
    if rest == ROUTE:
        cur = state.current(root)
        folder = Path(cur["dir"]) if cur else state.latest_test(root)
        if folder is None:
            return 404, {"error": NO_TEST}, ""
    else:
        found = dashboard.find(root, unquote(rest[len(ROUTE) + 1 :]))
        if found is None:
            return 404, {"error": NO_ID}, ""
        folder = found
    try:
        # The name goes into a header, so it has only safe characters.
        return 200, build(root, folder), re.sub(r"[^A-Za-z0-9._-]", "_", folder.name) + ".html"
    except ExportError as e:
        return 500, {"error": f"nookku: {e}"}, ""

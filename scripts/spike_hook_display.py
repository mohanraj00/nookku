"""Spike #176: can a blocked UserPromptSubmit command hook show the reply to the user? Local only.

A command hook blocks the first prompt. It returns a text in `reason`, in `systemMessage`, or in
both. The text has line breaks, Markdown, non-ASCII and astral characters, and a size of 1, 10 or
100 KiB. A second prompt passes the hook and goes to the model.

Claude Code runs 2 times for each case:

- in print mode with stream-json. The output gives the shown text as data, so the script compares
  it byte for byte;
- in the interactive CLI in a pseudo-terminal. The script reads the screen bytes and looks for the
  start and the end of the text.

A recording proxy between Claude Code and the model API tells if a request holds the text. A
request of the harness holds its own instructions, so the script keeps no request body. It writes
only the count of requests and the count that hold a marker.

The project is in .proof/hook-display/. The desktop apps need a person:

- --project SIZE writes the project with a text of SIZE bytes in both fields, and runs no case.
  A person opens the project in the desktop app and sends the 2 prompts that it prints.
- --person FILE adds the answers of the person (a JSON object) to the result, and runs no case.
They go into the result as they are. #193 adds the Codex answers to the same result file.

usage: python scripts/spike_hook_display.py claude-code [--project SIZE | --person FILE] [OUT]
       (default OUT: proofs/spikes/hook-display.json)
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from verbatim_relay import backend  # noqa: E402

MODEL = "haiku"
# The lines of the pseudo-terminal.
ROWS = 50
SIZES = (1024, 10 * 1024, 100 * 1024)
FIELDS = (("reason",), ("systemMessage",), ("reason", "systemMessage"))
PROMPT = "PROMPT-MARK-41d0"
BLOCKED = f"block: {PROMPT} a toy shop question"
PASSED = "pass: reply with the word ok"
# A blocked prompt in Claude Code 2.1.294 shows as this prefix, the reason, and this suffix.
SHOWN = re.compile(
    r"\AUserPromptSubmit operation blocked by hook:\n(.*)\n\nOriginal prompt: (.*)\Z", re.S
)
ESCAPES = re.compile(
    rb"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-B]|\x1b[=>78]"
)

HOOK = """import json, sys
event = json.load(sys.stdin)
if event.get("prompt", "").startswith("block"):
    print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8")), ensure_ascii=False))
"""


# The astral characters of each field, so that the screen check finds the field that shows.
ASTRAL = {"reason": "😀 𝄞", "systemMessage": "🧸 🎲"}


def marks(mark: str) -> tuple[str, str, str]:
    """The start, middle and end markers of a text."""
    return f"{mark}-START", f"{mark}-MID", f"{mark}-END"


def text(size: int, mark: str, astral: str) -> str:
    """A text of `size` UTF-8 bytes that starts with `mark`-START, has `mark`-MID near its
    middle, and ends with `mark`-END."""
    start, mid, end = marks(mark)
    head = f"{start}\n# Order 1042\n\n**Status:** shipped, _2 items_\n\n"
    head += f"- Café crème mug: 1 ü 中文 {astral}\n"
    tail = f"\n{end}"
    body = head
    n = 0
    while len((body + tail).encode()) < size:
        if n == max(1, size // 70):
            body += f"{mid}\n"
        body += f"line {n:05d} of the toy shop reply.\n"
        n += 1
    out = (body + tail).encode()
    cut = len(out) - size
    return (body[: len(body) - cut] + tail) if cut > 0 else body + tail


def project(payload: dict[str, str]) -> Path:
    """A project with one UserPromptSubmit command hook that blocks a prompt that starts with
    "block" and returns `payload`. It is in .proof/, inside the repo, so that the interactive CLI
    asks no question about the folder."""
    p = ROOT / ".proof" / "hook-display"
    shutil.rmtree(p, ignore_errors=True)
    (p / ".claude").mkdir(parents=True, exist_ok=True)
    (p / "hook.py").write_text(HOOK, encoding="utf-8")
    (p / "payload.json").write_text(json.dumps({"decision": "block", **payload}), encoding="utf-8")
    command = shlex.join(
        [shutil.which("python3") or "python3", str(p / "hook.py"), str(p / "payload.json")]
    )
    hooks = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}
    (p / ".claude" / "settings.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return p


def where(body: bytes, marks: tuple[str, ...]) -> dict[str, Any]:
    """The places in a model request that hold each mark: "system", or the role of a message."""
    try:
        data = json.loads(body)
    except ValueError:
        return {"json": False, "found": {m: ["body"] for m in marks if m.encode() in body}}
    if not isinstance(data, dict):
        data = {}
    places: dict[str, list[str]] = {}
    for m in marks:
        found = []
        if m in json.dumps(data.get("system"), ensure_ascii=False):
            found.append("system")
        for i, msg in enumerate(data.get("messages") or []):
            if m in json.dumps(msg, ensure_ascii=False):
                found.append(
                    f"messages[{i}].{msg.get('role')}"
                    if isinstance(msg, dict)
                    else f"messages[{i}]"
                )
        if not found and m in json.dumps(data, ensure_ascii=False):
            found.append("other")
        places[m] = found
    tools = data.get("tools") or []
    return {
        "model": data.get("model"),
        "tools": len(tools),
        "messages": len(data.get("messages") or []),
        "found": places,
    }


class SpikeProxy(backend.Proxy):
    """A model API proxy that keeps no header and no body. Each row gets only the places of the
    marks in its request."""

    marks: tuple[str, ...] = ()

    def describe(self, row: dict[str, Any], headers: list[tuple[str, str]], body: bytes) -> None:
        row["request_headers"] = None
        row["request_body"] = where(body, self.marks)

    def complete(self, row: dict[str, Any], body: bytes, encoding: str | None) -> None:
        row["response_headers"] = None
        row["response_body"] = None


def environment(proxy_env: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE"))}
    env.update(proxy_env)
    return env


ARGS = ["--model", MODEL, "--setting-sources", "project", "--strict-mcp-config"]


def run_print(p: Path, env: dict[str, str], payload: dict[str, str]) -> dict[str, Any]:
    """Print mode with stream-json: the blocked prompt, then the passed prompt."""
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": c}})
        for c in (BLOCKED, PASSED)
    ]
    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
    ]
    proc = subprocess.run(
        cmd + ARGS,
        cwd=p,
        env=env,
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        timeout=300,
    )
    shown: list[dict[str, Any]] = []
    results = 0
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        results += event.get("type") == "result"
        content = event.get("content")
        if event.get("subtype") == "informational" and isinstance(content, str):
            shown.append({"level": event.get("level"), "content": content})
    out: dict[str, Any] = {"exit": proc.returncode, "results": results, "events": len(shown)}
    for field, value in payload.items():
        hits = [s for s in shown if value in s["content"]]
        out[field] = {"shown": bool(hits), "byte_exact": False}
        if hits:
            m = SHOWN.match(hits[0]["content"])
            out[field].update(
                level=hits[0]["level"],
                byte_exact=m is not None and m.group(1) == value,
                form="prefix + text + original prompt" if m else "other",
            )
    return out


def screen(buf: bytes) -> str:
    return ESCAPES.sub(b" ", buf).decode("utf-8", "replace")


def run_tty(
    p: Path, env: dict[str, str], payload: dict[str, str], mark: str, rows: int = ROWS
) -> dict[str, Any]:
    """The interactive CLI in a pseudo-terminal of `rows` lines and 120 columns: the blocked
    prompt, then the passed prompt."""
    env = {**env, "TERM": "xterm-256color"}
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, 120, 0, 0))
        os.chdir(p)
        os.execvpe("claude", ["claude", *ARGS], env)
    buf = bytearray()

    def pump(seconds: float, until: bytes | None = None, start: int = 0) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if until is not None and until in re.sub(
                rb"\s+", b"", ESCAPES.sub(b"", bytes(buf[start:]))
            ):
                return
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    buf.extend(os.read(fd, 1 << 16))
                except OSError:
                    return

    try:
        pump(8)
        start = len(buf)
        os.write(fd, BLOCKED.encode())
        pump(1)
        os.write(fd, b"\r")
        pump(30, b"Originalprompt", start)
        pump(2)
        blocked = bytes(buf[start:])
        start = len(buf)
        os.write(fd, PASSED.encode())
        pump(1)
        os.write(fd, b"\r")
        pump(60, b"ok", start + len(PASSED) + 50)
        pump(3)
    finally:
        for key in (b"\x03", b"\x03"):
            with contextlib.suppress(OSError):
                os.write(fd, key)
            time.sleep(0.5)
        # Close the terminal first: on macOS, a process cannot exit while its terminal output
        # waits to be read.
        os.close(fd)
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
    flat = screen(blocked)
    joined = re.sub(r"\s+", "", flat)
    out: dict[str, Any] = {}
    for field in payload:
        m = f"{mark}-{field}"
        out[field] = {
            "start_shown": f"{m}-START" in joined,
            "end_shown": f"{m}-END" in joined,
            "astral_shown": all(c in flat for c in ASTRAL[field].split()),
        }
    # The CLI moves the cursor to start a new line, so the screen bytes cannot show a line break.
    # Markdown can be read only if the start of the text is on the screen.
    first = next(iter(payload))
    out["markdown_rendered"] = "**Status:**" not in joined if out[first]["start_shown"] else None
    out["prefix_shown"] = "UserPromptSubmitoperationblockedbyhook:" in joined
    return out


def case(fields: tuple[str, ...], size: int, n: int) -> dict[str, Any]:
    mark = f"HD{n:02d}"
    payload = {f: text(size, f"{mark}-{f}", ASTRAL[f]) for f in fields}
    with tempfile.TemporaryDirectory(prefix="hook-display-") as tmp:
        p = project(payload)
        record = Path(tmp) / "model.jsonl"
        out: dict[str, Any] = {"fields": list(fields), "size": size}
        for mode in ("print", "tty"):
            record.unlink(missing_ok=True)
            SpikeProxy.marks = (PROMPT, *(m for f in fields for m in marks(f"{mark}-{f}")))
            proxies = backend.Proxies(
                [backend.Backend("anthropic", "ANTHROPIC_BASE_URL", "https://api.anthropic.com")],
                record,
                SpikeProxy,
            )
            env = environment(proxies.start())
            try:
                if mode == "print":
                    result = run_print(p, env, payload)
                else:
                    result = run_tty(p, env, payload, mark)
            finally:
                proxies.stop()
            rows = record.read_text(encoding="utf-8").splitlines() if record.exists() else []
            result["model"] = [
                {"path": r["path"], **r["request_body"]}
                for r in map(json.loads, rows)
                if r.get("request_body")
            ]
            out[mode] = result
            print(f"{mark} {mode}: {json.dumps(result)}", flush=True)
        return out


def option(args: list[str], name: str) -> str | None:
    """Remove `name` and its value from `args`, and return the value."""
    if name not in args:
        return None
    i = args.index(name)
    value = args[i + 1]
    del args[i : i + 2]
    return value


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] != "claude-code":
        print(__doc__, file=sys.stderr)
        return 2
    size = option(args, "--project")
    person = option(args, "--person")
    out = Path(args[1]) if len(args) > 1 else ROOT / "proofs" / "spikes" / "hook-display.json"
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    if size is not None:
        p = project({f: text(int(size), f"DESK-{f}", ASTRAL[f]) for f in ASTRAL})
        print(f"Open {p} in the app. Send the prompt: {BLOCKED}")
        print(f"Then send the prompt: {PASSED}")
        return 0
    if person is not None:
        data["claude-code"]["person"] = json.loads(Path(person).read_text(encoding="utf-8"))
    else:
        version = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True
        ).stdout.split()[0]
        cases = [case(f, s, n) for n, (f, s) in enumerate((f, s) for f in FIELDS for s in SIZES)]
        data["claude-code"] = {
            "date": date.today().isoformat(),
            "versions": {"claude-code": version, "python": sys.version.split()[0]},
            "model": MODEL,
            "tty_rows": ROWS,
            "method": "scripts/spike_hook_display.py",
            "cases": cases,
            "person": data.get("claude-code", {}).get("person", {}),
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

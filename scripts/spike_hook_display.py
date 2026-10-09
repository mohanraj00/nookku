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
They go into the result as they are.

Codex uses a separate project in .proof/hook-display-codex-193/. In a managed worktree inside
Codex's home, the project goes in the primary checkout: the tested CLI did not discover the
project hook inside that worktree. Code changes stay in the worktree.
First run python scripts/spike_hook_display.py codex --project 1024,
then open Codex in that project and review and trust the command hook with /hooks. A person
must do this step. The script never writes trust state. The hook definition stays fixed while
the payload changes. Codex runs in exec mode and in an interactive pseudo-terminal. Each run
sends a blocked prompt, then a passed prompt in the same conversation. A streaming model API
proxy records marker locations only. Unrelated plugins are disabled for each CLI invocation;
the saved user config does not change. Desktop checks require a person; --fields selects reason,
systemMessage, or both for --project. --person imports their observations and desktop version.

usage: python scripts/spike_hook_display.py claude-code|codex [--project SIZE | --person FILE] [OUT]
       --fields reason|systemMessage|both (with --project only)
       codex --desktop: capture model requests while a person runs the desktop prompt matrix
       A person adds the printed openai_base_url to user config, then removes it after the cases.
       codex --copies DIR: compare copied field files after the desktop capture
       (default OUT: proofs/spikes/hook-display.json)
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import plistlib
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
# The first character of the input box of the interactive CLI.
READY = "\u276f".encode()  # HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT
# The lines of the pseudo-terminal.
ROWS = 50
SIZES = (1024, 10 * 1024, 100 * 1024)
FIELDS = (("reason",), ("systemMessage",), ("reason", "systemMessage"))
PROMPT = "PROMPT-MARK-41d0"
BLOCKED = f"block: {PROMPT} a toy shop question"
PASS = "PASS-MARK-77c1"
PASSED = f"pass: {PASS} reply with the word ok"
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
    middle, and ends with `mark`-END. The last filler line can end in the middle of a word
    to fit the exact byte size. The END marker stays whole."""
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
    command = shlex.join([sys.executable, str(p / "hook.py"), str(p / "payload.json")])
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
        source = "messages" if "messages" in data else "input"
        inputs = data.get(source) or []
        if not isinstance(inputs, list):
            inputs = [inputs]
        for i, msg in enumerate(inputs):
            if m in json.dumps(msg, ensure_ascii=False):
                found.append(
                    f"{source}[{i}].{msg.get('role') or msg.get('type')}"
                    if isinstance(msg, dict)
                    else f"{source}[{i}]"
                )
        if not found and m in json.dumps(data, ensure_ascii=False):
            found.append("other")
        places[m] = found
    tools = data.get("tools") or []
    return {
        "model": data.get("model"),
        "tools": len(tools),
        "messages": len(data.get("messages") or data.get("input") or []),
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

    def pump(seconds: float, until: bytes | None = None, start: int = 0) -> bool:
        """Read the screen for up to `seconds`. Return True when `until` shows after `start`."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if until is not None and until in re.sub(
                rb"\s+", b"", ESCAPES.sub(b"", bytes(buf[start:]))
            ):
                return True
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    buf.extend(os.read(fd, 1 << 16))
                except OSError:
                    return False
        return False

    try:
        # The input box of the CLI starts with this character when it is ready for a prompt.
        if not pump(60, READY):
            raise RuntimeError("the interactive CLI did not show its input box in 60 seconds")
        pump(2)
        start = len(buf)
        os.write(fd, BLOCKED.encode())
        pump(1)
        os.write(fd, b"\r")
        if not pump(30, b"Originalprompt", start):
            raise RuntimeError("the interactive CLI did not show the blocked prompt in 30 seconds")
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
            SpikeProxy.marks = (PROMPT, PASS, *(m for f in fields for m in marks(f"{mark}-{f}")))
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
                {"path": r["path"], "status": r.get("status"), **r["request_body"]}
                for r in map(json.loads, rows)
                if r.get("request_body")
            ]
            # The next turn must reach the model and get an answer. Else the case cannot tell
            # if the hook text reaches the model in the next turn.
            done = [
                m
                for m in result["model"]
                if m.get("tools") and m.get("found", {}).get(PASS) and m.get("status") == 200
            ]
            if not done or (mode == "print" and result["results"] != 2):
                raise RuntimeError(f"{mark} {mode}: the next turn did not complete")
            out[mode] = result
            print(f"{mark} {mode}: {json.dumps(result)}", flush=True)
        return out


CODEX_MODEL = "gpt-5.6-luna"
CODEX_HOOK = """import json, sys
from pathlib import Path
event = json.load(sys.stdin)
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
blocked = event.get("prompt", "").startswith("block")
row = {"blocked": blocked}
if "cases" in data:
    # This is only a fixture lookup. The event prompt is not changed.
    case = data["cases"].get(event.get("prompt", "").rstrip("\\r\\n"))
    row["case_match"] = case is not None
    payload = case["payload"] if case else {
        "decision": "block", "reason": "Use a listed spike prompt."
    }
    if case:
        row.update(case=case["id"], session_id=event.get("session_id"))
else:
    payload = data
with Path(sys.argv[2]).open("a", encoding="utf-8") as receipt:
    receipt.write(json.dumps(row) + "\\n")
if blocked:
    print(json.dumps(payload, ensure_ascii=False))
"""


def codex_project(payload: dict[str, str]) -> Path:
    """Write a fixed hook definition. Changing the payload does not write trust state."""
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
    proof_root = ROOT
    if home in ROOT.parents:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        proof_root = (ROOT / common).resolve().parent
    p = proof_root / ".proof" / "hook-display-codex-193"
    (p / ".codex").mkdir(parents=True, exist_ok=True)
    script = p / "hook.py"
    source = p / ".codex" / "hooks.json"
    if source.exists():
        try:
            existing = json.loads(source.read_text(encoding="utf-8"))
            handler = existing["hooks"]["UserPromptSubmit"][0]["hooks"][0]
            command = shlex.split(handler["command"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError("The toy hook definition is invalid. Review its source.") from error
        expected = [str(script), str(p / "payload.json"), str(p / "receipt.jsonl")]
        if (
            handler.get("type") != "command"
            or len(command) != 4
            or command[1:] != expected
            or not Path(command[0]).is_file()
            or not script.exists()
            or script.read_text(encoding="utf-8") != CODEX_HOOK
        ):
            raise RuntimeError("The existing toy hook differs from this method. Review its source.")
        # Keep the definition a person reviewed, including its interpreter from an earlier worktree.
        # require_codex_hook still checks that exact definition before a measurement.
    else:
        script.write_text(CODEX_HOOK, encoding="utf-8")
        command_text = shlex.join(
            [sys.executable, str(script), str(p / "payload.json"), str(p / "receipt.jsonl")]
        )
        hooks = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command_text}]}]}
        source.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=p, prefix="payload-", suffix=".tmp", delete=False
    ) as pending:
        json.dump(
            {"decision": "block", "reason": "Hook display control block.", **payload},
            pending,
            ensure_ascii=False,
        )
    Path(pending.name).replace(p / "payload.json")
    return p


def require_codex_hook(p: Path) -> list[str]:
    """Inspect the exact hook before a model call. Never create or change trust."""
    source = p / ".codex" / "hooks.json"
    expected = json.loads(source.read_text())["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    proc = subprocess.Popen(
        ["codex", "app-server", "--listen", "stdio://"],
        cwd=p,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    def request(number: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps({"id": number, "method": method, "params": params}) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if message.get("id") == number:
                if "error" in message:
                    raise RuntimeError(f"Cannot inspect hook trust: {message['error']}")
                return message["result"]
        raise RuntimeError("Cannot inspect hook trust: the app server did not answer.")

    try:
        request(
            0,
            "initialize",
            {
                "clientInfo": {"name": "hook_display_spike", "version": "0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        entries = request(1, "hooks/list", {"cwds": [str(p)]})["data"]
        found = [
            h
            for e in entries
            for h in e["hooks"]
            if h.get("sourcePath") == str(source) and h.get("eventName") == "userPromptSubmit"
        ]
        if len(found) != 1 or found[0].get("command") != expected["command"]:
            raise RuntimeError(
                f"Codex did not discover the required hook. Open codex -C {p}, then /hooks."
            )
        hook = found[0]
        if not hook.get("enabled") or hook.get("trustStatus") != "trusted":
            raise RuntimeError(
                f"The required hook is {hook.get('trustStatus')}. "
                f"Open codex -C {p}, review and trust it in /hooks, then retry."
            )
        config = request(2, "config/read", {"cwd": str(p), "includeLayers": False})["config"]
        return list(config.get("plugins", {}))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.stdin is not None:
            proc.stdin.close()
        if proc.stdout is not None:
            proc.stdout.close()


def codex_args(url: str, plugins: list[str]) -> list[str]:
    """Use ChatGPT auth with an HTTP Responses proxy. Do not change the user's config."""
    settings = {
        "model_provider": "hook_display",
        "model_providers.hook_display.name": "Hook display spike",
        "model_providers.hook_display.base_url": url,
        "model_providers.hook_display.wire_api": "responses",
        "model_providers.hook_display.requires_openai_auth": True,
        "model_providers.hook_display.supports_websockets": False,
        "sandbox_mode": "read-only",
    }
    return [
        "-m",
        CODEX_MODEL,
        *(a for k, v in settings.items() for a in ("-c", f"{k}={json.dumps(v)}")),
        *(a for plugin in plugins for a in ("-c", f"plugins.{json.dumps(plugin)}.enabled=false")),
    ]


def codex_receipts(p: Path) -> list[dict[str, Any]]:
    receipt = p / "receipt.jsonl"
    return list(map(json.loads, receipt.read_text().splitlines())) if receipt.exists() else []


def codex_exec(p: Path, args: list[str], payload: dict[str, str]) -> dict[str, Any]:
    """Block a turn and resume that conversation. Do not save model answers or raw events."""

    def run(prompt: str, session: str | None = None) -> subprocess.CompletedProcess[str]:
        command = ["codex", "--no-daemon", "exec"]
        if session:
            command += ["resume", session]
        command += ["--json", "--skip-git-repo-check", *args]
        return subprocess.run(
            [*command, "-"], input=prompt, capture_output=True, text=True, cwd=p, timeout=300
        )

    blocked = run(BLOCKED)
    events = [json.loads(line) for line in blocked.stdout.splitlines() if line.startswith("{")]
    thread = next((e["thread_id"] for e in events if e.get("type") == "thread.started"), None)
    if not thread or codex_receipts(p) != [{"blocked": True}]:
        raise RuntimeError("The Codex hook did not run. Review and trust it in /hooks, then retry.")
    # Decode each JSON string before comparing. JSON escaping is not a display change.
    strings: list[str] = [blocked.stderr]

    def collect(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for event in events:
        collect(event)
    passed = run(PASSED, thread)
    completed = any(
        json.loads(line).get("type") == "turn.completed"
        for line in passed.stdout.splitlines()
        if line.startswith("{")
    )
    if passed.returncode or not completed or codex_receipts(p)[-1:] != [{"blocked": False}]:
        raise RuntimeError("The next Codex exec turn did not complete. Check auth and the proxy.")
    return {
        "blocked_exit": blocked.returncode,
        "passed_exit": passed.returncode,
        "next_turn_completed": completed,
        "fields": {
            f: {
                "start_shown": any(v.splitlines()[0] in t for t in strings),
                "end_shown": any(v.splitlines()[-1] in t for t in strings),
                "byte_exact": any(v in t for t in strings),
            }
            for f, v in payload.items()
        },
    }


def codex_tty(
    p: Path, args: list[str], payload: dict[str, str], mark: str, record: Path
) -> dict[str, Any]:
    """Observe a blocked turn and the next answer in the same interactive CLI."""
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, 120, 0, 0))
        os.chdir(p)
        os.execvpe(
            "codex",
            ["codex", "--no-daemon", "--no-alt-screen", *args],
            {**os.environ, "TERM": "xterm-256color"},
        )
    buf = bytearray()

    def pump(until: Any, seconds: float = 60) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if until():
                return
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
                # Codex queries the terminal cursor before it draws the input box.
                if b"\x1b[6n" in chunk:
                    os.write(fd, b"\x1b[1;1R")
        raise RuntimeError("The Codex CLI did not reach the next step. Check /hooks and auth.")

    try:
        pump(lambda: "Tip:" in screen(bytes(buf)))
        start = len(buf)
        os.write(fd, b"\x1b[200~" + BLOCKED.encode() + b"\x1b[201~")
        pump(lambda: BLOCKED in screen(bytes(buf[start:])))
        start = len(buf)
        block_start = start
        os.write(fd, b"\r")
        pump(lambda: codex_receipts(p) == [{"blocked": True}])
        # Wait for the input box after the hook finishes, before submitting the next turn.
        pump(lambda: "\u203a" in screen(bytes(buf[start:])))
        blocked = bytes(buf[start:])
        start = len(buf)
        os.write(fd, b"\x1b[200~" + PASSED.encode() + b"\x1b[201~")
        pump(lambda: PASSED in screen(bytes(buf[start:])))
        os.write(fd, b"\r")
        pump(lambda: codex_receipts(p)[-1:] == [{"blocked": False}])
        start = len(buf)
        pump(lambda: re.search(r"\bok\b", screen(bytes(buf[start:]))))

        # Keep the CLI alive until the proxy has recorded the end of the API stream.
        def api_completed() -> bool:
            if not record.exists():
                return False
            return any(
                row.get("status") == 200 and row.get("request_body", {}).get("found", {}).get(PASS)
                for row in map(json.loads, record.read_text().splitlines())
            )

        pump(api_completed)
        blocked = bytes(buf[block_start:])
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.kill(pid, 9)
        with contextlib.suppress(OSError):
            os.waitpid(pid, 0)
    flat = screen(blocked)
    joined = re.sub(r"\s+", "", flat)
    return {
        "fields": {
            f: {
                "start_shown": marks(f"{mark}-{f}")[0] in joined,
                "end_shown": marks(f"{mark}-{f}")[2] in joined,
                "astral_shown": all(c in flat for c in ASTRAL[f].split()),
                "raw_utf8_payload_in_screen": payload[f].encode() in blocked,
                "byte_exact": None,
                "line_prefix": flat[: flat.find(f"{mark}-{f}-START")].rsplit("\n", 1)[-1][-80:]
                if f"{mark}-{f}-START" in flat
                else None,
            }
            for f in payload
        },
        "markdown_source_shown": "**Status:**" in joined,
        "next_turn_api_completed": True,
        "line_breaks_byte_exact": None,
        "form": {
            f: (
                "warning"
                if re.search(r"\u26a0\s*" + re.escape(f"{mark}-{f}-START"), flat)
                else "other"
                if f"{mark}-{f}-START" in flat
                else "not shown"
            )
            for f in payload
        },
    }


class CodexSpikeProxy(SpikeProxy):
    """Forward HTTP streams while keeping only request marker locations."""

    streaming = True


def codex_case(fields: tuple[str, ...], size: int, n: int, plugins: list[str]) -> dict[str, Any]:
    mark = f"CXHD{n:02d}"
    payload = {f: text(size, f"{mark}-{f}", ASTRAL[f]) for f in fields}
    p = codex_project(payload)
    out: dict[str, Any] = {"fields": list(fields), "size": size}
    if fields == ("systemMessage",):
        out["control_reason"] = "Hook display control block."
    for mode, runner in (("exec", codex_exec), ("tty", codex_tty)):
        (p / "receipt.jsonl").unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="codex-hook-display-") as tmp:
            record = Path(tmp) / "model.jsonl"
            CodexSpikeProxy.marks = (
                PROMPT,
                PASS,
                *(m for f in fields for m in marks(f"{mark}-{f}")),
            )
            proxy = backend.Proxies(
                [
                    backend.Backend(
                        "codex", "HOOK_DISPLAY_PROXY", "https://chatgpt.com/backend-api/codex"
                    )
                ],
                record,
                CodexSpikeProxy,
            )
            url = proxy.start()["HOOK_DISPLAY_PROXY"]
            try:
                result = (
                    runner(p, codex_args(url, plugins), payload)
                    if mode == "exec"
                    else runner(p, codex_args(url, plugins), payload, mark, record)
                )
            finally:
                proxy.stop()
            rows = list(map(json.loads, record.read_text().splitlines())) if record.exists() else []
            result["model"] = [
                {"path": r["path"], "status": r.get("status"), **r["request_body"]}
                for r in rows
                if r.get("request_body")
            ]
            print(f"{mark} {mode}: {json.dumps(result)}", flush=True)
            if not any(
                r.get("status") == 200 and r.get("found", {}).get(PASS) for r in result["model"]
            ):
                raise RuntimeError(
                    "No completed next-turn request reached the Codex model API proxy."
                )
            if any(r.get("found", {}).get(PROMPT) for r in result["model"]):
                raise RuntimeError(
                    "The blocked prompt reached the API. This is not a valid display case."
                )
            out[mode] = result
    return out


def desktop_version() -> dict[str, Any]:
    """Read the installed bundle. A person must confirm the app they tested."""
    info = Path("/Applications/ChatGPT.app/Contents/Info.plist")
    if not info.exists():
        return {"installed": None, "runtime": None}
    with info.open("rb") as file:
        data = plistlib.load(file)
    return {
        "installed": data.get("CFBundleShortVersionString"),
        "build": data.get("CFBundleVersion"),
        "runtime": None,
    }


def desktop_plan() -> list[dict[str, Any]]:
    """Distinct markers for every desktop case and both turns."""
    out = []
    for n, (fields, size) in enumerate((f, s) for f in FIELDS for s in SIZES):
        mark = f"DESK{n:02d}"
        payload = {f: text(size, f"{mark}-{f}", ASTRAL[f]) for f in fields}
        out.append(
            {
                "id": mark,
                "fields": list(fields),
                "size": size,
                "blocked_prompt": f"block: {mark}-PROMPT a toy shop question",
                "passed_prompt": f"pass: {mark}-PASS reply with the word ok",
                "payload": {
                    "decision": "block",
                    "reason": "Hook display control block.",
                    **payload,
                },
            }
        )
    return out


def codex_desktop(out: Path) -> None:
    """Keep a proxy running while a person tests a new local desktop chat."""
    p = codex_project({})
    plugins = require_codex_hook(p)
    plan = desktop_plan()
    payloads = {
        prompt: {"id": case["id"], "payload": case["payload"]}
        for case in plan
        for prompt in (case["blocked_prompt"], case["passed_prompt"])
    }
    (p / "payload.json").write_text(json.dumps({"cases": payloads}, ensure_ascii=False))
    receipt = p / "receipt.jsonl"
    receipt.unlink(missing_ok=True)
    instructions = [
        "# Desktop hook display check",
        "",
        f"Open `{p}` as a project in the desktop app. Start a new local chat in it.",
        "Keep all prompts in that chat. The capture script must stay running.",
        "For each case, send the block prompt. Note which field shows, whether its start and end",
        "show, whether it has line breaks, whether Markdown renders, and whether Café, 中文,",
        "😀, 𝄞, 🧸 and 🎲 show. Note whether it looks like a warning, an error or plain text.",
        "Then send the pass prompt and wait for its answer before the next case.",
        "Record the desktop version in About. Send the observations and the chat link to Codex.",
        "For a byte comparison, save each shown field's text as ID-FIELD.txt in this folder.",
        "Copy only the field's reply text. The script compares its UTF-8 bytes with the fixture.",
        "",
    ]
    for case in plan:
        instructions.extend(
            [
                f"## {case['id']}: {', '.join(case['fields'])}, {case['size']} bytes",
                "",
                "```text",
                case["blocked_prompt"],
                "```",
                "",
                "```text",
                case["passed_prompt"],
                "```",
                "",
            ]
        )
    checks = p / "desktop-check.md"
    checks.write_text("\n".join(instructions))
    config = p / ".codex" / "config.toml"
    old_config = config.read_bytes() if config.exists() else None
    with tempfile.TemporaryDirectory(prefix="codex-desktop-display-") as tmp:
        record = Path(tmp) / "model.jsonl"
        CodexSpikeProxy.marks = tuple(
            m
            for case in plan
            for m in (
                f"{case['id']}-PROMPT",
                f"{case['id']}-PASS",
                *(m for f in case["fields"] for m in marks(f"{case['id']}-{f}")),
            )
        )
        proxies = backend.Proxies(
            [
                backend.Backend(
                    "codex", "HOOK_DISPLAY_PROXY", "https://chatgpt.com/backend-api/codex"
                )
            ],
            record,
            CodexSpikeProxy,
        )
        url = proxies.start()["HOOK_DISPLAY_PROXY"]
        settings = [
            f"model = {json.dumps(CODEX_MODEL)}",
            'sandbox_mode = "read-only"',
            "[features]",
            "enable_request_compression = false",
        ]
        for plugin in plugins:
            settings.extend([f"[plugins.{json.dumps(plugin)}]", "enabled = false"])
        config.write_text("\n".join(settings) + "\n")
        provider = p / "desktop-provider.toml"
        provider.write_text(f"openai_base_url = {json.dumps(url)}\n")
        checks.write_text(
            "# Request recorder setup\n\n"
            "Pause other active chats during this capture. Add this line at the top of "
            "`~/.codex/config.toml`, before any table heading. This changes the provider URL "
            "for new local chats. The proxy forwards to the same backend "
            "and keeps markers only.\n\n"
            f"```toml\n{provider.read_text()}```\n\n"
            "Start a new local chat in this project. After the last pass answer, remove that "
            "line from user config before you resume other chats. Start a new chat for later model "
            "turns: the test chat keeps the recorder URL. The script never changes "
            "user config or hook trust.\n\n" + checks.read_text()
        )
        print(
            f"Desktop capture ready. Pause other chats. A person must add the line in {provider} "
            "at the top of ~/.codex/config.toml, then start a new local chat in this project. "
            "Project config cannot set a provider URL. The script does not change user config.",
            flush=True,
        )
        print(f"Follow {checks}. The capture waits for all listed prompt pairs.", flush=True)
        try:
            deadline = time.monotonic() + 3600
            user_config = (
                Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
            )
            completed: set[str] = set()
            while time.monotonic() < deadline:
                receipts = codex_receipts(p)
                if any(r.get("case_match") is False for r in receipts):
                    raise RuntimeError(
                        "A desktop prompt did not match a case. Use a listed prompt."
                    )
                rows = (
                    list(map(json.loads, record.read_text().splitlines()))
                    if record.exists()
                    else []
                )
                models = [
                    {"path": r["path"], "status": r.get("status"), **r["request_body"]}
                    for r in rows
                    if (r.get("request_body") or {}).get("model")
                ]
                for case in plan:
                    ident = case["id"]
                    saw_block = any(r.get("case") == ident and r["blocked"] for r in receipts)
                    saw_pass = any(r.get("case") == ident and not r["blocked"] for r in receipts)
                    api_pass = any(
                        r.get("status") == 200 and r.get("found", {}).get(f"{ident}-PASS")
                        for r in models
                    )
                    if saw_block and saw_pass and api_pass and ident not in completed:
                        completed.add(ident)
                        print(f"Captured {ident} and its next model request.", flush=True)
                if len(completed) == len(plan):
                    print(
                        "All cases captured. Remove the temporary openai_base_url "
                        "from user config. "
                        "The proxy stays available until that line is removed.",
                        flush=True,
                    )
                    while time.monotonic() < deadline:
                        current = user_config.read_text() if user_config.exists() else ""
                        setting = r"(?m)^\s*openai_base_url\s*=\s*[\"']" + re.escape(url)
                        if re.search(setting + r"[\"']", current) is None:
                            break
                        with proxies.lock:
                            proxies.lock.wait(timeout=1)
                    else:
                        raise RuntimeError("Remove the temporary openai_base_url from user config.")
                    break
                # A model call wakes the condition; hook receipts are checked at each timeout.
                with proxies.lock:
                    proxies.lock.wait(timeout=1)
            else:
                raise RuntimeError("The desktop capture timed out. Run --desktop again to retry.")
        finally:
            proxies.stop()
            if old_config is None:
                config.unlink(missing_ok=True)
            else:
                config.write_bytes(old_config)
        data = json.loads(out.read_text()) if out.exists() else {}
        desktop: dict[str, Any] = {
            "date": date.today().isoformat(),
            "version": desktop_version(),
            "method": "scripts/spike_hook_display.py codex --desktop",
            "provider_setup": "person sets openai_base_url in user config, then removes it",
            "request_compression": "disabled in project config so marker inspection reads JSON",
            "model": CODEX_MODEL,
            "capture_scope": "all JSON model requests during the capture; other chats paused",
            "unrelated_plugins": "disabled for this project during the capture",
            "sessions": sorted({r["session_id"] for r in receipts if r.get("session_id")}),
            "model_requests": models,
            "cases": [],
            "visual_observations": "pending the person's report",
        }
        for case in plan:
            copies = {}
            for field in case["fields"]:
                copy = p / f"{case['id']}-{field}.txt"
                copies[field] = {
                    "byte_exact": copy.read_bytes() == case["payload"][field].encode()
                    if copy.exists()
                    else None
                }
            desktop["cases"].append(
                {k: v for k, v in case.items() if k != "payload"}
                | {
                    "copy_checks": copies,
                    "hook_receipts": {
                        "blocked": sum(
                            r.get("case") == case["id"] and r["blocked"] for r in receipts
                        ),
                        "passed": sum(
                            r.get("case") == case["id"] and not r["blocked"] for r in receipts
                        ),
                    },
                }
            )
        data.setdefault("codex", {})["desktop"] = desktop
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(
            f"Wrote desktop capture to {out}. Visual observations still need a person's report.",
            flush=True,
        )


def codex_copy_checks(data: dict[str, Any], directory: Path) -> None:
    """Compare copied field files as bytes. Keep only sizes and hashes in the result."""
    desktop = data.get("codex", {}).get("desktop")
    if desktop is None:
        raise RuntimeError("Run the Codex desktop capture before importing copied fields.")
    recorded = {c["id"]: c for c in desktop["cases"]}
    for case in desktop_plan():
        for field in case["fields"]:
            copy = directory / f"{case['id']}-{field}.txt"
            if not copy.exists():
                continue
            actual = copy.read_bytes()
            expected = case["payload"][field].encode("utf-8")
            check = {
                "byte_exact": actual == expected,
                "copied_bytes": len(actual),
                "expected_bytes": len(expected),
                "copied_sha256": hashlib.sha256(actual).hexdigest(),
                "expected_sha256": hashlib.sha256(expected).hexdigest(),
            }
            recorded[case["id"]]["copy_checks"][field] = check
    desktop["copy_method"] = "scripts/spike_hook_display.py codex --copies DIR"


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
    if not args or args[0] not in ("claude-code", "codex"):
        print(__doc__, file=sys.stderr)
        return 2
    harness = args[0]
    desktop = "--desktop" in args
    if desktop:
        args.remove("--desktop")
        if harness != "codex":
            raise ValueError("--desktop is for Codex only")
    size = option(args, "--project")
    selected = option(args, "--fields") or "both"
    if selected not in ("reason", "systemMessage", "both"):
        raise ValueError("--fields must be reason, systemMessage or both")
    person = option(args, "--person")
    copies = option(args, "--copies")
    out = Path(args[1]) if len(args) > 1 else ROOT / "proofs" / "spikes" / "hook-display.json"
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    if copies is not None and (harness != "codex" or desktop or size is not None or person):
        raise ValueError("Use codex --copies DIR without --desktop, --project or --person.")
    if desktop:
        codex_desktop(out)
        return 0
    if size is not None:
        fields = ASTRAL if selected == "both" else {selected: ASTRAL[selected]}
        make_project = project if harness == "claude-code" else codex_project
        p = make_project({f: text(int(size), f"DESK-{f}", ASTRAL[f]) for f in fields})
        if harness == "codex":
            print(
                f"First start codex -C {shlex.quote(str(p))}. "
                "Review and trust the hook with /hooks."
            )
        print(f"Open {p} in the app. Send the prompt: {BLOCKED}")
        print(f"Then send the prompt: {PASSED}")
        return 0
    if copies is not None:
        codex_copy_checks(data, Path(copies))
    elif person is not None:
        data.setdefault(harness, {})["person"] = json.loads(
            Path(person).read_text(encoding="utf-8")
        )
    elif harness == "codex":
        prepared = codex_project({f: text(1024, f"DESK-{f}", ASTRAL[f]) for f in ASTRAL})
        plugins = require_codex_hook(prepared)
        version = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=True)
        cases = [
            codex_case(f, s, n, plugins)
            for n, (f, s) in enumerate((f, s) for f in FIELDS for s in SIZES)
        ]
        data["codex"] = {
            **data.get("codex", {}),
            "date": date.today().isoformat(),
            "versions": {"codex-cli": version.stdout.strip(), "python": sys.version.split()[0]},
            "model": CODEX_MODEL,
            "tty_rows": ROWS,
            "unrelated_plugins": "disabled for each CLI invocation",
            "method": "scripts/spike_hook_display.py",
            "cases": cases,
            "person": data.get("codex", {}).get("person", {}),
        }
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

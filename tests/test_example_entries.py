"""The example entries in other forms: the Node entry and the entry for an HTTP server. Each one
speaks the agent contract (SPEC.md section 6), and docs/how-to/connect-your-agent.md shows each
file with no change."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest
from proof_common import held_port

from nookku import contract
from nookku.audit import audit
from nookku.record import Writer
from nookku.state import tap_headers
from nookku.stdio import Agent, StdioTap, start_in_thread

ROOT = Path(__file__).resolve().parent.parent
NODE_ENTRY = ROOT / "examples" / "toy-shop-node" / "entry.mjs"
HTTP_ENTRY = ROOT / "examples" / "toy-shop" / "http_entry.py"
GUIDE = ROOT / "docs" / "how-to" / "connect-your-agent.md"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(not NODE_ENTRY.exists(), reason="the sdist has no examples folder")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")

SHIP = "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  "
FALLBACK = "Which item is this about: the mug or the teapot?"
# A message with the characters that a wrong line split breaks: \r\n in the text, U+2028 and
# U+2029. JSON escapes \r and \n, but the relays write U+2028 and U+2029 as they are.
ODD = "Hi  \r\n\u2028mug\u2029 for € 8?"


def lines(*requests: tuple[str, str]) -> bytes:
    return b"".join(contract.request(rid, "t-1", said, []) + b"\n" for rid, said in requests)


def post(tap: StdioTap, body: bytes) -> tuple[int, bytes]:
    req = urllib.request.Request(tap.url, data=body, method="POST", headers=tap_headers(tap.token))
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@needs_node
def test_the_node_entry_answers_each_line_and_logs_on_stderr() -> None:
    assert NODE is not None
    p = subprocess.run(
        [NODE, str(NODE_ENTRY)],
        input=lines(("m-1", "do you ship to delhi?"), ("m-2", "where is my order?"))
        + b"not json\n"
        + lines(("m-3", ODD)),
        capture_output=True,
        timeout=30,
    )
    out = p.stdout.split(b"\n")
    assert out[-1] == b"" and len(out) == 4
    assert contract.parse_reply(out[0], "m-1") == (SHIP, None)
    assert contract.parse_reply(out[1], "m-2") == (None, "the order service is down")
    assert contract.parse_reply(out[2], "m-3") == (FALLBACK, None)
    assert b"toy shop agent: ready" in p.stderr
    assert b"not a contract line" in p.stderr
    assert p.returncode == 0


@needs_node
def test_the_node_entry_passes_the_audit_through_the_stdio_tap(tmp_path: Path) -> None:
    assert NODE is not None
    agent = Agent([NODE, str(NODE_ENTRY)], tmp_path, tmp_path / "app.log", timeout=10)
    tap = StdioTap(("127.0.0.1", 0), agent, tmp_path / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    relay = Writer(tmp_path / "relay.jsonl")
    try:
        for rid, said in (("m-1", "do you ship to delhi?"), ("m-2", ODD)):
            status, body = post(tap, contract.request(rid, "t-1", said, []))
            assert status == 200
            shown, _ = contract.parse_reply(body, rid)
            relay.append({"type": "turn", "harness": "codex", "said": said, "shown": shown})
    finally:
        tap.shutdown()
        agent.stop(grace=1)
    rows = [json.loads(x) for x in (tmp_path / "tap.jsonl").read_text().split("\n") if x]
    assert [(r["type"], r["reply"]) for r in rows] == [("exchange", SHIP), ("exchange", FALLBACK)]
    assert "toy shop agent: ready" in (tmp_path / "app.log").read_text()
    assert audit(tmp_path / "tap.jsonl", relay.path).exit == 0


@needs_node
def test_node_readline_can_split_a_line_at_u2028_so_the_entry_does_not_use_it() -> None:
    """Node 25 readline ends a line at U+2028. An older Node does not. The entry splits only at
    \\n, so it works with both."""
    assert NODE is not None
    major = int(
        subprocess.run(
            [NODE, "-p", "process.versions.node.split('.')[0]"], capture_output=True, text=True
        ).stdout
    )
    count = "const rl = require('readline').createInterface({input: process.stdin}); let n = 0;"
    count += " rl.on('line', () => n++); rl.on('close', () => console.log(n));"
    p = subprocess.run([NODE, "-e", count], input="a\u2028b\n".encode(), capture_output=True)
    assert p.stdout in (b"1\n", b"2\n")
    if major >= 25:
        assert p.stdout == b"2\n"


def test_the_http_entry_starts_the_server_and_sends_each_message_to_it() -> None:
    with held_port() as port:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "TOY_SHOP_PORT": str(port)}
        p = subprocess.run(
            [sys.executable, str(HTTP_ENTRY)],
            input=lines(("m-1", "do you ship to delhi?"), ("m-2", ODD)),
            capture_output=True,
            timeout=120,
            env=env,
        )
    out = p.stdout.split(b"\n")
    assert out[-1] == b"" and len(out) == 3, p.stderr.decode(errors="replace")
    assert contract.parse_reply(out[0], "m-1") == (SHIP, None)
    assert contract.parse_reply(out[1], "m-2") == (FALLBACK, None)
    assert f"toy shop agent on http://127.0.0.1:{port}/".encode() in p.stderr
    assert p.returncode == 0
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


FENCE = re.compile(r"^```[a-z]*\n(.*?)^```$", re.MULTILINE | re.DOTALL)


@pytest.mark.parametrize("example", [NODE_ENTRY, HTTP_ENTRY], ids=lambda p: p.name)
def test_the_guide_shows_the_example_with_no_change(example: Path) -> None:
    blocks = FENCE.findall(GUIDE.read_text(encoding="utf-8"))
    assert example.read_text(encoding="utf-8") in blocks


EXAMPLES = ROOT / "examples"
IMPORTS_NOOKKU = re.compile(r"^(?:from|import) nookku\b", re.MULTILINE)
SCRIPT = (".py", ".mjs")


def documented_entries() -> list[tuple[Path, list[str]]]:
    """Each entry command that the README of an example or the HTTP entry gives, with the
    folder of the example."""
    found: list[tuple[Path, list[str]]] = []
    for readme in sorted(EXAMPLES.glob("*/README.md")):
        text = readme.read_text(encoding="utf-8")
        commands = re.findall(r'--entry "([^"]+)"', text)
        commands += re.findall(r"`((?:uv run|python3|node) [^`]+)`", text)
        found += [(readme.parent, shlex.split(c)) for c in commands]
    text = HTTP_ENTRY.read_text(encoding="utf-8")
    for raw in re.findall(r'"entry": (\[.*\])', text):
        found.append((HTTP_ENTRY.parent, json.loads(raw)))
    return [(folder, argv) for folder, argv in found if any(a.endswith(SCRIPT) for a in argv)]


ENTRIES = documented_entries()


@pytest.mark.parametrize(
    "folder, argv", ENTRIES, ids=[f"{f.name}:{' '.join(a)}" for f, a in ENTRIES]
)
def test_each_documented_entry_has_the_packages_of_its_script(
    folder: Path, argv: list[str]
) -> None:
    # A copy of an example outside the repo has no nookku project, so an entry that imports
    # nookku gets it with uv run --with nookku (#393).
    script = next(a for a in argv if a.endswith(SCRIPT))
    path = ROOT / script if script.startswith("examples/") else folder / script
    assert path.is_file(), path
    if IMPORTS_NOOKKU.search(path.read_text(encoding="utf-8")):
        assert argv[:2] == ["uv", "run"] and ("--with", "nookku") in pairwise(argv), argv

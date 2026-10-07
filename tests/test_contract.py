import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from verbatim_relay import contract
from verbatim_relay.audit import audit
from verbatim_relay.record import Writer
from verbatim_relay.stdio import Agent, StdioTap, start_in_thread

ROOT = Path(__file__).resolve().parent.parent
CASES = sorted((ROOT / "conformance" / "contract").iterdir())

# A scripted agent: it saves each input line, then does the step of the case for that line.
SCRIPTED = """
import json, sys, time
case = json.load(open(sys.argv[1], encoding="utf-8"))
got = open(sys.argv[2], "ab")
for i, raw in enumerate(sys.stdin.buffer):
    got.write(raw)
    got.flush()
    step = case["agent"][i] if i < len(case["agent"]) else {}
    if "exit" in step:
        sys.exit(step["exit"])
    time.sleep(step.get("sleep", 0))
    for line in step.get("lines", []):
        sys.stdout.buffer.write(line.encode("utf-8") + b"\\n")
    sys.stdout.buffer.flush()
"""


def post(url: str, body: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.mark.parametrize("case_dir", CASES, ids=[c.name for c in CASES])
def test_contract_case(case_dir: Path, tmp_path: Path) -> None:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    script, got = tmp_path / "agent.py", tmp_path / "got.bin"
    script.write_text(SCRIPTED)
    argv = [sys.executable, str(script), str(case_dir / "case.json"), str(got)]
    agent = Agent(argv, tmp_path, tmp_path / "app.log", timeout=1)
    tap = StdioTap(("127.0.0.1", 0), agent, tmp_path / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    try:
        statuses = []
        for body in case["requests"]:
            statuses.append(post(tap.url, body)[0])
            time.sleep(0.2)
    finally:
        tap.shutdown()
        agent.stop(grace=1)
    assert statuses == case["http"]
    sent = got.read_bytes() if got.exists() else b""
    assert sent == b"".join(case["requests"][i].encode() + b"\n" for i in case["forwarded"])
    rows = [json.loads(x) for x in (tmp_path / "tap.jsonl").read_text().split("\n") if x]
    assert len(rows) == len(case["rows"])
    for row, want in zip(rows, case["rows"], strict=True):
        assert {k: row.get(k) for k in want} == want
        assert row["v"] == "0.2"
        if row["type"] == "exchange":
            assert row["started"] <= row["ts"]


def test_an_error_after_a_crash_shows_the_end_of_the_log(tmp_path: Path) -> None:
    script = tmp_path / "agent.py"
    script.write_text(
        "import sys\nsys.stdin.readline()\n"
        "print('order db: no such table', file=sys.stderr)\nsys.exit(3)\n"
    )
    agent = Agent([sys.executable, str(script)], tmp_path, tmp_path / "app.log", timeout=5)
    tap = StdioTap(("127.0.0.1", 0), agent, tmp_path / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    try:
        status, body = post(
            tap.url, contract.request("m-1", "t-1", "Where is my mug?", []).decode()
        )
    finally:
        tap.shutdown()
        agent.stop(grace=1)
    assert status == 502
    error = json.loads(body)["error"]
    assert "the agent exited (code 3)" in error
    assert "order db: no such table" in error


def test_stop_ends_the_whole_process_group(tmp_path: Path) -> None:
    # The agent starts a child that ignores SIGTERM. stop() must still end it.
    script = tmp_path / "agent.py"
    script.write_text(
        "import signal, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(60)\n"
    )
    agent = Agent([sys.executable, str(script)], tmp_path, tmp_path / "app.log")
    agent.start()
    child = int(agent._lines.get(timeout=10) or b"0")
    agent.stop(grace=0.5)
    time.sleep(0.2)
    assert agent.proc is not None and agent.proc.poll() is not None
    alive = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True)
    assert alive.stdout.strip() in ("", "Z", "Z+")


def test_request_round_trip() -> None:
    line = contract.request("m-1", "t-1", "Ça marche?\u2028", [("Hi", "Hello  ")])
    assert b"\n" not in line
    assert contract.parse_request(line) == ("m-1", "Ça marche?\u2028", [("Hi", "Hello  ")])


@pytest.mark.parametrize(
    "line",
    [
        b'{"v": 1, "id": "m-1", "session": "t-1", "message": "hi"}',
        b'{"v": 1, "id": "m-1", "session": "t-1", "message": 5, "history": []}',
        b'{"v": true, "id": "m-1", "session": "t-1", "message": "hi", "history": []}',
        b'{"v": 1, "id": "m-1", "session": "t-1", "message": "hi", "history": [{"message": "a"}]}',
        b"[1]",
        b"\xff",
    ],
)
def test_request_refuses(line: bytes) -> None:
    with pytest.raises(contract.ContractError):
        contract.parse_request(line)


SERVED = """
from verbatim_relay.agent import serve

def reply(message, history):
    print("a log line from the toy shop")
    if message == "boom":
        raise RuntimeError("the order service is down")
    return f"{len(history)}|{message}"

serve(reply)
"""


def test_serve_speaks_the_contract(tmp_path: Path) -> None:
    script = tmp_path / "entry.py"
    script.write_text(SERVED)
    lines = [
        contract.request("m-1", "t-1", "Hi  \r\n\u2028€", [("a", "b")]),
        contract.request("m-2", "t-1", "boom", []),
        b"not json",
    ]
    p = subprocess.run(
        [sys.executable, str(script)],
        input=b"".join(x + b"\n" for x in lines),
        capture_output=True,
        timeout=30,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    out = p.stdout.split(b"\n")
    assert out[-1] == b""
    assert contract.parse_reply(out[0], "m-1") == ("1|Hi  \r\n\u2028€", None)
    assert contract.parse_reply(out[1], "m-2") == (None, "RuntimeError: the order service is down")
    assert json.loads(out[2])["error"].startswith("verbatim-relay agent:")
    assert len(out) == 4
    assert p.stderr.count(b"a log line from the toy shop") == 2
    assert p.returncode == 0


# The entry prints a line at import, before serve(). Stdout is a pipe, so Python buffers the line.
EARLY = """
from verbatim_relay.agent import serve

print("toy shop: loading catalog")
serve(lambda message, history: "We sell mugs.")
"""


def test_output_before_serve_goes_to_the_log(tmp_path: Path) -> None:
    script = tmp_path / "entry.py"
    script.write_text(EARLY)
    env = {"PYTHONPATH": str(ROOT / "src")}
    agent = Agent([sys.executable, str(script)], tmp_path, tmp_path / "app.log", env=env)
    tap = StdioTap(("127.0.0.1", 0), agent, tmp_path / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    said = "Do you sell mugs?"
    try:
        # Give the entry time to start, so that a stray line is on stdout before the request.
        time.sleep(0.5)
        status, body = post(tap.url, contract.request("m-1", "t-1", said, []).decode())
    finally:
        tap.shutdown()
        agent.stop(grace=1)
    assert status == 200
    shown, _ = contract.parse_reply(body, "m-1")
    rows = [json.loads(x) for x in (tmp_path / "tap.jsonl").read_text().split("\n") if x]
    assert [r["type"] for r in rows] == ["exchange"]
    assert "toy shop: loading catalog" in (tmp_path / "app.log").read_text()
    relay = Writer(tmp_path / "relay.jsonl")
    relay.append({"type": "turn", "harness": "codex", "said": said, "shown": shown})
    assert audit(tmp_path / "tap.jsonl", relay.path).exit == 0

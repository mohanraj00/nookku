import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from nookku import contract
from nookku.audit import audit
from nookku.record import Writer, lone_surrogate
from nookku.stdio import Agent, StdioTap, start_in_thread

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


def test_a_lone_surrogate_in_a_reply_is_named(tmp_path: Path) -> None:
    script = tmp_path / "agent.py"
    script.write_text(
        "import sys\nsys.stdin.readline()\n"
        'print(\'{"v": 1, "id": "m-1", "reply": "Your mug ships today \\\\ud83d"}\', '
        "flush=True)\nsys.stdin.readline()\n"
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
    note = "the agent reply has a lone surrogate U+D83D at character 21"
    assert status == 502 and note in json.loads(body)["error"]
    row = json.loads((tmp_path / "tap.jsonl").read_text())
    assert (row["status"], row["reply"], row["error"]) == (None, None, note)


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
        b'{"v": 1, "id": "m-1", "session": "t-1", "message": "hi", "history": [], "x": Infinity}',
    ],
)
def test_request_refuses(line: bytes) -> None:
    with pytest.raises(contract.ContractError):
        contract.parse_request(line)


def tap_status(line: str) -> int:
    """The status that the stdio tap returns for one agent line."""
    try:
        reply, error = contract.parse_reply(line.encode("utf-8"), "m-1")
    except contract.ContractError:
        return 502
    if lone_surrogate((reply if error is None else error) or ""):
        return 502
    return 200 if error is None else 500


def test_the_tap_reads_each_one_line_case_of_the_table() -> None:
    # The table holds the line and the HTTP status of each one-line conformance case.
    rows = json.loads((ROOT / "tests" / "tables.json").read_text("utf-8"))["contract_lines"]
    want = {}
    for d in CASES:
        case = json.loads((d / "case.json").read_text(encoding="utf-8"))
        steps = case["agent"]
        if len(case["requests"]) == 1 and len(steps) == 1 and len(steps[0].get("lines", [])) == 1:
            # The tap waits past a stray line until the timeout (504). One body with only the
            # stray line is not a valid output (502).
            status = 502 if case["http"][0] == 504 else case["http"][0]
            want[d.name] = [steps[0]["lines"][0], status]
    assert rows == want
    for line, status in rows.values():
        assert tap_status(line) == status


SERVED = """
from nookku.agent import serve

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
    assert json.loads(out[2])["error"].startswith("nookku agent:")
    assert len(out) == 4
    assert p.stderr.count(b"a log line from the toy shop") == 2
    assert p.returncode == 0


# The entry prints a line at import, before serve(). Stdout is a pipe, so Python buffers the line.
EARLY = """
from nookku.agent import serve

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


# The entry prints a log line on stdout just before each reply, with no wait. Only the line with
# the request id is the reply.
NOISY = """
import json, sys
for raw in sys.stdin.buffer:
    rid = json.loads(raw)["id"]
    print("toy shop: looking up the order", flush=True)
    print(json.dumps({"v": 1, "id": rid, "reply": "Order " + rid + " ships today."}), flush=True)
"""


def test_a_stray_line_before_the_reply_is_not_the_reply(tmp_path: Path) -> None:
    script = tmp_path / "entry.py"
    script.write_text(NOISY)
    agent = Agent([sys.executable, str(script)], tmp_path, tmp_path / "app.log", timeout=10)
    tap = StdioTap(("127.0.0.1", 0), agent, tmp_path / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    try:
        answers = [
            post(tap.url, contract.request(rid, "t-1", "Where is my mug?", []).decode())
            for rid in ("m-1", "m-2")
        ]
    finally:
        tap.shutdown()
        agent.stop(grace=1)
    assert [status for status, _ in answers] == [200, 200]
    rows = [json.loads(x) for x in (tmp_path / "tap.jsonl").read_text().split("\n") if x]
    exchanges = [r for r in rows if r["type"] == "exchange"]
    assert [r["reply"] for r in exchanges] == ["Order m-1 ships today.", "Order m-2 ships today."]
    stray = [r for r in rows if r["type"] == "unparsed"]
    assert [(r["method"], r["path"]) for r in stray] == [("STDIO", "stdout")] * 2
    assert all("toy shop: looking up the order" in r["error"] for r in stray)


# The entry writes its logs on stdout and never sends a reply line.
LOGS_ON_STDOUT = """
import sys
for raw in sys.stdin.buffer:
    for step in ("loading catalog", "looking up the order", "order found"):
        print("toy shop: " + step, flush=True)
"""


def test_a_timeout_after_stray_lines_names_them_and_the_fix(tmp_path: Path) -> None:
    script = tmp_path / "entry.py"
    script.write_text(LOGS_ON_STDOUT)
    agent = Agent([sys.executable, str(script)], tmp_path, tmp_path / "app.log", timeout=1)
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
    want = (
        "the agent printed 3 lines on stdout but no reply line for m-1 in 1 s, so the tap stopped "
        "it. Use nookku.agent.serve() or write logs to stderr. "
        "The first line: 'toy shop: loading catalog'"
    )
    assert status == 504
    assert want in json.loads(body)["error"]
    rows = [json.loads(x) for x in (tmp_path / "tap.jsonl").read_text().split("\n") if x]
    assert [r["type"] for r in rows] == ["unparsed"] * 3 + ["exchange"]
    assert rows[-1]["error"] == want


def test_an_agent_that_writes_stray_lines_all_the_time_still_times_out(tmp_path: Path) -> None:
    script = tmp_path / "agent.py"
    script.write_text(
        "import sys, time\nsys.stdin.readline()\n"
        "while True:\n    print('toy shop: still loading', flush=True)\n    time.sleep(0.01)\n"
    )
    agent = Agent([sys.executable, str(script)], tmp_path, tmp_path / "app.log", timeout=0.5)
    tap = StdioTap(("127.0.0.1", 0), agent, tmp_path / "tap.jsonl")
    agent.start()
    start_in_thread(tap)
    began = time.monotonic()
    try:
        status, body = post(
            tap.url, contract.request("m-1", "t-1", "Where is my mug?", []).decode()
        )
    finally:
        tap.shutdown()
        agent.stop(grace=1)
    assert status == 504
    assert time.monotonic() - began < 5
    assert "no reply line for m-1 in 0.5 s" in json.loads(body)["error"]

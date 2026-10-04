import json
from pathlib import Path

import pytest

from verbatim_relay import __version__
from verbatim_relay.cli import main
from verbatim_relay.record import Writer

CASES = Path(__file__).resolve().parent.parent / "conformance" / "cases"


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"verbatim-relay {__version__}"


@pytest.mark.parametrize(
    "case, code", [("clean", 0), ("altered_reply_word", 1), ("relay_record_missing", 2)]
)
def test_audit_exit_codes_and_text(case, code, capsys):
    d = CASES / case
    assert main(["audit", "--tap", str(d / "tap.jsonl"), "--relay", str(d / "relay.jsonl")]) == code
    out = capsys.readouterr().out
    assert {0: "clean (exit 0)", 1: "breaks found (exit 1)", 2: "cannot run (exit 2)"}[code] in out
    if code == 1:
        assert "expected 'Café" in out and "got 'Care" in out


def test_audit_json(capsys):
    d = CASES / "several_breaks"
    assert (
        main(["audit", "--tap", str(d / "tap.jsonl"), "--relay", str(d / "relay.jsonl"), "--json"])
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert [b["class"] for b in report["breaks"]] == [
        "altered_input",
        "altered_reply",
        "altered_input",
        "unshown_reply",
    ]
    assert report["breaks"][0]["evidence"]["first_difference"] == 33


def test_rows_from_the_writer_pass_the_audit(tmp_path, capsys):
    tap, relay = Writer(tmp_path / "tap.jsonl"), Writer(tmp_path / "relay.jsonl")
    tap.append({"type": "exchange", "input": "a ", "status": 200, "reply": "b\n"})
    relay.append({"type": "turn", "harness": "codex", "said": "a ", "shown": "b\n"})
    relay.append({"type": "blocked_call", "harness": "codex", "tool": "Bash", "detail": "curl"})
    assert main(["audit", "--tap", str(tap.path), "--relay", str(relay.path)]) == 0


def test_no_command_prints_help():
    assert main([]) == 2


def test_tap_command_end_to_end(tmp_path):
    import socket
    import subprocess
    import sys
    import urllib.request

    from toy_agent import ToyAgent, shop_reply

    agent = ToyAgent()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    record = tmp_path / "tap.jsonl"
    cmd = [
        sys.executable,
        "-m",
        "verbatim_relay",
        "tap",
        "--agent",
        agent.url,
        "--record",
        str(record),
        "--listen",
        f"127.0.0.1:{port}",
    ]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    try:
        assert "listening on" in (proc.stderr.readline() if proc.stderr else "")
        said = "Do you sell mugs?  "
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/", method="POST", data=json.dumps({"text": said}).encode()
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            shown = json.loads(resp.read())["reply"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        agent.shutdown()
    assert shown == shop_reply(said)
    relay = Writer(tmp_path / "relay.jsonl")
    relay.append({"type": "turn", "harness": "codex", "said": said, "shown": shown})
    assert main(["audit", "--tap", str(record), "--relay", str(relay.path)]) == 0

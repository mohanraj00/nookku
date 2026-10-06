import json
import sys
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


def test_transcript_without_a_config_uses_the_default_record(tmp_path, capsys):
    relay = Writer(tmp_path / ".verbatim-relay" / "relay.jsonl")
    relay.path.parent.mkdir()
    relay.append(
        {
            "type": "turn",
            "harness": "claude-code",
            "said": "hi ",
            "shown": "yo\n",
            "ok": True,
            "session": "s",
        }
    )
    assert main(["transcript", "--root", str(tmp_path)]) == 0
    assert "──── tester, turn 1 ────\nhi \n──── agent ────\nyo\n" in capsys.readouterr().out


TOY_SHOP = Path(__file__).resolve().parent.parent / "examples" / "toy-shop" / "agent.py"


def test_setup_prints_the_guide(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# verbatim-relay setup")
    assert "verbatim-relay check" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["tap", "--record", "t.jsonl"],
        ["tap", "--cmd", "--record", "t.jsonl"],
        ["tap", "--cmd", "--agent", "http://127.0.0.1:9/", "--record", "t.jsonl", "--", "x"],
    ],
)
def test_tap_needs_one_agent(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2


def test_init_start_and_end_a_test(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    entry = f"{sys.executable} {TOY_SHOP}"
    assert (
        main(["init", "codex", "--root", str(tmp_path), "--entry", entry, "--models", "codex"]) == 0
    )
    conf = json.loads((tmp_path / ".verbatim-relay" / "config.json").read_text())
    assert conf["entry"] == [sys.executable, str(TOY_SHOP)]
    assert conf["models"] == ["codex"]
    capsys.readouterr()
    assert main(["start", "--root", str(tmp_path), "--json"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert main(["status", "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"on": True, "test": started}
    assert main(["start", "--root", str(tmp_path)]) == 1
    assert "runs already" in capsys.readouterr().out
    assert main(["mode", "off", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"Test {started['test']} ended: 0 turns, 0 model sessions." in out
    assert main(["end", "--root", str(tmp_path)]) == 0
    assert "No test runs. Relay mode is off." in capsys.readouterr().out

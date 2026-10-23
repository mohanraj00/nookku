import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import egress_folder
import pytest

from nookku import __version__, bridge, kit, mcp, state
from nookku.cli import INTERNAL_COMMANDS, main
from nookku.kit import LEGEND
from nookku.record import Writer

CASES = Path(__file__).resolve().parent.parent / "conformance" / "cases"


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"nookku {__version__}"


@pytest.mark.parametrize(
    "case, code",
    [
        ("clean", 0),
        ("altered_reply_word", 1),
        ("relay_record_missing", 2),
        ("lone_surrogate_in_the_tap_record", 2),
    ],
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


def test_the_help_lists_no_internal_command_and_each_command_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "==SUPPRESS==" not in out
    words = out.replace("{", " ").replace("}", " ").replace(",", " ").split()
    assert "start" in words and "transcript" in words
    for name in INTERNAL_COMMANDS:
        assert name not in words, name
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(bridge, "run", lambda *args, **kw: calls.append((args, kw)) or 0)
    assert main(["bridge", "--root", str(tmp_path), "--test", "t-1"]) == 0
    assert calls == [
        ((tmp_path, "t-1", None), {"entry_name": None, "script_source": None, "check": False})
    ]
    served: list[Path] = []
    monkeypatch.setattr(mcp, "serve", lambda root: served.append(root) or 0)
    assert main(["mcp", "--root", str(tmp_path)]) == 0
    assert served == [tmp_path.resolve()]
    hooked: list[tuple[Path | None, str]] = []
    monkeypatch.setattr(
        kit, "run_hook", lambda root, harness, *streams: hooked.append((root, harness)) or 0
    )
    assert main(["hook", "--root", str(tmp_path), "--harness", "codex"]) == 0
    assert hooked == [(tmp_path.resolve(), "codex")]


def test_the_invalid_choice_error_does_not_name_an_internal_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["seal"])
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice: 'seal'" in err
    listed = err.split("choose from", 1)[1]
    assert "start" in listed and "transcript" in listed
    for name in ("bridge", "hook", "mcp"):
        assert name not in listed
    # Each internal command still runs.
    calls: list[str] = []
    monkeypatch.setattr(bridge, "run", lambda *args, **kw: calls.append("bridge") or 0)
    assert main(["bridge", "--root", str(tmp_path), "--test", "t-1"]) == 0
    assert calls == ["bridge"]
    with pytest.raises(SystemExit) as exit_info:
        main(["hook"])
    assert "--harness" in capsys.readouterr().err


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
    import faulthandler, time as _t
    _dump = open(tmp_path / "parent.txt", "w")
    faulthandler.dump_traceback_later(8, repeat=True, file=_dump)
    _began = _t.monotonic()
    _boot = (
        "import faulthandler, runpy, sys; "
        f"f = open({str(tmp_path / 'child.txt')!r}, 'w'); "
        "faulthandler.dump_traceback_later(8, repeat=True, file=f); "
        "sys.argv = ['nookku'] + sys.argv[1:]; runpy.run_module('nookku', run_name='__main__')"
    )
    cmd = [
        sys.executable,
        "-c",
        _boot,
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
    faulthandler.cancel_dump_traceback_later()
    _dump.close()
    _took = _t.monotonic() - _began
    if _took > 5:
        raise AssertionError(
            f"DIAG took {_took:.1f}s\nPARENT\n{(tmp_path / 'parent.txt').read_text()[:6000]}"
            f"\nCHILD\n{(tmp_path / 'child.txt').read_text()[:6000]}"
        )
    assert shown == shop_reply(said)
    relay = Writer(tmp_path / "relay.jsonl")
    relay.append({"type": "turn", "harness": "codex", "said": said, "shown": shown})
    assert main(["audit", "--tap", str(record), "--relay", str(relay.path)]) == 0


def test_the_stdio_tap_command_takes_its_token_from_the_environment(tmp_path):
    import os
    import socket
    import urllib.error
    import urllib.request

    from nookku import contract, stdio

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    entry = Path(__file__).resolve().parent.parent / "examples" / "toy-shop" / "agent.py"
    cmd = [sys.executable, "-m", "nookku", "tap", "--record", str(tmp_path / "tap.jsonl")]
    cmd += ["--listen", f"127.0.0.1:{port}", "--cmd", "--", sys.executable, str(entry)]
    token = "toy-shop-token-" + "x" * 29
    env = {**os.environ, stdio.TOKEN_ENV: token}
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, env=env, cwd=tmp_path)
    url, body = f"http://127.0.0.1:{port}/", contract.request("m-1", "t-1", "Hi", [])
    try:
        assert proc.stderr is not None and "listening on" in proc.stderr.readline()
        # The caller gave the token, so the tap does not write it to stderr.
        assert "X-Nookku-Token" not in proc.stderr.readline()
        refused = urllib.request.Request(url, body, state.tap_headers("other"), method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(refused, timeout=10)
        req = urllib.request.Request(url, body, state.tap_headers(token), method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    assert e.value.code == 403 and status == 200


def test_the_stdio_tap_command_refuses_a_short_token(tmp_path, monkeypatch, capsys):
    from nookku import stdio

    monkeypatch.setenv(stdio.TOKEN_ENV, "a")
    cmd = ["tap", "--record", str(tmp_path / "tap.jsonl"), "--cmd", "--", "true"]
    with pytest.raises(SystemExit) as e:
        main(cmd)
    assert e.value.code == 2 and "43 characters or more" in capsys.readouterr().err
    assert not (tmp_path / "tap.jsonl").exists()


def test_transcript_without_a_config_uses_the_default_record(tmp_path, capsys):
    relay = Writer(tmp_path / ".nookku" / "relay.jsonl")
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


def _turns(path: Path, harness: str) -> None:
    """Write the same turns as the plugin or the project hooks write them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("old question", "old answer", True, "s0"),
        ("Where is order 4471?  \n", "It ships on Monday.\n\n| item | price |\n", True, "s1"),
        ("And order 4417?", "nookku: cannot reach the tap", False, "s1"),
    ]
    for said, shown, ok, session in rows:
        Writer(path).append(
            {
                "type": "turn",
                "harness": harness,
                "said": said,
                "shown": shown,
                "ok": ok,
                "session": session,
            }
        )


def _transcript(capsys: pytest.CaptureFixture[str], argv: list[str]) -> str:
    assert main(["transcript", *argv]) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_the_plugin_and_the_kit_render_the_same_transcript_of_a_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], harness: str
) -> None:
    # The transcript tool takes a test id (`nookku transcript --test ID`). The evaluation
    # tells the model to run `nookku transcript`, which takes the latest test.
    state = tmp_path / ".nookku"
    state.mkdir()
    (state / "config.json").write_text(json.dumps({"entry": ["python", "agent.py"]}))
    test = "20261007-090000-ab12"
    _turns(state / "tests" / test / "relay.jsonl", harness)
    root = ["--root", str(tmp_path)]
    plugin = _transcript(capsys, [*root, "--test", test])
    kit = _transcript(capsys, root)
    assert plugin == kit
    lines = plugin.split("\n")
    assert lines[0].startswith(f"nookku transcript, test {test}: 3 turns.")
    assert lines[1] == LEGEND
    assert "──── tester, turn 2 ────\nWhere is order 4471?  \n\n──── agent ────\n" in plugin
    assert "──── relay error, not an agent reply ────\nnookku: cannot" in plugin
    assert "sha256" not in plugin and "s1" not in plugin


def test_the_plugin_and_the_kit_render_the_same_transcript_of_a_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Without an entry, `nookku transcript --record R --session S` gives one session, and
    # `nookku transcript` gives the session of the default record.
    record = tmp_path / ".nookku" / "relay.jsonl"
    _turns(record, "claude-code")
    root = ["--root", str(tmp_path)]
    plugin = _transcript(capsys, [*root, "--record", str(record), "--session", "s1"])
    kit = _transcript(capsys, root)
    assert plugin.startswith("nookku transcript, session s1: 2 turns.")
    assert kit.startswith("nookku transcript, the latest session: 2 turns.")
    assert plugin.split("\n")[1:] == kit.split("\n")[1:]
    assert "old question" not in plugin


def test_spec_has_the_legend_of_the_transcript() -> None:
    spec = (Path(__file__).resolve().parent.parent / "SPEC.md").read_text(encoding="utf-8")
    assert f'"{LEGEND}"' in spec


TOY_SHOP = Path(__file__).resolve().parent.parent / "examples" / "toy-shop" / "agent.py"


def test_setup_prints_the_guide(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Nookku setup")
    assert "nookku check" in out


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


def test_init_takes_the_openai_stream_flag(tmp_path: Path) -> None:
    args = ["init", "codex", "--root", str(tmp_path), "--adapter", "openai", "--openai-stream"]
    assert main(args) == 0
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert (conf["adapter"], conf["openai_stream"]) == ("openai", True)


def test_init_no_openai_stream_sets_the_key_back_to_false(tmp_path: Path) -> None:
    # A second init keeps each key with no flag, so only this flag sets the key back (#120).
    root = ["init", "codex", "--root", str(tmp_path)]
    assert main([*root, "--adapter", "openai", "--openai-stream"]) == 0
    path = tmp_path / ".nookku" / "config.json"
    assert json.loads(path.read_text())["openai_stream"] is True
    assert main(root) == 0
    assert json.loads(path.read_text())["openai_stream"] is True
    assert main([*root, "--no-openai-stream"]) == 0
    conf = json.loads(path.read_text())
    assert (conf["adapter"], conf["openai_stream"]) == ("openai", False)


def test_init_takes_the_check_message_flag(tmp_path: Path) -> None:
    args = ["init", "codex", "--root", str(tmp_path), "--check-message", "Do you sell teapots?"]
    assert main(args) == 0
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert conf["check_message"] == "Do you sell teapots?"


def test_init_takes_the_repeated_reply_flag(tmp_path: Path) -> None:
    assert main(["init", "codex", "--root", str(tmp_path), "--repeated-reply", "0"]) == 0
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert conf["repeated_reply"] == 0


def test_init_takes_the_model_reply_flags(tmp_path: Path) -> None:
    args = ["init", "codex", "--root", str(tmp_path), "--model-reply-field", "output.client_text"]
    assert main([*args, "--model-reply-match", "exact"]) == 0
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert (conf["model_reply_field"], conf["model_reply_match"]) == ("output.client_text", "exact")


@pytest.mark.parametrize(
    "flags",
    [["--backend", "stock", "STOCK_URL", "http://127.0.0.1:9001"], ["--model-api", "openai"]],
)
def test_init_has_no_egress_flag(tmp_path: Path, flags: list[str]) -> None:
    # The egress answer of each start replaces the flags of 0.5.1 (SPEC.md section 7.11).
    with pytest.raises(SystemExit) as e:
        main(["init", "codex", "--root", str(tmp_path), *flags])
    assert e.value.code == 2
    assert not (tmp_path / ".nookku").exists()


@pytest.mark.parametrize("key", ["backends", "model_api"])
def test_init_writes_nothing_with_an_old_egress_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str
) -> None:
    path = tmp_path / ".nookku" / "config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"entry": ["python3", "agent.py"], key: True}))
    before = path.read_text()
    assert main(["init", "codex", "--root", str(tmp_path), "--models", "codex"]) == 1
    err = capsys.readouterr().err
    assert f"has the keys ['{key}'] of nookku 0.5.1 and earlier" in err
    assert path.read_text() == before


def test_the_init_commands_of_the_full_toy_shop_write_the_documented_config(
    tmp_path: Path,
) -> None:
    # A tester writes the config of examples/toy-shop-full/ with no hand edit (#392).
    repo = Path(__file__).resolve().parent.parent
    readme = (repo / "examples" / "toy-shop-full" / "README.md").read_text()
    runs = re.findall(r"^ *(nookku init .+)$", readme, re.MULTILINE)
    assert len(runs) == 1
    # The README runs init in a copy of the folder, so the files of the spec exist.
    shutil.copytree(repo / "examples" / "toy-shop-full", tmp_path, dirs_exist_ok=True)
    for run in runs:
        assert main([*shlex.split(run)[1:], "--root", str(tmp_path)]) == 0
    page = (repo / "docs" / "reference" / "config.md").read_text()
    shown = page.split("The full toy shop, with a stock service", 1)[1]
    found = re.search(r"```json\n(.*?)```", shown, re.DOTALL)
    assert found is not None
    block = json.loads(found[1])
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert {k: conf[k] for k in block} == block


def test_init_refuses_an_unknown_model_reply_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "codex", "--root", str(tmp_path), "--model-reply-match", "loose"]) == 1
    assert "'model_reply_match' must be exact, normalized or off" in capsys.readouterr().err
    assert not (tmp_path / ".nookku" / "config.json").exists()


def test_init_refuses_a_repeated_reply_of_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "codex", "--root", str(tmp_path), "--repeated-reply", "1"]) == 1
    assert "'repeated_reply' must be 0 (off) or a whole number" in capsys.readouterr().err
    assert not (tmp_path / ".nookku" / "config.json").exists()


def test_init_refuses_an_empty_check_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "codex", "--root", str(tmp_path), "--check-message", " "]) == 1
    assert "'check_message' must be a string with text" in capsys.readouterr().err
    assert not (tmp_path / ".nookku" / "config.json").exists()


@pytest.mark.parametrize(
    "inside", [".nookku/tests/t1", ".nookku", ".NOOKKU/tests/t1", ".verbatim-relay"]
)
@pytest.mark.parametrize("harness", ["claude-code", "codex", "plugin"])
def test_init_refuses_a_root_inside_the_state_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], inside: str, harness: str
) -> None:
    root = tmp_path / inside
    root.mkdir(parents=True)
    # A folder of the old name in the root must not move (#148).
    (root / ".verbatim-relay").mkdir()
    (root / ".verbatim-relay" / "config.json").write_text('{"record": ".verbatim-relay/r.jsonl"}')
    before = {p: p.read_bytes() if p.is_file() else None for p in tmp_path.rglob("*")}
    assert main(["init", harness, "--root", str(root)]) == 1
    assert {p: p.read_bytes() if p.is_file() else None for p in tmp_path.rglob("*")} == before
    err = capsys.readouterr().err
    folder = tmp_path / inside.split("/")[0]
    assert f"is inside the state folder {folder}." in err
    assert f"--root {tmp_path}. Nothing was written." in err


def test_init_refuses_a_state_folder_that_is_a_symlink(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "store" / "tests" / "t1").mkdir(parents=True)
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / ".nookku").symlink_to(tmp_path / "store")
    before = sorted(tmp_path.rglob("*"))
    assert (
        main(["init", "codex", "--root", str(tmp_path / "shop" / ".nookku" / "tests" / "t1")]) == 1
    )
    assert sorted(tmp_path.rglob("*")) == before
    assert f"--root {tmp_path / 'shop'}. Nothing was written." in capsys.readouterr().err


def test_init_refuses_the_target_of_a_symlinked_state_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "shop").mkdir()
    assert main(["init", "codex", "--root", str(tmp_path / "shop")]) == 0
    (tmp_path / "shop" / ".nookku").rename(tmp_path / "store")
    (tmp_path / "shop" / ".nookku").symlink_to(tmp_path / "store")
    (tmp_path / "store" / "tests" / "t1").mkdir(parents=True)
    capsys.readouterr()
    before = sorted(tmp_path.rglob("*"))
    assert main(["init", "codex", "--root", str(tmp_path / "store" / "tests" / "t1")]) == 1
    monkeypatch.chdir(tmp_path / "store" / "tests" / "t1")
    assert main(["init", "codex", "--root", "."]) == 1
    assert sorted(tmp_path.rglob("*")) == before
    assert f"is inside the state folder {tmp_path / 'store'}." in capsys.readouterr().err


def test_init_refuses_a_copied_test_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = tmp_path / "backup" / "t1"
    copy.mkdir(parents=True)
    manifest = {"test": "t1", "root": "/home/me/shop", "versions": {"nookku": "0.4.0"}}
    (copy / "manifest.json").write_text(json.dumps(manifest))
    before = sorted(tmp_path.rglob("*"))
    assert main(["init", "codex", "--root", str(copy)]) == 1
    assert sorted(tmp_path.rglob("*")) == before
    err = capsys.readouterr().err
    assert f"is inside the test folder {copy}." in err
    assert "--root /home/me/shop. Nothing was written." in err


@pytest.mark.parametrize(
    "files",
    [
        {"mode": "on", "config.json": "{}"},
        {"mode": "off", "tests/x": ""},
        {"manifest.json": '{"name": "Toy shop", "start_url": "/"}'},
        {"manifest.json": '{"test": "t1", "versions": {"shop": "1.0"}}'},
    ],
    ids=["mode-and-config", "mode-and-tests", "web-manifest", "other-versions"],
)
def test_init_accepts_an_app_folder_with_similar_files(
    tmp_path: Path, files: dict[str, str]
) -> None:
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    assert main(["init", "plugin", "--root", str(tmp_path / "app")]) == 0


def test_init_marks_the_state_folder(tmp_path: Path) -> None:
    assert main(["init", "plugin", "--root", str(tmp_path)]) == 0
    marker = tmp_path / ".nookku" / "nookku-state"
    assert marker.read_text() == state.MARKER_TEXT


def test_init_prints_the_root_before_the_move_of_the_old_folder(tmp_path: Path) -> None:
    (tmp_path / ".verbatim-relay").mkdir()
    cmd = [sys.executable, "-m", "nookku", "init", "plugin", "--root", str(tmp_path)]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = out.stdout.splitlines()
    assert lines[0] == f"Project root: {tmp_path.resolve()}"
    assert lines[1].startswith("nookku: moved ")
    assert lines.count(lines[0]) == 1


def test_init_prints_the_absolute_root_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "codex", "--root", "."]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == [
        f"Project root: {tmp_path.resolve()}",
        f"wrote {tmp_path.resolve() / '.nookku' / 'config.json'}",
    ]
    assert f"wrote {tmp_path.resolve() / '.codex' / 'hooks.json'}" in out


@pytest.mark.parametrize(
    ("sub", "config", "warned"), [("shop", False, True), ("", False, False), ("shop", True, False)]
)
def test_init_warns_if_a_new_root_is_not_the_top_of_its_git_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sub: str, config: bool, warned: bool
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    root = (tmp_path / sub).resolve()
    root.mkdir(exist_ok=True)
    if config:
        assert main(["init", "plugin", "--root", str(root)]) == 0
        capsys.readouterr()
    assert main(["init", "plugin", "--root", str(root)]) == 0
    err = capsys.readouterr().err
    assert (f"is not the top level of its git work tree, {tmp_path.resolve()}." in err) == warned
    if warned:
        # With stderr in the same pipe, the output still starts with the root.
        (root / ".nookku" / "config.json").unlink()
        cmd = [sys.executable, "-m", "nookku", "init", "plugin", "--root", str(root)]
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = out.stdout.splitlines()
        assert lines[0] == f"Project root: {root}"
        assert lines[1].startswith("nookku: warning:")


def test_init_again_keeps_the_keys_that_have_no_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "codex", "--root", str(tmp_path), "--entry", "python3 agent.py"]) == 0
    assert "A new file. Keys that differ from the default: entry." in capsys.readouterr().out
    path = tmp_path / ".nookku" / "config.json"
    first = {**json.loads(path.read_text()), "otel": False, "evaluate": False}
    path.write_text(json.dumps(first))
    assert main(["init", "codex", "--root", str(tmp_path), "--models", "codex"]) == 0
    assert json.loads(path.read_text()) == {**first, "models": ["codex"]}
    kept = ", ".join(k for k in first if k != "models")
    assert f"Keys changed: models. Keys kept: {kept}." in capsys.readouterr().out


def test_init_adds_no_default_to_an_existing_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".nookku" / "config.json"
    path.parent.mkdir()
    path.write_text('{"entry": ["python3", "agent.py"], "evaluate": false}')
    args = ["init", "claude-code", "--root", str(tmp_path), "--adapter", "openai"]
    assert main([*args, "--entry", "python3 agent.py"]) == 0
    assert json.loads(path.read_text()) == {
        "entry": ["python3", "agent.py"],
        "evaluate": False,
        "adapter": "openai",
    }
    assert "Keys changed: adapter. Keys kept: entry, evaluate." in capsys.readouterr().out


@pytest.mark.parametrize(
    "config, settings, error",
    [
        ('{"tpa_url": "x"}', None, "config.json has unknown keys: ['tpa_url']"),
        ("{", None, "cannot read .nookku/config.json"),
        (None, "{", "settings.local.json: Expecting"),
        (None, '{"hooks": []}', "'hooks' is not a JSON object"),
        (None, '{"hooks": {"PreToolUse": [null]}}', "a group of 'hooks.PreToolUse' has no list"),
        (None, '{"hooks": {"PreToolUse": [{"hooks": {}}]}}', "a group of 'hooks.PreToolUse'"),
        (None, '{"hooks": {"UserPromptSubmit": [{"hooks": [1]}]}}', "'hooks.UserPromptSubmit'"),
    ],
)
def test_init_writes_nothing_if_a_file_cannot_be_kept(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    config: str | None,
    settings: str | None,
    error: str,
) -> None:
    files = {
        tmp_path / ".nookku" / "config.json": config,
        tmp_path / ".claude" / "settings.local.json": settings,
    }
    for path, text in files.items():
        if text is not None:
            path.parent.mkdir()
            path.write_text(text)
    assert main(["init", "claude-code", "--root", str(tmp_path), "--entry", "python3 a.py"]) == 1
    err = capsys.readouterr().err
    assert error in err and err.endswith("Nothing was written.\n")
    for path, text in files.items():
        assert (path.read_text() if path.exists() else None) == text
    assert not (tmp_path / ".nookku" / "mode").exists()


def test_an_unknown_key_stops_start_check_and_the_project_hooks_with_one_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "codex", "--root", str(tmp_path), "--entry", f"python3 {TOY_SHOP}"]) == 0
    path = tmp_path / ".nookku" / "config.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "tpa_url": "x"}))
    cause = ".nookku/config.json has unknown keys: ['tpa_url']. Correct or remove them."
    capsys.readouterr()
    for command in ("start", "check"):
        assert main([command, "--root", str(tmp_path)]) == 1
        assert capsys.readouterr().out == f"nookku: {cause}\n"
    assert main(["start", "--root", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"error": cause}
    # mode on starts a test, so it shows the same message and keeps relay mode off.
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == f"nookku: {cause}\n"
    assert not kit.is_on(tmp_path)
    assert not (tmp_path / ".nookku" / "tests").exists()
    kit.set_mode(tmp_path, True)
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "hi", "session_id": "s1"}
    answer = kit.handle(event, tmp_path, "codex")
    assert answer is not None and answer["decision"] == "block"
    broken = "nookku: relay mode is on, but the config is broken: "
    assert answer["reason"] == broken + cause


@pytest.mark.parametrize(
    ("key", "value", "rule"),
    [
        ("entry", "python3 agent.py", "'entry' must be a list of strings"),
        ("models", "claude", "'models' must be a list of claude-code, codex"),
        ("models", ["claude"], "'models' must be a list of claude-code, codex"),
        ("evaluate", "no", "'evaluate' must be true or false"),
        ("otel", 0, "'otel' must be true or false"),
        # An explicit null is not the same as a key that is not there.
        ("evaluate", None, "'evaluate' must be true or false"),
        ("tap_url", 8800, "'tap_url' must be a string"),
    ],
)
def test_a_wrong_type_stops_init_start_check_mode_on_and_the_project_hooks_with_one_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str, value: Any, rule: str
) -> None:
    # The one reader checks the type of each value (#121), so each command gives one error.
    assert main(["init", "codex", "--root", str(tmp_path), "--entry", f"python3 {TOY_SHOP}"]) == 0
    path = tmp_path / ".nookku" / "config.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), key: value}))
    text = path.read_text()
    capsys.readouterr()
    cause = f".nookku/config.json: {rule}"
    assert main(["init", "codex", "--root", str(tmp_path), "--adapter", "openai"]) == 1
    err = capsys.readouterr().err
    assert cause in err and err.endswith("Nothing was written.\n")
    assert path.read_text() == text
    for command in ("start", "check"):
        assert main([command, "--root", str(tmp_path)]) == 1
        assert capsys.readouterr().out.startswith(f"nookku: {cause}")
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out.startswith(f"nookku: {cause}")
    assert not kit.is_on(tmp_path)
    assert not (tmp_path / ".nookku" / "tests").exists()
    kit.set_mode(tmp_path, True)
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "hi", "session_id": "s1"}
    answer = kit.handle(event, tmp_path, "codex")
    assert answer is not None and answer["decision"] == "block"
    broken = "nookku: relay mode is on, but the config is broken: "
    assert answer["reason"].startswith(broken + cause)


def test_mode_on_with_no_entry_and_an_unknown_key_keeps_relay_mode_off(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".nookku" / "config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"agent_url": "http://127.0.0.1:9000/", "tpa_url": "x"}))
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    cause = ".nookku/config.json has unknown keys: ['tpa_url']. Correct or remove them."
    assert capsys.readouterr().out == f"nookku: {cause}\n"
    assert not kit.is_on(tmp_path)
    path.write_text(json.dumps({"agent_url": "http://127.0.0.1:9000/"}))
    assert main(["mode", "on", "--root", str(tmp_path)]) == 0
    assert kit.is_on(tmp_path)


@pytest.mark.parametrize("was_on", [False, True])
def test_mode_on_with_no_config_keeps_the_mode_file_and_says_the_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], was_on: bool
) -> None:
    # #357: with no config.json, mode on does not change the mode file, and its text is true.
    kit.set_mode(tmp_path, was_on)
    mode = kit.mode_path(tmp_path).read_text()
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    if was_on:
        text = (
            "nookku: this project has no .nookku/config.json. Relay mode is still on, "
            "so the relay blocks each prompt. Write the config with: nookku init plugin. "
            "Or switch relay mode off with: nookku mode off\n"
        )
    else:
        text = (
            "nookku: this project has no .nookku/config.json, so relay mode stays off. "
            "Write it with: nookku init plugin\n"
        )
    assert capsys.readouterr().out == text
    assert kit.mode_path(tmp_path).read_text() == mode
    assert kit.is_on(tmp_path) is was_on


def test_a_refusal_of_mode_on_has_the_prefix_one_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # #395: the mode text added "nookku: " to a refusal that had it, and showed it 2 times.
    kit.init(tmp_path, "plugin", {"entry": [sys.executable, "-c", "pass"]})

    def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise bridge.BridgeError("nookku: the test cannot start.")

    monkeypatch.setattr(bridge, "start", refuse)
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == "nookku: the test cannot start.\n"
    monkeypatch.setattr("nookku.claude_gate.problem", lambda root: "nookku: both are on.")
    (tmp_path / ".nookku" / "config.json").write_text("{}")
    assert main(["mode", "on", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == "nookku: both are on.\n"
    assert kit.prefixed("relay mode is on.") == "nookku: relay mode is on."


def test_init_remove_prints_each_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init", "codex", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    target = tmp_path / ".codex" / "hooks.json"
    assert main(["init", "--remove", "codex", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"removed 2 hooks from {target}\n" in out
    assert json.loads(target.read_text()) == {}
    assert (tmp_path / ".nookku" / "config.json").exists()
    assert main(["init", "codex", "--remove", "--root", str(tmp_path)]) == 0
    assert f"{target} has no hook of nookku. Nothing was changed." in capsys.readouterr().out


@pytest.mark.parametrize("running", [True, False])
def test_init_remove_refuses_while_a_test_or_relay_mode_is_on(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
) -> None:
    assert main(["init", "claude-code", "--root", str(tmp_path)]) == 0
    target = tmp_path / ".claude" / "settings.local.json"
    text = target.read_text()
    kit.set_mode(tmp_path, True)
    if running:
        monkeypatch.setattr(bridge, "current", lambda root: {"test": "t1"})
    capsys.readouterr()
    assert main(["init", "--remove", "claude-code", "--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert ("nookku end" if running else "nookku mode off") in err
    assert err.endswith("Nothing was changed.\n")
    assert target.read_text() == text


def test_init_remove_puts_the_hooks_back_if_relay_mode_starts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["init", "codex", "--root", str(tmp_path)]) == 0
    target = tmp_path / ".codex" / "hooks.json"
    text = target.read_text()
    remove = kit.remove

    def remove_then_mode_on(root: Path, harness: str) -> kit.Removed:
        done = remove(root, harness)
        assert "nookku hook" not in target.read_text()
        kit.set_mode(root, True)
        return done

    monkeypatch.setattr(kit, "remove", remove_then_mode_on)
    capsys.readouterr()
    assert main(["init", "--remove", "codex", "--root", str(tmp_path)]) == 1
    assert "nookku mode off" in capsys.readouterr().err
    assert target.read_text() == text


def test_init_remove_refuses_with_old_relay_mode_on_and_does_not_move_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = tmp_path / ".verbatim-relay"
    old.mkdir()
    (old / "mode").write_text("on\n")
    target = tmp_path / ".codex" / "hooks.json"
    target.parent.mkdir()
    hook = {"type": "command", "command": "python -m verbatim_relay hook --harness codex"}
    text = json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [hook]}]}})
    target.write_text(text)
    assert main(["init", "--remove", "codex", "--root", str(tmp_path)]) == 1
    assert "relay mode is on" in capsys.readouterr().err
    assert target.read_text() == text
    assert old.is_dir() and not (tmp_path / ".nookku").exists()


@pytest.mark.parametrize(
    "extra",
    [
        ["plugin"],
        ["codex", "--entry", "python3 a.py"],
        ["codex", "--openai-stream"],
        ["codex", "--no-openai-stream"],
    ],
)
def test_init_remove_takes_no_config_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    with pytest.raises(SystemExit) as e:
        main(["init", "--remove", *extra, "--root", str(tmp_path)])
    assert e.value.code == 2
    assert "--remove takes" in capsys.readouterr().err
    assert not (tmp_path / ".nookku").exists()


def test_init_remove_changes_nothing_in_a_broken_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / ".claude" / "settings.local.json"
    target.parent.mkdir()
    target.write_text("{")
    assert main(["init", "--remove", "claude-code", "--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert f"cannot read {target}" in err and err.endswith("Nothing was changed.\n")
    assert target.read_text() == "{"


@pytest.mark.parametrize("evaluate", [True, False])
def test_the_shell_start_text_gives_the_same_ways_to_end_a_test(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    evaluate: bool,
) -> None:
    cur = {"test": "t-1", "tap_url": "http://127.0.0.1:1/"}
    cur["dir"] = egress_folder.folder(tmp_path / "t-1")
    monkeypatch.setattr(bridge, "start", lambda root, session=None: cur)
    (tmp_path / ".nookku").mkdir()
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps({"evaluate": evaluate}))
    assert main(["start", "--root", str(tmp_path)]) == 0
    shell = capsys.readouterr().out
    ways = kit.end_ways(tmp_path)
    started = "Test t-1 started on http://127.0.0.1:1/. Relay mode is on."
    assert shell == f"{started}\n{ways}\n{egress_folder.NO_EGRESS}\n"
    # The plugin and the project hooks show kit.start_test, with the same ways.
    assert kit.start_test(tmp_path).endswith(
        f"goes to the entry. {ways}\n{egress_folder.NO_EGRESS}"
    )
    assert ("evaluation" in ways) is evaluate


def test_init_start_and_end_a_test(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    entry = f"{sys.executable} {TOY_SHOP}"
    assert (
        main(["init", "codex", "--root", str(tmp_path), "--entry", entry, "--models", "codex"]) == 0
    )
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert conf["entry"] == [sys.executable, str(TOY_SHOP)]
    assert conf["models"] == ["codex"] and conf["openai_stream"] is False
    capsys.readouterr()
    # A state folder of an older version has no marker. The start writes it.
    (tmp_path / ".nookku" / state.MARKER).unlink()
    assert main(["start", "--root", str(tmp_path), "--json"]) == 0
    assert (tmp_path / ".nookku" / state.MARKER).is_file()
    started = json.loads(capsys.readouterr().out)
    assert main(["status", "--root", str(tmp_path), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    text = kit.status(tmp_path)[8:]
    refuse = kit.ATTACHMENTS_REASON
    pane = status.pop("pane")
    expected = {"on": True, "test": started, "text": text, "attachments": refuse, "stopped": None}
    assert status == expected
    assert pane["test"] == started["test"] and pane["state"] == "running" and pane["turns"] == 0
    assert status["text"].startswith(f"relay mode is on. Test {started['test']} runs on ")
    assert main(["start", "--root", str(tmp_path)]) == 1
    assert "runs already" in capsys.readouterr().out
    assert main(["mode", "off", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"Test {started['test']} ended: 0 turns, 0 model sessions." in out
    assert "Trace: 0 model items in 0 turns, no findings." in out
    assert main(["trace", "--root", str(tmp_path)]) == 0
    assert "Trace: 0 model items in 0 turns, no findings." in capsys.readouterr().out
    assert main(["trace", "no-such-test", "--root", str(tmp_path)]) == 2
    assert main(["end", "--root", str(tmp_path)]) == 0
    assert "No test runs. Relay mode is off." in capsys.readouterr().out


# The text of the start refusal with no entry. A change of the text changes this test too.
NO_ENTRY = (
    ".nookku/config.json has no 'entry' command, so the test cannot start. Write the command "
    'that starts your agent with: nookku init <relay> --entry "<command>". <relay> is plugin, '
    "claude-code or codex."
)


@pytest.mark.parametrize("relay", ["plugin", "codex", "claude-code"])
def test_init_with_no_entry_ends_with_the_command_that_writes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], relay: str
) -> None:
    # A new tester ran init with no flags, and start then refused with no fix (Gate 1 of #401).
    assert main(["init", relay, "--root", str(tmp_path)]) == 0
    assert json.loads((tmp_path / ".nookku" / "config.json").read_text())["entry"] == []
    assert capsys.readouterr().out.splitlines()[-1] == (
        "Note: .nookku/config.json has no entry, so a test cannot start yet. Write the "
        f'command that starts your agent with: nookku init {relay} --entry "python3 agent.py". '
        "Replace python3 agent.py with your command."
    )


@pytest.mark.parametrize(
    "flags", [["--entry", "python3 agent.py"], ["--agent-url", "http://127.0.0.1:8700/"]]
)
def test_init_with_an_entry_or_an_agent_url_gives_no_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    assert main(["init", "plugin", "--root", str(tmp_path), *flags]) == 0
    assert "has no entry" not in capsys.readouterr().out
    # A second init with no flag keeps the key, so it gives no note too.
    assert main(["init", "plugin", "--root", str(tmp_path)]) == 0
    assert "has no entry" not in capsys.readouterr().out


def test_each_start_with_no_entry_gives_the_command_that_writes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "plugin", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["start", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == f"nookku: {NO_ENTRY}\n"
    assert main(["start", "--root", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"error": NO_ENTRY}
    assert main(["check", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == f"nookku: {NO_ENTRY}\n"
    turns = tmp_path / "turns.jsonl"
    turns.write_text('{"said": "Do you sell teapots?"}\n', "utf-8")
    assert main(["run", "--script", str(turns), "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == f"nookku: {NO_ENTRY}\n"
    # The prompt nookku start of the plugin and of the project hooks. Start still refuses.
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "nookku start", "session_id": "s1"}
    answer = kit.handle(event, tmp_path, "claude-code")
    assert answer is not None and answer["reason"] == f"nookku: {NO_ENTRY}"
    assert not kit.is_on(tmp_path)
    assert state.current(tmp_path) is None

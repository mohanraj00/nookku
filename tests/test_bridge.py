import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from verbatim_relay import bridge, kit, seal, stdio
from verbatim_relay.audit import CHECKS, audit
from verbatim_relay.record import RecordError, Writer

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
CLAUDE_SID = "4f1c2a7e-0d3b-4c55-9a61-2b8e5d7c9f10"
APP_THREAD = "019a0b1c-2d3e-7f40-8a5b-6c7d8e9f0a1b"
TESTER_THREAD = "019a0b1c-0000-7000-8000-000000004471"

# A toy shop app that runs one Claude Code session and one Codex thread. It writes the files that
# the harness binaries write: the pid file and the transcript of Claude Code, and a Codex rollout.
# It also writes a rollout for the tester's own thread, which the bridge must not take.
FIXTURE_APP = f"""
import json, os, sys, time
from pathlib import Path

claude, codex = Path(os.environ["CLAUDE_CONFIG_DIR"]), Path(os.environ["CODEX_HOME"])
(claude / "sessions").mkdir(parents=True, exist_ok=True)
project = claude / "projects" / "-toy-shop"
project.mkdir(parents=True, exist_ok=True)
(project / "{CLAUDE_SID}.jsonl").write_text('{{"type": "user"}}\\n')
pid_file = claude / "sessions" / f"{{os.getpid()}}.json"
pid_file.write_text(json.dumps({{"pid": os.getpid(), "sessionId": "{CLAUDE_SID}"}}))
day = codex / "sessions" / time.strftime("%Y/%m/%d")
day.mkdir(parents=True, exist_ok=True)
for name, sid in (("app", "{APP_THREAD}"), ("tester", "{TESTER_THREAD}")):
    meta = {{"id": sid, "cwd": os.getcwd(), "originator": "toy-shop-" + name}}
    line = json.dumps({{"type": "session_meta", "payload": meta}})
    (day / f"rollout-{{name}}-{{sid}}.jsonl").write_text(line + "\\n")
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = {{"v": 1, "id": request["id"], "reply": "Toy shop: " + request["message"]}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\\n")
    sys.stdout.flush()
"""


def project(tmp_path: Path, entry: list[str], models: list[str] | None = None) -> Path:
    root = tmp_path / "shop"
    (root / ".verbatim-relay").mkdir(parents=True)
    conf = {"entry": entry, "models": models or []}
    (root / ".verbatim-relay" / "config.json").write_text(json.dumps(conf))
    return root


@pytest.fixture
def homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    claude, codex = tmp_path / "claude-home", tmp_path / "codex-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    return claude, codex


def test_a_test_relays_and_records_both_sides(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    cur = bridge.start(root, "tester-1")
    try:
        assert (root / ".verbatim-relay" / "current.json").exists()
        assert cur["pid_start"] == bridge.process_start(cur["pid"])
        said = "Do you ship to Chennai?\u2028Line two  "
        shown, ok = bridge.send(cur, said)
        Writer(Path(cur["dir"]) / "relay.jsonl").append(
            {"type": "turn", "harness": "codex", "said": said, "shown": shown, "ok": ok}
        )
        with pytest.raises(bridge.BridgeError, match="runs already"):
            bridge.start(root)
    finally:
        manifest = bridge.end(root)
    assert ok and shown.startswith("We ship to Chennai")
    assert manifest is not None and manifest["ended"] >= manifest["started"]
    assert manifest["tester_sessions"] == ["tester-1"]
    assert manifest["model_sessions"] == []
    assert "config.json" in manifest["config_sha256"]
    folder = Path(cur["dir"])
    assert not (root / ".verbatim-relay" / "current.json").exists()
    assert "toy shop agent: ready" in (folder / "app.log").read_text()
    report = audit(folder / "tap.jsonl", folder / "relay.jsonl")
    assert (report.exit, report.turns, report.exchanges) == (0, 1, 1)
    # The last step of the end seals the folder, with a copy outside the project.
    assert seal.verify(folder)["intact"] and seal.verify(folder)["copy"] == "same"
    assert bridge.end(root) is None


def test_history_is_the_ok_turns_of_the_test(tmp_path: Path) -> None:
    relay = tmp_path / "relay.jsonl"
    w = Writer(relay)
    w.append({"type": "turn", "harness": "codex", "said": "a\u2028", "shown": "b", "ok": True})
    w.append({"type": "turn", "harness": "codex", "said": "c", "shown": "error", "ok": False})
    assert bridge.history(relay) == [("a\u2028", "b")]


def test_an_invalid_relay_record_is_an_error(tmp_path: Path) -> None:
    relay = tmp_path / "relay.jsonl"
    Writer(relay).append(
        {"type": "turn", "harness": "codex", "said": "a", "shown": "b", "ok": True}
    )
    relay.write_text(relay.read_text(encoding="utf-8").replace('"b"', '"c"'), encoding="utf-8")
    with pytest.raises(RecordError, match=r"relay\.jsonl: line 1: field shown_sha256"):
        bridge.history(relay)
    text = bridge.summary({"test": "t", "dir": str(tmp_path), "ended": 1.0})
    assert text.startswith("Test t ended: an invalid relay record (")
    assert bridge.history(tmp_path / "no-such.jsonl") == []


def test_a_stale_current_file_is_removed(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    current = root / ".verbatim-relay" / "current.json"
    current.write_text(json.dumps({"test": "x", "pid": dead.pid, "dir": "", "tap_url": ""}))
    assert bridge.current(root) is None
    assert not current.exists()


def test_a_live_process_that_is_not_the_bridge_gets_no_signal(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    other = subprocess.Popen(["sleep", "60"])
    try:
        current = root / ".verbatim-relay" / "current.json"
        real = bridge.process_start(other.pid)
        assert real
        cur = {"test": "x", "pid": other.pid, "dir": str(tmp_path), "tap_url": ""}
        # A file of an earlier version has no pid_start. A pid that the OS gave again has a
        # different start time.
        for start in ({}, {"pid_start": "ps:Thu Jan 1 00:00:00 1970"}):
            current.write_text(json.dumps({**cur, **start}))
            assert bridge.end(root, wait=1) is None
            assert not current.exists()
            current.write_text(json.dumps({**cur, **start}))
            assert bridge.current(root) is None
            assert not current.exists()
        assert other.poll() is None
        # The same process with its own start time is a bridge for current().
        current.write_text(json.dumps({**cur, "pid_start": real}))
        assert bridge.current(root) is not None
    finally:
        other.kill()
        other.wait()


def test_a_pid_that_changes_owner_after_the_check_gets_no_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    other = subprocess.Popen(["sleep", "60"])
    try:
        # current() saw the bridge, and then the OS gave its pid to another process.
        cur = {"test": "x", "pid": other.pid, "pid_start": "ps:old", "dir": str(tmp_path)}
        monkeypatch.setattr(bridge, "current", lambda root: cur)
        bridge.end(root, wait=1)
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_an_entry_that_exits_at_start_is_reported(tmp_path: Path, homes: tuple) -> None:
    script = "import sys; print('no toy shop database', file=sys.stderr); sys.exit(1)"
    root = project(tmp_path, [sys.executable, "-c", script])
    with pytest.raises(bridge.BridgeError, match="no toy shop database"):
        bridge.start(root)
    assert bridge.current(root) is None


def test_no_entry_is_an_error(tmp_path: Path) -> None:
    root = project(tmp_path, [])
    with pytest.raises(bridge.BridgeError, match="no 'entry'"):
        bridge.start(root)


def test_check_finds_the_model_sessions_of_the_app(tmp_path: Path, homes: tuple) -> None:
    script = tmp_path / "app.py"
    script.write_text(FIXTURE_APP)
    root = project(tmp_path, [sys.executable, str(script)], ["claude-code", "codex"])
    passed, lines = bridge.check(root)
    assert passed, lines
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    found = {(s["harness"], s["session"], s["inferred"]) for s in manifest["model_sessions"]}
    assert ("claude-code", CLAUDE_SID, False) in found
    assert ("codex", APP_THREAD, True) in found
    assert (folder / "sessions" / "claude-code" / f"{CLAUDE_SID}.jsonl").exists()
    rows = [json.loads(x) for x in (folder / "tap.jsonl").read_text().split("\n") if x]
    assert sum(r["type"] == "model_session" for r in rows) >= 2
    assert audit(folder / "tap.jsonl", folder / "relay.jsonl").exit == 0
    assert json.loads((folder / "audit.json").read_text())["exit"] == 0
    # The fixture files have no items and no version (SPEC.md section 8). `check` has no tester
    # session, so it also takes the tester rollout of the fixture.
    assert (folder / "trace.jsonl").read_text() == ""
    findings = json.loads((folder / "findings.json").read_text())
    assert findings["turns"] == 1
    assert {s["version"] for s in findings["sessions"]} == {"unknown"}
    assert findings["counts"]["version_untested"] == len(manifest["model_sessions"])
    assert findings["counts"]["session_inferred"] == len(manifest["model_sessions"]) - 1
    assert findings["counts"]["turn_without_model"] == 0


def test_the_tester_thread_is_not_an_app_session(tmp_path: Path, homes: tuple) -> None:
    script = tmp_path / "app.py"
    script.write_text(FIXTURE_APP)
    root = project(tmp_path, [sys.executable, str(script)], ["codex"])
    # As with codex exec, the prompt that ends the test is a new session: the tester thread of
    # the fixture. The kit passes it to the bridge (SPEC.md section 7.2).
    events = [
        {"hook_event_name": "UserPromptSubmit", "prompt": p, "session_id": sid}
        for p, sid in (
            ("verbatim-relay start", "tester-start"),
            ("Is the teapot in stock?", "tester-start"),
            ("verbatim-relay end", TESTER_THREAD),
        )
    ]
    answers = [kit.handle(e, root, "codex") for e in events]
    assert all(a and a["decision"] == "block" for a in answers[:2])
    assert "started" in answers[0]["reason"]
    # The end prompt goes on to the model, with the evaluation.
    assert "Evaluate test" in answers[2]["hookSpecificOutput"]["additionalContext"]
    assert not (root / ".verbatim-relay" / bridge.ENDING).exists()
    folder = bridge.latest_test(root)
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text())
    assert TESTER_THREAD in manifest["tester_sessions"]
    threads = [s["session"] for s in manifest["model_sessions"] if s["harness"] == "codex"]
    assert threads == [APP_THREAD]


def test_check_fails_without_a_model_session(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)], ["claude-code"])
    passed, lines = bridge.check(root)
    assert not passed
    assert any("No claude-code model session" in line for line in lines)


def test_check_gives_the_fix_for_logs_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The tap error of an entry that writes its logs on stdout (tests/test_contract.py makes it).
    error = (
        "the agent printed 3 lines on stdout but no reply line for m-1 in 240 s, so the tap "
        f"stopped it. {stdio.STRAY_HINT} The first line: 'toy shop: loading catalog'"
    )
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    folder = tmp_path / "test"
    folder.mkdir()
    monkeypatch.setattr(bridge, "start", lambda root: {"test": "t-1", "dir": str(folder)})
    monkeypatch.setattr(
        bridge, "send", lambda cur, said: (f"verbatim-relay: HTTP 504: {error}", False)
    )
    monkeypatch.setattr(bridge, "end", lambda root: {})
    # The tap wrote an unparsed row for each stray line, so the audit exits with 2.
    detail = "line 1: STDIO stdout: a stray line on stdout: 'toy shop: loading catalog'"
    row = {"class": "tap_unparsed", "record": "tap", "detail": detail}
    (folder / "audit.json").write_text(json.dumps({"exit": 2, "breaks": [], "errors": [row]}))
    passed, lines = bridge.check(root)
    assert not passed
    assert lines[-2:] == [
        "FAIL: The entry printed lines on stdout, but no reply line. " + stdio.STRAY_HINT,
        f"FAIL: tap_unparsed: tap {detail}. {stdio.STRAY_HINT}",
    ]


# An entry that prints a log line on stdout and then replies (#90). The reply comes, but the tap
# writes an unparsed row for the log line, so the audit of each real test exits with 2.
LOG_ON_STDOUT_APP = """
import json, sys
print("toy shop: loading catalog", flush=True)
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    out = {"v": 1, "id": request["id"], "reply": "Toy shop: " + request["message"]}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_check_fails_if_the_entry_logs_on_stdout_and_then_replies(
    tmp_path: Path, homes: tuple
) -> None:
    script = tmp_path / "app.py"
    script.write_text(LOG_ON_STDOUT_APP)
    root = project(tmp_path, [sys.executable, str(script)])
    passed, lines = bridge.check(root)
    assert not passed, lines
    assert "Reply: Toy shop: " + bridge.CHECK_MESSAGE in lines
    assert "Audit: exit 2" in lines
    stray = "a stray line on stdout: 'toy shop: loading catalog'. " + stdio.STRAY_HINT
    assert [line for line in lines if line.startswith("FAIL")] == [
        f"FAIL: tap_unparsed: tap line 1: STDIO stdout: {stray}"
    ]


def test_a_clean_entry_passes_the_check(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    passed, lines = bridge.check(root)
    assert passed, lines
    assert lines[-2:] == ["Audit: exit 0", "PASS"]


def test_check_fails_closed_without_a_valid_audit(tmp_path: Path) -> None:
    missing = "The audit.json of the test is missing. Read bridge.log in the test folder."
    assert bridge.audit_problems(tmp_path) == (None, [missing])
    for text in ("{", "[]", '{"exit": 0}', '{"exit": true, "breaks": [], "errors": []}'):
        (tmp_path / "audit.json").write_text(text)
        code, problems = bridge.audit_problems(tmp_path)
        assert code is None, text
        assert len(problems) == 1, text
        assert problems[0].startswith("The audit.json of the test is not valid"), text


def test_check_names_each_break_with_its_fix(tmp_path: Path) -> None:
    assert set(bridge.BREAK_FIX) == set(CHECKS)
    breaks = [
        {"class": "not_delivered", "relay_line": 1, "tap_line": None, "evidence": {}},
        {"class": "injected_input", "relay_line": None, "tap_line": 2, "evidence": {}},
    ]
    (tmp_path / "audit.json").write_text(json.dumps({"exit": 1, "breaks": breaks, "errors": []}))
    assert bridge.audit_problems(tmp_path) == (
        1,
        [
            "not_delivered break (relay line 1, tap line -). " + bridge.BREAK_FIX["not_delivered"],
            "injected_input break (relay line -, tap line 2). "
            + bridge.BREAK_FIX["injected_input"],
        ],
    )


def test_the_watcher_takes_only_processes_of_the_entry(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    parent = subprocess.Popen(
        [sys.executable, "-c", "import subprocess, sys; subprocess.run(['sleep', '30'])"]
    )
    try:
        child = None
        for _ in range(50):
            child = next(iter(bridge.descendants(parent.pid) - {parent.pid}), None)
            if child:
                break
            time.sleep(0.1)
        assert child is not None
        (sessions / f"{child}.json").write_text(json.dumps({"pid": child, "sessionId": "app"}))
        other = os.getpid()
        (sessions / f"{other}.json").write_text(json.dumps({"pid": other, "sessionId": "tester"}))
        (sessions / "partial.json").write_text('{"pid": ')
        watcher = bridge.ClaudeWatcher(parent.pid, Writer(tmp_path / "tap.jsonl"), sessions)
        watcher.poll()
        watcher.poll()
    finally:
        parent.kill()
    assert watcher.found == {"app": child}
    rows = (tmp_path / "tap.jsonl").read_text().split("\n")
    assert len([r for r in rows if r]) == 1


def test_codex_sessions_match_project_time_and_tester(tmp_path: Path) -> None:
    root = tmp_path / "shop"
    (root / "api").mkdir(parents=True)
    base = tmp_path / "sessions"
    day = base / time.strftime("%Y/%m/%d")
    day.mkdir(parents=True)

    def rollout(name: str, sid: str, cwd: Path, old: bool = False) -> None:
        f = day / f"rollout-{name}.jsonl"
        meta = {"type": "session_meta", "payload": {"id": sid, "cwd": str(cwd)}}
        f.write_text(json.dumps(meta) + "\n")
        if old:
            os.utime(f, (time.time() - 3600, time.time() - 3600))

    rollout("app", "app", root / "api")
    rollout("tester", "tester", root)
    rollout("elsewhere", "elsewhere", tmp_path)
    rollout("old", "old", root, old=True)
    (day / "rollout-broken.jsonl").write_text("not json\n")
    now = time.time()
    found = bridge.codex_sessions(root, now - 60, now + 1, {"tester"}, base)
    assert [meta["id"] for _, meta in found] == ["app"]


def test_kit_without_a_test_fails_closed(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    kit.set_mode(root, True)
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "Hi", "session_id": "s1"}
    answer = kit.handle(event, root, "claude-code")
    assert answer is not None and answer["decision"] == "block"
    assert "no test runs" in answer["reason"]


@pytest.mark.parametrize(
    ("tool", "tool_input", "denied"),
    [
        ("Write", {"file_path": ".verbatim-relay/entry.py", "content": "x"}, True),
        ("apply_patch", {"input": "*** Update File: .verbatim-relay/config.json"}, True),
        ("Bash", {"command": "cat .verbatim-relay/config.json"}, True),
        ("Read", {"file_path": ".verbatim-relay/config.json"}, False),
        ("Write", {"file_path": "shop/orders.py", "content": "x"}, False),
        ("Bash", {"command": "curl -s {tap_url}"}, True),
        ("Bash", {"command": "ls"}, False),
    ],
)
def test_kit_protects_the_test(
    tmp_path: Path, homes: tuple, tool: str, tool_input: dict, denied: bool
) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    kit.init(root, "claude-code", kit.Config(entry=[sys.executable, str(TOY_SHOP)]))
    cur = bridge.start(root)
    try:
        text = json.loads(json.dumps(tool_input).replace("{tap_url}", cur["tap_url"]))
        event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": text}
        answer = kit.handle(event, root, "claude-code")
    finally:
        bridge.end(root)
    assert (answer is not None) == denied


def test_view_follows_the_latest_test(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    kit.init(root, "claude-code", kit.Config(entry=[sys.executable, str(TOY_SHOP)]))
    for prompt in ("verbatim-relay start", "Refund policy?", "verbatim-relay end"):
        event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "session_id": "s1"}
        kit.handle(event, root, "claude-code")
    out = io.StringIO()
    kit.view_tests(root, False, out)
    text = out.getvalue()
    assert text.startswith("════ test ")
    assert "Refund policy?\n──── agent ────\nOur refund policy:" in text


def test_the_latest_test_is_the_one_that_started_last(tmp_path: Path) -> None:
    tests = tmp_path / ".verbatim-relay" / "tests"
    # The same second: the random part puts the older test last by name.
    for name, started in (("20261006-080000-ffff", 1.0), ("20261006-080000-0000", 2.0)):
        (tests / name).mkdir(parents=True)
        (tests / name / "manifest.json").write_text(json.dumps({"started": started}))
    assert bridge.latest_test(tmp_path) == tests / "20261006-080000-0000"
    # A folder with no manifest yet is a test that starts now.
    (tests / "20261006-075959-aaaa").mkdir()
    assert bridge.latest_test(tmp_path) == tests / "20261006-075959-aaaa"


# A toy shop app with OpenTelemetry: for each message, it sends one span to the endpoint that the
# bridge gives it, with a personal attribute that the receiver must remove.
OTEL_APP = """
import json, os, sys, time, urllib.request

url = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] + "/v1/traces"
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    now = time.time_ns()
    attrs = [
        {"key": "shop.sku", "value": {"stringValue": "teapot-set"}},
        {"key": "user.email", "value": {"stringValue": "tester@example.com"}},
    ]
    span = {"traceId": "0af7651916cd43dd8448eb211c80319c", "spanId": "b7ad6b7169203331",
            "name": "check_stock", "startTimeUnixNano": str(now), "endTimeUnixNano": str(now),
            "attributes": attrs}
    res = {"attributes": [{"key": "service.name", "value": {"stringValue": "toy-shop"}}]}
    body = {"resourceSpans": [{"resource": res, "scopeSpans": [{"spans": [span]}]}]}
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()
    out = {"v": 1, "id": request["id"], "reply": "3 teapot sets left."}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_the_receiver_records_the_app_spans(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, "-c", OTEL_APP])
    cur = bridge.start(root, "tester-1")
    try:
        shown, ok = bridge.send(cur, "Do you have the teapot set?")
    finally:
        bridge.end(root)
    assert ok and shown == "3 teapot sets left."
    folder = Path(cur["dir"])
    rows = [json.loads(x) for x in (folder / "otel.jsonl").read_text().splitlines()]
    assert [(r["type"], r["service"], r["name"]) for r in rows] == [
        ("span", "toy-shop", "check_stock")
    ]
    assert "example.com" not in (folder / "otel.jsonl").read_text()
    items = [json.loads(x) for x in (folder / "trace.jsonl").read_text().splitlines()]
    assert [(it["kind"], it["turn"], it["source"]["file"]) for it in items] == [
        ("span", 1, "otel.jsonl")
    ]
    assert seal.verify(folder)["intact"]


def test_otel_false_starts_no_receiver(tmp_path: Path, homes: tuple) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    config = root / ".verbatim-relay" / "config.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "otel": False}))
    cur = bridge.start(root, "tester-1")
    try:
        bridge.send(cur, "Hi")
    finally:
        bridge.end(root)
    assert not (Path(cur["dir"]) / "otel.jsonl").exists()
    assert "OTLP receiver" not in (Path(cur["dir"]) / "bridge.log").read_text()


# A toy shop app that asks its stock service for each message. It reads the URL from STOCK_URL.
STOCK_APP = """
import json, os, sys, urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    with urllib.request.urlopen(os.environ["STOCK_URL"] + "/stock?sku=teapot-set", timeout=5) as r:
        left = json.loads(r.read())["left"]
    out = {"v": 1, "id": request["id"], "reply": f"{left} teapot sets left."}
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
"""


def test_the_proxy_records_the_backend_calls(tmp_path: Path, homes: tuple) -> None:
    from toy_stock_server import StockServer

    root = project(tmp_path, [sys.executable, "-c", STOCK_APP])
    config = root / ".verbatim-relay" / "config.json"
    with StockServer() as stock:
        backends = [{"name": "stock", "env": "STOCK_URL", "url": stock.url}]
        config.write_text(json.dumps({**json.loads(config.read_text()), "backends": backends}))
        cur = bridge.start(root, "tester-1")
        try:
            shown, ok = bridge.send(cur, "Do you have the teapot set?")
        finally:
            bridge.end(root)
    assert ok and shown == "3 teapot sets left."
    folder = Path(cur["dir"])
    items = [json.loads(x) for x in (folder / "trace.jsonl").read_text().splitlines()]
    assert [(it["kind"], it["turn"], it["name"], it["exit_code"]) for it in items] == [
        ("http", 1, "GET /stock", 200)
    ]
    assert seal.verify(folder)["intact"]


MODEL_APP = """
import json, os, sys, urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    ask = {"model": "claude-toy", "stream": True, "messages": [
        {"role": "user", "content": request["message"]}]}
    call = urllib.request.Request(
        os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", data=json.dumps(ask).encode(),
        headers={"x-api-key": "sk-toy-k3y", "content-type": "application/json"})
    with urllib.request.urlopen(call, timeout=5) as r:
        lines = r.read().decode().split("\\n")
    events = [json.loads(x[6:]) for x in lines if x.startswith("data: ")]
    deltas = [e["delta"] for e in events if e["type"] == "content_block_delta"]
    text = "".join(d.get("text", "") for d in deltas)
    sys.stdout.write(json.dumps({"v": 1, "id": request["id"], "reply": text}) + "\\n")
    sys.stdout.flush()
"""


def test_the_proxy_records_the_direct_model_calls(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_model_api import STREAM
    from toy_model_server import ModelServer

    root = project(tmp_path, [sys.executable, "-c", MODEL_APP])
    with ModelServer() as model:
        model.parts = STREAM
        monkeypatch.setenv("ANTHROPIC_BASE_URL", model.url)
        cur = bridge.start(root, "tester-1")
        try:
            shown, ok = bridge.send(cur, "Do you have the teapot set?")
        finally:
            bridge.end(root)
    assert ok and shown == "3 teapot sets € left."
    folder = Path(cur["dir"])
    assert "k3y" not in (folder / "model_api.jsonl").read_text()
    items = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    assert [(it["kind"], it["turn"], it["role"], it["output"]) for it in items] == [
        ("message", 1, "user", "Do you have the teapot set?"),
        ("message", 1, "assistant", "3 teapot sets € left."),
    ]
    assert seal.verify(folder)["intact"]


def test_a_bad_model_api_config_stops_the_start(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    config = root / ".verbatim-relay" / "config.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "model_api": ["toy"]}))
    with pytest.raises(bridge.BridgeError, match="'model_api' must be"):
        bridge.start(root)


def test_a_bad_backend_config_stops_the_start(tmp_path: Path) -> None:
    root = project(tmp_path, [sys.executable, str(TOY_SHOP)])
    config = root / ".verbatim-relay" / "config.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "backends": [{"name": "x"}]}))
    with pytest.raises(bridge.BridgeError, match="'name', 'env' and 'url'"):
        bridge.start(root)


def test_an_invalid_relay_record_infers_no_codex_session(tmp_path: Path, homes: tuple) -> None:
    # Without the tester sessions of relay.jsonl, a tester rollout looks like an app session.
    script = tmp_path / "app.py"
    script.write_text(FIXTURE_APP)
    root = project(tmp_path, [sys.executable, str(script)], ["codex"])
    cur = bridge.start(root, "tester-start")
    folder = Path(cur["dir"])
    (folder / "relay.jsonl").write_text("not json\n", encoding="utf-8")
    time.sleep(0.5)
    bridge.end(root, wait=10)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert [s for s in manifest["model_sessions"] if s["harness"] == "codex"] == []
    assert not (folder / "sessions" / "codex").exists()
    log = (folder / "bridge.log").read_text(encoding="utf-8")
    assert "the relay record is invalid, so the test infers no Codex session" in log

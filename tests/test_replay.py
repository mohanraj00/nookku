"""Replay a script and show the changed replies side by side (#351, SPEC.md section 7.10)."""

from __future__ import annotations

import http.client
import json
import re
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nookku import bridge, kit, page, policy, replay, script_save
from nookku.cli import main
from nookku.record import Writer

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
OLD, NEW = "20261013-090000-aa11", "20261013-091000-bb22"
# Each turn: the said text, the tap reply and the relay shown text.
TURNS = [
    ("Do you ship to Chennai?", "We ship to Chennai and Pune.", "We ship to Chennai and Pune."),
    ("Is the teapot € 24?", "Yes, the teapot is € 24.", "Yes, the teapot is € 24."),
    ("Thanks.", "You are welcome.", "You are welcome."),
]


def make_test(
    root: Path, test: str, turns: list[tuple[str, str | None, str]], start: float
) -> Path:
    folder = root / ".nookku" / "tests" / test
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"started": start, "ended": start + 60}))
    relay, tap = Writer(folder / "relay.jsonl"), Writer(folder / "tap.jsonl")
    for said, reply, shown in turns:
        # A null reply is an agent error, with a status that is not 2xx (SPEC.md section 2.1).
        status = 200 if reply is not None else 500
        tap.append({"type": "exchange", "input": said, "status": status, "reply": reply})
        relay.append({"type": "turn", "harness": "pane", "said": said, "shown": shown, "ok": True})
    return folder


def pair(root: Path, new: list[tuple[str, str | None, str]]) -> dict[str, Any]:
    old_folder = make_test(root, OLD, TURNS, 1_800_000_000.0)
    new_folder = make_test(root, NEW, new, 1_800_000_600.0)
    return replay.diff(root, old_folder, new_folder)


def joined(parts: list[list[str]], keep: str) -> str:
    return "".join(text for op, text in parts if op in ("equal", keep))


def test_two_records_with_equal_replies_have_no_changed_turn(tmp_path: Path) -> None:
    result = pair(tmp_path, TURNS)
    assert result["error"] is None
    assert result["changed"] == 0
    assert len(result["turns"]) == 3
    assert all(not t["changed"] and not t["said_changed"] for t in result["turns"])
    assert [t["words"] for t in result["turns"]] == [[["equal", r]] for _, r, _ in TURNS]
    assert (result["old"]["id"], result["new"]["id"]) == (OLD, NEW)


def test_one_changed_reply_gives_one_changed_turn_and_its_words(tmp_path: Path) -> None:
    new = list(TURNS)
    new[1] = (TURNS[1][0], "No, the teapot is € 26 now.", "No, the teapot is € 26 now.")
    result = pair(tmp_path, new)
    assert result["changed"] == 1
    changed = [t for t in result["turns"] if t["changed"]]
    assert [t["n"] for t in changed] == [2]
    words = changed[0]["words"]
    assert [p for p in words if p[0] != "equal"] == [
        ["delete", "Yes,"],
        ["insert", "No,"],
        ["delete", "24."],
        ["insert", "26 now."],
    ]
    # The equal and deleted parts give the old reply, and the equal and inserted parts the new.
    assert joined(words, "delete") == TURNS[1][1]
    assert joined(words, "insert") == new[1][1]


def test_a_long_reply_gives_a_diff_with_no_long_wait() -> None:
    common = " ".join(["the blue mug"] * 3000)
    # One changed word in a long reply: the equal start and end need no matcher.
    parts = replay.words(common + " costs 8.", common + " costs 9.")
    assert [p for p in parts if p[0] != "equal"] == [["delete", "8."], ["insert", "9."]]
    # A changed part with more than MAX_TOKENS tokens is one delete and one insert.
    old = " ".join(["mug teapot"] * replay.MAX_TOKENS)
    new = " ".join(["teapot mug"] * replay.MAX_TOKENS)
    parts = replay.words("Hi. " + old + " Bye.", "Hi. " + new + " Bye.")
    assert [p[0] for p in parts] == ["equal", "delete", "insert", "equal"]
    assert joined(parts, "delete") == "Hi. " + old + " Bye."
    assert joined(parts, "insert") == "Hi. " + new + " Bye."


def test_the_diff_uses_the_tap_reply_not_the_shown_text(tmp_path: Path) -> None:
    new = list(TURNS)
    # The relay showed other text, but the agent sent the same reply: no change.
    new[0] = (TURNS[0][0], TURNS[0][1], "A changed shown text.")
    # The agent sent another reply, but the relay showed the old text: a change.
    new[2] = (TURNS[2][0], "You are welcome!", TURNS[2][2])
    result = pair(tmp_path, new)
    assert [t["n"] for t in result["turns"] if t["changed"]] == [3]
    assert result["turns"][2]["reply_new"] == "You are welcome!"


def test_a_different_count_of_turns_gives_a_changed_turn_for_each_extra_turn(
    tmp_path: Path,
) -> None:
    extra = ("Do you sell cups?", "Yes, blue cups.", "Yes, blue cups.")
    result = pair(tmp_path, [*TURNS, extra])
    assert result["changed"] == 1
    last = result["turns"][3]
    assert last["changed"] and last["said_old"] is None and last["reply_old"] is None
    assert last["said_new"] == extra[0]
    assert last["words"] == [["insert", extra[1]]]
    # And in the other direction: the old test has more turns.
    shorter = replay.diff(
        tmp_path, tmp_path / ".nookku" / "tests" / OLD, tmp_path / ".nookku" / "tests" / NEW
    )
    assert shorter["changed"] == 1
    fewer = replay.diff(
        tmp_path, tmp_path / ".nookku" / "tests" / NEW, tmp_path / ".nookku" / "tests" / OLD
    )
    assert fewer["turns"][3]["said_new"] is None
    assert fewer["turns"][3]["words"] == [["delete", extra[1]]]


def test_a_null_reply_and_a_missing_exchange_have_no_reply(tmp_path: Path) -> None:
    new = list(TURNS)
    new[0] = (TURNS[0][0], None, "nookku: the agent sent no reply")
    result = pair(tmp_path, new)
    assert result["turns"][0]["reply_new"] is None and result["turns"][0]["changed"]
    # A turn with no tap exchange.
    folder = tmp_path / ".nookku" / "tests" / OLD
    Writer(folder / "relay.jsonl").append(
        {"type": "turn", "harness": "pane", "said": "Lost?", "shown": "x", "ok": True}
    )
    assert replay.replies(folder)[-1] == ("Lost?", None)


def test_the_report_names_the_test_with_no_reply_next_to_an_empty_reply(tmp_path: Path) -> None:
    new = list(TURNS)
    new[0] = (TURNS[0][0], None, "nookku: the agent sent no reply")
    old_folder = make_test(tmp_path, OLD, [(TURNS[0][0], "", "")], 1_800_000_000.0)
    new_folder = make_test(tmp_path, NEW, new[:1], 1_800_000_600.0)
    lines, data = replay.report(tmp_path, old_folder, new_folder)
    # An empty reply and no reply give the same empty word diff, but the turn changed.
    assert data["diff"]["changed"] == 1 and data["diff"]["turns"][0]["words"] == []
    assert f"Turn 1: test {NEW} has no reply in the tap record." in lines
    assert not any(OLD in line and "no reply" in line for line in lines)


def test_an_invalid_record_gives_an_error_and_no_turns(tmp_path: Path) -> None:
    pair(tmp_path, TURNS)
    folder = tmp_path / ".nookku" / "tests" / NEW
    with (folder / "tap.jsonl").open("a") as f:
        f.write("not json\n")
    result = replay.diff(tmp_path, tmp_path / ".nookku" / "tests" / OLD, folder)
    assert result["turns"] == [] and result["changed"] is None
    assert result["error"].startswith("nookku: ")


def test_the_answer_finds_each_test_only_by_a_folder_name(tmp_path: Path) -> None:
    pair(tmp_path, TURNS)
    status, data = replay.answer(tmp_path, f"api/diff/{OLD}/{NEW}")
    assert status == 200 and data["changed"] == 0
    for rest in (
        "api/diff",
        f"api/diff/{OLD}",
        f"api/diff/{OLD}/{NEW}/x",
        f"api/diff/{OLD}/..",
        f"api/diff/{OLD}/..%2F..%2Fx",
        f"api/diff/{OLD}/unknown",
    ):
        assert replay.answer(tmp_path, rest)[0] == 404, rest


def get(
    srv: page.PageServer, rest: str, headers: dict[str, str] | None = None, token: str = ""
) -> tuple[int, dict[str, str], bytes]:
    port = srv.server_address[1]
    sent = {"Host": f"127.0.0.1:{port}"} | (headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("GET", f"/p/{token or srv.token}/{rest}", headers=sent)
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def _decision(root: Path, command: str) -> str | None:
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }
    answer = kit.handle(event, root, "claude-code")
    return None if answer is None else answer["hookSpecificOutput"]["permissionDecision"]


@pytest.fixture
def server(tmp_path: Path) -> Iterator[page.PageServer]:
    pair(tmp_path, TURNS)
    srv = page.PageServer(tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_page_serves_the_diff_with_the_checks_of_the_page(server: page.PageServer) -> None:
    status, headers, body = get(server, f"api/diff/{OLD}/{NEW}")
    assert status == 200 and json.loads(body)["changed"] == 0
    assert headers["content-security-policy"] == page.CSP
    for name in ("diff.html", "diff.js", "diff.css", "compare.js"):
        status, headers, _ = get(server, name)
        assert status == 200 and headers["content-security-policy"] == page.CSP
    assert get(server, f"api/diff/{OLD}/{NEW}", token="wrong")[0] == 404
    assert get(server, f"api/diff/{OLD}/{NEW}", {"Host": "evil.test"})[0] == 403
    assert get(server, f"api/diff/{OLD}/{NEW}", {"Origin": "http://evil.test"})[0] == 403
    assert get(server, f"api/diff/{OLD}/nope")[0] == 404


def test_the_diff_page_has_no_inline_script_and_no_html_from_text() -> None:
    html = page.page_file("diff.html").decode()
    assert re.findall(r"<script[^>]*>", html) == [
        '<script src="theme.js">',
        '<script src="diff.js" defer>',
        '<script src="keys.js" defer>',
    ]
    assert not re.search(r"\son\w+=", html) and "style=" not in html
    for name in ("diff.html", "diff.js", "diff.css", "compare.js"):
        text = page.page_file(name).decode()
        assert not re.search(r"https?://", text), name
        for sink in ("innerHTML", "insertAdjacentHTML", "outerHTML"):
            assert sink not in text, name
    # An answer for an old hash does not replace the diff of the current hash.
    assert "if (hash !== window.location.hash)" in page.page_file("diff.js").decode()


def test_the_guard_denies_a_model_replay_with_each_policy(tmp_path: Path) -> None:
    for value in ("person", "model"):
        policy.set_key(tmp_path, "scripts", value)
        for command in ("nookku replay a.jsonl", "uv run nookku replay --json a.jsonl"):
            assert _decision(tmp_path, command) == "deny", (value, command)


def test_an_unknown_base_runs_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".nookku").mkdir()
    code = main(["replay", "a.jsonl", "--base", "nope", "--root", str(tmp_path)])
    assert code == 2
    assert "no test has the id 'nope'" in capsys.readouterr().out
    assert not (tmp_path / ".nookku" / "tests").exists()


@pytest.fixture
def homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))


def _config(root: Path, agent: Path) -> None:
    conf = {"entry": [sys.executable, str(agent)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))


def test_a_replay_after_a_change_to_one_toy_shop_reply_shows_one_changed_turn(
    tmp_path: Path, homes: None, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "shop"
    (root / ".nookku").mkdir(parents=True)
    _config(root, TOY_SHOP)
    first = tmp_path / "first.jsonl"
    messages = ["What is your refund policy?", "Do you ship to Chennai?", "What is the price?"]
    first.write_text("".join(json.dumps({"said": m}) + "\n" for m in messages))
    passed, lines, old = bridge.run_script(root, first)
    assert passed, lines
    path, _ = script_save.save(root, old.name)
    # The fix: the toy agent now gives another shipping time. The other replies stay the same.
    fixed = tmp_path / "agent.py"
    source = TOY_SHOP.read_text()
    assert source.count("3 to 5 days") == 1
    fixed.write_text(source.replace("3 to 5 days", "2 to 4 days"))
    _config(root, fixed)
    capsys.readouterr()
    code = main(["replay", str(path), "--root", str(root), "--json", "--no-evaluate"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["pass"], out
    result = out["diff"]
    assert result["old"]["id"] == old.name and result["new"]["id"] != old.name
    assert result["changed"] == 1
    assert [t["n"] for t in result["turns"] if t["changed"]] == [2]
    words = [p for p in result["turns"][1]["words"] if p[0] != "equal"]
    assert words == [["delete", "3"], ["insert", "2"], ["delete", "5"], ["insert", "4"]]
    assert f"Replay of test {old.name}: 1 of 3 turns changed." in out["report"]
    marked = "We ship to Chennai and Pune. Delivery takes [-3-]{+2+} to [-5-]{+4+} days.  "
    assert f"Turn 2 reply: {marked}" in out["report"]
    # The text form gives the same lines, with the test ids to select on the dashboard.
    code = main(["replay", str(path), "--root", str(root), "--no-evaluate"])
    text = capsys.readouterr().out
    assert code == 0
    assert "1 of 3 turns changed." in text
    assert f"select tests {old.name} and " in text

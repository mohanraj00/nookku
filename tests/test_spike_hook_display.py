"""Checks of the spike's blocking fixtures and private request summaries. No model calls."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import spike_hook_display as spike


def test_responses_markers_name_the_input_role_and_do_not_keep_the_body() -> None:
    body = json.dumps(
        {
            "instructions": "private toy shop instructions",
            "input": [
                {"role": "user", "content": "prompt marker"},
                {"type": "function_call_output", "output": "reply marker"},
            ],
        }
    ).encode()
    result = spike.where(body, ("prompt marker", "reply marker", "absent marker"))
    assert result["found"] == {
        "prompt marker": ["input[0].user"],
        "reply marker": ["input[1].function_call_output"],
        "absent marker": [],
    }
    assert "private toy shop instructions" not in json.dumps(result)


def test_the_proxy_keeps_no_request_or_response_header_or_body() -> None:
    proxy = object.__new__(spike.CodexSpikeProxy)
    proxy.marks = ("toy marker",)
    row = {"response_headers": [["private", "private value"]], "response_body": "private reply"}
    proxy.describe(row, [("Authorization", "private key")], b'{"input":"toy marker"}')
    proxy.complete(row, b"private reply", None)
    assert row["request_headers"] is None
    assert row["response_headers"] is None
    assert row["response_body"] is None
    assert "private" not in json.dumps(row)
    assert row["request_body"]["found"]["toy marker"]


@pytest.mark.parametrize("desktop", [False, True])
@pytest.mark.parametrize("trailing", ["", "\n", "\r\n"])
def test_a_system_message_case_also_has_a_block_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, desktop: bool, trailing: str
) -> None:
    monkeypatch.setattr(spike, "ROOT", tmp_path)
    p = spike.codex_project({"systemMessage": "a toy shop reply"})
    prompt = "block: a toy shop question"
    if desktop:
        case = next(c for c in spike.desktop_plan() if c["fields"] == ["systemMessage"])
        prompt = case["blocked_prompt"]
        (p / "payload.json").write_text(
            json.dumps({"cases": {prompt: {"id": case["id"], "payload": case["payload"]}}})
        )
    proc = subprocess.run(
        [sys.executable, str(p / "hook.py"), str(p / "payload.json"), str(p / "receipt.jsonl")],
        input=json.dumps({"prompt": prompt + trailing}),
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(proc.stdout)
    assert output["decision"] == "block"
    assert output["reason"] == "Hook display control block."
    assert output["systemMessage"]
    assert "hookSpecificOutput" not in output
    receipt = json.loads((p / "receipt.jsonl").read_text())
    assert receipt["blocked"] is True
    if desktop:
        assert receipt["case"] == case["id"]
    assert prompt not in json.dumps(receipt)


def test_a_new_worktree_interpreter_does_not_replace_the_reviewed_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spike, "ROOT", tmp_path)
    project = spike.codex_project({"reason": "toy shop first reply"})
    source = project / ".codex" / "hooks.json"
    reviewed = source.read_bytes()
    script = (project / "hook.py").read_bytes()
    monkeypatch.setattr(spike.sys, "executable", str(tmp_path / "another-worktree/python"))
    assert spike.codex_project({"reason": "toy shop next reply"}) == project
    assert source.read_bytes() == reviewed
    assert (project / "hook.py").read_bytes() == script
    assert json.loads((project / "payload.json").read_text())["reason"] == "toy shop next reply"


@pytest.mark.parametrize("suffix", [b"", b"\n", b"\r\n"])
def test_a_desktop_copy_keeps_its_line_end_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: bytes
) -> None:
    reply = "DESK08-reason-START\nCafé 中文 😀\nDESK08-reason-END"
    monkeypatch.setattr(
        spike,
        "desktop_plan",
        lambda: [{"id": "DESK08", "fields": ["reason"], "payload": {"reason": reply}}],
    )
    (tmp_path / "DESK08-reason.txt").write_bytes(reply.encode("utf-8") + suffix)
    case = {"id": "DESK08", "copy_checks": {}}
    data = {"codex": {"desktop": {"cases": [case]}}}
    spike.codex_copy_checks(data, tmp_path)
    check = case["copy_checks"]["reason"]
    assert check["byte_exact"] is (suffix == b"")
    assert check["copied_bytes"] == len(reply.encode("utf-8")) + len(suffix)
    assert (
        check["copied_sha256"] == check["expected_sha256"]
        if not suffix
        else (check["copied_sha256"] != check["expected_sha256"])
    )

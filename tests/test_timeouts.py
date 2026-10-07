"""The timeouts on the relay path, in order: agent < tap answer < relay < hook deadline."""

import inspect
import json
import re
import time
from pathlib import Path

import pytest
from test_tap import post
from toy_agent import ToyAgent

from verbatim_relay import bridge, kit, stdio, tap
from verbatim_relay.adapters import make
from verbatim_relay.record import Exchange, read_tap

ROOT = Path(__file__).resolve().parent.parent
# The most time that a tap needs after the agent timeout to write its row and answer.
ANSWER = 5.0


@pytest.fixture
def agent():
    server = ToyAgent()
    yield server
    server.release.set()
    server.shutdown()


def test_each_timeout_ends_before_the_next_one() -> None:
    # One constant sets the agent timeout of both taps.
    assert inspect.signature(tap.Tap).parameters["timeout"].default == stdio.TIMEOUT
    assert inspect.signature(stdio.Agent).parameters["timeout"].default == stdio.TIMEOUT
    answer = stdio.TIMEOUT + ANSWER
    relay = [kit.TIMEOUT, bridge.TIMEOUT]
    assert stdio.TIMEOUT < answer < min(relay)
    assert max(relay) < kit.HOOK_DEADLINE


def test_the_plugin_sets_no_relay_timeout_of_its_own() -> None:
    # $.http.fetch has no timeout, and its time does not count against the hook budget. So the
    # plugin waits for the tap, and the tap answers after its agent timeout. If the plugin gets a
    # relay timeout, this test must compare it with the others.
    source = (ROOT / "plugins" / "claude-code" / "hooks" / "register.tsx").read_text()
    fetches = re.findall(r"\$\.http\.fetch\([^)]*\)", source, re.S)
    assert len(fetches) >= 2
    assert not any(re.search(r"timeout|signal", f, re.I) for f in fetches)


def test_a_slow_agent_gives_504_and_an_error_row(agent, tmp_path):
    timeout = 0.3
    t = tap.Tap(("127.0.0.1", 0), agent.url, tmp_path / "tap.jsonl", make("json"), timeout)
    tap.start_in_thread(t)
    began = time.monotonic()
    status, _, out = post(t, "/slow", b'{"text": "Where is my mug?"}')
    took = time.monotonic() - began
    agent.release.set()
    t.shutdown()

    assert status == 504
    assert json.loads(out)["error"] == "verbatim-relay tap: the agent sent no response in 0.3 s"
    assert timeout <= took < timeout + ANSWER
    assert read_tap(tmp_path / "tap.jsonl") == [Exchange(1, "Where is my mug?", None, None)]
    row = json.loads((tmp_path / "tap.jsonl").read_text())
    assert row["error"] == "the agent sent no response in 0.3 s"

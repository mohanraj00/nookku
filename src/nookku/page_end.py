"""The "End test" button of the chat page (#391, SPEC.md section 5, "End from the page").

The page ends the running test with the same steps as `nookku end` in a shell: relay mode goes
off, then the bridge stops, and the test gets its trace, its audit and its seal. The page starts
no evaluation, and its page server continues, so the tester can export the test and save it as a
script. The prompt `nookku end` in the harness starts the evaluation and stops the page server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nookku import bridge, kit, state
from nookku.record import id_problem

ROUTE = "api/end"
NO_TEST = "nookku: no test runs, so the page ended nothing."
OTHER_TEST = (
    "nookku: the page shows test {shown}, but the running test is {running}. The page ended "
    "nothing."
)
SCRIPTED = (
    "nookku: this test is a scripted test. nookku run ends it after the last message. The page "
    "ended nothing."
)
CHECK = "nookku: this test is a test of nookku check, which ends it. The page ended nothing."
SENDING = (
    "nookku: the page sends a message now. Wait for the reply, then end the test. The page ended "
    "nothing."
)
NOT_ENDED = "nookku: the test did not end. Try again, or run nookku end in a separate terminal."


def bad_body(data: Any) -> str | None:
    """The problem of the body of an end request, or None. The body names the shown test."""
    if not isinstance(data, dict) or not isinstance(data.get("test"), str):
        return 'the body needs the text "test"'
    found = id_problem(data["test"])
    return f'the "test" of the body has {found}' if found else None


def end(root: Path, test_id: str) -> dict[str, Any]:
    """End the running test if its id is test_id. Return what the page shows: `ended`, and the
    end text or the error. The caller holds the page lock, so no send of the page runs. A send of
    the harness can run: the end of the bridge waits for it, as for `nookku end` in a shell."""
    cur = state.current(root)
    if cur is None:
        return {"ended": False, "error": NO_TEST}
    if cur["test"] != test_id:
        return {"ended": False, "error": OTHER_TEST.format(shown=test_id, running=cur["test"])}
    manifest = state.manifest_of(Path(cur["dir"])) or {}
    if manifest.get("script") is not None:
        return {"ended": False, "error": SCRIPTED}
    if manifest.get("check") is True:
        return {"ended": False, "error": CHECK}
    # The steps of `nookku end` in a shell: relay mode off, then the end of the bridge. No
    # evaluation, and the chat page continues.
    kit.set_mode(root, False)
    ended = bridge.end(root, find_stopped=False, test=test_id)
    if ended is None:
        return {"ended": False, "error": _give_back_mode(root, test_id)}
    return {"ended": True, "text": bridge.summary(ended)}


def _give_back_mode(root: Path, test_id: str) -> str:
    """The end did not end test_id. If another test runs now, it started after the first check,
    and its start set relay mode on before this request set it off. Set relay mode on again, else
    a message of the harness of that test can reach the model. On is the safe side: with relay
    mode on, the hook sends each prompt of the tester to the relay. Return the error text."""
    now = state.current(root)
    if now is None or now["test"] == test_id:
        return NOT_ENDED
    kit.set_mode(root, True)
    return OTHER_TEST.format(shown=test_id, running=now["test"])

"""The trace steps and the time of each turn on the chat page (#353).

The page shows the trace rows of a turn under its reply (SPEC.md section 5, "Chat page"). A turn
of `relay.jsonl` gets the exchange of `tap.jsonl` that the audit pairs with it (SPEC.md section
3.2), and the trace rows of that exchange (SPEC.md section 8.3). After the end of a test, the rows
come from `trace.jsonl`. During a test, they come from the files that the proxies and the OTLP
receiver write live: `otel.jsonl`, `backend.jsonl` and `model_api.jsonl`. The harness session
files go into the test folder only at the end, so their rows show after the end.

The page server reads only the files of one test folder. The answer holds data of the agent: the
page puts it in with textContent, never as HTML.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from nookku import audit, backend, dashboard, evaluation, mcp_proxy, model_api, otlp, state, trace
from nookku.record import Exchange, RecordError, read_rows, turns

ROUTE = "api/trace"
TRACE = "trace.jsonl"
# The files that change the answer. The cache keeps the answer of a test folder while these
# files do not change.
SOURCES = (
    "manifest.json",
    "relay.jsonl",
    "tap.jsonl",
    TRACE,
    otlp.FILE,
    backend.FILE,
    model_api.FILE,
    mcp_proxy.FILE,
)
# The fields of a trace row that the page does not show.
HIDDEN = frozenset({"v", "type", "turn", trace.CALL_ID})

# The cache keeps the answers of the last few test folders only, so a page server that shows many
# tests does not keep all of their rows.
CACHE_SIZE = 4
_cache: dict[Path, tuple[Any, dict[str, Any]]] = {}
_lock = threading.Lock()


def _signature(folder: Path, running: bool) -> Any:
    out: list[Any] = [running]
    for name in SOURCES:
        try:
            st = (folder / name).stat()
            out.append((st.st_size, st.st_mtime_ns))
        except OSError:
            out.append(None)
    return tuple(out)


def built_after_end(folder: Path) -> bool:
    """True if the manifest has `ended` and trace.jsonl is newer than the manifest. The end writes
    `ended` into the manifest before it builds the trace. Thus a trace.jsonl from `nookku trace`
    before the end, or from an end whose build failed, is older than the manifest."""
    if (state.manifest_of(folder) or {}).get("ended") is None:
        return False
    try:
        return (folder / TRACE).stat().st_mtime_ns >= (folder / "manifest.json").stat().st_mtime_ns
    except OSError:
        return False


def items(folder: Path, spans: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """The trace rows of a test, each with its turn. If the end built trace.jsonl, the rows come
    from it. Else they come from the live sources, with the turn rule of SPEC.md section 8.3: for
    a running test, a test that stopped with no end, and an end whose build failed."""
    if built_after_end(folder):
        # The reader of the evaluation: it splits on \n only and stops at a bad line.
        return evaluation._items(folder / TRACE)
    found: list[dict[str, Any]] = []
    readers = ((otlp.FILE, trace.read_otel), (backend.FILE, trace.read_backend))
    more = ((model_api.FILE, trace.read_model_api), (mcp_proxy.FILE, trace.read_mcp))
    for name, reader in (*readers, *more):
        if (folder / name).exists():
            found += reader(folder / name)[0]
    found.sort(key=lambda it: it["ts"] if it["ts"] is not None else float("inf"))
    trace.assign(found, spans)
    return found


def _step(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in HIDDEN}


def steps(folder: Path, running: bool) -> dict[str, Any]:
    """The steps and the time of each turn of `relay.jsonl`, in the order of the page.

    `turns[i]` belongs to turn i + 1 of the page (`data-turn` on the page). `pending` holds the
    rows after the last exchange of a running test: the steps of a message that waits for its
    reply."""
    relay = turns(folder / "relay.jsonl", missing_ok=True)
    # One read of tap.jsonl, so that the rows and the exchanges agree while the tap writes.
    tap = read_rows("tap", folder / "tap.jsonl", missing_ok=True)
    lines = [(n, r) for n, r in tap if r["type"] == "exchange"]
    rows = [r for _, r in lines]
    exchanges = [Exchange(n, r["input"], r["status"], r["reply"]) for n, r in lines]
    spans = trace.windows(rows)
    found = items(folder, spans)
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for row in found:
        if isinstance(row.get("turn"), int):
            by_turn.setdefault(row["turn"], []).append(_step(row))
    matched = dict(audit.pairs(relay, exchanges)[0])
    out: list[dict[str, Any]] = []
    for i in range(len(relay)):
        j = matched.get(i)
        if j is None:
            out.append({"exchange": None, "started": None, "ended": None, "steps": []})
            continue
        started = rows[j].get("started")
        out.append(
            {
                "exchange": j + 1,
                "started": started if isinstance(started, (int, float)) else None,
                "ended": rows[j].get("ts"),
                "steps": by_turn.get(j + 1, []),
            }
        )
    pending: list[dict[str, Any]] = []
    if running:
        end = spans[-1][1] if spans else float("-inf")
        pending = [
            _step(r)
            for r in found
            if r.get("turn") is None and isinstance(r.get("ts"), (int, float)) and r["ts"] > end
        ]
    return {"turns": out, "pending": pending}


def _shown(root: Path, test_id: str | None) -> tuple[Path | None, bool]:
    """The test folder that the page shows, as `page.view` finds it, and True if it runs."""
    cur = state.current(root)
    folder = Path(cur["dir"]) if cur else state.latest_test(root)
    if test_id is not None:
        folder = dashboard.find(root, test_id)
    running = folder is not None and cur is not None and Path(cur["dir"]).name == folder.name
    return folder, running


def answer(root: Path, rest: str) -> tuple[int, dict[str, Any]]:
    """The status and the answer of `api/trace` (the shown test) or `api/trace/<test id>`."""
    test_id = unquote(rest[len(ROUTE) + 1 :]) if rest != ROUTE else None
    folder, running = _shown(root, test_id)
    if folder is None:
        error = "nookku: no test has this id." if test_id is not None else None
        empty: dict[str, Any] = {"test": None, "turns": [], "pending": [], "error": error}
        return (404 if test_id is not None else 200), empty
    sign = _signature(folder, running)
    with _lock:
        hit = _cache.get(folder)
    if hit is not None and hit[0] == sign:
        return 200, hit[1]
    try:
        data = {"test": folder.name, **steps(folder, running), "error": None}
    except (RecordError, OSError, UnicodeDecodeError) as e:
        return 200, {"test": folder.name, "turns": [], "pending": [], "error": f"nookku: {e}"}
    with _lock:
        _cache.pop(folder, None)
        _cache[folder] = (sign, data)
        while len(_cache) > CACHE_SIZE:
            del _cache[next(iter(_cache))]
    return 200, data

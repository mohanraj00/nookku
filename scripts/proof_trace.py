"""Proof that the trace reads real model sessions (SPEC.md section 8). Local only.

The entry is the toy shop app of tests/toy_models_entry.py: one Claude Agent SDK session and one
codex app-server thread. The test sends 4 messages. The trace must show each tool call with its
result or its error, in the correct turn. Each run makes about 8 model calls.

The results keep no model text: a message shows only its SHA-256 and its length. The tool
outputs come from the toy tools.

usage: python scripts/proof_trace.py [OUT_DIR]   (default proofs/trace)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from proof_sessions import ENTRY  # noqa: E402

from nooku import bridge  # noqa: E402

MESSAGES = [
    "Where is my order 4471?",
    "Where is my order 9999?",
    "Is the teapot in stock?",
    "Can I return a mug?",
]
# (harness, turn, kind, name, input, what the result must have)
EXPECT = [
    ("claude-code", 1, "tool_call", "lookup_order", {"order": "4471"}, ("output", "delivered")),
    ("claude-code", 2, "tool_call", "lookup_order", {"order": "9999"}, ("error", "no such order")),
    ("codex", 1, "tool_call", "lookup_order", {"order": "4471"}, ("output", "delivered")),
    ("codex", 2, "tool_call", "lookup_order", {"order": "9999"}, ("error", "no such order")),
    ("codex", 3, "tool_call", "check_stock", {"product": "teapot"}, ("output", '"in_stock": 0')),
    ("codex", 4, "command", None, None, ("exit_code", 1)),
]


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x]


def found(items: list[dict], harness, turn, kind, name, args, result) -> bool:
    field, value = result
    for it in items:
        if (it["harness"], it["turn"], it["kind"]) != (harness, turn, kind):
            continue
        if name is not None and (it["name"] != name or it["input"] != args):
            continue
        got = it[field]
        if (got == value) if isinstance(value, int) else (isinstance(got, str) and value in got):
            return True
    return False


def digest(value: object) -> dict | None:
    """The SHA-256 and the length of a value, in place of its text."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}


def public(it: dict) -> dict:
    """A trace row without model text.

    A message keeps only a digest of its text. A tool call and a command keep their input and
    output, which come from the toy tools. Any other item, for example an OpenTelemetry log of the
    harness with the prompt and the answer, keeps only its attribute names and digests.
    """
    out = {k: it[k] for k in ("turn", "harness", "kind", "role", "server", "name", "exit_code")}
    out |= {"harness_internal": it["harness_internal"], "line": it["source"]["line"]}
    if it["kind"] == "message":
        out["output"] = digest(it["output"] or "")
    elif it["kind"] in ("tool_call", "command"):
        out |= {"input": it["input"], "output": it["output"], "error": it["error"]}
    else:
        keys = sorted(it["input"]) if isinstance(it["input"], dict) else None
        out |= {"input_keys": keys, "input": digest(it["input"])}
        out |= {"output": digest(it["output"]), "error": digest(it["error"])}
    return out


def scrub(text: str) -> str:
    """The text without the local paths of this machine. A model command can name them."""
    return text.replace(str(ROOT), "<repo>").replace(str(Path.home()), "~")


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "proofs" / "trace"
    project = ROOT / ".proof" / "trace"
    shutil.rmtree(project, ignore_errors=True)
    (project / ".nooku").mkdir(parents=True)
    config = {"entry": ENTRY, "models": ["claude-code", "codex"]}
    (project / ".nooku" / "config.json").write_text(json.dumps(config))
    cur = bridge.start(project, wait=120)
    try:
        for m in MESSAGES:
            _, ok = bridge.send(cur, m)
            print("sent", repr(m), "ok" if ok else "FAILED", flush=True)
    finally:
        manifest = bridge.end(project)
    assert manifest is not None
    folder = Path(cur["dir"])
    findings = json.loads((folder / "findings.json").read_text())
    items = rows(folder / "trace.jsonl")
    checks = [
        {"expect": [h, t, k, n, a, list(r)], "found": found(items, h, t, k, n, a, r)}
        for h, t, k, n, a, r in EXPECT
    ]
    sdk = subprocess.run(
        [*ENTRY[:7], "python", "-c", "import claude_agent_sdk as s; print(s.__version__)"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    versions = {s["harness"]: s["version"] for s in findings["sessions"]}
    report = {
        "date": date.today().isoformat(),
        "versions": {"session files": versions, "claude-agent-sdk": sdk, **manifest["versions"]},
        "turns": findings["turns"],
        "sessions": [
            {k: s[k] for k in ("harness", "inferred", "version", "items", "ignored")}
            for s in findings["sessions"]
        ],
        "counts": findings["counts"],
        "checks": checks,
        "trace": [public(it) for it in items],
    }
    report["pass"] = (
        findings["turns"] == len(MESSAGES)
        and {s["harness"] for s in findings["sessions"]} == {"claude-code", "codex"}
        and all(c["found"] for c in checks)
        and findings["counts"]["version_untested"] == 0
    )
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    (out / "results.json").write_text(scrub(text))
    print("PASS" if report["pass"] else "FAIL", out / "results.json")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

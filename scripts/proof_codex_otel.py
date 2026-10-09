"""Check if Codex sends OpenTelemetry data from the OTEL_* variables of a test. Local only.

The bridge gives the entry the variables of SPEC.md section 7.5. This script runs `codex exec`
with the same variables and an OTLP receiver, and counts the rows that the receiver writes. It
writes proofs/otel/codex.json. The model's reply is not stored.

usage: python scripts/proof_codex_otel.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from proof_common import json_lines  # noqa: E402

from nookku import otlp  # noqa: E402
from nookku.stdio import start_in_thread  # noqa: E402

PROMPT = "Reply with one word: done."


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nookku-otel-"))
    record = work / otlp.FILE
    receiver = otlp.Receiver(("127.0.0.1", 0), record)
    start_in_thread(receiver)
    variables = otlp.environment(receiver.url)
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "read-only", "-C", str(work)]
    try:
        p = subprocess.run(
            [*cmd, PROMPT],
            env={**os.environ, **variables},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
        )
        receiver.quiet(limit=5)
    finally:
        receiver.shutdown()
        receiver.server_close()
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout
    events = json_lines(p.stdout)
    rows = [x for x in record.read_text().split("\n") if x] if record.exists() else []
    result = {
        "date": date.today().isoformat(),
        "codex": version.strip(),
        "command": [*cmd[:-1], "<temporary folder>", PROMPT],
        "variables": variables | {"OTEL_EXPORTER_OTLP_ENDPOINT": "<receiver URL>"},
        "exit_code": p.returncode,
        "turn_completed": any(e.get("type") == "turn.completed" for e in events),
        "receiver_rows": len(rows),
        "codex_reads_the_variables": bool(rows),
    }
    out = ROOT / "proofs" / "otel" / "codex.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result))
    # The proof is the measurement. It passes if codex ran its turn.
    return 0 if p.returncode == 0 and result["turn_completed"] else 1


if __name__ == "__main__":
    sys.exit(main())

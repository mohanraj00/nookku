"""Record the Claude Code version that each Claude Agent SDK release bundles. Local only.

The trace readers are tested for some Claude Code versions only (TESTED of trace.py). An app gets
the version that its Agent SDK bundles. This script installs each given release in a temporary
uv environment and reads claude_agent_sdk._cli_version.__cli_version__. It needs no model.

usage: python scripts/proof_sdk_bundles.py VERSION... [--out FILE]
       (default FILE proofs/trace/sdk-bundles.json)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READ = "import claude_agent_sdk._cli_version as c; print(c.__cli_version__)"


def bundled(release: str) -> str | None:
    """The Claude Code version of one Agent SDK release, or None if uv cannot install it."""
    argv = ["uv", "run", "--quiet", "--no-project", "--with", f"claude-agent-sdk=={release}"]
    p = subprocess.run([*argv, "python", "-I", "-c", READ], capture_output=True, text=True)
    if p.returncode != 0:
        return None
    return p.stdout.strip() or None


def main() -> int:
    args = sys.argv[1:]
    out = ROOT / "proofs" / "trace" / "sdk-bundles.json"
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        del args[i : i + 2]
    if not args:
        print(__doc__)
        return 2
    rows = [{"claude-agent-sdk": r, "claude-code": bundled(r)} for r in args]
    report = {"date": date.today().isoformat(), "releases": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for row in rows:
        print(row["claude-agent-sdk"], row["claude-code"])
    return 0 if all(r["claude-code"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

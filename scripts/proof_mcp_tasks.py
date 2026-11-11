"""Show the task states and scope challenges of a toy stock MCP server.

usage: uv run python scripts/proof_mcp_tasks.py
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from nookku import __version__, bridge
from nookku.record import loads

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from toy_mcp_tasks import CASE, observe  # noqa: E402


def main() -> int:
    case = loads(CASE.read_bytes())
    with TemporaryDirectory(prefix="nookku-mcp-tasks-") as work:
        result = observe(Path(work))
    expected = {key: case[key] for key in ("auth", "tasks", "unfinished")}
    passed = result == {**expected, "credential_absent": True}
    proof = {
        "date": datetime.date.today().isoformat(),
        "versions": {
            "nookku": __version__,
            "claude_code": bridge._version("claude"),
            "codex": bridge._version("codex"),
        },
        "method": "scripts/proof_mcp_tasks.py",
        "case": "conformance/mcp/task-auth.json",
        "model_used": False,
        "passed": passed,
        **result,
    }
    out = ROOT / "proofs" / "mcp-tasks" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if passed else 'FAIL'}: {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

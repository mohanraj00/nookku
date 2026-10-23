"""Proof of egress discovery, the MCP proxies, the Postgres proxy and the driver trace in a real
harness (issue #437, SPEC.md sections 7.11 to 7.13 and 8.6). Local only.

The app is the egress toy shop (examples/toy-shop-egress/): an Agent SDK session with a catalog MCP
server over HTTP, a notes MCP server over stdio, the orders in Postgres and the returns in a
SQLite file. The proof runs Postgres 16 in Docker and the catalog server on their default ports
in the code of the app. The harness gets DATABASE_URL, as a developer has it.

The tester types `nookku start`. The harness model reads the app and runs `nookku register` with
its egress answer, with no help from the script. If no answer is registered, the tester types
`nookku start` again, at most 3 times. Then the tester types `nookku start`, sends the toy shop
messages and types `nookku end`. The test has no evaluation. The results file also records a test
that did not start, with the last answer of the harness.

E1  The manifest has the answer of the model: the catalog server over HTTP with its variable and
    URL, the notes server over stdio with its variable, the orders database with `record: proxy`
    and the returns database with `record: driver`. The Agent SDK model API is anthropic,
    with ANTHROPIC_BASE_URL. `unseen` is empty.
E2  The model added, removed or changed no project file in the discovery, except the answer
    files and the test folder. The guard can add blocked_call rows to .nookku/relay.jsonl.
E3  Each call of the session to the catalog and notes tools has a `tools/call` in mcp.jsonl, with
    the same tool and arguments, in the same turn. Each order lookup has a query of the orders in
    database.jsonl in its turn. Each return has a driver query `INSERT INTO returns` in its turn.
E4  The psycopg spans of the app go to the address of the Postgres proxy, and `unseen_call` finds
    no break. The audit finds no break, and the seal is intact.

usage: python scripts/proof_egress.py SETUP (plugin-claude-code, plugin-codex, hooks-claude-code
       or hooks-codex)
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import proof_report as pr

from nookku import discovery, seal

EGRESS = pr.ROOT / "examples" / "toy-shop-egress"
sys.path[:0] = [str(EGRESS)]

import catalog_mcp  # noqa: E402

# The packages of the app, with the versions that the proof records.
PACKAGES = (
    "psycopg[binary]==3.3.6",
    "opentelemetry-sdk==1.44.0",
    "opentelemetry-exporter-otlp-proto-http==1.44.0",
    "opentelemetry-instrumentation-psycopg==0.65b0",
    "opentelemetry-instrumentation-sqlite3==0.65b0",
)
POSTGRES_IMAGE = "postgres:16-alpine"
PG_PORT = 55432
# A toy password of a local Docker database. The app has the same default.
DATABASE_URL = f"postgres://shop:toy-shop-pw@127.0.0.1:{PG_PORT}/shop"
MESSAGES = [
    "Hi, what is the status of my order 7310?",
    "How much is the wooden train set, and do you have it in stock?",
    "The wooden train set from order 7310 has a broken wheel. Please start a return for it.",
]
DISCOVERY_ATTEMPTS = 3
TOOLS = ("find_product", "add_note", "lookup_order", "start_return")
# The discovery reads the code, writes the answer file and runs nookku register --file
# (src/nookku/discover.md). The Write tool of Claude Code can edit only the answer file, because
# the app already has the instrumentation of its drivers. Its Bash runs in the sandbox of Claude
# Code, which can write each file in the project, as Codex runs in its workspace-write sandbox. E2
# checks each project file, except the discovery answer files and the test folder. When the guard
# denies a call outside a test, it adds a blocked_call row to .nookku/relay.jsonl. E2 accepts only
# these added rows in that file.
# An allow list refuses a loop or a pipe that only reads.
SANDBOX = {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}}
CLAUDE_DISCOVERY = [
    "--tools=Bash,Read,Grep,Glob,Write",
    "--allowedTools=Read,Grep,Glob,Edit(./.nookku/egress.json)",
    f"--settings={json.dumps(SANDBOX)}",
]


def free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def postgres() -> str:
    """Start Postgres in Docker with the orders. Return the container name."""
    name = f"nookku-proof-egress-{int(time.time())}"
    env = ["-e", "POSTGRES_USER=shop", "-e", "POSTGRES_PASSWORD=toy-shop-pw"]
    env += ["-e", "POSTGRES_DB=shop"]
    port = ["-p", f"127.0.0.1:{PG_PORT}:5432"]
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, *env, *port, POSTGRES_IMAGE],
        check=True,
        capture_output=True,
    )
    psql = ["docker", "exec", "-i", "-e", "PGPASSWORD=toy-shop-pw", name, "psql"]
    psql += ["-h", "127.0.0.1", "-U", "shop", "-d", "shop", "-v", "ON_ERROR_STOP=1", "-q"]
    # The init server of the image listens on no TCP port, so a TCP query waits for the real one.
    for _ in range(60):
        if subprocess.run([*psql, "-c", "SELECT 1"], capture_output=True).returncode == 0:
            break
        time.sleep(1)
    subprocess.run(psql, input=(EGRESS / "orders.sql").read_bytes(), check=True)
    return name


def digest(project: Path) -> dict[str, str]:
    """The SHA-256 of each project file, except the answer files and the test folder.

    register writes discovery.json and removes egress.json. These are the expected changes.
    Keep config.json and each other state file in the check.
    """
    excluded = {f".nookku/{discovery.NAME}", f".nookku/{discovery.ANSWER_FILE}"}
    out = {}
    for path in project.rglob("*"):
        name = path.relative_to(project).as_posix()
        if name in excluded or name.startswith(".nookku/tests/"):
            continue
        if path.is_symlink():
            out[name] = "symlink:" + str(path.readlink())
        elif path.is_file():
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


GUARD_RECORD = ".nookku/relay.jsonl"


def guard_rows(before: bytes, after: bytes) -> int | None:
    """The number of blocked_call rows that the guard added, or None for each other change."""
    if not after.startswith(before) or (before and not before.endswith(b"\n")):
        return None
    added = after[len(before) :]
    if not added.endswith(b"\n"):
        return None
    rows = added.split(b"\n")[:-1]
    for row in rows:
        try:
            item = json.loads(row)
        except ValueError:
            return None
        if not isinstance(item, dict) or item.get("type") != "blocked_call":
            return None
    return len(rows)


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Each file that was added, removed or changed."""
    return sorted(n for n in before.keys() | after.keys() if before.get(n) != after.get(n))


def by_kind(answer: dict[str, Any]) -> dict[str, Any]:
    """The parts of the answer that the proof checks, by what they are, not by their names."""
    servers = answer["mcp_servers"]
    dbs = answer["databases"]
    return {
        "http": [p for p in servers if p["transport"] == "http"],
        "stdio": [p for p in servers if p["transport"] == "stdio"],
        "postgres": [d for d in dbs if discovery.db_system(d["kind"]) == "postgresql"],
        "sqlite": [d for d in dbs if discovery.db_system(d["kind"]) == "sqlite"],
    }


def e1(answer: dict[str, Any], egress: dict[str, Any], catalog: str) -> bool:
    parts = by_kind(answer)
    http, stdio, pg, lite = parts["http"], parts["stdio"], parts["postgres"], parts["sqlite"]
    return (
        answer["model_apis"] == [{"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": None}]
        and len(answer["mcp_servers"]) == 2
        and len(answer["databases"]) == 2
        and len(http) == 1
        and http[0]["env"] == "CATALOG_MCP_URL"
        and http[0]["url"] == catalog
        and len(stdio) == 1
        and stdio[0]["env"] == "NOTES_MCP_COMMAND"
        and stdio[0]["command"][-1].endswith("notes_mcp.py")
        and len(pg) == 1
        and pg[0]["env"] == "DATABASE_URL"
        and pg[0]["record"] == "proxy"
        and len(lite) == 1
        and lite[0]["record"] == "driver"
        and egress["unseen"] == []
        and egress["driver"] == [lite[0]["name"]]
        and egress["proxies"].get(stdio[0]["name"]) == "stdio"
        and http[0]["name"] in egress["proxies"]
        and pg[0]["name"] in egress["proxies"]
        and "anthropic" in egress["proxies"]
    )


def tool(name: str) -> str:
    """The tool name with no MCP prefix: mcp__catalog__find_product is find_product."""
    return name.rsplit("__", 1)[-1]


def matched(
    calls: list[dict[str, Any]], records: list[dict[str, Any]], same: Any
) -> list[dict[str, Any]]:
    """Each session call with no record in its turn that `same` matches. A record matches only
    one call."""
    left = list(records)
    missing = []
    for c in calls:
        hit = next((r for r in left if r["turn"] == c["turn"] and same(c, r)), None)
        if hit is None:
            missing.append({"turn": c["turn"], "name": c["name"], "input": c["input"]})
        else:
            left.remove(hit)
    return missing


def main() -> int:
    relay = sys.argv[1] if len(sys.argv) > 1 else ""
    if relay not in pr.SETUPS:
        sys.exit(f"usage: proof_egress.py {'|'.join(pr.SETUPS)}")
    for port in (catalog_mcp.PORT, PG_PORT):
        if not free(port):
            sys.exit(f"the port {port} is in use. The app has it as its default.")
    # The bridge reads the postgres URL from the environment of the harness (SPEC.md 7.13).
    pr.ENV["DATABASE_URL"] = DATABASE_URL
    project, run, start, end, end_args = pr.relay_runner(relay)
    for name in ("notes.json", "returns.db"):
        (project / name).unlink(missing_ok=True)
    pr.setup(project, EGRESS, config={"evaluate": False}, packages=PACKAGES)
    discovery.take(project)
    before = digest(project)
    record = project / GUARD_RECORD
    record_before = record.read_bytes() if record.is_file() else b""
    container = catalog = None
    try:
        container = postgres()
        catalog = catalog_mcp.CatalogServer()
        threading.Thread(target=catalog.serve_forever, daemon=True).start()
        extra = CLAUDE_DISCOVERY if relay.endswith("claude-code") else end_args
        # A model can register its answer with a command that the proof does not allow, for
        # example a pipe from python3. Then the next start prompt sends the task again.
        answers: list[str] = []
        pending = None
        while pending is None and len(answers) < DISCOVERY_ATTEMPTS:
            answers.append(run(start, extra))
            pending = discovery.pending(project)
        found = answers[-1]
        after = digest(project)
        changed = changed_files(before, after)
        blocked = None
        if GUARD_RECORD in changed and record.is_file() and not record.is_symlink():
            blocked = guard_rows(record_before, record.read_bytes())
            if blocked is not None:
                changed.remove(GUARD_RECORD)
        ran = None
        if pending is not None:
            ran = pr.run_test(project, run, start, end, end_args, MESSAGES, registered=True)
    finally:
        if catalog is not None:
            catalog.shutdown()
            catalog.server_close()
        if container is not None:
            subprocess.run(["docker", "stop", container], capture_output=True)
    hidden = pr.private(found)
    result: dict[str, Any] = {
        "date": date.today().isoformat(),
        "relay": relay,
        "discovery_registered": pending is not None,
        "discovery_attempts": len(answers),
        # A text that shares 8 words with an instruction file stays out of the repo.
        "discovery_answer": None if hidden else pr.scrub(found, project),
        "method": "scripts/proof_egress.py",
        "E2_app_files_changed": changed,
        "E2_guard_rows_added": blocked or 0,
        "E2_files_before": before,
        "E2_files_after": after,
    }
    if ran is None:
        result["versions"] = {"claude-code": version("claude"), "codex": version("codex")}
        result["pass"] = False
        return write(relay, result)
    folder, _ = ran

    manifest = json.loads((folder / "manifest.json").read_text())
    findings = json.loads((folder / "findings.json").read_text())
    audit = json.loads((folder / "audit.json").read_text())
    trace = [json.loads(x) for x in (folder / "trace.jsonl").read_text().split("\n") if x]
    egress = manifest["egress"]
    answer = egress["answer"]
    parts = by_kind(answer)
    session = [it for it in trace if it["kind"] == "tool_call" and it["harness"] == "claude-code"]
    calls = {t: [c for c in session if tool(c["name"]) == t] for t in TOOLS}
    mcp = [it for it in trace if it["harness"] == "mcp" and it["kind"] == "tool_call"]
    queries = [it for it in trace if it["harness"] == "database" and it["kind"] == "query"]
    driver = [it for it in trace if it["harness"] == "driver" and it["kind"] == "query"]
    spans = [
        it
        for it in trace
        if it["harness"] == "otel"
        and isinstance(it["input"], dict)
        and it["input"].get("db.system") == "postgresql"
    ]
    proxy = egress["proxies"].get(parts["postgres"][0]["name"]) if parts["postgres"] else None
    span_hosts = sorted(
        {f"{s['input'].get('net.peer.name')}:{s['input'].get('net.peer.port')}" for s in spans}
    )

    def mcp_same(server: str) -> Any:
        return lambda c, r: (
            r["session"] == server
            and tool(r["name"]) == tool(c["name"])
            and r["input"] == c["input"]
        )

    def text(r: dict[str, Any]) -> str:
        return json.dumps(r["input"]).lower()

    servers = {p["transport"]: p["name"] for p in answer["mcp_servers"]}
    missing = {
        "find_product": matched(calls["find_product"], mcp, mcp_same(servers.get("http", ""))),
        "add_note": matched(calls["add_note"], mcp, mcp_same(servers.get("stdio", ""))),
        "lookup_order": matched(
            calls["lookup_order"], queries, lambda c, r: "from orders" in text(r)
        ),
        "start_return": matched(
            calls["start_return"], driver, lambda c, r: "insert into returns" in text(r)
        ),
    }
    # The proxy records the Postgres queries, so the trace gives no driver query of them.
    twice = [r for r in driver if "from orders" in text(r)]
    sealed = seal.verify(folder)
    result.update(
        {
            "versions": {
                **manifest["versions"],
                "agent sdk": pr.AGENT_SDK,
                "app packages": list(PACKAGES),
                "postgres": POSTGRES_IMAGE,
                "session files": {s["harness"]: s["version"] for s in findings["sessions"]},
            },
            "plugins": sorted(pr.PLUGINS) if relay.endswith("claude-code") else None,
            "turns": audit["turns"],
            "audit_exit": audit["exit"],
            # The address of a SQLite file can name the project folder of this machine.
            "answer": json.loads(pr.scrub(json.dumps(answer), project)),
            "unseen": egress["unseen"],
            "driver": egress["driver"],
            "proxies": sorted(egress["proxies"]),
            "sslmode": egress.get("sslmode"),
            "E1_manifest_has_the_answer": e1(answer, egress, catalog.url),
            "session_calls": {t: [c["turn"] for c in cs] for t, cs in calls.items()},
            "mcp_calls": [
                {"turn": r["turn"], "server": r["session"], "name": r["name"]} for r in mcp
            ],
            "database_queries": [
                {"turn": r["turn"], "name": r["name"], "input": r["input"]} for r in queries
            ],
            "driver_queries": [
                {"turn": r["turn"], "name": r["name"], "input": r["input"]} for r in driver
            ],
            "calls_with_no_record": missing,
            "postgres_driver_queries": len(twice),
            "E3_each_call_has_a_record": (
                all(calls[t] for t in TOOLS) and not any(missing.values()) and not twice
            ),
            "postgres_spans": len(spans),
            "postgres_span_addresses": span_hosts,
            "postgres_proxy": proxy,
            "unseen_call": findings["counts"]["unseen_call"],
            "counts": {k: v for k, v in findings["counts"].items() if v},
            "seal": {k: v for k, v in sealed.items() if k != "test"},
        }
    )
    result["E4_no_unseen_call"] = (
        bool(spans)
        and proxy is not None
        and span_hosts == [proxy.removeprefix("postgresql://")]
        and result["unseen_call"] == 0
        and audit["exit"] == 0
        and sealed["intact"]
    )
    result["pass"] = (
        result["E1_manifest_has_the_answer"]
        and not changed
        and result["E3_each_call_has_a_record"]
        and result["E4_no_unseen_call"]
    )
    return write(relay, result)


def version(cli: str) -> str | None:
    """The version of a harness CLI, or None if it is not installed."""
    try:
        p = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return None
    return p.stdout.strip()


def write(relay: str, result: dict[str, Any]) -> int:
    """Write the results file of the setup, also for a test that did not start."""
    out = pr.ROOT / "proofs" / "egress" / f"{relay}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "discovery_answer"}))
    print("PASS" if result["pass"] else "FAIL", out)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

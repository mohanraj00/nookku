"""Tests of the read-only public API of the evaluation dashboard (#581, docs/reference/api.md)."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nookku import api, bridge, gate, seal
from nookku.cli import main

ROOT = Path(__file__).resolve().parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
SUBJECT = "sha256:ab12cd34"
MESSAGES = ["What is your refund policy?", "Do you ship to Pune?"]


def _shop(root: Path) -> Path:
    """A toy shop project with 1 script and a gate file with 1 test of the script."""
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    (root / "gates" / "scripts").mkdir(parents=True)
    text = "".join(json.dumps({"said": m}) + "\n" for m in MESSAGES)
    (root / "gates" / "scripts" / "refund.jsonl").write_text(text)
    path = root / "gates" / "gate.json"
    tests = [{"name": "refund", "script": "scripts/refund.jsonl"}]
    path.write_text(json.dumps({"v": 1, "tests": tests}))
    return path


@pytest.fixture
def project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """A project with 1 gate run (and its 1 test) and 1 more scripted test."""
    root = tmp_path / "shop"
    path = _shop(root)
    argv = ["gate", "run", str(path), "--subject", SUBJECT, "--root", str(root), "--json"]
    assert main(argv) == 0
    passed, _, _ = bridge.run_script(root, root / "gates" / "scripts" / "refund.jsonl")
    assert passed
    capsys.readouterr()
    return root


@pytest.fixture
def server(project: Path, tmp_path: Path) -> Iterator[api.Server]:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html><title>Runs</title>")
    (site / "app.js").write_text("export {};\n")
    (tmp_path / "secret.txt").write_text("not a site file")
    srv = api.Server(project, "127.0.0.1", 0, site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def call(
    srv: api.Server,
    path: str,
    method: str = "GET",
    host: str | None = None,
    auth: str | None = "",
) -> tuple[int, dict[str, str], bytes]:
    """One request. With `auth` "", the request sends the token of the server. With None, it
    sends no Authorization header. Else `auth` is the value of the header."""
    port = srv.server_address[1]
    address = "::1" if srv.address_family == socket.AF_INET6 else "127.0.0.1"
    conn = http.client.HTTPConnection(address, port, timeout=10)
    try:
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
        if auth is not None:
            conn.putheader("Authorization", auth or f"Bearer {srv.token}")
        conn.endheaders()
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


def get_json(srv: api.Server, path: str, status: int = 200) -> dict[str, Any]:
    got, headers, body = call(srv, path)
    assert got == status, body
    assert headers["content-type"] == "application/json; charset=utf-8"
    data: dict[str, Any] = json.loads(body)
    assert data["api"] == api.VERSION
    return data


def test_the_index_names_each_route(server: api.Server) -> None:
    data = get_json(server, "/api/v1")
    assert "/api/v1/runs/<run>/findings" in data["routes"]
    assert get_json(server, "/api/v1/") == data


def test_the_runs_have_their_counts_their_seal_and_their_verdict(server: api.Server) -> None:
    rows = get_json(server, "/api/v1/runs")["runs"]
    assert len(rows) == 2
    assert rows[0]["started"] >= rows[1]["started"]
    for row in rows:
        assert row["state"] == "ended"
        assert row["turns"] == len(MESSAGES)
        assert row["breaks"] == 0
        assert row["seal"] == "intact"
        assert row["verdict"] == "pass"
        assert row["verdict_problem"] is None
    one = get_json(server, f"/api/v1/runs/{rows[0]['id']}")["run"]
    assert one == rows[0]


def test_the_findings_and_the_verdict_of_a_run(server: api.Server) -> None:
    run_id = get_json(server, "/api/v1/runs")["runs"][0]["id"]
    found = get_json(server, f"/api/v1/runs/{run_id}/findings")
    assert found["run"] == run_id
    assert found["sealed"] is True
    assert found["error"] is None
    assert isinstance(found["findings"]["findings"], list)
    report = get_json(server, f"/api/v1/runs/{run_id}/verdict")
    assert report["verdict"]["verdict"] == "pass"
    assert report["problem"] is None
    # The run had no evaluation, so it has no report.
    evaluation = get_json(server, f"/api/v1/runs/{run_id}/evaluation")
    assert evaluation["report"] is None
    assert evaluation["sealed"] is False


def test_a_broken_seal_shows_and_its_verdict_cannot_be_used(
    project: Path, server: api.Server
) -> None:
    run_id = get_json(server, "/api/v1/runs")["runs"][0]["id"]
    folder = project / ".nookku" / "tests" / run_id
    data = json.loads((folder / "findings.json").read_text())
    data["findings"] = []
    (folder / "findings.json").write_text(json.dumps(data))
    row = get_json(server, f"/api/v1/runs/{run_id}")["run"]
    assert row["seal"] == "broken"
    assert row["verdict"] is None
    assert row["verdict_problem"]
    found = get_json(server, f"/api/v1/runs/{run_id}/findings")
    assert found["sealed"] is False
    assert found["findings"]["findings"] == []
    # The other run does not change.
    other = get_json(server, "/api/v1/runs")["runs"][1]
    assert other["seal"] == "intact"
    assert other["verdict"] == "pass"


def test_a_report_that_is_not_in_the_seal_is_not_sealed(project: Path, server: api.Server) -> None:
    run_id = get_json(server, "/api/v1/runs")["runs"][0]["id"]
    (project / ".nookku" / "tests" / run_id / api.REPORT).write_text("# Report\n\nA note.\n")
    evaluation = get_json(server, f"/api/v1/runs/{run_id}/evaluation")
    assert evaluation["report"] == "# Report\n\nA note.\n"
    assert evaluation["sealed"] is False


def test_the_gate_runs_have_their_verdict_and_their_subject(
    project: Path, server: api.Server
) -> None:
    rows = get_json(server, "/api/v1/gates")["gates"]
    assert len(rows) == 1
    row = rows[0]
    assert row["verdict"] == "pass"
    assert row["subject"] == SUBJECT
    assert row["tests"] == 1
    assert row["seal"] == "intact"
    assert row["problem"] is None
    result = get_json(server, f"/api/v1/gates/{row['id']}")
    assert result["result"]["subject"] == SUBJECT
    folder = gate.find(project, None)
    assert folder is not None
    (folder / gate.RUN).write_text("{}")
    broken = get_json(server, "/api/v1/gates")["gates"][0]
    assert broken["seal"] == "broken"
    assert broken["verdict"] is None
    assert broken["problem"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/runs/20991231-000000-0000",
        "/api/v1/runs/..",
        "/api/v1/runs/%2e%2e%2fconfig.json",
        "/api/v1/runs/x/trace",
        "/api/v1/gates/..",
        "/api/v1/gates/%2e%2e",
        "/api/v1/nothing",
        "/api/v2/runs",
    ],
)
def test_a_wrong_path_gets_404(server: api.Server, path: str) -> None:
    status, _, body = call(server, path)
    assert status == 404
    assert "error" in json.loads(body) if body.startswith(b"{") else True


@pytest.mark.parametrize(
    "host", ["evil.example:80", "127.0.0.1", "127.0.0.1.evil.example:8765", ""]
)
def test_a_wrong_host_header_gets_403(server: api.Server, host: str) -> None:
    status, _, body = call(server, "/api/v1/runs", host=host)
    assert status == 403
    assert json.loads(body)["error"] == "wrong Host header"


def test_localhost_and_an_allowed_host_get_an_answer(project: Path) -> None:
    srv = api.Server(project, "127.0.0.1", 0, None, ["dash.example:443"])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        for host in (f"localhost:{port}", f"[::1]:{port}", "DASH.example:443"):
            assert call(srv, "/api/v1", host=host)[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_the_api_is_read_only(server: api.Server, method: str) -> None:
    status, _, body = call(server, "/api/v1/runs", method=method)
    assert status == 405
    assert json.loads(body)["error"] == "the API is read-only"


def test_the_answers_have_the_safe_headers_and_no_cors(server: api.Server) -> None:
    for path in ("/api/v1/runs", "/", "/app.js"):
        status, headers, _ = call(server, path)
        assert status == 200
        assert headers["cache-control"] == "no-store"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["content-security-policy"] == api.CSP
        assert not any(k.startswith("access-control-") for k in headers)
    assert call(server, "/app.js")[1]["content-type"] == "text/javascript; charset=utf-8"
    status, headers, body = call(server, "/api/v1/runs", method="HEAD")
    assert status == 200 and body == b""


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/link.txt", "/none.html", "/sub/"]
)
def test_a_site_path_outside_the_site_gets_404(server: api.Server, path: str) -> None:
    assert server.site is not None
    os.symlink(server.site.parent / "secret.txt", server.site / "link.txt")
    status, _, body = call(server, path)
    assert status == 404
    assert b"not a site file" not in body


def test_an_index_symlink_to_a_file_outside_the_site_gets_404(server: api.Server) -> None:
    assert server.site is not None
    sub = server.site / "sub2"
    sub.mkdir()
    os.symlink(server.site.parent / "secret.txt", sub / "index.html")
    status, _, body = call(server, "/sub2/")
    assert status == 404
    assert b"not a site file" not in body


def test_a_site_index_that_is_a_symlink_outside_gets_404(project: Path, tmp_path: Path) -> None:
    site = tmp_path / "linked-site"
    site.mkdir()
    (tmp_path / "outside.html").write_text("not a site file")
    os.symlink(tmp_path / "outside.html", site / "index.html")
    srv = api.Server(project, "127.0.0.1", 0, site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, _, body = call(srv, "/")
        assert status == 404
        assert b"not a site file" not in body
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("kind", ["none", "wrong", "basic", "longer"])
def test_an_api_request_with_no_valid_token_gets_401(server: api.Server, kind: str) -> None:
    auth = {
        "none": None,
        "wrong": "Bearer not-the-token",
        "basic": f"Basic {server.token}",
        "longer": f"Bearer {server.token}x",
    }[kind]
    for path in ("/api/v1", "/api/v1/runs", "/api/v1/runs/no-such-run"):
        status, headers, body = call(server, path, auth=auth)
        assert status == 401
        assert headers["www-authenticate"] == "Bearer"
        assert json.loads(body) == {"api": api.VERSION, "error": "no valid token"}


def test_a_site_file_needs_no_token(server: api.Server) -> None:
    status, _, body = call(server, "/", auth=None)
    assert status == 200 and b"<title>Runs</title>" in body


def test_each_server_has_a_new_token(project: Path) -> None:
    one = api.Server(project, "127.0.0.1", 0)
    two = api.Server(project, "127.0.0.1", 0)
    try:
        assert one.token != two.token
        assert len(one.token) >= 40
    finally:
        one.server_close()
        two.server_close()


def test_the_server_listens_on_an_ipv6_address(project: Path) -> None:
    try:
        srv = api.Server(project, "::1", 0)
    except OSError as e:
        pytest.skip(f"this computer has no IPv6 loopback: {e}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        assert srv.url == f"http://[::1]:{port}/"
        assert call(srv, "/api/v1/runs", host=f"[::1]:{port}")[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_with_no_site_a_page_path_gets_a_short_404(project: Path) -> None:
    srv = api.Server(project, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, _, body = call(srv, "/")
        assert status == 404
        assert b"--site" in body
        assert call(srv, "/api/v1/runs")[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = (p.read_bytes(), p.stat().st_mtime_ns)
    return out


def test_the_api_changes_no_file(project: Path, server: api.Server) -> None:
    before = _snapshot(project)
    copies = _snapshot(seal.home())
    rows = get_json(server, "/api/v1/runs")["runs"]
    gates = get_json(server, "/api/v1/gates")["gates"]
    for row in rows:
        for part in ("", "/verdict", "/findings", "/evaluation"):
            get_json(server, f"/api/v1/runs/{row['id']}{part}")
    get_json(server, f"/api/v1/gates/{gates[0]['id']}")
    assert _snapshot(project) == before
    assert _snapshot(seal.home()) == copies


def test_a_project_with_no_runs_gives_empty_lists(tmp_path: Path) -> None:
    assert api.answer(tmp_path, "/api/v1/runs") == (200, {"api": 1, "runs": []})
    assert api.answer(tmp_path, "/api/v1/gates") == (200, {"api": 1, "gates": []})


def test_a_seal_with_no_copy_is_not_sealed(project: Path) -> None:
    run_id = api.runs(project)["runs"][0]["id"]
    shutil.rmtree(seal.home() / "seals")
    assert api.run_findings(project, run_id)["sealed"] is False


def test_the_command_refuses_a_site_with_no_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "site").mkdir()
    argv = ["dashboard", "--root", str(tmp_path), "--site", str(tmp_path / "site")]
    assert main(argv) == 2
    assert "has no index.html" in capsys.readouterr().err


def test_hosts_for_a_loopback_and_a_named_address() -> None:
    assert "localhost:8765" in api.hosts_for("127.0.0.1", 8765, [])
    assert api.hosts_for("10.0.0.5", 80, []) == {"10.0.0.5:80"}
    assert api.hosts_for("::1", 80, []) >= {"[::1]:80", "127.0.0.1:80"}


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read a file with mode 000")
def test_a_run_or_a_gate_run_with_a_file_that_cannot_be_read_does_not_stop_the_lists(
    project: Path, server: api.Server
) -> None:
    runs = get_json(server, "/api/v1/runs")["runs"]
    bad = project / ".nookku" / "tests" / runs[0]["id"] / "findings.json"
    folder = gate.find(project, None)
    assert folder is not None
    result = folder / gate.RUN
    bad.chmod(0)
    result.chmod(0)
    try:
        rows = get_json(server, "/api/v1/runs")["runs"]
        verdict = get_json(server, f"/api/v1/runs/{runs[0]['id']}/verdict")
        gates = get_json(server, "/api/v1/gates")["gates"]
        one = get_json(server, f"/api/v1/gates/{folder.name}")
    finally:
        bad.chmod(0o644)
        result.chmod(0o644)
    assert len(rows) == 2
    assert rows[0]["verdict"] is None and "cannot be read" in rows[0]["verdict_problem"]
    assert rows[1]["verdict"] == "pass"
    assert verdict["verdict"] is None and "cannot be read" in verdict["problem"]
    assert gates[0]["verdict"] is None and gates[0]["problem"]
    assert one["result"] is None and "cannot be read" in one["problem"]


def test_a_partial_request_times_out_and_a_connection_above_the_limit_gets_503(
    server: api.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = server.server_address[1]
    monkeypatch.setattr(api.Handler, "timeout", 0.5)
    partial = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        partial.sendall(b"GET /api/v1/runs HTTP/1.1\r\n")
        # The server closes the connection after its read timeout, with no answer.
        assert partial.recv(65536) == b""
    finally:
        partial.close()
    monkeypatch.setattr(api.Handler, "timeout", 30)
    held = [socket.create_connection(("127.0.0.1", port), timeout=5)]
    try:
        for _ in range(server.connection_limit - 1):
            held.append(socket.create_connection(("127.0.0.1", port), timeout=5))
        extra = socket.create_connection(("127.0.0.1", port), timeout=5)
        held.append(extra)
        answer = extra.recv(65536)
        assert answer.startswith(b"HTTP/1.1 503 ")
    finally:
        for s in held:
            s.close()

"""Run the check of the evaluation dashboard (#581). CI runs it in the job `dashboard`.

The check:

1. makes a toy shop project with a gate run of 2 scripted tests, 1 more scripted test, and 1
   scripted test with a broken seal;
2. builds the site with build.py (the pinned mugham kit);
3. starts `nookku dashboard --site` on a free port of 127.0.0.1;
4. checks the API with urllib: the runs, the broken seal, the gate run, a POST and a wrong Host;
5. runs Chrome with no window on test/harness.html. The harness loads the dashboard at 360 px and
   at 1280 px, and compares the page with the API;
6. writes the result as JSON and gives exit code 0 only if each check passes.

It needs no model. Chrome is $CHROME, else the first of google-chrome, chromium and
chromium-browser on PATH, else Google Chrome in /Applications on macOS.

usage: python run.py [--mugham CHECKOUT] [--out results.json] [--serve]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TOY_SHOP = ROOT / "examples" / "toy-shop" / "agent.py"
SUBJECT = "sha256:0123456789abcdef"
SCRIPTS = {
    "refund": ["What is your refund policy?", "Do you ship to Pune?"],
    "price": ["What is the price of the blue mug?", "Is the teapot in stock?"],
}
WAIT_S = 90
EMPTY_ANSWER = {"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}


def nookku(
    *args: str, env: dict[str, str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "nookku", *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )


def make_project(work: Path, env: dict[str, str]) -> dict[str, Any]:
    """The toy shop project of the check. Return the ids of its gate run and of its tests."""
    root = work / "shop"
    (root / ".nookku").mkdir(parents=True)
    conf = {"entry": [sys.executable, str(TOY_SHOP)], "models": []}
    (root / ".nookku" / "config.json").write_text(json.dumps(conf))
    scripts = root / "gates" / "scripts"
    scripts.mkdir(parents=True)
    for name, messages in SCRIPTS.items():
        text = "".join(json.dumps({"said": m}) + "\n" for m in messages)
        (scripts / f"{name}.jsonl").write_text(text)
    tests = [{"name": n, "script": f"scripts/{n}.jsonl"} for n in SCRIPTS]
    gate = root / "gates" / "gate.json"
    gate.write_text(json.dumps({"v": 1, "tests": tests}))
    # The toy shop agent calls no backend, so its egress answer is empty (SPEC.md section 7.11).
    done = nookku("register", "--root", str(root), env=env, stdin=json.dumps(EMPTY_ANSWER))
    if done.returncode != 0:
        raise SystemExit(f"nookku register failed: {done.stdout}{done.stderr}")
    done = nookku(
        "gate", "run", str(gate), "--subject", SUBJECT, "--root", str(root), "--json", env=env
    )
    if done.returncode != 0:
        raise SystemExit(f"nookku gate run failed: {done.stdout}{done.stderr}")
    result = json.loads(done.stdout)["result"]
    gate_id = result["gate"]
    bases = {t["name"]: t["test"] for t in result["tests"]}
    ids = []
    # 2 more tests: a replay of each script of the gate run.
    for name in ("refund", "price"):
        args = ("replay", str(scripts / f"{name}.jsonl"), "--base", bases[name], "--json")
        done = nookku(*args, "--root", str(root), "--no-evaluate", env=env)
        if done.returncode != 0:
            raise SystemExit(f"nookku replay failed: {done.stdout}{done.stderr}")
        ids.append(json.loads(done.stdout)["diff"]["new"]["id"])
    # The second extra test gets a broken seal: a file changes after the seal.
    broken = root / ".nookku" / "tests" / ids[1] / "findings.json"
    data = json.loads(broken.read_text())
    data["findings"] = []
    broken.write_text(json.dumps(data))
    return {"root": root, "gate": gate_id, "intact": ids[0], "broken": ids[1]}


def build_site(work: Path, mugham: Path | None) -> Path:
    out = work / "site"
    args = [sys.executable, str(HERE / "build.py"), "--out", str(out)]
    if mugham is not None:
        args += ["--mugham", str(mugham)]
    done = subprocess.run(args, capture_output=True, text=True, check=False, timeout=300)
    if done.returncode != 0:
        raise SystemExit(f"build.py failed: {done.stderr}")
    shutil.copytree(HERE / "test", out / "test")
    return out


def start_dashboard(
    root: Path, site: Path, env: dict[str, str]
) -> tuple[subprocess.Popen[str], str]:
    args = [sys.executable, "-m", "nookku", "dashboard", "--root", str(root), "--port", "0"]
    proc = subprocess.Popen(
        [*args, "--site", str(site)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line:
        proc.kill()
        error = proc.stderr.read() if proc.stderr else ""
        raise SystemExit(f"nookku dashboard did not start: {error}")
    return proc, json.loads(line)["url"]


def fetch(url: str, method: str = "GET", host: str | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(url, method=method)
    if host is not None:
        request.add_header("Host", host)
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def api_checks(url: str, ids: dict[str, Any]) -> dict[str, bool]:
    base = url + "api/v1"
    _, runs = fetch(base + "/runs")
    rows = {r["id"]: r for r in runs["runs"]}
    _, gates = fetch(base + "/gates")
    gate = gates["gates"][0] if gates["gates"] else {}
    _, found = fetch(f"{base}/runs/{ids['broken']}/findings")
    _, verdict = fetch(f"{base}/runs/{ids['intact']}/verdict")
    status_post, _ = fetch(base + "/runs", method="POST")
    status_host, _ = fetch(base + "/runs", host="evil.example")
    status_none, _ = fetch(base + "/runs/no-such-run")
    return {
        "runs": len(rows) == 4,
        "intact_seal": rows.get(ids["intact"], {}).get("seal") == "intact",
        "broken_seal": rows.get(ids["broken"], {}).get("seal") == "broken",
        "broken_has_no_verdict": rows.get(ids["broken"], {}).get("verdict") is None,
        "broken_findings_not_sealed": found.get("sealed") is False,
        "verdict": (verdict.get("verdict") or {}).get("verdict") == "pass",
        "gate": gate.get("id") == ids["gate"] and gate.get("verdict") == "pass",
        "gate_subject": gate.get("subject") == SUBJECT,
        "post_refused": status_post == 405,
        "wrong_host_refused": status_host == 403,
        "no_such_run": status_none == 404,
    }


class Collector(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), CollectorHandler)
        self.result: dict[str, Any] | None = None
        self.got = threading.Event()


class CollectorHandler(BaseHTTPRequestHandler):
    server: Collector

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == "/result" and not self.server.got.is_set():
            try:
                self.server.result = json.loads(parse_qs(parts.query)["r"][0])
            except (KeyError, ValueError) as e:
                self.server.result = {"pass": False, "error": f"bad result: {e}"}
            self.server.got.set()
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def chrome() -> str:
    found = os.environ.get("CHROME")
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = found or shutil.which(name)
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not found and Path(mac).is_file():
        found = mac
    if not found:
        raise SystemExit("no Chrome: set CHROME to the path of a Chrome or a Chromium")
    return found


def browser_checks(url: str, broken: str, work: Path) -> tuple[dict[str, Any], str]:
    collector = Collector()
    threading.Thread(target=collector.serve_forever, daemon=True).start()
    port = collector.server_address[1]
    page = f"{url}test/harness.html?collector={port}&broken={broken}"
    profile = work / "chrome-profile"
    args = [
        chrome(),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile}",
        "--window-size=1400,1000",
        page,
    ]
    if os.environ.get("CI") and sys.platform.startswith("linux"):
        args.insert(1, "--no-sandbox")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        if not collector.got.wait(WAIT_S):
            return {"pass": False, "error": f"no result from the harness after {WAIT_S} s"}, args[0]
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        collector.shutdown()
        collector.server_close()
    assert collector.result is not None
    return collector.result, args[0]


def chrome_version(path: str) -> str | None:
    try:
        done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mugham", type=Path, help="a git checkout of the kit at the pin")
    parser.add_argument("--out", type=Path, help="write the result JSON to this file")
    parser.add_argument(
        "--serve", action="store_true", help="keep the dashboard open after the checks"
    )
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="nookku-dashboard-"))
    env = dict(os.environ)
    env["NOOKKU_HOME"] = str(work / "home")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(ROOT / "src"), env.get("PYTHONPATH")) if p)
    env.pop("NOOKKU_TESTS_DIR", None)
    ids = make_project(work, env)
    site = build_site(work, args.mugham)
    proc, url = start_dashboard(ids["root"], site, env)
    try:
        api = api_checks(url, ids)
        browser, path = browser_checks(url, ids["broken"], work)
        if args.serve:
            print(f"the dashboard is at {url}. Stop it with Ctrl-C.", file=sys.stderr)
            with contextlib.suppress(KeyboardInterrupt):
                proc.wait()
    finally:
        proc.terminate()
        proc.wait(10)
    pin = json.loads((HERE / "mugham.json").read_text())
    result = {
        "kit": {"tag": pin["tag"], "commit": pin["commit"]},
        "browser": chrome_version(path),
        "python": sys.version.split()[0],
        "api": api,
        "page": browser,
        "pass": all(api.values()) and browser.get("pass") is True,
    }
    text = json.dumps(result, indent=1)
    if args.out is not None:
        args.out.write_text(text + "\n")
    print(text)
    if result["pass"]:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"the work folder stays at {work}", file=sys.stderr)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

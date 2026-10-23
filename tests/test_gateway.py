"""The gateway logs of SPEC.md section 8.9."""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from nookku import gateway, seal, trace
from nookku.cli import main

CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "gateway").iterdir())
TRACE_CASE = Path(__file__).resolve().parent.parent / "conformance" / "trace" / "gateway_toy_shop"
KEY = "sk-toy-gateway-master"
ALIAS = "kd-0f3a9c2e-5b7d-4c1e-9a8b-2d4f6e8a0c1b"


def rows(path: Path) -> list[Any]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case(case: Path, tmp_path: Path) -> None:
    given = json.loads((case / "case.json").read_text())
    manifest = json.loads((case / "manifest.json").read_text())
    source = str(case / given["source"])
    head = gateway.load(tmp_path, manifest, source, given["key_aliases"], given["tag"])
    found = rows(tmp_path / gateway.FILE)
    assert found[0] == head
    assert isinstance(found[0].pop("read"), float)
    assert found == rows(case / "expect_gateway.jsonl")


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("2026-10-06T08:00:00Z", 1791273600.0),
        ("2026-10-06T08:00:00.5+00:00", 1791273600.5),
        ("2026-10-06T10:00:00.250+02:00", 1791273600.25),
        ("2026-10-06 08:00:00.123456", 1791273600.123456),
        ("2026-10-06T08:00:00", 1791273600.0),
        (1791273600, 1791273600.0),
        ("not a time", None),
        (None, None),
        (True, None),
    ],
)
def test_the_time_of_a_log(text: Any, expect: float | None) -> None:
    assert gateway.parse_time(text) == expect


def test_no_secret_of_the_log_goes_into_the_record(tmp_path: Path) -> None:
    case = next(c for c in CASES if c.name == "toy_shop")
    manifest = json.loads((case / "manifest.json").read_text())
    gateway.load(tmp_path, manifest, str(case / "spend_logs.json"), [ALIAS], None)
    text = (tmp_path / gateway.FILE).read_text()
    for secret in ("854dbec007247ea1", "sk-toy-client-key", "user_api_key", "x-litellm-tags"):
        assert secret not in text


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (b"\xff", "not UTF-8"),
        (b'{"a": 1}\nnot json\n', "line 2 of the gateway log is not JSON"),
    ],
)
def test_a_log_that_is_not_json_stops_the_read(text: bytes, error: str) -> None:
    with pytest.raises(gateway.GatewayError, match=error):
        gateway.logs(text)


def test_a_test_with_no_end_reads_no_log(tmp_path: Path) -> None:
    with pytest.raises(gateway.GatewayError, match="End the test first"):
        gateway.load(tmp_path, {"started": 1.0, "ended": None}, "x.json", [ALIAS], None)
    assert not (tmp_path / gateway.FILE).exists()


class _Gateway(BaseHTTPRequestHandler):
    """A toy LiteLLM: GET /spend/logs gives the logs if the key is right."""

    seen: ClassVar[list[dict[str, Any]]] = []
    body = b"[]"
    redirect = ""

    def do_GET(self) -> None:
        self.seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
        if self.redirect:
            self.send_response(302)
            self.send_header("Location", self.redirect)
            self.end_headers()
            return
        ok = self.headers.get("Authorization") == f"Bearer {KEY}"
        self.send_response(200 if ok else 401)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def toy_gateway() -> Any:
    _Gateway.seen = []
    _Gateway.redirect = ""
    case = next(c for c in CASES if c.name == "toy_shop")
    _Gateway.body = (case / "spend_logs.json").read_bytes()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_api_read_sends_the_key_and_the_days_of_the_test(
    toy_gateway: str, tmp_path: Path
) -> None:
    case = next(c for c in CASES if c.name == "toy_shop")
    manifest = json.loads((case / "manifest.json").read_text())
    environ = {gateway.KEY_VARIABLE: KEY}
    head = gateway.load(tmp_path, manifest, toy_gateway + "/", [ALIAS], None, environ)
    assert _Gateway.seen == [
        {
            "path": "/spend/logs?start_date=2026-10-06&end_date=2026-10-07&summarize=false",
            "auth": f"Bearer {KEY}",
        }
    ]
    assert head["source"] == toy_gateway + "/"
    assert rows(tmp_path / gateway.FILE)[1:] == rows(case / "expect_gateway.jsonl")[1:]
    assert KEY not in (tmp_path / gateway.FILE).read_text()


def test_the_api_read_needs_the_key_and_a_right_key(toy_gateway: str, tmp_path: Path) -> None:
    manifest = {"started": 1.0, "ended": 2.0}
    with pytest.raises(gateway.GatewayError, match=gateway.KEY_VARIABLE):
        gateway.load(tmp_path, manifest, toy_gateway, [ALIAS], None, {})
    assert _Gateway.seen == []
    wrong = {gateway.KEY_VARIABLE: "sk-wrong"}
    with pytest.raises(gateway.GatewayError, match="status 401"):
        gateway.load(tmp_path, manifest, toy_gateway, [ALIAS], None, wrong)
    assert not (tmp_path / gateway.FILE).exists()


def test_the_key_does_not_follow_a_redirect(toy_gateway: str, tmp_path: Path) -> None:
    _Gateway.redirect = toy_gateway + "/other"
    environ = {gateway.KEY_VARIABLE: KEY}
    with pytest.raises(gateway.GatewayError, match="status 302"):
        gateway.load(tmp_path, {"started": 1.0, "ended": 2.0}, toy_gateway, [ALIAS], None, environ)
    assert [s["path"] for s in _Gateway.seen] == [
        "/spend/logs?start_date=1970-01-01&end_date=1970-01-02&summarize=false"
    ]


@pytest.mark.parametrize("url", ["http://", "http://gw:99999", "http://gw/?key=sk-toy"])
def test_a_url_that_is_not_valid_is_refused(url: str, tmp_path: Path) -> None:
    environ = {gateway.KEY_VARIABLE: KEY}
    with pytest.raises(gateway.GatewayError, match="not valid"):
        gateway.load(tmp_path, {"started": 1.0, "ended": 2.0}, url, [ALIAS], None, environ)


def test_the_source_name_has_no_user_and_no_query() -> None:
    assert gateway.source_name("https://u:p@gw.toy:4000/litellm") == "https://gw.toy:4000/litellm"
    assert gateway.source_name("/home/tester/logs/spend.json") == "spend.json"


def _sealed_test(root: Path) -> Path:
    """A sealed test folder of the trace case gateway_toy_shop, with no gateway.jsonl."""
    folder = root / ".nookku" / "tests" / "20261006-080000-gw01"
    shutil.copytree(TRACE_CASE, folder, ignore=shutil.ignore_patterns("expect_*", "gateway.jsonl"))
    manifest = json.loads((folder / "manifest.json").read_text())
    started = 1791273600.0
    manifest.update(started=started, ended=started + 50)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    seal.write(folder, root / "home")
    return folder


def test_trace_with_gateway_logs_adds_them_to_the_trace_and_the_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = _sealed_test(tmp_path)
    logs = tmp_path / "spend.json"
    shutil.copy(next(c for c in CASES if c.name == "toy_shop") / "spend_logs.json", logs)
    at = ["--root", str(tmp_path), "--json"]
    assert main(["trace", *at, "--gateway", str(logs), "--key-alias", ALIAS]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["gateway"]["items"] == 7
    assert {r["harness"] for r in rows(folder / "trace.jsonl")} == {"gateway"}
    assert seal.verify(folder)["intact"]
    # A later rebuild reads gateway.jsonl again, with no --gateway.
    assert main(["trace", *at]) == 0
    assert json.loads(capsys.readouterr().out)["gateway"] == report["gateway"]
    assert seal.verify(folder)["intact"]


def test_trace_with_a_broken_seal_reads_no_gateway_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = _sealed_test(tmp_path)
    (folder / "tap.jsonl").write_text("")
    logs = next(c for c in CASES if c.name == "toy_shop") / "spend_logs.json"
    args = ["trace", "--root", str(tmp_path), "--gateway", str(logs), "--key-alias", ALIAS]
    assert main(args) == 2
    assert "the trace was not rebuilt" in capsys.readouterr().err
    assert not (folder / gateway.FILE).exists()


@pytest.mark.parametrize(
    "extra",
    [["--gateway", "spend.json"], ["--key-alias", ALIAS], ["--gateway-tag", "toy-shop"]],
)
def test_the_gateway_options_go_together(
    extra: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["trace", "--root", str(tmp_path), *extra]) == 2
    assert "--gateway needs --key-alias" in capsys.readouterr().err


def test_a_log_that_cannot_be_read_stops_the_trace_with_no_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = _sealed_test(tmp_path)
    before = seal.hashes(folder)
    args = ["trace", "--root", str(tmp_path), "--gateway", str(tmp_path / "none.json")]
    assert main([*args, "--key-alias", ALIAS]) == 2
    assert "the gateway logs were not read: cannot read the gateway log" in capsys.readouterr().err
    assert seal.hashes(folder) == before


def _chat_row(alias: str, t: float, messages: list[Any], calls: list[Any]) -> dict[str, Any]:
    return {
        "v": 1,
        "type": "call",
        "gateway": "litellm",
        "call_type": "acompletion",
        "api": "openai",
        "path": "/v1/chat/completions",
        "key_alias": alias,
        "started": t,
        "ts": t + 0.5,
        "status": None,
        "error": None,
        "request": {"model": "toy", "messages": messages},
        "request_cut": False,
        "response_cut": False,
        "result": {"text": "", "tool_calls": calls},
    }


def test_a_tool_result_matches_only_a_call_of_the_same_key_alias(tmp_path: Path) -> None:
    """Two apps with two keys reuse the tool call id call_1. Each result stays with its key."""
    other = "ws-shop-toy-ab12cd34"
    ask = [{"role": "user", "content": "Is the teapot set in stock?"}]
    call = [{"id": "call_1", "name": "check_stock", "input": {"sku": "teapot-set"}}]

    def answer(text: str) -> list[Any]:
        said = {"role": "assistant", "tool_calls": [{"id": "call_1"}]}
        return [*ask, said, {"role": "tool", "tool_call_id": "call_1", "content": text}]

    found = [
        _chat_row(ALIAS, 1.0, ask, call),
        _chat_row(other, 2.0, ask, call),
        _chat_row(other, 3.0, answer("other key: 0 in stock"), []),
        _chat_row(ALIAS, 4.0, answer("agent key: 3 in stock"), []),
    ]
    path = tmp_path / gateway.FILE
    path.write_text("".join(json.dumps(r) + "\n" for r in found))
    items, _ = trace.read_gateway(path)
    outputs = {it["session"]: it["output"] for it in items if it["kind"] == "tool_call"}
    assert outputs == {ALIAS: "agent key: 3 in stock", other: "other key: 0 in stock"}


@pytest.mark.parametrize("url", ["http://gw.toy:4000", "http://10.0.0.5:4000/litellm"])
def test_the_key_goes_to_no_plain_http_url_on_a_network(url: str, tmp_path: Path) -> None:
    environ = {gateway.KEY_VARIABLE: KEY}
    with pytest.raises(gateway.GatewayError, match="is not https"):
        gateway.load(tmp_path, {"started": 1.0, "ended": 2.0}, url, [ALIAS], None, environ)
    assert not (tmp_path / gateway.FILE).exists()


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://127.0.0.1:4000", True),
        ("http://127.8.0.1", True),
        ("http://localhost:4000", True),
        ("http://[::1]:4000", True),
        ("http://gw.toy", False),
        ("http://127.0.0.1.gw.toy", False),
        ("http://[::ffff:10.0.0.5]", False),
    ],
)
def test_the_loopback_hosts(url: str, loopback: bool) -> None:
    assert gateway._loopback(url) is loopback


def test_a_plain_http_url_stops_the_trace_with_exit_code_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(gateway.KEY_VARIABLE, KEY)
    folder = _sealed_test(tmp_path)
    before = seal.hashes(folder)
    args = ["trace", "--root", str(tmp_path), "--gateway", "http://gw.toy:4000"]
    assert main([*args, "--key-alias", ALIAS]) == 2
    assert "is not https" in capsys.readouterr().err
    assert seal.hashes(folder) == before


def test_a_failed_gateway_read_does_not_copy_the_egress_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = _sealed_test(tmp_path)
    before = seal.hashes(folder)
    spans = tmp_path / "spans.jsonl"
    spans.write_text("")
    args = ["trace", "--root", str(tmp_path), "--egress", str(spans)]
    args += ["--gateway", str(tmp_path / "none.json"), "--key-alias", ALIAS]
    assert main(args) == 2
    assert "the gateway logs were not read" in capsys.readouterr().err
    assert not (folder / "egress.jsonl").exists()
    assert seal.hashes(folder) == before


def test_a_failed_rebuild_after_the_gateway_read_keeps_the_seal_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOOKKU_HOME", str(tmp_path / "home"))
    folder = _sealed_test(tmp_path)
    # A tap record that is not valid, sealed as it is: the seal is intact, the build fails.
    (folder / "tap.jsonl").write_text("not json\n")
    seal.write(folder, tmp_path / "home")
    logs = next(c for c in CASES if c.name == "toy_shop") / "spend_logs.json"
    args = ["trace", "--root", str(tmp_path), "--gateway", str(logs), "--key-alias", ALIAS]
    assert main(args) == 2
    assert "the trace was not rebuilt" in capsys.readouterr().err
    assert (folder / gateway.FILE).exists()
    assert seal.verify(folder)["intact"]

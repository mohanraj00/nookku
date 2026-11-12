"""The gateway key of a Koodam TestKey (SPEC.md section 7.16)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest
from test_bridge import homes as homes
from test_bridge import project
from toy_model_server import ModelServer

from nookku import bridge, discovery, seal, state, testkey

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "examples" / "toy-shop" / "gateway_agent.py"
KEY = "sk-toy-gateway-9f3c1e7a"
ALIAS = "tk-shop-test-1-0a1b2c3d"
ANSWER = json.dumps({"choices": [{"message": {"role": "assistant", "content": "mock answer"}}]})


def key_folder(path: Path, base_url: str = "http://gateway.toy:4000", **files: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    values = {"key": KEY, "alias": ALIAS, "base-url": base_url, "model": "mock-1", **files}
    for name, value in values.items():
        (path / name).write_text(value)
    return path


def test_no_folder_and_an_empty_folder_give_no_key(tmp_path: Path) -> None:
    assert testkey.read(tmp_path / "none") is None
    (tmp_path / "empty").mkdir()
    assert testkey.read(tmp_path / "empty") is None


def test_the_folder_gives_the_key_and_the_record_has_no_key(tmp_path: Path) -> None:
    folder = key_folder(tmp_path / "k", "http://gateway.toy:4000/\n", alias=ALIAS + "\n")
    key = testkey.read(folder)
    assert key is not None
    assert (key.key, key.alias, key.base_url, key.model) == (
        KEY,
        ALIAS,
        "http://gateway.toy:4000",
        "mock-1",
    )
    url = "http://gateway.toy:4000"
    assert key.record() == {"alias": ALIAS, "base_url": url, "model": "mock-1"}
    assert KEY not in repr(key)
    assert key.environment(["openai", "anthropic"]) == {
        "OPENAI_API_KEY": KEY,
        "ANTHROPIC_API_KEY": KEY,
        "NOOKKU_TEST_KEY_MODEL": "mock-1",
    }
    assert key.environment([]) == {}


def test_the_variable_gives_another_folder() -> None:
    assert testkey.folder({}) == testkey.FOLDER
    assert testkey.folder({testkey.DIR_ENV: "/tmp/k"}) == Path("/tmp/k")


@pytest.mark.parametrize(
    ("files", "error"),
    [
        ({"alias": "kd-agent-1"}, "does not have the form"),
        ({"alias": "tk-shop-ABCDEF12"}, "does not have the form"),
        ({"key": ""}, "the file key is empty"),
        ({"key": "sk two"}, "not visible ASCII"),
        ({"base-url": "ftp://gateway.toy"}, "is not an http or https URL"),
        ({"model": ""}, "the file model is empty"),
        ({"model": "x" * (testkey.LIMIT + 1)}, "more than 4096 bytes"),
    ],
)
def test_a_value_that_is_not_valid_is_an_error_with_no_key(
    tmp_path: Path, files: dict[str, str], error: str
) -> None:
    folder = key_folder(tmp_path / "k", **files)
    with pytest.raises(testkey.GatewayKeyError, match=error) as e:
        testkey.read(folder)
    assert KEY not in str(e.value)


def test_a_folder_with_some_of_the_files_is_an_error(tmp_path: Path) -> None:
    folder = key_folder(tmp_path / "k")
    (folder / "model").unlink()
    with pytest.raises(testkey.GatewayKeyError, match="has no file model"):
        testkey.read(folder)


def test_a_key_that_is_not_valid_stops_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(AGENT)])
    folder = key_folder(tmp_path / "k", alias="kd-agent-1")
    monkeypatch.setenv(testkey.DIR_ENV, str(folder))
    egress = {"registered": time.time(), "answer": discovery.make()}
    with pytest.raises(bridge.BridgeError, match="the test gateway key of Koodam"):
        bridge.start(root, egress=egress)
    assert state.current(root) is None


def test_a_model_api_with_another_url_stops_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(AGENT)])
    monkeypatch.setenv(testkey.DIR_ENV, str(key_folder(tmp_path / "k")))
    apis = [{"api": "openai", "env": "OPENAI_BASE_URL", "url": "https://other.toy/v1"}]
    egress = {"registered": time.time(), "answer": discovery.make(model_apis=apis)}
    with pytest.raises(bridge.BridgeError, match=re.escape("is for http://gateway.toy:4000")):
        bridge.start(root, egress=egress)
    assert state.current(root) is None


def test_a_test_sends_its_model_calls_with_its_own_key(
    tmp_path: Path, homes: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path, [sys.executable, str(AGENT)])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-tester-own-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.invalid/v1")
    with ModelServer() as gateway:
        gateway.parts = [ANSWER.encode()]
        gateway.content_type = "application/json"
        monkeypatch.setenv(testkey.DIR_ENV, str(key_folder(tmp_path / "k", gateway.url)))
        apis = [{"api": "openai", "env": "OPENAI_BASE_URL", "url": None}]
        egress = {"registered": time.time(), "answer": discovery.make(model_apis=apis)}
        cur = bridge.start(root, "tester-1", egress=egress)
        try:
            shown, ok = bridge.send(cur, "Is the blue mug in stock?")
        finally:
            bridge.end(root)
    assert ok and shown == "Toy shop: mock answer"
    # The gateway got the call through the proxy, with the key of the test and its model.
    [call] = gateway.seen
    assert call["path"] == "/chat/completions"
    assert ("Authorization", f"Bearer {KEY}") in call["headers"]
    assert json.loads(call["body"])["model"] == "mock-1"
    folder = Path(cur["dir"])
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["test_key"] == {"alias": ALIAS, "base_url": gateway.url, "model": "mock-1"}
    assert manifest["egress"]["proxies"]["openai"].startswith("http://127.0.0.1:")
    assert seal.verify(folder)["intact"]
    # No file of the test folder and no file of the state folder holds the key.
    files = [p for d in (folder, root / ".nookku") for p in d.rglob("*") if p.is_file()]
    assert files
    assert [p for p in files if KEY.encode() in p.read_bytes()] == []

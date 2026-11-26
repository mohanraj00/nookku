"""Run the Node helper with the contract lines that an entry reads and writes."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from nookku import contract

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "src" / "nookku" / "helpers" / "contract.mjs"
EXAMPLE = ROOT / "examples" / "toy-shop-node" / "contract.mjs"
CASES = ROOT / "conformance" / "contract"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def case(name: str) -> dict:
    return json.loads((CASES / name / "case.json").read_text(encoding="utf-8"))


def run_node(script: str, stdin: bytes) -> subprocess.CompletedProcess[bytes]:
    assert NODE is not None
    code = f"import {{ serve }} from {json.dumps(HELPER.as_uri())};\n{script}"
    result = subprocess.run(
        [NODE, "--input-type=module", "--eval", code],
        input=stdin,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result


@pytest.mark.skipif(not EXAMPLE.parent.is_dir(), reason="the sdist has no examples folder")
def test_the_example_uses_the_packaged_helper() -> None:
    assert EXAMPLE.read_bytes() == HELPER.read_bytes()


@needs_node
@pytest.mark.parametrize(
    "name", ["reply_is_exact", "other_fields_are_ignored", "error_is_status_500"]
)
def test_the_helper_speaks_the_contract(name: str) -> None:
    data = case(name)
    line = data["requests"][0]
    request = json.loads(line)
    expected = data["rows"][0]
    message = json.dumps(request["message"])
    history = json.dumps(request["history"])
    if expected["reply"] is None:
        field = {"error": f"Error: {expected['error']}"}
        action = f"throw new Error({json.dumps(expected['error'])});"
    else:
        field = {"reply": expected["reply"]}
        action = f"return {json.dumps(expected['reply'])};"
    result = run_node(
        f"""
        import assert from "node:assert/strict";
        await serve((message, history) => {{
          assert.deepEqual(message, {message});
          assert.deepEqual(history, {history});
          {action}
        }});
        """,
        line.encode("utf-8") + b"\n",
    )
    output, end = result.stdout.split(b"\n")
    assert json.loads(output) == {"v": 1, "id": request["id"], **field}
    assert end == result.stderr == b""


@needs_node
def test_the_helper_keeps_console_output_off_stdout() -> None:
    log = case("stray_lines_before_the_reply")["agent"][0]["lines"][0]
    text = " Mug  \r\n € ₹ 🧸\u2028Teapot\u2029  "
    first = contract.request("log", "test", "Load the catalog", [])
    last = contract.request("ok", "test", text, [])
    result = run_node(
        f"""
        import {{ log }} from "node:console";
        console.info("toy shop ready");
        await serve((message) => {{
          if (message === "Load the catalog") {{
            log({json.dumps(log)});
            console.debug("catalog debug");
            console.warn("catalog warning");
            console.error("catalog error");
            process.stdout.write("catalog stdout\\n");
          }}
          return message;
        }});
        """,
        first + b"\r\n" + last + b"\n",
    )
    one, two, end = result.stdout.split(b"\n")
    assert contract.parse_reply(one, "log") == ("Load the catalog", None)
    assert contract.parse_reply(two, "ok") == (text, None)
    assert end == b""
    for line in (
        "toy shop ready",
        log,
        "catalog debug",
        "catalog warning",
        "catalog error",
        "catalog stdout",
    ):
        assert line.encode("utf-8") + b"\n" in result.stderr


@needs_node
@pytest.mark.parametrize(
    "line",
    [
        b"",
        b"not JSON",
        b"\xff",
        b"\xff\r ",
        b'[{"message":"mug"}]',
        b'{"v":true}',
        b'{"v":1}',
        b'{"v":1,"id":"bad","session":"test","message":5}',
        b'{"v":1,"id":"bad","session":"test","message":"Mug"}',
        b'{"v":1,"id":"bad","session":"test","message":"Mug","history":[null]}',
        b'{"v":1,\r"id":"bad"}',
        b'{"extra":["NaN",{"stock":NaN}]}',
        b'{"extra":Infinity}',
        b'{"extra":-Infinity',
        b"{NaN:0}",
    ],
)
def test_the_helper_answers_an_invalid_request_and_continues(line: bytes) -> None:
    with pytest.raises(contract.ContractError) as error:
        contract.parse_request(line)
    request = contract.request("mug", "test", "Mug", [])
    result = run_node("await serve((message) => message);", line + b"\n" + request + b"\n")
    bad, good, end = result.stdout.split(b"\n")
    assert json.loads(bad) == {"v": 1, "id": "", "error": f"nookku agent: {error.value}"}
    assert contract.parse_reply(good, "mug") == ("Mug", None)
    assert end == result.stderr == b""


@needs_node
def test_the_helper_continues_after_a_rejection_and_a_wrong_return_type() -> None:
    result = run_node(
        """
        await serve(async (message) => {
          if (message === "order") {
            const error = new Error("The order service is down.");
            error.name = "OrderError";
            throw error;
          }
          if (message === "stock") throw "Stock is unknown.";
          if (message === "number") return 1;
          return "";
        });
        """,
        b"".join(
            contract.request(message, "test", message, []) + b"\n"
            for message in ("order", "stock", "number", "mug")
        ),
    )
    order, stock, number, mug, end = result.stdout.split(b"\n")
    assert contract.parse_reply(order, "order") == (None, "OrderError: The order service is down.")
    assert contract.parse_reply(stock, "stock") == (None, "Stock is unknown.")
    assert contract.parse_reply(number, "number") == (
        None,
        "TypeError: reply() must return a string",
    )
    assert contract.parse_reply(mug, "mug") == ("", None)
    assert end == result.stderr == b""


@needs_node
def test_the_helper_answers_the_last_line_without_a_newline() -> None:
    last = contract.request("mug", "test", "Mug", [])
    result = run_node("await serve((message) => message);", last)
    output, end = result.stdout.split(b"\n")
    assert contract.parse_reply(output, "mug") == ("Mug", None)
    assert end == result.stderr == b""

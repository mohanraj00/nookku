"""The gateway logs of SPEC.md section 8.9: the model calls that a LiteLLM gateway logged.

If the app gets its model key from a LiteLLM gateway, the spend logs of the gateway have each
model call of that key. `nookku trace --gateway` reads them from a file or from the gateway API,
keeps the calls of the key aliases that the tester gives in the time window of the test, and
writes them to gateway.jsonl in the test folder. The trace reads gateway.jsonl as it reads
model_api.jsonl. Nookku sends nothing to the gateway except the read of its logs.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from . import model_api
from .config import is_http_url
from .record import json_text, loads

FILE = "gateway.jsonl"
GATEWAY = "litellm"
# The variable that holds the key of the gateway API. Nookku never writes its value.
KEY_VARIABLE = "NOOKKU_GATEWAY_KEY"
# The largest log that Nookku reads, from a file or from the API. A chosen value, not a
# measurement: the parse holds all of the log in memory.
READ_LIMIT = 256 * 1024 * 1024
# The wait for the gateway API, in seconds.
TIMEOUT = 60.0
# The mark that LiteLLM puts in a string that it cut before it stored the log (LiteLLM 1.104.2).
TRUNCATED = "(litellm_truncated skipped "
# The LiteLLM call types that are model calls: the API and the path of the call. The path selects
# the format of the request and of the result (model_api.CALLS).
CALL_TYPES = {
    "completion": ("openai", "/v1/chat/completions"),
    "acompletion": ("openai", "/v1/chat/completions"),
    "anthropic_messages": ("anthropic", "/v1/messages"),
    "responses": ("openai", "/v1/responses"),
    "aresponses": ("openai", "/v1/responses"),
}
# The keys of the request that LiteLLM adds or that can hold a secret. LiteLLM puts the hash of
# the key and the request headers in `metadata` and `litellm_metadata`.
DROPPED = ("metadata", "litellm_metadata", "litellm_call_id", "extra_headers")
SECRET_PARTS = ("api_key", "secret", "password", "authorization")


class GatewayError(ValueError):
    """The gateway logs cannot be read. The message gives the cause and the next step."""


def parse_time(value: Any) -> float | None:
    """The Unix time of a LiteLLM time: an ISO 8601 text, in UTC if it has no zone, or a number."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "T", 1)
    text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    # Python 3.10 reads only 3 or 6 digits after the point.
    text = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when.timestamp()


def _object(value: Any) -> dict[str, Any] | None:
    """A JSON object of a log: an object, or a text of an object. An empty object is None."""
    if isinstance(value, str):
        try:
            value = loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) and value else None


def _secret(name: str) -> bool:
    low = name.lower()
    return low in DROPPED or any(part in low for part in SECRET_PARTS)


def _cut(value: Any) -> bool:
    return value is not None and TRUNCATED in json_text(value)


def result(api: str, path: str, response: dict[str, Any] | None) -> dict[str, Any] | None:
    """The result of a logged call (SPEC.md section 7.7), or None if the log has no response.
    LiteLLM can store the response in the form of an other API, so the shape selects the parser:
    `choices` for Chat Completions, `output` for Responses, and a `content` list for Messages."""
    if response is None:
        return None
    if isinstance(response.get("choices"), list):
        parse = model_api.openai
    elif isinstance(response.get("output"), list):
        parse = model_api.responses
    elif isinstance(response.get("content"), list):
        parse = model_api.anthropic
    else:
        form = model_api.call_format(api, path)
        parse = model_api.PARSERS[form] if form else model_api.openai
    return parse(json_text(response).encode("utf-8"), False)


def call_row(log: dict[str, Any]) -> dict[str, Any]:
    """The row of gateway.jsonl for one LiteLLM spend log (SPEC.md section 8.9)."""
    given = log.get("metadata")
    meta: dict[str, Any] = given if isinstance(given, dict) else {}
    call_type = str(log.get("call_type") or "")
    api, path = CALL_TYPES.get(call_type, (None, None))
    tags = log.get("request_tags")
    request = _object(log.get("proxy_server_request"))
    if request is not None:
        request = {k: v for k, v in request.items() if not _secret(str(k))}
    response = _object(log.get("response"))
    failed = meta.get("error_information")
    info: dict[str, Any] = failed if isinstance(failed, dict) else {}
    status, error = None, None
    if log.get("status") != "success":
        message = info.get("error_message")
        error = str(message) if message else f"the gateway logged the status {log.get('status')}"
        code = str(info.get("error_code") or "")
        status = int(code) if code.isdigit() and len(code) <= 3 else None
    out = {
        "v": 1,
        "type": "call",
        "gateway": GATEWAY,
        "request_id": log.get("request_id"),
        "call_type": call_type,
        "api": api,
        "path": path,
        "key_alias": meta.get("user_api_key_alias"),
        "tags": [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else [],
        "started": parse_time(log.get("startTime")),
        "ts": parse_time(log.get("endTime")),
        "status": status,
        "error": error,
        "request": request,
        "request_cut": _cut(request),
        "response": response,
        "response_cut": _cut(response) or _cut(log.get("response")),
        "result": None,
    }
    if api is not None and path is not None:
        out["result"] = result(api, path, response)
    return out


def logs(data: bytes) -> list[Any]:
    """The spend logs of a file or of the API: a JSON list (GET /spend/logs), an object with a
    `data` list (GET /spend/logs/v2), or one JSON object on each line."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise GatewayError(f"the gateway log is not UTF-8 ({e.reason}).") from None
    try:
        whole = loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, list):
        return whole
    if isinstance(whole, dict) and isinstance(whole.get("data"), list):
        return list(whole["data"])
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            out.append(loads(line))
        except ValueError:
            raise GatewayError(
                f"line {n} of the gateway log is not JSON. Give the output of "
                "GET /spend/logs of LiteLLM, as a JSON list or as one JSON object on each line."
            ) from None
    return out


def select(
    found: list[Any], aliases: list[str], tag: str | None, start: float, end: float
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The rows of the logs of a key alias in the window from start to end, both ends included,
    sorted by their start, and the count of the logs that were skipped, by reason."""
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for log in found:
        if not isinstance(log, dict):
            skipped["not_a_log"] += 1
            continue
        row = call_row(log)
        if row["key_alias"] not in aliases:
            skipped["other_key"] += 1
        elif row["started"] is None or not start <= row["started"] <= end:
            skipped["outside_test"] += 1
        elif tag is not None and tag not in row["tags"]:
            skipped["no_tag"] += 1
        else:
            rows.append(row)
    rows.sort(key=lambda r: r["started"])
    return rows, dict(skipped)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse each redirect, so that the key never goes to an other URL."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _day(t: float, days: int = 0) -> str:
    when = datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(days)
    return when.strftime("%Y-%m-%d")


def logs_url(base: str, start: float, end: float) -> str:
    """The URL of the full spend logs of the days of the window, in UTC (LiteLLM 1.104.2)."""
    query = {"start_date": _day(start), "end_date": _day(end, 1), "summarize": "false"}
    return f"{base.rstrip('/')}/spend/logs?{urllib.parse.urlencode(query)}"


def fetch(base: str, start: float, end: float, key: str) -> bytes:
    """The spend logs of the gateway API for the days of the window."""
    req = urllib.request.Request(logs_url(base, start, end))
    req.add_header("Authorization", f"Bearer {key}")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            data: bytes = resp.read(READ_LIMIT + 1)
    except urllib.error.HTTPError as e:
        raise GatewayError(
            f"the gateway gave the status {e.code} for GET /spend/logs. Make sure that "
            f"{KEY_VARIABLE} holds a key that can read the spend logs."
        ) from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise GatewayError(f"the gateway did not answer ({reason}). Check the URL.") from None
    if len(data) > READ_LIMIT:
        raise GatewayError(f"the gateway log is larger than {READ_LIMIT} bytes.")
    return data


def _loopback(url: str) -> bool:
    """True if the host of the URL is this computer: localhost or a loopback address."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read(source: str, start: float, end: float, environ: dict[str, str] | None = None) -> bytes:
    """The bytes of the logs: a GET of the gateway API for an http or https URL, else a file."""
    if source.startswith(("http://", "https://")):
        if not is_http_url(source) or urllib.parse.urlsplit(source).query:
            raise GatewayError(f"the gateway URL is not valid: {source!r}.")
        if source.startswith("http://") and not _loopback(source):
            # The key goes in a header, so it must not go over plain text on a network.
            raise GatewayError(
                f"the gateway URL {source_name(source)} is not https. Nookku sends "
                f"{KEY_VARIABLE} only over https, or over http to this computer."
            )
        key = (environ if environ is not None else dict(os.environ)).get(KEY_VARIABLE)
        if not key:
            raise GatewayError(
                f"{KEY_VARIABLE} has no value. Put a key that can read the spend logs in it."
            )
        return fetch(source, start, end, key)
    path = Path(source)
    try:
        with path.open("rb") as f:
            data = f.read(READ_LIMIT + 1)
    except OSError as e:
        raise GatewayError(f"cannot read the gateway log {source}: {e.strerror}.") from None
    if len(data) > READ_LIMIT:
        raise GatewayError(f"the gateway log is larger than {READ_LIMIT} bytes.")
    return data


def source_name(source: str) -> str:
    """The source for the record: a URL with no user and no query, or the name of the file."""
    if source.startswith(("http://", "https://")):
        parts = urllib.parse.urlsplit(source)
        host = parts.hostname or ""
        host = f"[{host}]" if ":" in host else host
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{host}{port}{parts.path}"
    return Path(source).name


def load(
    folder: Path,
    manifest: dict[str, Any],
    source: str,
    aliases: list[str],
    tag: str | None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read the logs, and write gateway.jsonl in the test folder. Return its source row."""
    start, end = manifest.get("started"), manifest.get("ended")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise GatewayError("the test has no start or no end time. End the test first.")
    rows, skipped = select(logs(read(source, start, end, environ)), aliases, tag, start, end)
    head = {
        "v": 1,
        "type": "source",
        "gateway": GATEWAY,
        "source": source_name(source),
        "key_aliases": aliases,
        "tag": tag,
        "window": [start, end],
        "read": time.time(),
        "kept": len(rows),
        "skipped": skipped,
    }
    text = "".join(json_text(r) + "\n" for r in [head, *rows])
    (folder / FILE).write_text(text, encoding="utf-8")
    return head

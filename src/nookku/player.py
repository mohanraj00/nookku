"""The players of a replay with the recorded backends (#523, SPEC.md section 7.10, "Recorded
backends").

In a replay with `--recorded`, each HTTP proxy of the test (a backend, a model API or an MCP server
over HTTP) is a player. It answers each request of the app with a response of the base test, and
makes no outside call. The proxy code stays the same: the player gives the proxy a connection
object that answers from the record, so the proxy reads the request, writes its row and sends the
response to the app as it does for a live backend.

A request matches the first unused call of the base record of its proxy with the same method,
path, query and SHA-256 of the request body, in the order of `started`. A request with no such
call, or with a call that the record cannot give again, is a miss: the app gets status 502.
The match rules of a proxy (the config key `replay_ignore`) remove declared query parameters and
JSON body values before the compare.

Each player has a new random token. The URL that the app gets has the token as the first part of
its path, and the proxy refuses a request with no token with status 403. Thus another local
process that finds the port of a player does not get the recorded responses.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from nookku.record import loads

# The prefix of the error of a row whose backend did not answer (SPEC.md section 7.6).
NO_ANSWER = "the backend did not answer: "
# The prefix of the error of a row whose response stopped before its end.
STOPPED = "the stream stopped: "
# The prefix of the error of a row whose request upload stopped. The player never gets such a
# request, because the proxy stops it first.
UPLOAD_STOPPED = "the request stream stopped: "
# The error of a row of a call that was open at the end of the test (backend.ENDED).
ENDED = "the test ended before the backend answered"
# The error of a row of a response that was open at the end of the test (backend.STREAM_ENDED).
STREAM_ENDED = "the test ended before the stream ended"

# The reasons of a miss. Each one is the text after `the replay has no recorded response: `.
NO_CALL = "the base test has no unused call with this method, path, query and body"
CUT = "the recorded response is cut at record_limit"
OMITTED = "the record of a harness call keeps no body"
OPEN = "the base test ended before this call ended"
NOT_SAME = "the recorded body does not have its SHA-256"
MISS = "the replay has no recorded response"
REMOVED = "a recorded response header has a removed secret value"
NO_LENGTH = "the record has no length of a response with no body"
# The error of a request to a player with no token in its path.
NO_TOKEN = "nookku player: the request path has no token of this test"
# The value that backend.headers_row writes for a secret header (SPEC.md section 7.6).
REMOVED_VALUE = "<removed>"


class Miss(OSError):
    """The player has no response for a request. The proxy then sends status 502."""


def calls(data: bytes, field: str, name: str) -> list[tuple[int, dict[str, Any]]]:
    """The call rows of the proxy `name` in the bytes of a record file, with the number of each
    line (from 1), in the order of `started` and then of the lines. `field` is the field of the
    name: `backend`, `api` or `server`. A row that is not a JSON object, a row of another type or
    proxy, and a row with no request body (a refused request) does not count. A row of a stopped
    upload does not count either, because the proxy stops such a request before the player."""
    out: list[tuple[int, dict[str, Any]]] = []
    for n, line in enumerate(data.split(b"\n"), 1):
        if not line.strip():
            continue
        try:
            row = loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("type") != "call" or row.get(field) != name:
            continue
        error = row.get("error")
        if not isinstance(row.get("request_body"), dict):
            continue
        if isinstance(error, str) and error.startswith(UPLOAD_STOPPED):
            continue
        out.append((n, row))
    started = [r.get("started") for _, r in out]
    key = [s if isinstance(s, (int, float)) and not isinstance(s, bool) else 0.0 for s in started]
    order = sorted(range(len(out)), key=lambda i: (key[i], out[i][0]))
    return [out[i] for i in order]


def request_key(row: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """The part of a call row that a match compares: the method, the path, the query and the
    SHA-256 of the request body."""
    body = row.get("request_body")
    sha = body.get("sha256") if isinstance(body, dict) else None
    return (row.get("method"), row.get("path"), row.get("query"), sha)


def match(
    recorded: list[tuple[int, dict[str, Any]]],
    used: set[int],
    request: dict[str, Any],
    rules: dict[str, list[str]] | None = None,
) -> tuple[int | None, list[str]]:
    """The index in `recorded` of the first call that is not in `used` and has the method, the
    path, the query and the body SHA-256 of `request`, else None. With match rules, the query
    and the body compare with no ignored part. The second value is the sorted list of the rules
    that the match used (SPEC.md section 7.10, "Match rules")."""
    want = request_key(request)
    for i, (_, row) in enumerate(recorded):
        if i in used:
            continue
        if not rules:
            if request_key(row) == want:
                return i, []
            continue
        ignored = _ruled(rules, request, row)
        if ignored is not None:
            return i, ignored
    return None, []


def _ruled(rules: dict[str, list[str]], a: dict[str, Any], b: dict[str, Any]) -> list[str] | None:
    """The rules whose values are not the same in 2 call rows, or None if the rows do not match
    with the rules."""
    if (a.get("method"), a.get("path")) != (b.get("method"), b.get("path")):
        return None
    ignored: list[str] = []
    names = set(rules.get("query", []))
    qa, qb = a.get("query"), b.get("query")
    if names:
        # An absent query is None in a row, and an empty query for the query rules.
        qa, qb = ("" if q is None else q for q in (qa, qb))
    if names and isinstance(qa, str) and isinstance(qb, str):
        kept = [_query(qa, names, False), _query(qb, names, False)]
        if kept[0] != kept[1]:
            return None
        for name in sorted(names):
            if _query(qa, {name}, True) != _query(qb, {name}, True):
                ignored.append(f"query:{name}")
    elif qa != qb:
        return None
    paths = rules.get("body", [])
    ja, jb = _json_body(a), _json_body(b)
    if not paths or ja is _NOT_JSON or jb is _NOT_JSON:
        return ignored if request_key(a)[3] == request_key(b)[3] else None
    if _canonical(_without(ja, paths)) != _canonical(_without(jb, paths)):
        return None
    for path in paths:
        if _at(ja, path) != _at(jb, path):
            ignored.append(f"body:{path}")
    return sorted(ignored)


def _query(query: str, names: set[str], keep: bool) -> list[str]:
    """The parts of a query with a name in `names` (keep) or with no such name."""
    parts = query.split("&") if query else []
    return [p for p in parts if (p.split("=", 1)[0] in names) == keep]


_NOT_JSON = object()


def _json_body(row: dict[str, Any]) -> Any:
    """The JSON value of the complete text of a request body, or _NOT_JSON."""
    body = row.get("request_body")
    if not isinstance(body, dict) or body.get("cut") is not False:
        return _NOT_JSON
    text = body.get("text")
    if not isinstance(text, str):
        return _NOT_JSON
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return _NOT_JSON


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _step(data: Any, key: str) -> tuple[bool, Any]:
    if isinstance(data, dict) and key in data:
        return True, data[key]
    if isinstance(data, list) and key.isdigit() and int(key) < len(data):
        return True, data[int(key)]
    return False, None


def _at(data: Any, path: str) -> str | None:
    """The JSON text of the value at a dot path, or None if the path has no value."""
    for key in path.split("."):
        found, data = _step(data, key)
        if not found:
            return None
    return _canonical(data)


def _without(data: Any, paths: list[str]) -> Any:
    """A copy of a JSON value with no value at each path. A key of an object goes, and an item
    of a list becomes null, so the other indexes do not change."""
    data = json.loads(_canonical(data))
    for path in paths:
        *head, last = path.split(".")
        parent: Any = data
        for key in head:
            found, parent = _step(parent, key)
            if not found:
                break
        else:
            if isinstance(parent, dict):
                parent.pop(last, None)
            elif _step(parent, last)[0]:
                parent[int(last)] = None
    return data


def body_bytes(body: Any) -> tuple[bytes | None, str | None]:
    """The bytes that a recorded response body gives to the app, and the reason of a miss if the
    record cannot give them. A decoded body gives its decoded bytes."""
    if not isinstance(body, dict):
        return None, CUT
    if body.get("omitted"):
        return None, OMITTED
    if body.get("cut") is not False:
        return None, CUT
    try:
        if isinstance(body.get("text"), str):
            data = body["text"].encode("utf-8")
        elif isinstance(body.get("base64"), str):
            data = base64.b64decode(body["base64"], validate=True)
        else:
            return None, CUT
    except (ValueError, UnicodeEncodeError):
        return None, NOT_SAME
    if body.get("decoded") is None and hashlib.sha256(data).hexdigest() != body.get("sha256"):
        return None, NOT_SAME
    return data, None


class Response:
    """A recorded response, with the part of the interface of http.client.HTTPResponse that the
    proxy reads. `stopped` is the reason of a stream that stopped: `read1` raises it after the
    last byte, as a live stream does."""

    def __init__(
        self, status: int, headers: list[tuple[str, str]], data: bytes, stopped: str | None
    ) -> None:
        self.status = status
        self.headers = headers
        self.data = data
        self.stopped = stopped
        # A stopped stream goes to the app chunked, as a live one with no length does.
        self.chunked = stopped is not None
        self.length: int | None = None if self.chunked else len(data)

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self.headers)

    def getheader(self, name: str, default: str | None = None) -> str | None:
        low = name.lower()
        return next((v for k, v in self.headers if k.lower() == low), default)

    def read1(self, n: int = -1) -> bytes:
        size = len(self.data) if n < 0 else n
        part, self.data = self.data[:size], self.data[size:]
        if self.length is not None:
            self.length -= len(part)
        if not part and self.stopped is not None:
            raise OSError(self.stopped)
        return part


def response(row: dict[str, Any]) -> Response | Miss | OSError:
    """What the player gives for a recorded call: a response, a miss, or the error of a backend
    that did not answer. The app then gets status 502, as in the base test."""
    error = row.get("error")
    status = row.get("status")
    headers = row.get("response_headers")
    if not isinstance(status, int) or isinstance(status, bool) or not isinstance(headers, list):
        if isinstance(error, str) and error.startswith(NO_ANSWER):
            return OSError(error[len(NO_ANSWER) :])
        return Miss(f"{MISS}: {OPEN}" if error == ENDED else f"{MISS}: {CUT}")
    if error == STREAM_ENDED:
        # The record has only the start of the response.
        return Miss(f"{MISS}: {OPEN}")
    data, reason = body_bytes(row.get("response_body"))
    if data is None:
        return Miss(f"{MISS}: {reason}")
    pairs = [(str(h[0]), str(h[1])) for h in headers if isinstance(h, list) and len(h) == 2]
    if any(v == REMOVED_VALUE for _, v in pairs):
        # The record has no true value, and a placeholder would change the input of the app.
        return Miss(f"{MISS}: {REMOVED}")
    if row.get("method") == "HEAD" or status in (204, 304):
        # The proxy gives the length of a response with no body from the record. A row of an
        # older Nookku has no length, so the player cannot give the same response.
        if "response_length" not in row:
            return Miss(f"{MISS}: {NO_LENGTH}")
        if isinstance(row["response_length"], str):
            pairs.append(("Content-Length", row["response_length"]))
    if isinstance(row["response_body"], dict) and row["response_body"].get("decoded"):
        # The record keeps the decoded body, so the app gets it with no Content-Encoding.
        pairs = [(k, v) for k, v in pairs if k.lower() != "content-encoding"]
    stopped = None
    if isinstance(error, str) and error.startswith(STOPPED):
        stopped = error[len(STOPPED) :]
    return Response(status, pairs, data, stopped)


class Player:
    """The recorded calls of one proxy. One lock keeps each recorded call for one request."""

    def __init__(
        self,
        recorded: list[tuple[int, dict[str, Any]]],
        rules: dict[str, list[str]] | None = None,
    ) -> None:
        self.recorded = recorded
        # The match rules of the proxy (SPEC.md section 7.10, "Match rules").
        self.rules = rules or {}
        self.used: set[int] = set()
        self.lock = threading.Lock()
        # The first part of the path of each request to the player (SPEC.md section 7.10).
        self.token = secrets.token_urlsafe(32)

    def strip(self, target: str) -> str | None:
        """The request target with no token prefix, or None if it does not start with the
        token of the player."""
        prefix = "/" + self.token
        if not hmac.compare_digest(target[: len(prefix)].encode(), prefix.encode()):
            return None
        rest = target[len(prefix) :]
        if rest[:1] not in ("", "/", "?"):
            return None
        return rest if rest.startswith("/") else "/" + rest

    @classmethod
    def load(
        cls, path: Path, field: str, name: str, rules: dict[str, list[str]] | None = None
    ) -> Player:
        """The player of the proxy `name` from a copied record file, with its match rules. A
        file that does not exist gives a player with no calls."""
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b""
        return cls(calls(data, field, name), rules)

    def answer(self, request: dict[str, Any]) -> tuple[int | None, Response | OSError, list[str]]:
        """The line of the matched call in the base record (or None), what the proxy gives to
        the app, and the rules that the match used."""
        with self.lock:
            i, ignored = match(self.recorded, self.used, request, self.rules)
            if i is None:
                return None, Miss(f"{MISS}: {NO_CALL}"), []
            self.used.add(i)
        line, row = self.recorded[i]
        return line, response(row), ignored


def play(path: Path, proxies: list[Any], rules: dict[str, dict[str, list[str]]]) -> list[str]:
    """Make each proxy a player with its calls of the copied base record at `path` and the match
    rules of its name (SPEC.md section 7.10). Return a log line for each player."""
    out = []
    for p in proxies:
        name = p.backend.name
        p.player = Player.load(path, p.target_field, name, rules.get(name))
        out.append(f"player {name}: {len(p.player.recorded)} recorded calls")
    return out


class Connection:
    """A connection of a player, with the part of the interface of http.client.HTTPConnection
    that the proxy uses. It sends nothing on a network. `getresponse` answers from the record,
    with the request fields of the row of the call, after the proxy wrote them."""

    def __init__(self, player: Player, row: dict[str, Any], lock: threading.Condition) -> None:
        self.player = player
        self.row = row
        self.lock = lock

    def putrequest(self, *args: Any, **kwargs: Any) -> None:
        pass

    def putheader(self, *args: Any) -> None:
        pass

    def endheaders(self, body: bytes | None = None) -> None:
        pass

    def send(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        pass

    def getresponse(self) -> Response:
        line, out, ignored = self.player.answer(self.row)
        miss = str(out) if isinstance(out, Miss) else None
        with self.lock:
            self.row["replay"] = {"line": line, "miss": miss, "ignored": [] if miss else ignored}
        if isinstance(out, OSError):
            raise out
        return out


def case(
    recorded: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    rules: dict[str, dict[str, list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """The outcome of each request of a conformance case (conformance/replay/): the line of the
    matched call and the miss, or the status, the body and the Content-Length that the app
    gets, and the rules that the match used. `rules` is the manifest value `replay.ignore`."""
    data = b"".join(json.dumps(r).encode() + b"\n" for r in recorded)
    names = {r.get("backend") for r in requests}
    rules = rules or {}
    players = {n: Player(calls(data, "backend", str(n)), rules.get(str(n))) for n in names}
    out = []
    for r in requests:
        line, got, ignored = players[r.get("backend")].answer(r)
        if isinstance(got, Response):
            body, stopped = b"", None
            try:
                while part := got.read1(65536):
                    body += part
            except OSError as e:
                stopped = str(e)
            out.append(
                {
                    "line": line,
                    "miss": None,
                    "status": got.status,
                    "body": body.decode(),
                    "stopped": stopped,
                    "length": got.getheader("Content-Length"),
                    "ignored": ignored,
                }
            )
        else:
            miss = str(got) if isinstance(got, Miss) else None
            out.append(
                {
                    "line": line,
                    "miss": miss,
                    "status": 502,
                    "body": None,
                    "stopped": None,
                    "length": None,
                    "ignored": [],
                }
            )
    return out

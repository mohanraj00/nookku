# API reference

`nookku dashboard` serves a read-only HTTP API of the runs and the gate runs of one project ([cli.md](cli.md#nookku-dashboard)). A script and the dashboard of [examples/evaluation-dashboard/](../../examples/evaluation-dashboard/) read the same data. The code is [src/nookku/api.py](../../src/nookku/api.py), and `tests/test_api.py` checks each route.

## Version

The API version is 1. Each route starts with `/api/v1`, and each JSON answer has the key `"api": 1`. A change that removes or renames a key, or that changes the type of a value, gets a new version and a new prefix. A new key does not change the version, so a client must ignore a key that it does not know.

## Rules of each answer

- The API answers only `GET` and `HEAD`. `POST`, `PUT`, `DELETE` and `PATCH` get status 405 with `{"api": 1, "error": "the API is read-only"}`.
- The API reads the files of the [test folders](glossary.md#test-folder) and of the gate folders. It changes no file, and it writes no [seal](glossary.md#seal) copy.
- A run or a gate run that does not exist, and a path that is not a route, get status 404 with `{"api": 1, "error": "..."}`. An id must be the name of a folder, so a path cannot leave the tests folder or the gates folder.
- Each request to `/api/v1` must send the header `Authorization: Bearer <token>`. The server makes a new random token each time it starts, and `nookku dashboard` prints it ([cli.md](cli.md#nookku-dashboard)). A request with no token or a wrong token gets status 401 with `{"api": 1, "error": "no valid token"}`. Thus a process of another user on the same computer cannot read the records through the port. The static files of `--site` need no token, so the site folder must hold no record.
- The server holds at most 64 open connections. A connection above this limit gets status 503 before the server reads a byte. A connection that sends no part of a request for 10 seconds closes. Thus a client with no token cannot keep the threads of the server.
- A request with a `Host` header that is not the address of the server gets status 403 with `{"api": 1, "error": "wrong Host header"}`. With `127.0.0.1`, the server also accepts `localhost` and `[::1]` at the same port. This stops a page of another site that reaches the server through a DNS name that points to `127.0.0.1`.
- Each answer has `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and a Content Security Policy that lets a page load only files of the same server. The server sends no CORS header, so a page of another origin cannot read an answer.
- A time is a number of seconds since 1970-01-01 UTC, as in `manifest.json`.

## Seals

The seal of a test is in its folder and a copy is outside the folder ([SPEC.md section 7.4](../../SPEC.md#74-seal)). The API marks a run with a broken seal in 2 ways:

- `seal` of a run is `intact`, `broken`, `none` (the run has no seal) or `unknown` (a file cannot be read), with the rule of `nookku verify`.
- `sealed` of a file is `true` only if the seal of the folder is intact, its copy is the same, and the SHA-256 of the bytes that the API read is the SHA-256 in the copy. A file that changed after the seal, or that the seal does not cover, gives `false`. The API still gives its content, so a person can see what changed. Do not use a file with `"sealed": false` as evidence.

A verdict is in an answer only if a process can use it: the verdict agrees with the copy of the seal ([SPEC.md section 7.14](../../SPEC.md#714-verdict), "The verdict of an exit code"). Else the verdict is `null`, and a problem gives the reason.

## Routes

### `GET /api/v1`

The version and the routes.

```json
{"api": 1, "routes": ["/api/v1/runs", "/api/v1/runs/<run>", "..."]}
```

### `GET /api/v1/runs`

Each run of the tests folder, the newest first. A run is a test: a conversation from a [harness](glossary.md#harness) or from a script.

```json
{
 "api": 1,
 "runs": [
  {
   "id": "20261119-124100-f583",
   "started": 1795066860.2,
   "ended": 1795066861.9,
   "state": "ended",
   "turns": 2,
   "breaks": 0,
   "findings": 0,
   "seal": "intact",
   "errors": [],
   "verdict": "pass",
   "verdict_problem": null
  }
 ]
}
```

| Key | Type | Meaning |
|---|---|---|
| `id` | string | The test id. |
| `started`, `ended` | number or null | The start time and the end time from `manifest.json`. |
| `state` | string | `running`, `ended`, `stopped` (no end time) or `unknown` (no manifest). |
| `turns` | integer or null | The count of turns in `relay.jsonl`. |
| `breaks` | integer or null | The count of [breaks](glossary.md#break) in `audit.json`. |
| `findings` | integer or null | The count of [findings](glossary.md#findings) in `findings.json`. |
| `seal` | string | `intact`, `broken`, `none` or `unknown`. |
| `errors` | list of strings | Each file of the run that cannot be read or is not valid. |
| `verdict` | string or null | `pass` or `fail`, or null if a process cannot use the verdict. |
| `verdict_problem` | string or null | Why the verdict is null. A running test has `The run has not ended.` |

### `GET /api/v1/runs/<run>`

One run, with the keys of a row of `/runs`.

```json
{"api": 1, "run": {"id": "20261119-124100-f583", "...": "..."}}
```

### `GET /api/v1/runs/<run>/verdict`

The verdict report of `verdict.json` ([SPEC.md section 7.14](../../SPEC.md#714-verdict)), only if a process can use it.

```json
{"api": 1, "run": "20261119-124100-f583", "verdict": {"verdict": "pass", "classes": ["..."]}, "problem": null}
```

`verdict` is the object of `verdict.json`, or null. `problem` is null, or the reason why the verdict cannot be used.

### `GET /api/v1/runs/<run>/findings`

The content of `findings.json` ([SPEC.md section 8.6](../../SPEC.md#86-findings)).

```json
{"api": 1, "run": "20261119-124100-f583", "findings": {"counts": {"agent_error": 0}, "findings": []}, "sealed": true, "error": null}
```

`findings` is the JSON object of the file, or null if the file is missing or not valid. `error` is null, or the reason why the file is not valid.

### `GET /api/v1/runs/<run>/evaluation`

The text of `report.md`, the report of the [evaluation](glossary.md#evaluation) ([SPEC.md section 9.3](../../SPEC.md#93-report)). A model writes this report, so the API gives it as text, and no code reads it.

```json
{"api": 1, "run": "20261119-124100-f583", "report": "# Report\n...", "sealed": false, "error": null}
```

`report` is null if the run has no report. `error` is set if the file is not UTF-8.

### `GET /api/v1/gates`

Each gate run of the project, the newest first ([SPEC.md section 7.15](../../SPEC.md#715-gate-run)).

```json
{
 "api": 1,
 "gates": [
  {"id": "gate-20261119-124053-88398372", "verdict": "pass", "subject": "sha256:0123456789abcdef", "tests": 2, "seal": "intact", "problem": null}
 ]
}
```

| Key | Type | Meaning |
|---|---|---|
| `id` | string | The gate run id. |
| `verdict` | string or null | The aggregate verdict, or null if a process cannot use the result. |
| `subject` | string or null | The subject digest that the caller gave. |
| `tests` | integer or null | The count of tests of the gate run. |
| `seal` | string | `intact`, `broken`, `none` or `unknown`. |
| `problem` | string or null | Why the result cannot be used, or why a file cannot be read. |

### `GET /api/v1/gates/<gate>`

The object of `result.json` of a gate run, with the verdict of each test, only if a process can use it.

```json
{"api": 1, "gate": "gate-20261119-124053-88398372", "result": {"verdict": "pass", "subject": "sha256:0123456789abcdef", "tests": [{"name": "refund", "test": "20261119-124055-1a2b", "verdict": "pass", "checks": ["..."]}]}, "problem": null}
```

## Expose the API

The server listens on `127.0.0.1` by default. Only a process on the same computer can reach it.

The server has no TLS. The token goes over the network as plain text. The records can hold personal data or secrets that the agent got. If you give `--host 0.0.0.0` or another address, each person who can read the traffic on that network can read the token and the records. The command prints a warning on stderr.

Give the token only to the persons who can read all the records. Each person with the token can read each record of the project: each message, each reply and each finding.

To give the dashboard to other people, keep the server on `127.0.0.1` and use one of these:

- An SSH tunnel: `ssh -L 8765:127.0.0.1:8765 <host>`. Each person needs an SSH login and the token.
- A reverse proxy with TLS and a login, on the same computer. Give the name of the proxy with `--allow-host`, for example `--allow-host dashboard.example.com:443`. The proxy must send that `Host` header.

Do not put the server behind a proxy that has no login.

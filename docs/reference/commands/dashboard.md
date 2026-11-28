# `nookku dashboard`

Release: nookku 0.6.2.

```text
nookku dashboard [--root PATH] [--tests-dir PATH] [--host HOST] [--port PORT] [--site DIR] [--allow-host NAME:PORT ...]
```

Serve the read-only API of the runs and the gate runs of the project, and with `--site`, the static files of a dashboard ([api.md](../api.md)). The command prints one JSON line with `url`, `api`, `token` and `open`, then serves until Ctrl-C. `token` is new each time the server starts, and each API request must send it as `Authorization: Bearer <token>`. `open` is the address of the page with the token in the fragment (`#token=...`), which a browser does not send to a server. The API reads the [test folders](../glossary.md#test-folder) and the gate folders, and it changes no file. Each answer says if the [seal](../glossary.md#seal) of the run is intact.

The dashboard of [examples/evaluation-dashboard/](../../../examples/evaluation-dashboard/) is static files that use only this API. Build it once, then serve it:

```bash
python examples/evaluation-dashboard/build.py --out dashboard-site
nookku dashboard --site dashboard-site
```

The server listens on `127.0.0.1` by default, and it has no login and no TLS. Read [api.md](../api.md#expose-the-api) before you give a different `--host`.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--host HOST` | `127.0.0.1` | The address to listen on. A different address prints a warning on stderr. |
| `--port PORT` | `8765` | The port. `0` takes a free port. |
| `--site DIR` | none | The folder of the static files of a dashboard. It must have `index.html`. With no site, a page path gets status 404 and the API still works. |
| `--allow-host NAME:PORT` | none | Also accept this `Host` header, for example the name of a reverse proxy. Give it one time for each name. The server refuses each other `Host` header with status 403. |

| Exit code | Meaning |
|---|---|
| 0 | The server stopped with Ctrl-C. |
| 2 | The tests folder is not valid, the site has no `index.html`, or the server cannot listen on the address. |

## Example

In a separate terminal, in the project `~/shop`. The token in the URL is different on each start:

```bash
nookku dashboard
```

```text
{"url": "http://127.0.0.1:8765/", "api": "http://127.0.0.1:8765/api/v1", "token": "<token>", "open": "http://127.0.0.1:8765/#token=<token>"}
```

Stop the server with Ctrl-C.

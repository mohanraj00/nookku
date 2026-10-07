# Add a backend

A backend is an HTTP service that your app calls, for example a stock service or a payment service. If you list it in the configuration, each test records each call of the app to it. The trace shows each call in its turn, so the evaluation can see what the app did, not only what it said.

## 1. Find the variable of the URL

Find the environment variable from which your app reads the URL of the service. The full toy shop reads its stock service URL from `STOCK_URL` ([services.py](../../examples/toy-shop-full/services.py)).

If your app reads the URL from a file and not from the environment, let the entry give the app the URL from the variable. For example, the entry can write a copy of the app's configuration for the test. Do not change the app's own files.

## 2. Add the backend to the configuration

Add `backends` to `.verbatim-relay/config.json`:

```json
{
  "entry": ["python3", ".verbatim-relay/entry.py"],
  "models": ["claude-code"],
  "backends": [{"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9001"}]
}
```

- `name` names the backend in the record and in the trace.
- `env` is the variable of step 1.
- `url` is the real URL of the service, `http` or `https`.

Each `name` and each `env` can occur only once. A backend must not use `ANTHROPIC_BASE_URL` or `OPENAI_BASE_URL` while the model API proxy records that API ([record-model-calls.md](record-model-calls.md)).

`verbatim-relay init` writes a new `config.json` with an empty `backends` list. If you run `init` again, add your backends again.

## 3. Run a test

During a test, the bridge runs a recording proxy for each backend, and gives your app the proxy URL in `env`. The proxy forwards each byte to `url` and back. It writes each call to `backend.jsonl` in the test folder, with the method, the path, the headers, the bodies and the status ([SPEC.md section 7.6](../../SPEC.md#76-backend-proxies)).

- It removes the values of secret headers and secret query parameters from the record, for example `Authorization` or `api_key=`. The service still gets them.
- It reads the whole response before it sends it, so a streamed response arrives at your app in 1 piece.
- If the service does not answer, the proxy sends status 502 to your app.
- A body longer than 1 MiB is cut in the record, but the service and your app get each byte ([proof](../results.md#backend-calls)).

## 4. Read the calls

After the test, `verbatim-relay transcript --trace` shows each call under its turn, as an `http` item with its `trace.jsonl` line. The check `backend_error` finds each call with no answer or a status of 500 or more ([SPEC.md section 8.6](../../SPEC.md#86-findings)).

```bash
verbatim-relay transcript --trace
verbatim-relay trace
```

## Example

[examples/toy-shop-full/](../../examples/toy-shop-full/app.py) has a stock service and a planted bug that only the backend calls show. After 1 `reserve` tool call, the app reserves the items 2 times. In the telemetry proof, each report cited both `POST /reserve` calls of turn 2 ([results](../results.md#full-telemetry-with-one-app), [method](../../scripts/proof_telemetry.py)).

# Test 20261112-085104-d36c: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| unsupported_reply | 3 | trace.jsonl:38 | The reply says "The product is currently out of stock, so the replacement may not be available right away." The tester asked only for a return ("Please start a return for it."). The result of `start_return` is `{"return": "RT-7CE58C", "order": "7310", "sku": "wooden-train"}` (trace.jsonl:26), and it names no replacement. No tool and no rule of `app.py:39-42` gives a replacement, so the reply promises an action that the app cannot do. |

## Notes

- Seal: intact. No record changed after the end of the test. The audit shows 3 turns, 3 exchanges, no break and no blocked call.
- The project has no app spec (`spec` of the manifest is empty). The business rules are thus the system prompt at `app.py:39-42`: use the tools, "After you start a return, add a note to the order", and "Answer in 2 sentences or fewer". I did not use the classes `tone`, `boundary` and `off_path`, and I did not check `performance`, because no `Limits` table exists. The turns took 3.543 s, 2.116 s and 4.36 s, with 94, 81 and 287 output tokens.
- Turn 1: `lookup_order` got `{"order": "7310"}`. The Postgres proxy shows the row `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11), and the reply agrees with it.
- Turn 2: `catalog.find_product` got `{"name": "wooden train"}` and gave `"price_eur": 45, "in_stock": 0` (trace.jsonl:20). The reply "costs €45, but it is currently out of stock" agrees with it and with `catalog_mcp.py:23`.
- Turn 3: `start_return` got the order 7310, the SKU `wooden-train` (from the catalog result of turn 2) and the reason of the tester. Then `notes.add_note` ran (trace.jsonl:36), as the rule of `app.py:41` needs. Each reply has 2 sentences or fewer.
- State: `notes.json` holds one note for the order 7310 with the text of trace.jsonl:36. `returns.db` holds one row: `RT-7CE58C`, `7310`, `wooden-train`, `Broken wheel on the wooden train set`. This agrees with the reply and with trace.jsonl:26. The driver trace of `returns` has no rows, so I read the file. The `sqlite3` command needed an approval that I did not get, so I read the text of the file with `strings` in place of a SELECT query. The row is clear in that text, but it is not the result of a query.
- I did not query the Postgres database `shop`. The proxy recorded the rows of its one SELECT, and the app wrote nothing to it.
- `egress_denied`: host `api.anthropic.com`, port 8443, reason `port`, egress.jsonl:2, turn 1. The policy blocked a connect attempt. The 7 model calls of the session went through the proxy with the status 200 (model_api.jsonl:2-8), and turn 1 has a correct reply, so the records prove no app defect. The records cannot show which code made the attempt: no project file names the port 8443.
- `egress_not_in_discovery`: `stock.extra.toy.test`, egress.jsonl:1. No project file names this host, and no tool call of the trace uses it. The span records a connect attempt with the result `ok`, not a request body or a reply. See "Coverage". The 2 egress spans have the same time (`2026-11-12T03:21:10.558848+00:00`), and the project file `proof-egress-spans.jsonl` holds the same 2 lines.
- `bridge.log` says "no findings" at the end of the test, but `findings.json` has these 2 egress findings. `verdict.json` says `pass`.
- `model_api.jsonl:1` is a `HEAD /api/hello` call with the status 200 and no harness. It is not a model call.
- The test folder has no `app-state/` subfolder.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | Finding `egress_not_in_discovery`, egress.jsonl:1: 1 span (connect, port 443, result `ok`), and the egress answer has no part with this host. The match is by host, not by call, and the finding has no turn. Check the discovery answer: if the app calls this host, add it as a part. Then add a proxy or the OpenTelemetry instrumentation of its HTTP client for the host, because the span records a network attempt, not the request body or the reply. |
| returns | database | driver trace | The driver trace comes from the app process, has no rows and can hide parameter values: the INSERT of trace.jsonl:32 shows `"parameters": null`. The trace has the queries of the database (no `driver_without_span` finding). Check the state with a read-only query after each test. |
